#! /usr/bin/env python
"""SearchSource: OpenCitations"""
from __future__ import annotations

import json
import typing
from pathlib import Path

import requests
from pydantic import Field

import colrev.exceptions as colrev_exceptions
import colrev.package_manager.interfaces
import colrev.package_manager.package_manager
import colrev.package_manager.package_settings
import colrev.record.record
from colrev.constants import Fields
from colrev.constants import RecordState
from colrev.constants import SearchSourceHeuristicStatus
from colrev.constants import SearchType
from colrev.packages.crossref.src import crossref_api

# pylint: disable=unused-argument
# pylint: disable=duplicate-code


class OpenCitationsSearchSource(
    colrev.package_manager.interfaces.SearchSourceInterface
):
    """Forward search based on OpenCitations
    Scope: all included papers with colrev_status in (rev_included, rev_synthesized)
    """

    settings_class = colrev.package_manager.package_settings.DefaultSourceSettings
    endpoint = "colrev.open_citations_forward_search"
    source_identifier = "fwsearch_ref"
    search_types = [SearchType.FORWARD_SEARCH]

    ci_supported: bool = Field(default=True)
    heuristic_status = SearchSourceHeuristicStatus.supported

    def __init__(
        self, *, source_operation: colrev.process.operation.Operation, settings: dict
    ) -> None:
        self.search_source = self.settings_class(**settings)
        self.review_manager = source_operation.review_manager
        self.crossref_api = crossref_api.CrossrefAPI(params={})

    @classmethod
    def get_default_source(cls) -> colrev.settings.SearchSource:
        """Get the default SearchSource settings"""
        return colrev.settings.SearchSource(
            endpoint="colrev.open_citations_forward_search",
            filename=Path("data/search/forward_search.bib"),
            search_type=SearchType.FORWARD_SEARCH,
            search_parameters={
                "scope": {Fields.STATUS: "rev_included|rev_synthesized"}
            },
            comment="",
        )

    def _validate_source(self) -> None:
        """Validate the SearchSource (parameters etc.)"""

        source = self.search_source

        self.review_manager.logger.debug(f"Validate SearchSource {source.filename}")

        assert source.search_type == SearchType.FORWARD_SEARCH

        if "scope" not in source.search_parameters:
            raise colrev_exceptions.InvalidQueryException(
                "Scope required in the search_parameters"
            )

        if (
            source.search_parameters["scope"][Fields.STATUS]
            != "rev_included|rev_synthesized"
        ):
            raise colrev_exceptions.InvalidQueryException(
                "search_parameters/scope/colrev_status must be rev_included|rev_synthesized"
            )

        self.review_manager.logger.debug(f"SearchSource {source.filename} validated")

    def _fw_search_condition(self, *, record: dict) -> bool:
        if Fields.DOI not in record:
            return False

        # rev_included/rev_synthesized required, but record not in rev_included/rev_synthesized
        if (
            Fields.STATUS in self.search_source.search_parameters["scope"]
            and self.search_source.search_parameters["scope"][Fields.STATUS]
            == "rev_included|rev_synthesized"
            and record[Fields.STATUS]
            not in [
                RecordState.rev_included,
                RecordState.rev_synthesized,
            ]
        ):
            return False

        return True

    def _get_forward_search_records(self, *, record_dict: dict) -> list:
        forward_citations = []

        url = f"https://opencitations.net/index/coci/api/v1/citations/{record_dict['doi']}"
        # headers = {"authorization": "YOUR-OPENCITATIONS-ACCESS-TOKEN"}
        headers: typing.Dict[str, str] = {}

        ret = requests.get(url, headers=headers, timeout=300)
        try:
            items = json.loads(ret.text)

            for doi in [x["citing"] for x in items]:
                retrieved_record = self.crossref_api.query_doi(doi=doi)
                # if not crossref_query_return:
                #     raise colrev_exceptions.RecordNotFoundInPrepSourceException()
                retrieved_record.data[Fields.ID] = retrieved_record.data[Fields.DOI]
                forward_citations.append(retrieved_record.data)
        except json.decoder.JSONDecodeError:
            self.review_manager.logger.info(
                f"Error retrieving citations from Opencitations for {record_dict['ID']}"
            )

        return forward_citations

    def search(self, rerun: bool) -> None:
        """Run a forward search based on OpenCitations"""

        # pylint: disable=too-many-branches

        self._validate_source()

        records = self.review_manager.dataset.load_records_dict()

        if not records:
            print("No records imported. Cannot run forward search yet.")
            return

        forward_search_feed = self.search_source.get_api_feed(
            review_manager=self.review_manager,
            source_identifier=self.source_identifier,
            update_only=(not rerun),
        )

        for record in records.values():
            if not self._fw_search_condition(record=record):
                continue

            self.review_manager.logger.info(
                f"Run forward search for {record[Fields.ID]}"
            )

            new_records = self._get_forward_search_records(record_dict=record)

            for new_record in new_records:
                try:
                    new_record["fwsearch_ref"] = (
                        record[Fields.ID] + "_forward_search_" + new_record[Fields.ID]
                    )
                    new_record["cites_IDs"] = record[Fields.ID]
                    retrieved_record = colrev.record.record.Record(new_record)

                    forward_search_feed.add_update_record(
                        retrieved_record=retrieved_record
                    )
                except colrev_exceptions.NotFeedIdentifiableException:
                    continue

        forward_search_feed.save()

        if self.review_manager.dataset.has_record_changes():
            self.review_manager.dataset.create_commit(
                msg="Forward search", script_call="colrev search"
            )

    @classmethod
    def heuristic(cls, filename: Path, data: str) -> dict:
        """Source heuristic for forward searches (OpenCitations)"""

        result = {"confidence": 0.0}

        return result

    @classmethod
    def add_endpoint(
        cls,
        operation: colrev.ops.search.Search,
        params: str,
    ) -> colrev.settings.SearchSource:
        """Add SearchSource as an endpoint"""

        search_source = cls.get_default_source()
        operation.add_source_and_search(search_source)
        return search_source

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
            )
            return records

        raise NotImplementedError

    def prepare(
        self, record: colrev.record.record.Record, source: colrev.settings.SearchSource
    ) -> colrev.record.record.Record:
        """Source-specific preparation for forward searches (OpenCitations)"""
        return record
