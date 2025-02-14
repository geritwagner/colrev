#! /usr/bin/env python
"""SearchSource: Springer Link"""
from __future__ import annotations

import re
import typing
import urllib.parse
from pathlib import Path

import inquirer
import pandas as pd
import requests
from pydantic import Field

import colrev.exceptions as colrev_exceptions
import colrev.package_manager.interfaces
import colrev.package_manager.package_manager
import colrev.package_manager.package_settings
import colrev.record.record
import colrev.settings
from colrev.constants import Colors
from colrev.constants import ENTRYTYPES
from colrev.constants import Fields
from colrev.constants import SearchSourceHeuristicStatus
from colrev.constants import SearchType

# pylint: disable=unused-argument
# pylint: disable=duplicate-code

# Note : API requires registration
# https://dev.springernature.com/


class SpringerLinkSearchSource(colrev.package_manager.interfaces.SearchSourceInterface):
    """Springer Link"""

    settings_class = colrev.package_manager.package_settings.DefaultSourceSettings

    endpoint = "colrev.springer_link"
    # pylint: disable=colrev-missed-constant-usage
    source_identifier = "url"
    search_types = [SearchType.DB, SearchType.API]

    ci_supported: bool = Field(default=False)
    heuristic_status = SearchSourceHeuristicStatus.supported

    SETTINGS = {
        "api_key": "packages.search_source.colrev.springer_link.api_key",
    }
    db_url = "https://link.springer.com/"

    def __init__(
        self, *, source_operation: colrev.process.operation.Operation, settings: dict
    ) -> None:
        self.review_manager = source_operation.review_manager
        self.search_source = self.settings_class(**settings)
        self.quality_model = self.review_manager.get_qm()
        self.source_operation = source_operation
        self.language_service = colrev.env.language_service.LanguageService()

    @classmethod
    def heuristic(cls, filename: Path, data: str) -> dict:
        """Source heuristic for Springer Link"""

        result = {"confidence": 0.0}

        if filename.suffix == ".csv":
            if data.count("http://link.springer.com") > data.count("\n") - 2:
                result["confidence"] = 1.0
                return result

        # Note : no features in bib file for identification

        return result

    @classmethod
    def add_endpoint(
        cls,
        operation: colrev.ops.search.Search,
        params: str,
    ) -> colrev.settings.SearchSource:
        """Add SearchSource as an endpoint (based on query provided to colrev search --add )"""

        params_dict: dict[str, str] = {}
        search_type = operation.select_search_type(
            search_types=cls.search_types, params=params_dict
        )

        if search_type == SearchType.DB:
            search_source = operation.create_db_source(
                search_source_cls=cls,
                params={},
            )

        elif search_type == SearchType.API:
            filename = operation.get_unique_filename(file_path_string="springer_link")
            search_source = colrev.settings.SearchSource(
                endpoint=cls.endpoint,
                filename=filename,
                search_type=SearchType.API,
                search_parameters={},
                comment="",
            )
            params_dict.update(vars(search_source))
            instance = cls(source_operation=operation, settings=params_dict)
            instance.api_ui()
            search_source.search_parameters = instance._add_constraints()

        else:
            raise NotImplementedError

        operation.add_source_and_search(search_source)
        return search_source

    def search(self, rerun: bool) -> None:
        """Run a search of SpringerLink"""

        if self.search_source.search_type == SearchType.DB:
            self.source_operation.run_db_search(  # type: ignore
                search_source_cls=self.__class__,
                source=self.search_source,
            )
            return

        if self.search_source.search_type == SearchType.API:
            springer_feed = self.search_source.get_api_feed(
                review_manager=self.review_manager,
                source_identifier=self.source_identifier,
                update_only=(not rerun),
            )
            self._run_api_search(springer_feed=springer_feed, rerun=rerun)
            return

        raise NotImplementedError

    def _add_constraints(self) -> dict:
        """add constraints for API query"""
        complex_query_prompt = [
            inquirer.List(
                name="complex_query",
                message="Select how the search will be entered",
                choices=["interactively", "complete_search_string"],
            ),
        ]

        answers = inquirer.prompt(complex_query_prompt)

        if answers["complex_query"] == "complete_search_string":
            query = input("Please enter your search string: ")
            search_parameters = {"query": query}

        else:

            print(
                "Please enter your search parameter for the following constraints"
                + "(or just press enter to continue):"
            )
            keyword = input("keyword: ")
            subject_choices = [
                inquirer.Checkbox(
                    name="subject",
                    message="Select subject(s) or press Enter to skip:",
                    choices=[
                        "Astronomy",
                        "Behavioral Sciences",
                        "Biomedical Sciences",
                        "Business and Management",
                        "Chemistry",
                        "Climate",
                        "Computer Science",
                        "Earth Sciences",
                        "Economics",
                        "Education and Language",
                        "Energy",
                        "Engineering",
                        "Environmental Sciences",
                        "Food Science and Nutrition",
                        "General Interest",
                        "Geography",
                        "Law",
                        "Life Sciences",
                        "Materials",
                        "Mathematics",
                        "Medicine",
                        "Philosophy",
                        "Physics",
                        "Public Health",
                        "Social Sciences",
                        "Statistics",
                        "Water",
                    ],
                ),
            ]
            answers = inquirer.prompt(subject_choices)
            subject = ",".join(answers["subject"])

            language_choices = [
                inquirer.Checkbox(
                    name="language",
                    message="Select language(s) or press Enter to skip:",
                    choices=[
                        "en",
                        "de",
                        "fr",
                        "es",
                        "it",
                        "pt",
                        "nl",
                    ],
                ),
            ]
            answers = inquirer.prompt(language_choices)
            language = ",".join(answers["language"])

            year_choices = [
                inquirer.Text(
                    name="year",
                    message="Select year(s) or press Enter to skip:",
                    validate=self._is_year,
                ),
            ]
            answers = inquirer.prompt(year_choices)
            year = answers["year"]

            doc_type_choices = [
                inquirer.Checkbox(
                    name="doc_type",
                    message="Select doc_type(s) or press Enter to skip:",
                    choices=["Journal", "Book"],
                ),
            ]
            answers = inquirer.prompt(doc_type_choices)
            doc_type = ",".join(answers["doc_type"])

            search_parameters = {
                "subject": subject,
                "keyword": keyword,
                "language": language,
                "year": year,
                "type": doc_type,
            }

        return search_parameters

    def build_query(self, search_parameters: dict) -> str:
        """build API query"""

        if "query" in search_parameters:
            query = search_parameters["query"]

        else:
            constraints = []
            for key, value in search_parameters.items():
                if value == "":
                    continue

                if key in ["subject", "language", "doc_type"]:

                    subject_query = (
                        f'{key}:"'
                        + f'" OR {key}:"'.join(value for value in value.split(","))
                        + '"'
                    )
                    constraints.append(f"({subject_query})")
                    continue

                if value:
                    constraints.append(f'{key}:"{value}"')

            query = " AND ".join(constraints)

        return urllib.parse.quote(query)

    def _build_api_search_url(self, query: str, api_key: str, start: int = 1) -> str:
        return f"https://api.springernature.com/meta/v2/json?q={query}&api_key={api_key}&s={start}"

    def get_query_return(self) -> typing.Iterator[colrev.record.record.Record]:
        """Get the records from a API search"""
        query = self.build_query(self.search_source.search_parameters)
        api_key = self.get_api_key()
        start = 1

        while True:
            full_url = self._build_api_search_url(
                query=query, api_key=api_key, start=start
            )
            response = requests.get(full_url, timeout=10)
            if response.status_code != 200:
                print(
                    f"Error - API search failed for the following reason: {response.status_code}"
                )
                return

            data = response.json()

            for record in data.get("records", []):
                yield self._create_record(record)

            next_page = data.get("nextPage")
            if not next_page:
                break

            start_str = next_page.split("s=")[1].split("&")[0]
            start = int(start_str)

    def _run_api_search(
        self, springer_feed: colrev.ops.search_api_feed.SearchAPIFeed, rerun: bool
    ) -> None:
        """save API search results"""
        for record in self.get_query_return():
            springer_feed.add_update_record(record)

        springer_feed.save()

    def _create_record(self, doc: dict) -> colrev.record.record.Record:
        """Fieldmapper API search"""
        record_dict = {Fields.ID: doc["identifier"]}
        record_dict[Fields.ENTRYTYPE] = "misc"

        if "Article" in doc["contentType"]:
            record_dict[Fields.ENTRYTYPE] = "article"
        elif "Chapter" in doc["contentType"]:
            record_dict[Fields.ENTRYTYPE] = "inproceedings"
        elif "Book" in doc["contentType"]:
            record_dict[Fields.ENTRYTYPE] = "book"

        record_dict.update(
            {
                Fields.AUTHOR: " and ".join(
                    creator.get("creator", "") for creator in doc.get("creators", [])
                ),
                Fields.TITLE: doc.get("title", ""),
                Fields.PUBLISHER: doc.get("publisher", ""),
                Fields.BOOKTITLE: (
                    doc.get("publicationName", "")
                    if doc.get("publicationType") == "Book"
                    else ""
                ),
                Fields.JOURNAL: (
                    doc.get("publicationName", "")
                    if doc.get("publicationType") == "Journal"
                    else ""
                ),
                Fields.YEAR: (
                    doc.get("publicationDate", "").split("-")[0]
                    if doc.get("publicationDate")
                    else ""
                ),
                Fields.VOLUME: doc.get("volume", ""),
                Fields.NUMBER: doc.get("number", ""),
                Fields.PAGES: (
                    f"{doc.get('startingPage', '')}-{doc.get('endingPage', '')}"
                    if doc.get("startingPage") and doc.get("endingPage")
                    else ""
                ),
                Fields.DOI: doc.get("doi", ""),
                Fields.URL: next(
                    (
                        url.get("value", "")
                        for url in doc.get("url", [])
                        if url.get("format") == "html"
                    ),
                    doc.get("url", [{}])[0].get("value", "") if doc.get("url") else "",
                ),
            }
        )

        record = colrev.record.record.Record(data=record_dict)
        if Fields.LANGUAGE in record.data:
            try:
                record.data[Fields.LANGUAGE] = record.data[Fields.LANGUAGE][0]
                self.language_service.unify_to_iso_639_3_language_codes(record=record)
            except colrev_exceptions.InvalidLanguageCodeException:
                del record.data[Fields.LANGUAGE]
        return record

    def prep_link_md(
        self,
        prep_operation: colrev.ops.prep.Prep,
        record: colrev.record.record.Record,
        save_feed: bool = True,
        timeout: int = 10,
    ) -> colrev.record.record.Record:
        """Not implemented"""
        return record

    def _load_csv(self) -> dict:
        def entrytype_setter(record_dict: dict) -> None:
            if record_dict["Content Type"] == "Article":
                record_dict[Fields.ENTRYTYPE] = ENTRYTYPES.ARTICLE
            elif record_dict["Content Type"] == "Book":
                record_dict[Fields.ENTRYTYPE] = ENTRYTYPES.BOOK
            elif record_dict["Content Type"] == "Chapter":
                record_dict[Fields.ENTRYTYPE] = ENTRYTYPES.INBOOK
            else:
                record_dict[Fields.ENTRYTYPE] = "misc"

        def field_mapper(record_dict: dict) -> None:
            record_dict[Fields.TITLE] = record_dict.pop("Item Title", "")
            if record_dict[Fields.ENTRYTYPE] == ENTRYTYPES.ARTICLE:
                record_dict[Fields.JOURNAL] = record_dict.pop("Publication Title", "")
            elif record_dict[Fields.ENTRYTYPE] == ENTRYTYPES.BOOK:
                record_dict[Fields.BOOKTITLE] = record_dict.pop("Book Series Title", "")
            elif record_dict[Fields.ENTRYTYPE] == ENTRYTYPES.INBOOK:
                record_dict[Fields.CHAPTER] = record_dict.pop("Item Title", "")
                record_dict[Fields.TITLE] = record_dict.pop("Publication Title", "")
            record_dict[Fields.VOLUME] = record_dict.pop("Journal Volume", "")
            record_dict[Fields.NUMBER] = record_dict.pop("Journal Issue", "")
            record_dict[Fields.DOI] = record_dict.pop("Item DOI", "")
            record_dict[Fields.AUTHOR] = record_dict.pop("Authors", "")
            record_dict[Fields.YEAR] = record_dict.pop("Publication Year", "")
            record_dict[Fields.URL] = record_dict.pop("URL", "")
            record_dict.pop("Content Type", None)

            # Fix authors
            # pylint: disable=colrev-missed-constant-usage
            if Fields.AUTHOR in record_dict:
                # a-bd-z: do not match McDonald
                record_dict[Fields.AUTHOR] = re.sub(
                    r"([a-bd-z]{1})([A-Z]{1})",
                    r"\g<1> and \g<2>",
                    record_dict["author"],
                )

            for key in list(record_dict.keys()):
                value = record_dict[key]
                record_dict[key] = str(value)
                if value == "" or pd.isna(value):
                    del record_dict[key]

        records = colrev.loader.load_utils.load(
            filename=self.search_source.filename,
            unique_id_field="Item DOI",
            entrytype_setter=entrytype_setter,
            field_mapper=field_mapper,
            logger=self.review_manager.logger,
            format_names=True,
        )
        return records

    def api_ui(self) -> None:
        """User API key insertion"""

        api_key = self.get_api_key()

        if api_key:
            print("Your API key is available\n")

            change_api_key = [
                inquirer.List(
                    name="change_api_key",
                    message="Do you want to change your saved API key?",
                    choices=["no", "yes"],
                ),
            ]

            answers = inquirer.prompt(change_api_key)

            if answers["change_api_key"] == "no":
                return

        print("\n An API key is required for search \n\n")
        self._api_key_ui()

    def get_api_key(self) -> str:
        """Get API key from settings"""
        api_key = self.review_manager.environment_manager.get_settings_by_key(
            self.SETTINGS["api_key"]
        )
        if api_key:
            return api_key
        return ""

    def _is_springer_link_api_key(self, previous: dict, answer: str) -> bool:
        """Validate SpringerLink API key format"""
        api_key_pattern = re.compile(r"[a-z0-9]{32}")
        if not api_key_pattern.fullmatch(answer):
            raise inquirer.errors.ValidationError(
                "", reason="Invalid SpringerLink API key format."
            )

        full_url = self._build_api_search_url(
            query="doi:10.1007/978-3-319-07410-8_4", api_key=answer
        )
        response = requests.get(full_url, timeout=10)
        if response.status_code != 200:
            raise inquirer.errors.ValidationError("", reason="Error: Invalid API key.")
        print(
            f"\n{Colors.GREEN}Successfully authenticated with Springer Link API{Colors.END}"
        )
        return True

    def _is_year(self, previous: dict, answer: str) -> bool:
        """Validate year format"""
        year_pattern = re.compile(r"\d{4}")
        if not year_pattern.fullmatch(answer) and not answer == "":
            raise inquirer.errors.ValidationError("", reason="Invalid year format.")
        return True

    def _api_key_ui(self) -> None:
        """User Interface to enter API key"""

        questions = [
            inquirer.Text(
                "github_api_key",
                message="Enter your Springer Link API key",
                validate=self._is_springer_link_api_key,
            ),
        ]
        answers = inquirer.prompt(questions)
        input_key = answers["github_api_key"]
        self.review_manager.environment_manager.update_registry(
            self.SETTINGS["api_key"], input_key
        )

    def _load_bib(self) -> dict:
        """load bib file"""
        records = colrev.loader.load_utils.load(
            filename=self.search_source.filename,
            logger=self.review_manager.logger,
            unique_id_field="ID",
            format_names=True,
        )
        return records

    def load(self, load_operation: colrev.ops.load.Load) -> dict:
        """Load the records from the SearchSource file"""

        if self.search_source.filename.suffix == ".csv":
            return self._load_csv()

        if self.search_source.filename.suffix == ".bib":
            return self._load_bib()

        raise NotImplementedError

    def prepare(
        self, record: colrev.record.record.Record, source: colrev.settings.SearchSource
    ) -> colrev.record.record.Record:
        """Source-specific preparation for Springer Link"""

        return record
