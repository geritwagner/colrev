#! /usr/bin/env python
"""SearchSource: JSTOR"""
from __future__ import annotations

from pathlib import Path

from pydantic import Field

import colrev.package_manager.interfaces
import colrev.package_manager.package_manager
import colrev.package_manager.package_settings
import colrev.record.record
from colrev.constants import ENTRYTYPES
from colrev.constants import Fields
from colrev.constants import SearchSourceHeuristicStatus
from colrev.constants import SearchType

# pylint: disable=unused-argument
# pylint: disable=duplicate-code


class JSTORSearchSource(colrev.package_manager.interfaces.SearchSourceInterface):
    """JSTOR"""

    settings_class = colrev.package_manager.package_settings.DefaultSourceSettings
    endpoint = "colrev.jstor"
    # pylint: disable=colrev-missed-constant-usage
    source_identifier = "url"
    search_types = [SearchType.DB]

    ci_supported: bool = Field(default=False)
    heuristic_status = SearchSourceHeuristicStatus.supported

    db_url = "http://www.jstor.org"

    def __init__(
        self, *, source_operation: colrev.process.operation.Operation, settings: dict
    ) -> None:
        self.search_source = self.settings_class(**settings)
        self.operation = source_operation
        self.review_manager = source_operation.review_manager

    @classmethod
    def heuristic(cls, filename: Path, data: str) -> dict:
        """Source heuristic for JSTOR"""

        result = {"confidence": 0.1}

        if "www.jstor.org:" in data:
            if data.count("www.jstor.org") > data.count("\n@"):
                result["confidence"] = 1.0
        if data.startswith("Provider: JSTOR http://www.jstor.org"):
            result["confidence"] = 1.0

        return result

    @classmethod
    def add_endpoint(
        cls,
        operation: colrev.ops.search.Search,
        params: str,
    ) -> colrev.settings.SearchSource:
        """Add SearchSource as an endpoint (based on query provided to colrev search --add )"""

        search_source = operation.create_db_source(
            search_source_cls=cls,
            params={},
        )
        operation.add_source_and_search(search_source)
        return search_source

    def search(self, rerun: bool) -> None:
        """Run a search of JSTOR"""

        if self.search_source.search_type == SearchType.DB:
            self.operation.run_db_search(  # type: ignore
                search_source_cls=self.__class__,
                source=self.search_source,
            )
            return

        raise NotImplementedError

    def prep_link_md(
        self,
        prep_operation: colrev.ops.prep.Prep,
        record: colrev.record.record.Record,
        save_feed: bool = True,
        timeout: int = 10,
    ) -> colrev.record.record.Record:
        """Not implemented"""
        return record

    def _load_ris(self) -> dict:

        def id_labeler(records: list) -> None:
            for record_dict in records:
                record_dict[Fields.ID] = record_dict["UR"].split("/")[-1]

        def entrytype_setter(record_dict: dict) -> None:
            if record_dict["TY"] == "JOUR":
                record_dict[Fields.ENTRYTYPE] = "article"
            elif record_dict["TY"] == "RPRT":
                record_dict[Fields.ENTRYTYPE] = "techreport"
            elif record_dict["TY"] == "CHAP":
                record_dict[Fields.ENTRYTYPE] = "inbook"
            else:
                record_dict[Fields.ENTRYTYPE] = "misc"

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
                ENTRYTYPES.INBOOK: {
                    "PY": Fields.YEAR,
                    "AU": Fields.AUTHOR,
                    "TI": Fields.CHAPTER,
                    "T2": Fields.TITLE,
                    "DO": Fields.DOI,
                    "PB": Fields.PUBLISHER,
                    "UR": Fields.URL,
                    "AB": Fields.ABSTRACT,
                    "SN": Fields.ISBN,
                    "A2": Fields.EDITOR,
                },
                ENTRYTYPES.TECHREPORT: {
                    "PY": Fields.YEAR,
                    "AU": Fields.AUTHOR,
                    "TI": Fields.TITLE,
                    "UR": Fields.URL,
                    "PB": Fields.PUBLISHER,
                },
            }

            if record_dict[Fields.ENTRYTYPE] == ENTRYTYPES.ARTICLE:
                if "T1" in record_dict and "TI" not in record_dict:
                    record_dict["TI"] = record_dict.pop("T1")

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

            record_dict.pop("TY", None)
            record_dict.pop("Y2", None)
            record_dict.pop("DB", None)
            record_dict.pop("C1", None)
            record_dict.pop("T3", None)
            record_dict.pop("ER", None)

            for key, value in record_dict.items():
                record_dict[key] = str(value)

        records = colrev.loader.load_utils.load(
            filename=self.search_source.filename,
            id_labeler=id_labeler,
            entrytype_setter=entrytype_setter,
            field_mapper=field_mapper,
            logger=self.review_manager.logger,
        )

        return records

    def load(self, load_operation: colrev.ops.load.Load) -> dict:
        """Load the records from the SearchSource file"""

        if self.search_source.filename.suffix == ".ris":
            return self._load_ris()

        raise NotImplementedError

    def prepare(
        self, record: colrev.record.record.Record, source: colrev.settings.SearchSource
    ) -> colrev.record.record.Record:
        """Source-specific preparation for JSTOR"""

        return record
