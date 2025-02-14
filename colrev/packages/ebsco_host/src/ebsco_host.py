#! /usr/bin/env python
"""SearchSource: EBSCOHost"""
from __future__ import annotations

import re
from pathlib import Path

from pydantic import Field

import colrev.package_manager.interfaces
import colrev.package_manager.package_manager
import colrev.package_manager.package_settings
import colrev.record.record
from colrev.constants import Fields
from colrev.constants import FieldValues
from colrev.constants import SearchSourceHeuristicStatus
from colrev.constants import SearchType

# pylint: disable=unused-argument
# pylint: disable=duplicate-code


class EbscoHostSearchSource(colrev.package_manager.interfaces.SearchSourceInterface):
    """EBSCOHost"""

    settings_class = colrev.package_manager.package_settings.DefaultSourceSettings

    endpoint = "colrev.ebsco_host"
    # https://connect.ebsco.com/s/article/
    # What-is-the-Accession-Number-AN-in-EBSCOhost-records?language=en_US
    # Note : ID is the accession number.
    source_identifier = "{{ID}}"
    search_types = [SearchType.DB]

    ci_supported: bool = Field(default=False)
    heuristic_status = SearchSourceHeuristicStatus.supported

    db_url = "https://search.ebscohost.com/"

    def __init__(
        self, *, source_operation: colrev.process.operation.Operation, settings: dict
    ) -> None:
        self.search_source = self.settings_class(**settings)
        self.review_manager = source_operation.review_manager
        self.source_operation = source_operation

    @classmethod
    def heuristic(cls, filename: Path, data: str) -> dict:
        """Source heuristic for EBSCOHost"""

        result = {"confidence": 0.0}

        if data.count("@") >= 1:
            if "URL = {https://search.ebscohost.com/" in data:
                if re.match(r"@.*{\d{17}\,\n", data):
                    result["confidence"] = 1.0

        return result

    @classmethod
    def add_endpoint(
        cls,
        operation: colrev.ops.search.Search,
        params: str,
    ) -> colrev.settings.SearchSource:
        """Add SearchSource as an endpoint"""

        search_source = operation.create_db_source(
            search_source_cls=cls,
            params={},
        )
        operation.add_source_and_search(search_source)
        return search_source

    def search(self, rerun: bool) -> None:
        """Run a search of EbscoHost"""

        if self.search_source.search_type == SearchType.DB:
            self.source_operation.run_db_search(  # type: ignore
                search_source_cls=self.__class__,
                source=self.search_source,
            )
        else:
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
        self,
        record: colrev.record.record_prep.PrepRecord,
        source: colrev.settings.SearchSource,
    ) -> colrev.record.record.Record:
        """Source-specific preparation for EBSCOHost"""

        record.format_if_mostly_upper(Fields.AUTHOR, case=Fields.TITLE)
        record.format_if_mostly_upper(Fields.TITLE, case=Fields.TITLE)

        if record.data.get(Fields.PAGES) == "N.PAG -- N.PAG":
            record.data[Fields.PAGES] = FieldValues.UNKNOWN
        return record
