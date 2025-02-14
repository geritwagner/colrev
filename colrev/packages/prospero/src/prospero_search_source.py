#!/usr/bin/env python
"""SearchSource: PROSPERO

A CoLRev SearchSource plugin to scrape and import records from PROSPERO.
"""
from __future__ import annotations

import typing
from pathlib import Path

from pydantic import Field

import colrev.exceptions as colrev_exceptions
import colrev.loader.load_utils
import colrev.ops.load
import colrev.ops.search_api_feed
import colrev.package_manager.interfaces
import colrev.package_manager.package_settings
import colrev.packages.prospero.src.prospero_api
import colrev.process
import colrev.settings
from colrev.constants import Fields
from colrev.constants import SearchSourceHeuristicStatus
from colrev.constants import SearchType
from colrev.ops.search import Search
from colrev.settings import SearchSource


class ProsperoSearchSource(colrev.package_manager.interfaces.SearchSourceInterface):
    """Prospero Search Source for retrieving protocol data"""

    settings_class = colrev.package_manager.package_settings.DefaultSourceSettings
    endpoint = "colrev.prospero"
    source_identifier = Fields.PROSPERO_ID

    search_types = [SearchType.API]
    heuristic_status = SearchSourceHeuristicStatus.supported
    ci_supported: bool = Field(default=True)
    db_url = "https://www.crd.york.ac.uk/prospero/"

    def __init__(
        self,
        *,
        source_operation: colrev.process.operation.Operation,
        settings: typing.Optional[dict] = None,
    ) -> None:
        """Initialize the ProsperoSearchSource plugin."""

        self.search_source = self._get_search_source(settings)
        self.review_manager = source_operation.review_manager
        self.operation = source_operation

        # TODO: check the following:
        self.search_word: typing.Optional[str] = None

    def _get_search_source(
        self, settings: typing.Optional[dict]
    ) -> colrev.settings.SearchSource:
        """Retrieve and configure the search source based on provided settings."""
        if settings:
            return self.settings_class(**settings)

        fallback_filename = Path("data/search/prospero.bib")
        return SearchSource(
            endpoint="colrev.prospero",
            filename=fallback_filename,
            search_type=SearchType.API,
            search_parameters={},
            comment="fallback search_source",
        )

    @classmethod
    def add_endpoint(
        cls, operation: Search, params: str
    ) -> colrev.settings.SearchSource:
        """Adds Prospero as a search source endpoint based on user-provided parameters."""
        if len(params) == 0:
            search_source = operation.create_api_source(endpoint=cls.endpoint)
            search_source.search_parameters[Fields.URL] = (
                cls.db_url + "search?" + "#searchadvanced"
            )
            search_source.search_parameters["version"] = "0.1.0"
            operation.add_source_and_search(search_source)
            return search_source

        query = {"query": params}
        filename = operation.get_unique_filename(file_path_string="prospero_results")

        new_search_source = SearchSource(
            endpoint=cls.endpoint,
            filename=filename,
            search_type=SearchType.API,
            search_parameters=query,
            comment="Search source for Prospero protocols",
        )
        operation.add_source_and_search(new_search_source)
        return new_search_source

    # pylint: disable=unused-argument
    @classmethod
    def heuristic(cls, filename: Path, data: str) -> dict:
        """Source heuristic for Prospero."""

        result = {"confidence": 0.0}
        return result

    def _validate_source(self) -> None:
        """Minimal source validation."""
        if not self.search_source:
            raise colrev_exceptions.InvalidQueryException("No search_source available.")
        if self.search_source.search_type not in self.search_types:
            raise colrev_exceptions.InvalidQueryException(
                f"Prospero search_type must be one of {self.search_types}, "
                f"not {self.search_source.search_type}"
            )
        if self.review_manager.logger:
            self.review_manager.logger.debug(
                "Validate SearchSource %s", self.search_source.filename
            )

    def get_search_word(self) -> str:
        """
        Get the search query from settings or prompt the user.
        If there's no 'query' in the search_parameters, we ask the user.
        """
        if self.search_word is not None:
            return self.search_word

        if "query" in (self.search_source.search_parameters or {}):
            self.search_word = self.search_source.search_parameters["query"]
            self.review_manager.logger.debug(
                "Using query from search_parameters: %s", self.search_word
            )
        else:
            self.search_word = input("Enter your search query: ").strip()
            self.review_manager.logger.debug(
                "Using user-input query: %s", self.search_word
            )

        return self.search_word

    def run_api_search(
        self, *, prospero_feed: colrev.ops.search_api_feed.SearchAPIFeed, rerun: bool
    ) -> None:
        """Add newly scraped records to the feed."""
        if rerun and self.review_manager:
            self.review_manager.logger.info(
                "Performing a search of the full history (may take time)"
            )

        search_word = self.get_search_word()
        self.review_manager.logger.info("Prospero search with query: %s", search_word)

        prospero_api = colrev.packages.prospero.src.prospero_api.PROSPEROAPI(
            search_word, logger=self.review_manager.logger
        )

        for record_dict in prospero_api.get_next_record():
            self.review_manager.logger.info(
                f"retrieve record: {record_dict[Fields.URL]}"
            )

            try:
                if not record_dict.get(Fields.AUTHOR, "") and not record_dict.get(
                    Fields.TITLE, ""
                ):
                    continue
                prep_record = colrev.record.record_prep.PrepRecord(record_dict)
                prospero_feed.add_update_record(prep_record)
            except colrev_exceptions.NotFeedIdentifiableException:
                continue

        prospero_feed.save()

    def search(self, rerun: bool) -> None:
        """Scrape Prospero using Selenium, save .bib file with results."""

        self._validate_source()

        prospero_feed = self.search_source.get_api_feed(
            review_manager=self.review_manager,
            source_identifier=self.source_identifier,
            update_only=False,
        )

        self.run_api_search(prospero_feed=prospero_feed, rerun=rerun)

    # pylint: disable=unused-argument
    def prep_link_md(
        self,
        prep_operation: typing.Any,
        record: colrev.record.record.Record,
        save_feed: bool = True,
        timeout: int = 10,
    ) -> colrev.record.record.Record:
        """Empty method as requested."""
        return record

    def _load_bib(self) -> dict:
        """Helper to load from .bib file using CoLRev's load_utils."""
        return colrev.loader.load_utils.load(
            filename=self.search_source.filename,
            logger=self.review_manager.logger,
            unique_id_field="ID",
        )

    # pylint: disable=unused-argument
    def load(self, load_operation: colrev.ops.load.Load) -> dict:
        """
        The interface requires a load method.
        We only handle .bib files here,
        so we raise NotImplementedError for other formats.
        """
        if self.search_source.filename.suffix == ".bib":
            return self._load_bib()
        raise NotImplementedError(
            "Only .bib loading is implemented for ProsperoSearchSource."
        )

    # pylint: disable=unused-argument
    def prepare(
        self,
        record: colrev.record.record_prep.PrepRecord,
        source: colrev.settings.SearchSource,
    ) -> colrev.record.record_prep.PrepRecord:
        """Map fields to standardized fields for CoLRev (matching interface signature)."""
        return record
