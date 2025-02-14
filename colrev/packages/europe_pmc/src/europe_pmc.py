#! /usr/bin/env python
"""SearchSource: Europe PMC"""
from __future__ import annotations

import json
import typing
from multiprocessing import Lock
from pathlib import Path
from sqlite3 import OperationalError
from urllib.parse import quote
from urllib.parse import urlparse

import requests
from pydantic import BaseModel
from pydantic import Field
from rapidfuzz import fuzz

import colrev.exceptions as colrev_exceptions
import colrev.package_manager.interfaces
import colrev.package_manager.package_manager
import colrev.package_manager.package_settings
import colrev.record.record
import colrev.record.record_prep
import colrev.record.record_similarity
import colrev.settings
from colrev.constants import Fields
from colrev.constants import RecordState
from colrev.constants import SearchSourceHeuristicStatus
from colrev.constants import SearchType
from colrev.packages.europe_pmc.src import europe_pmc_api

# pylint: disable=duplicate-code
# pylint: disable=unused-argument


class EuropePMCSearchSourceSettings(colrev.settings.SearchSource, BaseModel):
    """Settings for EuropePMCSearchSource"""

    # pylint: disable=too-many-instance-attributes
    endpoint: str
    filename: Path
    search_type: SearchType
    search_parameters: dict
    comment: typing.Optional[str]

    _details = {
        "search_parameters": {
            "tooltip": "Currently supports a scope item "
            "with venue_key and journal_abbreviated fields."
        },
    }


class EuropePMCSearchSource(colrev.package_manager.interfaces.SearchSourceInterface):
    """Europe PMC"""

    settings_class = colrev.package_manager.package_settings.DefaultSourceSettings
    #
    source_identifier = Fields.EUROPE_PMC_ID
    search_types = [
        SearchType.API,
        SearchType.DB,
        SearchType.MD,
    ]
    endpoint = "colrev.europe_pmc"

    ci_supported: bool = Field(default=True)
    heuristic_status = SearchSourceHeuristicStatus.supported

    _europe_pmc_md_filename = Path("data/search/md_europe_pmc.bib")
    _SOURCE_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/article/"

    settings_class = EuropePMCSearchSourceSettings

    def __init__(
        self,
        *,
        source_operation: colrev.process.operation.Operation,
        settings: typing.Optional[dict] = None,
    ) -> None:
        self.review_manager = source_operation.review_manager
        if settings:
            # EuropePMC as a search_source
            self.search_source = self.settings_class(**settings)
        else:
            # EuropePMC as an md-prep source
            europe_pmc_md_source_l = [
                s
                for s in source_operation.review_manager.settings.sources
                if s.filename == self._europe_pmc_md_filename
            ]
            if europe_pmc_md_source_l:
                self.search_source = europe_pmc_md_source_l[0]
            else:
                self.search_source = colrev.settings.SearchSource(
                    endpoint=self.endpoint,
                    filename=self._europe_pmc_md_filename,
                    search_type=SearchType.MD,
                    search_parameters={},
                    comment="",
                )

        self.europe_pmc_lock = Lock()
        self.source_operation = source_operation

    # @classmethod
    # def check_status(cls, *, prep_operation: colrev.ops.prep.Prep) -> None:
    # ...

    @classmethod
    def _get_similarity(
        cls,
        *,
        record: colrev.record.record.Record,
        retrieved_record: colrev.record.record.Record,
    ) -> float:
        title_similarity = fuzz.partial_ratio(
            retrieved_record.data[Fields.TITLE].lower(),
            record.data.get(Fields.TITLE, "").lower(),
        )
        container_similarity = fuzz.partial_ratio(
            retrieved_record.get_container_title().lower(),
            record.get_container_title().lower(),
        )

        weights = [0.6, 0.4]
        similarities = [title_similarity, container_similarity]
        similarity = sum(similarities[g] * weights[g] for g in range(len(similarities)))
        return similarity

    def _europe_pmc_query(
        self,
        *,
        record_input: colrev.record.record.Record,
        most_similar_only: bool = True,
        timeout: int = 60,
    ) -> list:
        """Retrieve records from Europe PMC based on a query"""

        try:
            api = europe_pmc_api.EPMCAPI(
                params={"query": quote(record_input.data[Fields.TITLE])},
                email=self.review_manager.get_committer()[1],
                session=self.review_manager.get_cached_session(),
            )

            record = record_input.copy_prep_rec()

            record_list = []
            counter = 0
            most_similar, most_similar_record = 0.0, {}
            for retrieved_record in api.get_records():
                counter += 1

                if Fields.TITLE not in retrieved_record.data:
                    continue

                similarity = self._get_similarity(
                    record=record, retrieved_record=retrieved_record
                )

                source = (
                    f"{self._SOURCE_URL}{retrieved_record.data[Fields.EUROPE_PMC_ID]}"
                )
                retrieved_record.set_masterdata_complete(
                    source=source,
                    masterdata_repository=self.review_manager.settings.is_curated_repo(),
                )

                if not most_similar_only:
                    record_list.append(retrieved_record)

                elif most_similar < similarity:
                    most_similar = similarity
                    most_similar_record = retrieved_record.get_data()
                if most_similar_only and counter > 5:
                    break

        except (requests.exceptions.RequestException, json.decoder.JSONDecodeError):
            return []
        except OperationalError as exc:
            raise colrev_exceptions.ServiceNotAvailableException(
                "sqlite, required for requests CachedSession "
                "(possibly caused by concurrent operations)"
            ) from exc

        if most_similar_only:
            record_list = [colrev.record.record_prep.PrepRecord(most_similar_record)]

        return record_list

    def prep_link_md(
        self,
        prep_operation: colrev.ops.prep.Prep,
        record: colrev.record.record.Record,
        save_feed: bool = True,
        timeout: int = 10,  # pylint: disable=unused-argument
    ) -> colrev.record.record.Record:
        """Retrieve masterdata from Europe PMC based on similarity with the record provided"""

        # pylint: disable=too-many-branches
        # pylint: disable=too-many-return-statements

        # https://www.ebi.ac.uk/europepmc/webservices/rest/article/MED/23245604
        if len(record.data.get(Fields.TITLE, "")) < 35:
            return record

        try:

            retrieved_records = self._europe_pmc_query(
                record_input=record,
                timeout=timeout,
            )
            if not retrieved_records:
                return record

            retrieved_record = retrieved_records.pop()
            if 0 == len(retrieved_record.data):
                return record

            if not colrev.record.record_similarity.matches(record, retrieved_record):
                return record

            self.europe_pmc_lock.acquire(timeout=60)

            # Note : need to reload file because the object is not shared between processes
            europe_pmc_feed = self.search_source.get_api_feed(
                review_manager=prep_operation.review_manager,
                source_identifier=self.source_identifier,
                update_only=False,
                prep_mode=True,
            )
            europe_pmc_feed.add_update_record(retrieved_record=retrieved_record)

            record.merge(
                retrieved_record,
                default_source=retrieved_record.data[Fields.ORIGIN][0],
            )

            record.set_masterdata_complete(
                source=retrieved_record.data[Fields.ORIGIN][0],
                masterdata_repository=self.review_manager.settings.is_curated_repo(),
            )
            record.set_status(RecordState.md_prepared)
            europe_pmc_feed.save()

        except requests.exceptions.RequestException:
            pass
        except colrev_exceptions.NotFeedIdentifiableException:
            pass
        finally:
            try:
                self.europe_pmc_lock.release()
            except ValueError:
                pass

        return record

    def _validate_source(self) -> None:
        """Validate the SearchSource (parameters etc.)"""

        source = self.search_source

        self.review_manager.logger.debug(f"Validate SearchSource {source.filename}")

        assert source.search_type in self.search_types

        if "query" not in source.search_parameters:
            raise colrev_exceptions.InvalidQueryException(
                "Query required in search_parameters"
            )

        self.review_manager.logger.debug(f"SearchSource {source.filename} validated")

    def search(self, rerun: bool) -> None:
        """Run a search of Europe PMC"""

        self._validate_source()
        # https://europepmc.org/RestfulWebService

        europe_pmc_feed = self.search_source.get_api_feed(
            review_manager=self.review_manager,
            source_identifier=self.source_identifier,
            update_only=(not rerun),
        )

        if self.search_source.search_type == SearchType.API:
            self._run_api_search(
                europe_pmc_feed=europe_pmc_feed,
                rerun=rerun,
            )

        elif self.search_source.search_type == SearchType.DB:
            self.source_operation.run_db_search(  # type: ignore
                search_source_cls=self.__class__,
                source=self.search_source,
            )

        # if self.search_source.search_type == colrev.settings.SearchSource.MD:
        # self._run_md_search_update(
        #     search_operation=search_operation,
        #     europe_pmc_feed=europe_pmc_feed,
        # )

        else:
            raise NotImplementedError

    def _run_api_search(
        self,
        *,
        europe_pmc_feed: colrev.ops.search_api_feed.SearchAPIFeed,
        rerun: bool,
    ) -> None:

        try:
            _, email = self.review_manager.get_committer()
            api = europe_pmc_api.EPMCAPI(
                params=self.search_source.search_parameters,
                email=email,
                session=self.review_manager.get_cached_session(),
            )

            while api.url:

                for retrieved_record in api.get_records():
                    if Fields.TITLE not in retrieved_record.data:
                        self.review_manager.logger.warning(
                            f"Skipped record: {retrieved_record.data}"
                        )
                        continue

                    source = f"{self._SOURCE_URL}{retrieved_record.data[Fields.EUROPE_PMC_ID]}"
                    retrieved_record.set_masterdata_complete(
                        source=source,
                        masterdata_repository=self.review_manager.settings.is_curated_repo(),
                    )

                    europe_pmc_feed.add_update_record(retrieved_record)

        except (requests.exceptions.RequestException, json.decoder.JSONDecodeError):
            pass
        except OperationalError as exc:
            raise colrev_exceptions.ServiceNotAvailableException(
                "sqlite, required for requests CachedSession "
                "(possibly caused by concurrent operations)"
            ) from exc
        finally:
            europe_pmc_feed.save()

    @classmethod
    def heuristic(cls, filename: Path, data: str) -> dict:
        """Source heuristic for Europe PMC"""

        result = {"confidence": 0.0}
        # pylint: disable=colrev-missed-constant-usage
        if "europe_pmc_id" in data:
            result["confidence"] = 1.0

        if "https://europepmc.org" in data:  # nosec
            if data.count("https://europepmc.org") >= data.count("\n@"):
                result["confidence"] = 1.0

        return result

    @classmethod
    def add_endpoint(
        cls,
        operation: colrev.ops.search.Search,
        params: str,
    ) -> colrev.settings.SearchSource:
        """Add SearchSource as an endpoint (based on query provided to colrev search --add )"""

        params_dict = {}
        if params:
            if params.startswith("http"):
                params_dict = {Fields.URL: params}
            else:
                for item in params.split(";"):
                    key, value = item.split("=")
                    params_dict[key] = value

        if len(params_dict) == 0:
            search_source = operation.create_api_source(endpoint=cls.endpoint)

        # pylint: disable=colrev-missed-constant-usage
        elif "url" in params_dict:
            host = urlparse(params_dict["url"]).hostname

            if host and host.endswith("europepmc.org"):
                query = params_dict["url"].replace(
                    "https://europepmc.org/search?query=", ""
                )
                filename = operation.get_unique_filename(file_path_string="europepmc")
                search_source = colrev.settings.SearchSource(
                    endpoint=cls.endpoint,
                    filename=filename,
                    search_type=SearchType.API,
                    search_parameters={"query": query},
                    comment="",
                )
            else:
                raise NotImplementedError
        else:
            raise NotImplementedError

        operation.add_source_and_search(search_source)
        return search_source

    def _load_bib(self) -> dict:
        def field_mapper(record_dict: dict) -> None:
            for key in list(record_dict.keys()):
                if key not in ["ID", "ENTRYTYPE"]:
                    record_dict[key.lower()] = record_dict.pop(key)

        records = colrev.loader.load_utils.load(
            filename=self.search_source.filename,
            logger=self.review_manager.logger,
            unique_id_field="ID",
            field_mapper=field_mapper,
        )
        return records

    def load(self, load_operation: colrev.ops.load.Load) -> dict:
        """Load the records from the SearchSource file"""

        if self.search_source.filename.suffix == ".bib":
            return self._load_bib()

        raise NotImplementedError

    def prepare(
        self, record: colrev.record.record.Record, source: colrev.settings.SearchSource
    ) -> colrev.record.record.Record:
        """Source-specific preparation for Europe PMC"""
        record.data[Fields.AUTHOR].rstrip(".")
        record.data[Fields.TITLE].rstrip(".")
        return record
