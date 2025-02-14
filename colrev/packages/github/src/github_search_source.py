#! /usr/bin/env python
"""SearchSource: GitHub"""
from __future__ import annotations

import re
import typing
from multiprocessing import Lock
from pathlib import Path

import inquirer
from github import Auth
from github import Github
from pydantic import Field

import colrev.exceptions as colrev_exceptions
import colrev.ops.search
import colrev.package_manager.interfaces
import colrev.package_manager.package_manager
import colrev.package_manager.package_settings
from colrev.constants import Fields
from colrev.constants import SearchSourceHeuristicStatus
from colrev.constants import SearchType
from colrev.packages.github.src import record_transformer

# pylint: disable=unused-argument


def is_github_api_key(previous: dict, answer: str) -> bool:
    """Validate GitHub API key format"""
    api_key_pattern = re.compile(r"[a-zA-Z0-9_-]{40}")
    if api_key_pattern.fullmatch(answer):
        return True
    raise inquirer.errors.ValidationError("", reason="Invalid GitHub API key format.")


class GitHubSearchSource(colrev.package_manager.interfaces.SearchSourceInterface):
    """GitHub API"""

    settings_class = colrev.package_manager.package_settings.DefaultSourceSettings
    search_types = [SearchType.API]
    endpoint = "colrev.github"
    source_identifier = Fields.URL
    ci_supported: bool = Field(default=True)

    heuristic_status = SearchSourceHeuristicStatus.todo

    docs_link = (
        "https://colrev-environment.github.io/colrev/dev_docs/packages/"
        + "package_interfaces.html#colrev.package_manager.interfaces.SearchSourceInterface"
        + "https://docs.github.com/en/rest?apiVersion=2022-11-28"
    )
    db_url = "https://github.com/"
    SETTINGS = {
        "api_key": "packages.search_source.colrev.github.api_key",
    }
    _github_md_filename = Path("data/search/md_github.bib")

    def __init__(
        self,
        *,
        source_operation: colrev.process.operation.Operation,
        settings: typing.Optional[dict] = None,
    ) -> None:
        self.review_manager = source_operation.review_manager
        if settings:
            # GitHub as a search source
            self.search_source = self.settings_class(**settings)
        else:
            # GitHub as a md-prep source
            github_md_source_l = [
                s
                for s in source_operation.review_manager.settings.sources
                if s.filename == self._github_md_filename
            ]
            if github_md_source_l:
                self.search_source = github_md_source_l[0]
            else:
                self.search_source = colrev.settings.SearchSource(
                    endpoint=self.endpoint,
                    filename=self._github_md_filename,
                    search_type=SearchType.MD,
                    search_parameters={},
                    comment="",
                )
            self.github_lock = Lock()

    @classmethod
    def heuristic(cls, filename: Path, data: str) -> dict:
        """Source heuristic for GitHub"""

        result = {"confidence": 0.0}

        return result

    @classmethod
    def _choice_scope(cls) -> str:
        questions = [
            inquirer.Checkbox(
                "search_in",
                message="Where do you want to search?",
                choices=[("URL", "url"), ("Readme", "readme"), ("Topic", "topic")],
            )
        ]

        answers = inquirer.prompt(questions)
        return ",".join(answers["search_in"])

    @classmethod
    def add_endpoint(
        cls, operation: colrev.ops.search.Search, params: str
    ) -> colrev.settings.SearchSource:
        """Add SearchSource as an endpoint (based on query provided to colrev search --add )"""

        cls._get_api_key()
        params_dict = {}
        if params:
            for item in params.split(";"):
                try:
                    key, value = item.split("=")
                    if key in ["title", "readme"]:
                        params_dict[key] = value
                    else:
                        raise colrev_exceptions.InvalidQueryException(
                            "GitHub search_parameters support title or readme field"
                        )
                except ValueError:
                    print("Invalid search parameter format")

        if len(params_dict) == 0:
            search_source = operation.create_api_source(endpoint="colrev.github")

            # Checking where to search
            search_source.search_parameters["scope"] = cls._choice_scope()

        else:
            if Fields.URL in params_dict:
                query = {
                    "query": (
                        params_dict[Fields.URL]
                        .replace("https://github.com/search?q=%2F", "")
                        .replace("https://github.com/search?q=", "")
                        .replace("&type=repositories", "")
                        .replace("+", " ")
                    )
                }
            else:
                query = params_dict

            filename = operation.get_unique_filename(file_path_string="github")
            search_source = colrev.settings.SearchSource(
                endpoint="colrev.github",
                filename=filename,
                search_type=SearchType.API,
                search_parameters=query,
                comment="",
            )

        operation.add_source_and_search(search_source)
        return search_source

    @classmethod
    def _get_api_key(cls) -> str:
        env_man = colrev.env.environment_manager.EnvironmentManager()
        api_key = env_man.get_settings_by_key(cls.SETTINGS["api_key"])
        if api_key is not None and is_github_api_key({}, api_key):
            return api_key

        questions = [
            inquirer.Text(
                "github_api_key",
                message="Enter your GitHub API key",
                validate=is_github_api_key,
            ),
        ]
        answers = inquirer.prompt(questions)
        input_key = answers["github_api_key"]
        env_man.update_registry(cls.SETTINGS["api_key"], input_key)
        print("API key saved in environment settings.")
        return input_key

    def _run_api_search(
        self, github_feed: colrev.ops.search_api_feed.SearchAPIFeed
    ) -> None:

        if not self.search_source.search_parameters:
            raise ValueError("No search parameters defined for GitHub search source")

        keywords = self.search_source.search_parameters.get("query", "")
        scope = self.search_source.search_parameters.get("scope", "")
        query = f"{keywords} in:{scope}"

        # Getting API key
        token = self._get_api_key()
        auth = Auth.Token(token)
        github_connection = Github(auth=auth)

        # Searching on Github
        repositories = github_connection.search_repositories(query=query)

        # Saving search results
        for repo in repositories:

            record = record_transformer.repo_to_record(repo=repo)
            github_feed.add_update_record(record)

        github_feed.save()
        github_connection.close()

    def search(self, rerun: bool = False) -> None:
        """Run a search on GitHub"""

        if self.search_source.search_type == SearchType.API:
            github_feed = self.search_source.get_api_feed(
                review_manager=self.review_manager,
                source_identifier=self.source_identifier,
                update_only=(not rerun),
            )
            self._run_api_search(github_feed)

    def load(self, load_operation: colrev.ops.load.Load) -> dict:
        """Load the records from the SearchSource file"""
        if self.search_source.filename.suffix == ".bib":
            records = colrev.loader.load_utils.load(
                filename=self.search_source.filename,
                logger=self.review_manager.logger,
                unique_id_field="url",
            )

            return records
        raise NotImplementedError

    def prepare(
        self, record: colrev.record.record.Record, source: colrev.settings.SearchSource
    ) -> colrev.record.record.Record:
        """Source-specific preparation for GitHub"""
        return record

    def prep_link_md(
        self,
        prep_operation: colrev.ops.prep.Prep,
        record: colrev.record.record.Record,
        save_feed: bool = True,
        timeout: int = 10,
    ) -> colrev.record.record.Record:
        """Prepare the record based on GitHub"""

        if Fields.URL not in record.data:
            return record

        pattern = r"https?://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)$"
        match = re.match(pattern, record.data[Fields.URL].strip('"'))
        if match:  # Check whether record contains GitHub url

            # get API access
            token = self._get_api_key()
            auth = Auth.Token(token)
            github_connection = Github(auth=auth)

            repo = github_connection.get_repo(match.group(1) + "/" + match.group(2))
            new_record = record_transformer.repo_to_record(repo=repo)
            record.data.update(new_record.data)

        return record
