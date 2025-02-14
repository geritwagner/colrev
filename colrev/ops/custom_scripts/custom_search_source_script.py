#! /usr/bin/env python
"""Template for a custom SearchSource PackageEndpoint"""
from __future__ import annotations

from pathlib import Path

import colrev.exceptions as colrev_exceptions
import colrev.package_manager.interfaces
import colrev.package_manager.package_settings
import colrev.process.operation
import colrev.record.record
from colrev.constants import Fields


class CustomSearch(colrev.package_manager.interfaces.SearchSourceInterface):
    """Class for custom search scripts"""

    settings_class = colrev.package_manager.package_settings.DefaultSourceSettings
    source_identifier = "custom"

    def __init__(
        self,
        *,
        source_operation: colrev.ops.search.Search,
        settings: dict,
    ) -> None:
        self.search_source: colrev.settings.SearchSource = self.settings_class(
            **settings
        )
        self.review_manager = source_operation.review_manager

    def search(self, rerun: bool) -> None:
        """Run the search"""

        feed = self.search_source.get_api_feed(
            review_manager=self.review_manager,
            source_identifier=self.source_identifier,
            update_only=(not rerun),
        )
        retrieved_record = {
            Fields.ID: "ID00001",
            Fields.ENTRYTYPE: "article",
            Fields.AUTHOR: "Smith, M.",
            Fields.TITLE: "Editorial",
            Fields.JOURNAL: "nature",
            Fields.YEAR: "2020",
        }

        feed.add_update_record(colrev.record.record.Record(retrieved_record))
        feed.save()

    @classmethod
    def validate_search_params(cls, query: str) -> None:
        """Validate the search parameters"""

        if " SCOPE " not in query:
            raise colrev_exceptions.InvalidQueryException(
                "CROSSREF queries require a SCOPE section"
            )

        scope = query[query.find(" SCOPE ") :]
        if "journal_issn" not in scope:
            raise colrev_exceptions.InvalidQueryException(
                "CROSSREF queries require a journal_issn field in the SCOPE section"
            )

    @classmethod
    def heuristic(
        cls, filename: Path, data: str  # pylint: disable=unused-argument
    ) -> dict:
        """Heuristic to identify the custom source"""

        result = {"confidence": 0}

        return result

    def load(
        self,
        load_operation: colrev.ops.load.Load,  # pylint: disable=unused-argument
    ) -> dict:
        """Load fixes for the custom source"""
        records = {"ID1": {"ID": "ID1", "title": "..."}}

        return records

    def prepare(
        self,
        record: colrev.record.record.Record,
        source: colrev.settings.SearchSource,
    ) -> colrev.record.record.Record:
        """Source-specific preparation for the custom source"""

        return record
