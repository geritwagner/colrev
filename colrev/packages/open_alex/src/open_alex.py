#! /usr/bin/env python
"""SearchSource: OpenAlex"""
from __future__ import annotations

import typing
from multiprocessing import Lock
from pathlib import Path

import requests
from pydantic import Field

import colrev.exceptions as colrev_exceptions
import colrev.package_manager.interfaces
import colrev.package_manager.package_manager
import colrev.package_manager.package_settings
import colrev.record.record
import colrev.record.record_prep
from colrev.constants import Fields
from colrev.constants import SearchSourceHeuristicStatus
from colrev.constants import SearchType
from colrev.packages.open_alex.src import open_alex_api

# pylint: disable=unused-argument
# pylint: disable=duplicate-code


class OpenAlexSearchSource(colrev.package_manager.interfaces.SearchSourceInterface):
    """OpenAlex API"""

    settings_class = colrev.package_manager.package_settings.DefaultSourceSettings
    endpoint = "colrev.open_alex"
    source_identifier = "openalex_id"
    search_types = [SearchType.MD]

    ci_supported: bool = Field(default=True)
    heuristic_status = SearchSourceHeuristicStatus.oni

    _open_alex_md_filename = Path("data/search/md_open_alex.bib")

    def __init__(
        self,
        *,
        source_operation: colrev.process.operation.Operation,
        settings: typing.Optional[dict] = None,
    ) -> None:
        self.review_manager = source_operation.review_manager
        # Note: not yet implemented
        # Note : once this is implemented, add "colrev.open_alex" to the default settings
        # if settings:
        #     # OpenAlex as a search_source
        #     self.search_source = self.settings_class(**settings)
        # else:
        # OpenAlex as an md-prep source
        open_alex_md_source_l = [
            s
            for s in self.review_manager.settings.sources
            if s.filename == self._open_alex_md_filename
        ]
        if open_alex_md_source_l:
            self.search_source = open_alex_md_source_l[0]
        else:
            self.search_source = colrev.settings.SearchSource(
                endpoint="colrev.open_alex",
                filename=self._open_alex_md_filename,
                search_type=SearchType.MD,
                search_parameters={},
                comment="",
            )

        self.open_alex_lock = Lock()

    @classmethod
    def heuristic(cls, filename: Path, data: str) -> dict:
        """Source heuristic for OpenAlex"""

        result = {"confidence": 0.0}

        return result

    @classmethod
    def add_endpoint(
        cls,
        operation: colrev.ops.search.Search,
        params: str,
    ) -> colrev.settings.SearchSource:
        """Add SearchSource as an endpoint (based on query provided to colrev search --add )"""

        raise colrev_exceptions.PackageParameterError(
            f"Cannot add OpenAlex endpoint with query {params}"
        )

    def check_availability(
        self, *, source_operation: colrev.process.operation.Operation
    ) -> None:
        """Check status (availability) of the OpenAlex API"""

    def _get_masterdata_record(
        self, *, record: colrev.record.record.Record
    ) -> colrev.record.record.Record:
        try:

            _, email = self.review_manager.get_committer()
            api = open_alex_api.OpenAlexAPI(email=email)
            retrieved_record = api.get_record(
                open_alex_id=record.data["colrev.open_alex.id"]
            )

            self.open_alex_lock.acquire(timeout=120)

            # Note : need to reload file because the object is not shared between processes
            open_alex_feed = self.search_source.get_api_feed(
                review_manager=self.review_manager,
                source_identifier=self.source_identifier,
                update_only=False,
                prep_mode=True,
            )

            open_alex_feed.add_update_record(retrieved_record)
            record.change_entrytype(
                new_entrytype=retrieved_record.data[Fields.ENTRYTYPE],
                qm=self.review_manager.get_qm(),
            )

            record.merge(
                retrieved_record,
                default_source=retrieved_record.data[Fields.ORIGIN][0],
            )
            open_alex_feed.save()
        except (
            colrev_exceptions.RecordNotParsableException,
            requests.exceptions.RequestException,
        ):
            pass
        except Exception as exc:
            raise exc
        finally:
            try:
                self.open_alex_lock.release()
            except ValueError:
                pass

        return record

    def prep_link_md(
        self,
        prep_operation: colrev.ops.prep.Prep,
        record: colrev.record.record.Record,
        save_feed: bool = True,
        timeout: int = 30,
    ) -> colrev.record.record.Record:
        """Retrieve masterdata from OpenAlex based on similarity with the record provided"""

        if "colrev.open_alex.id" in record.data:
            # Note: not yet implemented
            # https://github.com/OpenAPC/openapc-de/blob/master/python/import_dois.py
            # if len(record.data.get(Fields.TITLE, "")) < 35 and Fields.DOI not in record.data:
            #     return record
            # record = self._check_doi_masterdata(record=record)
            record = self._get_masterdata_record(record=record)

        return record

    def search(self, rerun: bool) -> None:
        """Run a search of OpenAlex"""

        # https://docs.openalex.org/api-entities/works

        raise NotImplementedError

    def load(self, load_operation: colrev.ops.load.Load) -> dict:
        """Load the records from the SearchSource file"""

        if self.search_source.filename.suffix == ".bib":
            records = colrev.loader.load_utils.load(
                filename=self.search_source.filename,
                logger=self.review_manager.logger,
            )
            return records

        raise NotImplementedError

    def prepare(
        self, record: colrev.record.record.Record, source: colrev.settings.SearchSource
    ) -> colrev.record.record.Record:
        """Source-specific preparation for OpenAlex"""

        return record
