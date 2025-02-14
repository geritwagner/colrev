#! /usr/bin/env python
"""SearchSource: IEEEXplore"""
from __future__ import annotations

import typing
from pathlib import Path

import pandas as pd
from pydantic import Field

import colrev.ops.prep
import colrev.package_manager.interfaces
import colrev.package_manager.package_manager
import colrev.package_manager.package_settings
import colrev.packages.ieee.src.ieee_api
import colrev.record.record
import colrev.record.record_prep
from colrev.constants import ENTRYTYPES
from colrev.constants import Fields
from colrev.constants import SearchSourceHeuristicStatus
from colrev.constants import SearchType

# pylint: disable=unused-argument
# pylint: disable=duplicate-code


class IEEEXploreSearchSource(colrev.package_manager.interfaces.SearchSourceInterface):
    """IEEEXplore"""

    flag = True

    settings_class = colrev.package_manager.package_settings.DefaultSourceSettings

    # pylint: disable=colrev-missed-constant-usage
    source_identifier = "ID"
    search_types = [SearchType.API]
    endpoint = "colrev.ieee"

    ci_supported: bool = Field(default=True)
    heuristic_status = SearchSourceHeuristicStatus.oni

    db_url = "https://ieeexplore.ieee.org/Xplore/home.jsp"
    SETTINGS = {
        "api_key": "packages.search_source.colrev.ieee.api_key",
    }

    def __init__(
        self,
        *,
        source_operation: colrev.process.operation.Operation,
        settings: typing.Optional[dict] = None,
    ) -> None:
        self.review_manager = source_operation.review_manager

        if settings:
            self.search_source = self.settings_class(**settings)
        else:
            self.search_source = colrev.settings.SearchSource(
                endpoint=self.endpoint,
                filename=Path("data/search/ieee.bib"),
                search_type=SearchType.OTHER,
                search_parameters={},
                comment="",
            )
        self.source_operation = source_operation

    # For run_search, a Python SDK would be available:
    # https://developer.ieee.org/Python_Software_Development_Kit

    @classmethod
    def heuristic(cls, filename: Path, data: str) -> dict:
        """Source heuristic for IEEEXplore"""

        result = {"confidence": 0.1}

        if "Date Added To Xplore" in data:
            result["confidence"] = 0.9
            return result

        return result

    @classmethod
    def add_endpoint(
        cls, operation: colrev.ops.search.Search, params: str
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

        search_type = operation.select_search_type(
            search_types=cls.search_types, params=params_dict
        )

        if search_type == SearchType.API:
            if len(params_dict) == 0:
                search_source = operation.create_api_source(endpoint=cls.endpoint)

            # pylint: disable=colrev-missed-constant-usage
            elif (
                "https://ieeexploreapi.ieee.org/api/v1/search/articles?"
                in params_dict["url"]
            ):
                query = (
                    params_dict["url"]
                    .replace(
                        "https://ieeexploreapi.ieee.org/api/v1/search/articles?", ""
                    )
                    .lstrip("&")
                )

                parameter_pairs = query.split("&")
                search_parameters = {}
                for parameter in parameter_pairs:
                    key, value = parameter.split("=")
                    search_parameters[key] = value

                last_value = list(search_parameters.values())[-1]

                filename = operation.get_unique_filename(
                    file_path_string=f"ieee_{last_value}"
                )

                search_source = colrev.settings.SearchSource(
                    endpoint=cls.endpoint,
                    filename=filename,
                    search_type=SearchType.API,
                    search_parameters=search_parameters,
                    comment="",
                )
            else:
                raise NotImplementedError

        elif search_type == SearchType.DB:
            search_source = operation.create_db_source(
                search_source_cls=cls,
                params=params_dict,
            )
        else:
            raise NotImplementedError

        operation.add_source_and_search(search_source)
        return search_source

    def search(self, rerun: bool) -> None:
        """Run a search of IEEEXplore"""

        if self.search_source.search_type == SearchType.API:
            ieee_feed = self.search_source.get_api_feed(
                review_manager=self.review_manager,
                source_identifier=self.source_identifier,
                update_only=(not rerun),
            )
            self._run_api_search(ieee_feed=ieee_feed, rerun=rerun)

        elif self.search_source.search_type == SearchType.DB:
            self.source_operation.run_db_search(  # type: ignore
                search_source_cls=self.__class__,
                source=self.search_source,
            )

        else:
            raise NotImplementedError

    def _get_api_key(self) -> str:
        api_key = self.review_manager.environment_manager.get_settings_by_key(
            self.SETTINGS["api_key"]
        )
        if api_key is None or len(api_key) != 24:
            api_key = input("Please enter api key: ")
            self.review_manager.environment_manager.update_registry(
                self.SETTINGS["api_key"], api_key
            )
        return api_key

    def _run_api_search(
        self, ieee_feed: colrev.ops.search_api_feed.SearchAPIFeed, rerun: bool
    ) -> None:
        api_key = self._get_api_key()

        api = colrev.packages.ieee.src.ieee_api.XPLORE(
            parameters=self.search_source.search_parameters, api_key=api_key
        )
        while True:
            retrieved_records = api.get_records()
            if not retrieved_records:
                break

            for retrieved_record in retrieved_records:
                ieee_feed.add_update_record(retrieved_record)

            api.startRecord += api.resultSetMax

        ieee_feed.save()

    def prep_link_md(
        self,
        prep_operation: colrev.ops.prep.Prep,
        record: colrev.record.record.Record,
        save_feed: bool = True,
        timeout: int = 10,
    ) -> colrev.record.record.Record:
        """Not implemented"""
        return record

    def _load_ris(self, load_operation: colrev.ops.load.Load) -> dict:
        def entrytype_setter(record_dict: dict) -> None:
            if record_dict["TY"] == "JOUR":
                record_dict[Fields.ENTRYTYPE] = ENTRYTYPES.ARTICLE
            elif record_dict["TY"] == "CONF":
                record_dict[Fields.ENTRYTYPE] = ENTRYTYPES.INPROCEEDINGS
            else:
                record_dict[Fields.ENTRYTYPE] = ENTRYTYPES.MISC

        def field_mapper(record_dict: dict) -> None:

            key_maps = {
                ENTRYTYPES.ARTICLE: {
                    "PY": Fields.YEAR,
                    "AU": Fields.AUTHOR,
                    "TI": Fields.TITLE,
                    "T2": Fields.JOURNAL,
                    "AB": Fields.ABSTRACT,
                    "VL": Fields.VOLUME,
                    "IS": Fields.NUMBER,
                    "DO": Fields.DOI,
                    "PB": Fields.PUBLISHER,
                    "UR": Fields.URL,
                    "SN": Fields.ISSN,
                },
                ENTRYTYPES.INPROCEEDINGS: {
                    "PY": Fields.YEAR,
                    "AU": Fields.AUTHOR,
                    "TI": Fields.TITLE,
                    "T2": Fields.BOOKTITLE,
                    "DO": Fields.DOI,
                    "SN": Fields.ISSN,
                },
            }

            key_map = key_maps[record_dict[Fields.ENTRYTYPE]]
            for ris_key in list(record_dict.keys()):
                if ris_key in key_map:
                    standard_key = key_map[ris_key]
                    record_dict[standard_key] = record_dict.pop(ris_key)

            if "SP" in record_dict and "EP" in record_dict:
                record_dict[Fields.PAGES] = (
                    f"{record_dict.pop('SP')}--{record_dict.pop('EP')}"
                )

            if Fields.AUTHOR in record_dict and isinstance(
                record_dict[Fields.AUTHOR], list
            ):
                record_dict[Fields.AUTHOR] = " and ".join(record_dict[Fields.AUTHOR])
            if Fields.EDITOR in record_dict and isinstance(
                record_dict[Fields.EDITOR], list
            ):
                record_dict[Fields.EDITOR] = " and ".join(record_dict[Fields.EDITOR])
            if Fields.KEYWORDS in record_dict and isinstance(
                record_dict[Fields.KEYWORDS], list
            ):
                record_dict[Fields.KEYWORDS] = ", ".join(record_dict[Fields.KEYWORDS])

            record_dict.pop("TY", None)
            record_dict.pop("Y2", None)
            record_dict.pop("DB", None)
            record_dict.pop("C1", None)
            record_dict.pop("T3", None)
            record_dict.pop("AD", None)
            record_dict.pop("CY", None)
            record_dict.pop("M3", None)
            record_dict.pop("EP", None)
            record_dict.pop("Y1", None)
            record_dict.pop("Y2", None)
            record_dict.pop("JA", None)
            record_dict.pop("JO", None)
            record_dict.pop("VO", None)
            record_dict.pop("VL", None)
            record_dict.pop("IS", None)
            record_dict.pop("ER", None)

            for key, value in record_dict.items():
                record_dict[key] = str(value)

        load_operation.ensure_append_only(self.search_source.filename)
        records = colrev.loader.load_utils.load(
            filename=self.search_source.filename,
            unique_id_field="INCREMENTAL",
            entrytype_setter=entrytype_setter,
            field_mapper=field_mapper,
            logger=self.review_manager.logger,
            format_names=True,
        )

        return records

    def _load_csv(self) -> dict:
        def entrytype_setter(record_dict: dict) -> None:
            if record_dict["Category"] == "Magazine":
                record_dict[Fields.ENTRYTYPE] = ENTRYTYPES.ARTICLE
            elif record_dict["Category"] == "Conference Publication":
                record_dict[Fields.ENTRYTYPE] = ENTRYTYPES.INPROCEEDINGS
            else:
                record_dict[Fields.ENTRYTYPE] = ENTRYTYPES.MISC

        def field_mapper(record_dict: dict) -> None:
            record_dict[Fields.TITLE] = record_dict.pop("Title", "")
            record_dict[Fields.AUTHOR] = record_dict.pop("Authors", "")
            record_dict[Fields.ABSTRACT] = record_dict.pop("Abstract", "")
            record_dict[Fields.DOI] = record_dict.pop("DOI", "")

            if record_dict[Fields.ENTRYTYPE] == ENTRYTYPES.ARTICLE:
                record_dict[Fields.JOURNAL] = record_dict.pop("Publication", "")
            if record_dict[Fields.ENTRYTYPE] == ENTRYTYPES.INPROCEEDINGS:
                record_dict[Fields.BOOKTITLE] = record_dict.pop("Publication", "")

            record_dict.pop("Category", None)
            record_dict.pop("Affiliations", None)

            for key in list(record_dict.keys()):
                value = record_dict[key]
                record_dict[key] = str(value)
                if value == "" or pd.isna(value):
                    del record_dict[key]

        records = colrev.loader.load_utils.load(
            filename=self.search_source.filename,
            unique_id_field="DOI",
            entrytype_setter=entrytype_setter,
            field_mapper=field_mapper,
            logger=self.review_manager.logger,
        )
        return records

    def load(self, load_operation: colrev.ops.load.Load) -> dict:
        """Load the records from the SearchSource file"""

        if self.search_source.filename.suffix == ".ris":
            return self._load_ris(load_operation)

        if self.search_source.filename.suffix == ".csv":
            return self._load_csv()

        raise NotImplementedError

    def prepare(
        self, record: colrev.record.record.Record, source: colrev.settings.SearchSource
    ) -> colrev.record.record.Record:
        """Source-specific preparation for IEEEXplore"""

        if source.filename.suffix == ".csv":
            if Fields.AUTHOR in record.data:
                record.data[Fields.AUTHOR] = (
                    colrev.record.record_prep.PrepRecord.format_author_field(
                        record.data[Fields.AUTHOR]
                    )
                )
            return record
        return record
