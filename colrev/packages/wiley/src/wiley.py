#! /usr/bin/env python
"""SearchSource: Wiley"""
from __future__ import annotations

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


class WileyOnlineLibrarySearchSource(
    colrev.package_manager.interfaces.SearchSourceInterface
):
    """Wiley"""

    settings_class = colrev.package_manager.package_settings.DefaultSourceSettings
    endpoint = "colrev.wiley"
    source_identifier = "url"
    search_types = [SearchType.DB]

    ci_supported: bool = Field(default=False)
    heuristic_status = SearchSourceHeuristicStatus.supported

    db_url = "https://onlinelibrary.wiley.com/"

    def __init__(
        self, *, source_operation: colrev.process.operation.Operation, settings: dict
    ) -> None:
        self.search_source = self.settings_class(**settings)
        self.source_operation = source_operation
        self.review_manager = source_operation.review_manager

    @classmethod
    def heuristic(cls, filename: Path, data: str) -> dict:
        """Source heuristic for Wiley"""

        result = {"confidence": 0.0}

        # Simple heuristic:
        if "eprint = {https://onlinelibrary.wiley.com/doi/pdf/" in data:
            result["confidence"] = 0.7
            return result

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
        """Run a search of Wiley"""

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

    def load(self, load_operation: colrev.ops.load.Load) -> dict:
        """Load the records from the SearchSource file"""

        if self.search_source.filename.suffix == ".bib":
            records = colrev.loader.load_utils.load(
                filename=self.search_source.filename,
                logger=self.review_manager.logger,
                unique_id_field="ID",
            )
            for record_dict in records.values():
                if "eprint" not in record_dict:
                    continue
                record_dict[Fields.FULLTEXT] = record_dict.pop("eprint")
            return records

        raise NotImplementedError

    def prepare(
        self, record: colrev.record.record.Record, source: colrev.settings.SearchSource
    ) -> colrev.record.record.Record:
        """Source-specific preparation for Wiley"""

        if record.data.get(Fields.ENTRYTYPE, "") == "inbook":
            record.rename_field(key=Fields.TITLE, new_key=Fields.CHAPTER)
            record.rename_field(key=Fields.BOOKTITLE, new_key=Fields.TITLE)

        return record
