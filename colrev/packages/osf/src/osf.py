#!/usr/bin/env python3
"""Searchsource:OSF"""
from __future__ import annotations

import typing
from pathlib import Path

from pydantic import Field

import colrev.env.environment_manager
import colrev.loader.load_utils
import colrev.ops.load
import colrev.ops.prep
import colrev.ops.search
import colrev.ops.search_api_feed
import colrev.package_manager.interfaces
import colrev.package_manager.package_manager
import colrev.package_manager.package_settings
import colrev.packages.osf.src.osf_api
import colrev.process.operation
import colrev.record.record
import colrev.record.record_prep
import colrev.review_manager
import colrev.settings
from colrev.constants import Fields
from colrev.constants import SearchSourceHeuristicStatus
from colrev.constants import SearchType
from colrev.packages.osf.src.osf_api import OSFApiQuery

# pylint: disable=unused-argument
# pylint: disable=duplicate-code


class OSFSearchSource(colrev.package_manager.interfaces.SearchSourceInterface):
    """OSF"""

    settings_class = colrev.package_manager.package_settings.DefaultSourceSettings

    source_identifier = Fields.ID
    search_types = [SearchType.API]
    endpoint = "colrev.osf"

    ci_supported: bool = Field(default=True)
    heuristic_status = SearchSourceHeuristicStatus.oni

    db_url = "https://osf.io/"
    SETTINGS = {
        "api_key": "packages.search_source.colrev.osf.api_key",
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
                filename=Path("data/search/osf.bib"),
                search_type=SearchType.API,
                search_parameters={},
                comment="",
            )
            self.source_operation = source_operation

    @classmethod
    def heuristic(cls, filename: Path, data: str) -> dict:
        """Source heuristic for OSF"""

        result = {"confidence": 0.1}

        return result

    @classmethod
    def add_endpoint(
        cls, operation: colrev.ops.search.Search, params: str
    ) -> colrev.settings.SearchSource:
        """Add SearchSource as an endpoint (based on query provided to colrev search -a)"""

        params_dict: typing.Dict[str, str] = {}
        if params and isinstance(params, str) and params.startswith("http"):
            params_dict = {Fields.URL: params}

        # Select the search type based on the provided parameters
        search_type = operation.select_search_type(
            search_types=cls.search_types, params={"query": params_dict}
        )

        # Handle different search types
        if search_type == SearchType.API:
            # Check for params being empty and initialize if needed
            if len(params_dict) == 0:
                search_source = operation.create_api_source(endpoint=cls.endpoint)
                # Search title per default (other fields may be supported later)
                search_source.search_parameters["query"] = {
                    "title": search_source.search_parameters["query"]
                }
            elif "https://api.osf.io/v2/nodes/?filter" in params_dict.get("url", ""):
                query = (
                    params_dict["url"]
                    .replace("https://api.osf.io/v2/nodes/?filter", "")
                    .lstrip("&")
                )

                parameter_pairs = query.split("&")
                search_parameters = {
                    key.lstrip("[").rstrip("]"): value
                    for key, value in (pair.split("=") for pair in parameter_pairs)
                }
                last_value = list(search_parameters.values())[-1]
                filename = operation.get_unique_filename(
                    file_path_string=f"osf_{last_value}"
                )
                search_source = colrev.settings.SearchSource(
                    endpoint=cls.endpoint,
                    filename=filename,
                    search_type=SearchType.API,
                    search_parameters={"query": search_parameters},
                    comment="",
                )
        else:
            raise NotImplementedError("Unsupported search type.")

        # Adding the source and performing the search
        operation.add_source_and_search(search_source)
        return search_source

    def _get_api_key(self) -> str:
        api_key = self.review_manager.environment_manager.get_settings_by_key(
            self.SETTINGS["api_key"]
        )
        if api_key is None or len(api_key) == 0:
            api_key = input("Please enter api key: ")
            self.review_manager.environment_manager.update_registry(
                self.SETTINGS["api_key"], api_key
            )
        return api_key

    def search(self, rerun: bool) -> None:
        """Run a search of OSF"""
        osf_feed = self.search_source.get_api_feed(
            review_manager=self.review_manager,
            source_identifier=self.source_identifier,
            update_only=(not rerun),
        )
        self._run_api_search(osf_feed=osf_feed, rerun=rerun)

    def _run_api_search(
        self, osf_feed: colrev.ops.search_api_feed.SearchAPIFeed, rerun: bool
    ) -> None:

        api = OSFApiQuery(
            parameters=self.search_source.search_parameters["query"],
            api_key=self._get_api_key(),
        )
        self.review_manager.logger.info(f"Retrieve {api.overall()} records")

        while True:
            for record_dict in api.retrieve_records():
                record = colrev.record.record.Record(record_dict)
                osf_feed.add_update_record(record)

            if api.pages_completed():
                break

        osf_feed.save()

    def prep_link_md(
        self,
        prep_operation: colrev.ops.prep.Prep,
        record: colrev.record.record.Record,
        save_feed: bool = True,
        timeout: int = 60,
    ) -> colrev.record.record.Record:
        """Not implemented"""

        return record

    def prepare(
        self,
        record: colrev.record.record_prep.PrepRecord,
        source: colrev.settings.SearchSource,
    ) -> colrev.record.record.Record:
        """Needs manual preparation"""

        return record

    def load(self, load_operation: colrev.ops.load.Load) -> dict:
        """Load the records."""

        if self.search_source.filename.suffix == ".bib":
            records = colrev.loader.load_utils.load(
                filename=self.search_source.filename,
                logger=load_operation.review_manager.logger,
                unique_id_field="ID",
            )
            return records

        raise NotImplementedError
