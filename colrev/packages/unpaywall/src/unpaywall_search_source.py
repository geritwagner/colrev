#! /usr/bin/env python
"""SearchSource: Unpaywall"""
from __future__ import annotations

import typing
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

import requests
import zope.interface
from dacite import from_dict
from dataclasses_jsonschema import JsonSchemaMixin

import colrev.exceptions as colrev_exceptions
from colrev.constants import SearchSourceHeuristicStatus, SearchType
import colrev.exceptions as colrev_exceptions
import colrev.package_manager.interfaces
import colrev.package_manager.package_manager
import colrev.package_manager.package_settings
from colrev.constants import Fields
import colrev.record.record

from colrev.constants import ENTRYTYPES
from colrev.constants import Fields
from colrev.constants import SearchSourceHeuristicStatus
from colrev.constants import SearchType
from colrev.packages.unpaywall.src import utils


@zope.interface.implementer(colrev.package_manager.interfaces.SearchSourceInterface)
@dataclass
class UnpaywallSearchSource(JsonSchemaMixin):
    """Unpaywall Search Source"""

    settings_class = colrev.package_manager.package_settings.DefaultSourceSettings
    source_identifier = "ID"
    search_types = [SearchType.API]
    endpoint = "colrev.unpaywall"

    ci_supported: bool = False
    heuristic_status = SearchSourceHeuristicStatus.oni
    # docs_link

    short_name = "Unpaywall"

    
    """API_FIELDS = [
        "data_standard",
        "doi",
        "doi_url",
        "genre",
        "is_paratext",
        "is_oa",
        "journal_is_in_doaj",
        "journal_is_oa",
        "journal_issns",
        "journal_issn_l",
        "journal_name",
        "oa_status",
        "has_repository_copy",
        "published_date",
        "publisher",
        "title",
        "updated",
        "year",
        "z_authors",
    ]"""

    ENTRYTYPE_MAPPING = {
        "journal-article": ENTRYTYPES.ARTICLE,
        "book": ENTRYTYPES.BOOK,
        "proceedings-article": ENTRYTYPES.INPROCEEDINGS,
        "book-chapter": ENTRYTYPES.INBOOK,
        "conference": ENTRYTYPES.CONFERENCE,
        "dissertation": ENTRYTYPES.PHDTHESIS,
        "report": ENTRYTYPES.TECHREPORT,
        "other": ENTRYTYPES.MISC
    }

    def __init__(
        self,
        *,
        source_operation: colrev.process.operation.Operation,
        settings: typing.Optional[dict] = None,
    ) -> None:
        self.review_manager = source_operation.review_manager
        if settings:
            # Unpaywall as a search_source
            self.search_source = from_dict(
                data_class=self.settings_class, data=settings
            )
        else:
            self.search_source = colrev.settings.SearchSource(
                endpoint=self.endpoint,
                filename=Path("data/search/unpaywall.bib"),
                search_type=SearchType.API,
                search_parameters={},
                comment="",
            )

    @classmethod
    def heuristic(cls, filename: Path, data: str) -> dict:
        """Source heuristic for Unpaywall"""
        # Not yet implemented
        result = {"confidence": 0.0}
        return result

    @classmethod
    def add_endpoint(
        cls, operation: colrev.ops.search.Search, params: dict
    ) -> colrev.settings.SearchSource:
        #"""Add SearchSource as an endpoint (based on query provided to colrev search -a )"""
        #"""Typically called for automated searches when running “colrev search -a SOURCE_NAME” to add search and query."""
        #"""Not implemented"""

        params_dict = {}
        if params:
            if params.startswith("http"):
                params_dict = {Fields.URL: params}
            else:
                for item in params.split("&"): # TODO figurte our what happens with the first part 	https://api.unpaywall.org/v2/search? 
                    key, value = item.split("=")
                    params_dict[key] = value
        
        search_type = operation.select_search_type(
            search_types=cls.search_types, params=params_dict
        )

        if search_type == SearchType.API:
            if len(params) == 0: 
                add_source = operation.add_api_source(search_source_cls=cls, params=params)
                return add_source

            # TODO: delete one of the following "url", depending on the occurrence
            elif "https://api.unpaywall.org/v2/request?" or "https://api.unpaywall.org/v2/search?" in params_dict["url"]: # api.unpaywall.org/my/request?email=YOUR_EMAIL or [...].org/v2/search?query=:your_query[&is_oa=boolean][&page=integer]
                url_parsed = urllib.parse.urlparse(params_dict["url"])  
                new_query = urllib.parse.parse_qs(url_parsed.query)
                search_query = new_query.get("query", [""])[0]   
                is_oa = new_query.get("is_oa", [""])[0] 
                page = new_query.get("page", [""])[0] 
                # email = new_query.get("email", ["fillermail@thathastobechangedordeleted.net"])[0] # TODO: how to handle E-Mail? Save it? (I guess not, because it is not needed for the search itself)

                filename = operation.get_unique_filename(file_path_string=f"unpaywall_{search_query}")
                search_source = colrev.settings.SearchSource(
                    endpoint=cls.endpoint,
                    filename=filename, 
                    search_type=SearchType.API,
                    search_parameters={"query": search_query, "is_oa": is_oa, "page": page},
                    comment="",
                )
        elif search_type == SearchType.DB: 
            search_source = operation.create_db_source(
                search_source_cls=cls,
                params=params_dict,
            )

        else:
            raise colrev_exceptions.PackageParameterError(
                f"Cannot add UNPAYWALL endpoint with query {params}"
            )
        
        operation.add_source_and_search(search_source)
        
    def add_endpoint(cls, operation: colrev.ops.search.Search, params: str) -> None:
        """Add SearchSource as an endpoint (based on query provided to colrev search -a )"""

        params_dict = {}
        if params:
            if params.startswith("http"):
                params_dict = {Fields.URL: params}
            else:
                for item in params.split(";"):
                    key, value = item.split("=")
                    params_dict[key] = value

        if len(params_dict) == 0:
            search_source = operation.create_api_source(endpoint=cls.endpoint)

        # pylint: disable=colrev-missed-constant-usage
        elif "https://api.unpaywall.org/v2/search?" in params_dict["url"]:
            query = (
                params_dict["url"]
                .replace("https://api.unpaywall.org/v2/search?", "")
                .lstrip("&")
            )

            parameter_pairs = query.split("&")
            search_parameters = {}
            for parameter in parameter_pairs:
                key, value = parameter.split("=")
                search_parameters[key] = value

            filename = operation.get_unique_filename(file_path_string="unpaywall")

            search_source = colrev.settings.SearchSource(
                endpoint=cls.endpoint,
                filename=filename,
                search_type=SearchType.API,
                search_parameters=search_parameters,
                comment="",
            )
        else:
            raise NotImplementedError

        operation.add_source_and_search(search_source)

    def _run_api_search(
        self, *, unpaywall_feed: colrev.ops.search_api_feed.SearchAPIFeed, rerun: bool
    ) -> None:
        for record in self.get_query_records():
            unpaywall_feed.add_update_record(record)

        unpaywall_feed.save()

    def get_query_records(self) -> typing.Iterator[colrev.record.record.Record]:
        """Get the records from a query"""
        full_url = self._build_search_url()
        response = requests.get(full_url, timeout=90)
        if response.status_code != 200:
            return

        with open("test.json", "wb") as file:
            file.write(response.content)
        data = response.json()

        if "results" not in data:
            raise colrev_exceptions.ServiceNotAvailableException(
                f"Could not reach API. Status Code: {response.status_code}"
            )

        for result in data["results"]:
            article = result["response"]
            record = self._create_record(article)
            yield record

    def _get_authors(self, article: dict) -> typing.List[str]:
        authors = []
        z_authors = article.get("z_authors", [])
        if z_authors:
            for author in z_authors:
                given_name = author.get("given", "")
                family_name = author.get("family", "")
                authors.append(f"{family_name}, {given_name}")
        return authors

    def _create_record(self, article: dict) -> colrev.record.record.Record:
        record_dict = {Fields.ID: article["doi"]}

        entrytype = self.ENTRYTYPE_MAPPING.get(
            article.get("genre", "other"), ENTRYTYPES.MISC
        )
        record_dict[Fields.ENTRYTYPE] = entrytype

        record_dict[Fields.AUTHOR] = " and ".join(self._get_authors(article))
        record_dict[Fields.TITLE] = article.get("title", "")
        record_dict[Fields.YEAR] = article.get("year", "")

        if entrytype == ENTRYTYPES.ARTICLE:
            record_dict[Fields.JOURNAL] = article.get("journal_name", "")
        elif entrytype == ENTRYTYPES.BOOK:
            record_dict[Fields.PUBLISHER] = article.get("publisher", "")
        elif entrytype == ENTRYTYPES.INPROCEEDINGS:
            record_dict[Fields.BOOKTITLE] = article.get("booktitle", "")
        elif entrytype == ENTRYTYPES.INBOOK:
            record_dict[Fields.BOOKTITLE] = article.get("booktitle", "")
            record_dict[Fields.PUBLISHER] = article.get("publisher", "")
        elif entrytype == ENTRYTYPES.CONFERENCE:
            record_dict[Fields.BOOKTITLE] = article.get("booktitle", "")
        elif entrytype == ENTRYTYPES.PHDTHESIS:
            record_dict[Fields.SCHOOL] = article.get("school", "")  # oder publisher?
        elif entrytype == ENTRYTYPES.TECHREPORT:
            record_dict[Fields.INSTITUTION] = article.get(
                "publisher", ""
            )  # habe hier als default publisher, richtig?

        record = colrev.record.record.Record(record_dict)

        return record

    def _build_search_url(self) -> str:
        url = "https://api.unpaywall.org/v2/search?"
        params = self.search_source.search_parameters
        query = params["query"]
        is_oa = params.get("is_oa", "null")
        page = params.get("page", 1)
        email = params.get("email", utils.get_email(self.review_manager))

        return f"{url}query={query}&is_oa={is_oa}&page={page}&email={email}"

    def search(self, rerun: bool) -> None:
        """Run a search of Unpaywall"""

        unpaywall_feed = self.search_source.get_api_feed(
            review_manager=self.review_manager,
            source_identifier=self.source_identifier,
            update_only=(not rerun),
        )

        if self.search_source.search_type == SearchType.API:
            self._run_api_search(unpaywall_feed=unpaywall_feed, rerun=rerun)
        else:
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

    def prep_link_md(
        self,
        prep_operation: colrev.ops.prep.Prep,
        record: colrev.record.record.Record,
        save_feed: bool = True,
        timeout: int = 10,
    ) -> colrev.record.record.Record:
        """Not implemented"""
        return record

    def prepare(
        self, record: colrev.record.record.Record, source: colrev.settings.SearchSource
    ) -> colrev.record.record.Record:
        """Source-specific preparation for Unpaywall"""
        """Not implemented"""
        return record
        return record
