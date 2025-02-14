#! /usr/bin/env python
"""SearchSource: Taylor and Francis"""
from __future__ import annotations

import re
from pathlib import Path

from pydantic import Field

import colrev.package_manager.interfaces
import colrev.package_manager.package_manager
import colrev.package_manager.package_settings
import colrev.record.record
from colrev.constants import Fields
from colrev.constants import SearchSourceHeuristicStatus
from colrev.constants import SearchType

# pylint: disable=unused-argument
# pylint: disable=duplicate-code


class TaylorAndFrancisSearchSource(
    colrev.package_manager.interfaces.SearchSourceInterface
):
    """Taylor and Francis"""

    settings_class = colrev.package_manager.package_settings.DefaultSourceSettings
    endpoint = "colrev.taylor_and_francis"
    source_identifier = "{{doi}}"
    search_types = [SearchType.DB]
    ci_supported: bool = Field(default=False)
    heuristic_status = SearchSourceHeuristicStatus.supported

    def __init__(
        self, *, source_operation: colrev.process.operation.Operation, settings: dict
    ) -> None:
        self.search_source = self.settings_class(**settings)
        self.review_manager = source_operation.review_manager
        self.source_operation = source_operation

    @classmethod
    def heuristic(cls, filename: Path, data: str) -> dict:
        """Source heuristic for Taylor and Francis"""

        result = {"confidence": 0.0}

        if data.count("\n@") > 1:
            if data.count("eprint = { \n    \n    ") >= data.count("\n@"):
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
        """Run a search of TaylorAndFrancis"""

        if self.search_source.search_type == SearchType.DB:
            self.source_operation.run_db_search(  # type: ignore
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

    def _load_bib(self) -> dict:
        def field_mapper(record_dict: dict) -> None:
            if "note" in record_dict:
                record_dict[f"{self.endpoint}.note"] = record_dict.pop("note")
            if "eprint" in record_dict:
                record_dict[f"{self.endpoint}.eprint"] = record_dict.pop("eprint")

            for key in list(record_dict.keys()):
                if key not in ["ID", "ENTRYTYPE"]:
                    record_dict[key.lower()] = record_dict.pop(key)

        records = colrev.loader.load_utils.load(
            filename=self.search_source.filename,
            logger=self.review_manager.logger,
            unique_id_field="ID",
            field_mapper=field_mapper,
            format_names=True,
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
        """Source-specific preparation for Taylor and Francis"""

        # remove eprint and URL fields (they only have dois...)
        record.remove_field(key="colrev.taylor_and_francis.eprint")
        if "colrev.taylor_and_francis.note" in record.data and re.match(
            r"PMID: \d*", record.data["colrev.taylor_and_francis.note"]
        ):
            record.rename_field(
                key="colrev.taylor_and_francis.note", new_key=Fields.PUBMED_ID
            )
            record.data[Fields.PUBMED_ID] = record.data[Fields.PUBMED_ID][6:]

        return record
