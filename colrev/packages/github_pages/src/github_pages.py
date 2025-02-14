#! /usr/bin/env python
"""Creation of a github-page for the review as part of the data operations"""
from __future__ import annotations

from pathlib import Path

import git
from pydantic import BaseModel
from pydantic import Field

import colrev.env.utils
import colrev.package_manager.interfaces
import colrev.package_manager.package_manager
import colrev.package_manager.package_settings
import colrev.record.record
from colrev.constants import Colors
from colrev.constants import Fields
from colrev.constants import RecordState
from colrev.writer.write_utils import write_file


class GHPagesSettings(
    colrev.package_manager.package_settings.DefaultSettings, BaseModel
):
    """Settings for GithubPages"""

    endpoint: str
    version: str
    auto_push: bool

    _details = {
        "auto_push": {
            "tooltip": "Indicates whether the Github Pages branch "
            "should be pushed automatically"
        },
    }


class GithubPages(colrev.package_manager.interfaces.DataInterface):
    """Export the literature review into a Github Page"""

    settings: GHPagesSettings
    settings_class = GHPagesSettings

    ci_supported: bool = Field(default=False)

    GH_PAGES_BRANCH_NAME = "gh-pages"

    settings_class = GHPagesSettings

    def __init__(
        self,
        *,
        data_operation: colrev.ops.data.Data,
        settings: dict,
    ) -> None:
        # Set default values (if necessary)
        if "version" not in settings:
            settings["version"] = "0.1.0"
        if "auto_push" not in settings:
            settings["auto_push"] = True

        self.settings = self.settings_class(**settings)
        self.review_manager = data_operation.review_manager
        self.git_repo = self.review_manager.dataset.get_repo()

    # pylint: disable=unused-argument
    @classmethod
    def add_endpoint(cls, operation: colrev.ops.data.Data, params: str) -> None:
        """Add as an endpoint"""

        add_source = {
            "endpoint": "colrev.github_pages",
            "version": "0.1",
            "auto_push": True,
        }

        operation.review_manager.settings.data.data_package_endpoints.append(add_source)

    def _setup_github_pages_branch(self) -> None:
        # if branch does not exist: create and add index.html
        self.review_manager.logger.info("Setup gh-pages branch")
        self.git_repo.git.checkout("--orphan", self.GH_PAGES_BRANCH_NAME)
        self.git_repo.git.rm("-rf", Path("."))

        colrev.env.utils.retrieve_package_file(
            template_file=Path("packages/github_pages/github_pages/README.md"),
            target=Path("README.md"),
        )
        project_title = self.review_manager.settings.project.title
        colrev.env.utils.inplace_change(
            filename=Path("README.md"),
            old_string="{{project_title}}",
            new_string=project_title.rstrip(" ").capitalize(),
        )
        self.review_manager.dataset.add_changes(Path("README.md"))

        colrev.env.utils.retrieve_package_file(
            template_file=Path("packages/github_pages/github_pages/index.html"),
            target=Path("index.html"),
        )
        self.review_manager.dataset.add_changes(Path("index.html"))

        colrev.env.utils.retrieve_package_file(
            template_file=Path("packages/github_pages/github_pages/_config.yml"),
            target=Path("_config.yml"),
        )
        colrev.env.utils.inplace_change(
            filename=Path("_config.yml"),
            old_string="{{project_title}}",
            new_string=project_title,
        )
        self.review_manager.dataset.add_changes(Path("_config.yml"))

        colrev.env.utils.retrieve_package_file(
            template_file=Path("packages/github_pages/github_pages/about.md"),
            target=Path("about.md"),
        )
        self.review_manager.dataset.add_changes(Path("about.md"))

        self.review_manager.dataset.create_commit(
            msg="Setup gh-pages branch", skip_status_yaml=True
        )

    def _update_data(
        self,
        *,
        silent_mode: bool,
    ) -> None:
        if not silent_mode:
            self.review_manager.logger.info("Update data on github pages")

        records = self.review_manager.dataset.load_records_dict()

        included_records = {
            r[Fields.ID]: r
            for r in records.values()
            if r[Fields.STATUS]
            in [
                RecordState.rev_synthesized,
                RecordState.rev_included,
            ]
        }

        self.git_repo.git.checkout(self.GH_PAGES_BRANCH_NAME)
        if not self.review_manager.paths.pre_commit_config.is_file():
            colrev.env.utils.retrieve_package_file(
                template_file=Path(
                    "packages/github_pages/github_pages/pre-commit-config.yaml"
                ),
                target=self.review_manager.paths.PRE_COMMIT_CONFIG,
            )
            self.review_manager.dataset.add_changes(
                self.review_manager.paths.PRE_COMMIT_CONFIG
            )

        data_file = Path("data.bib")
        write_file(records_dict=included_records, filename=data_file)

        self.review_manager.dataset.add_changes(data_file)

        self.review_manager.dataset.create_commit(
            msg="Update sample", skip_status_yaml=True
        )

    def _push_branch(
        self,
        *,
        silent_mode: bool,
    ) -> None:
        if not silent_mode:
            self.review_manager.logger.info("Push to github pages")
        if "origin" in self.git_repo.remotes:
            if "origin/gh-pages" in [r.name for r in self.git_repo.remotes.origin.refs]:
                try:
                    self.git_repo.remotes.origin.push(
                        refspec=f"{self.GH_PAGES_BRANCH_NAME}:{self.GH_PAGES_BRANCH_NAME}"
                    )
                except git.exc.GitCommandError:  # pylint: disable=no-member
                    self.review_manager.logger.error(
                        "Could not push branch gh-pages. Please resolve manually, i.e., run "
                        f"{Colors.ORANGE}git switch gh-pages && "
                        f"git pull --rebase && git push{Colors.END}"
                    )
            else:
                self.git_repo.git.push(
                    "--set-upstream",
                    "origin",
                    self.GH_PAGES_BRANCH_NAME,
                    "--no-verify",
                )

            username, project = (
                self.git_repo.remotes.origin.url.replace("https://github.com/", "")
                .replace(".git", "")
                .split("/")
            )
            if not silent_mode:
                self.review_manager.logger.info(
                    f"Data available at: https://{username}.github.io/{project}/"
                )
        else:
            if not silent_mode:
                self.review_manager.logger.info("No remotes specified")

    def _check_gh_pages_setup(self) -> None:
        username, project = (
            self.git_repo.remotes.origin.url.replace("https://github.com/", "")
            .replace(".git", "")
            .split("/")
        )
        gh_page_link = f"https://{username}.github.io/{project}/"
        if Path("readme.md").is_file():
            if gh_page_link in (self.review_manager.path / Path("readme.md")).read_text(
                encoding="utf-8"
            ):
                return
        print(
            f"{Colors.ORANGE}The Github page is not yet linked in the readme.md file.\n"
            "To make it easier to access the page, add the following to the readme.md file:\n"
            f"\n    [Github page]({gh_page_link}){Colors.END}\n"
        )

    def update_data(
        self,
        records: dict,  # pylint: disable=unused-argument
        synthesized_record_status_matrix: dict,  # pylint: disable=unused-argument
        silent_mode: bool,
    ) -> None:
        """Update the data/github pages"""

        # pylint: disable=too-many-branches

        if self.review_manager.in_ci_environment():
            self.review_manager.logger.error(
                "Running in CI environment. Skipping github-pages generation."
            )
            return

        if self.review_manager.dataset.has_record_changes():
            self.review_manager.logger.error(
                "Cannot update github pages because there are uncommited changes."
            )
            return

        active_branch = self.git_repo.active_branch

        # check if there is an "origin" remote

        if "origin" in self.git_repo.remotes:
            # check if remote.origin has a gh-pages branch
            self.git_repo.remotes.origin.fetch()
            if f"origin/{self.GH_PAGES_BRANCH_NAME}" in [
                r.name for r in self.git_repo.remotes.origin.refs
            ]:
                try:
                    if "origin/gh-pages" not in [
                        r.name for r in self.git_repo.remotes.origin.refs
                    ]:
                        self.git_repo.git.push(
                            "--set-upstream",
                            "origin",
                            self.GH_PAGES_BRANCH_NAME,
                            "--no-verify",
                        )
                    else:
                        self.git_repo.remotes.origin.pull(ff_only=True)

                    # update
                    self.git_repo.git.checkout(active_branch)
                    self._update_data(
                        silent_mode=silent_mode,
                    )

                    # Push gh-pages branch to remote origin
                    if self.settings.auto_push:
                        self._push_branch(
                            silent_mode=silent_mode,
                        )
                except git.exc.GitCommandError as exc:  # pylint: disable=no-member
                    print("Error in gh-pages:")
                    print(exc)
                    return
            else:
                # create branch
                if self.GH_PAGES_BRANCH_NAME not in [
                    h.name for h in self.git_repo.heads
                ]:
                    self._setup_github_pages_branch()

                # update
                self.git_repo.git.checkout(active_branch)
                self._update_data(
                    silent_mode=silent_mode,
                )

                # Push gh-pages branch to remote origin
                if self.settings.auto_push:
                    self._push_branch(
                        silent_mode=silent_mode,
                    )
            self.git_repo.git.checkout(active_branch)
            self._check_gh_pages_setup()
        else:
            self.review_manager.logger.warning(
                "Cannot push github pages because there is no remote origin. "
                "gh-pages branch will only be created locally."
            )
            # create branch
            if self.GH_PAGES_BRANCH_NAME not in [h.name for h in self.git_repo.heads]:
                self._setup_github_pages_branch()

            # update
            self.git_repo.git.checkout(active_branch)
            self._update_data(
                silent_mode=silent_mode,
            )

        self.git_repo.git.checkout(active_branch)

    def update_record_status_matrix(
        self,
        synthesized_record_status_matrix: dict,
        endpoint_identifier: str,
    ) -> None:
        """Update the record_status_matrix"""

        # Note : automatically set all to True / synthesized
        for syn_id in synthesized_record_status_matrix:
            synthesized_record_status_matrix[syn_id][endpoint_identifier] = True

    def get_advice(
        self,
    ) -> dict:
        """Get advice on the next steps (for display in the colrev status)"""

        data_endpoint = "Data operation [github pages data endpoint]: "

        advice = {"msg": f"{data_endpoint}", "detailed_msg": "TODO"}
        if self.review_manager.dataset.get_remote_url() == "NA":
            advice["msg"] += (
                "\n    - To make the repository available on Github pages, "
                + "push it to a Github repository\nhttps://github.com/new"
            )
        else:
            advice[
                "msg"
            ] += "\n    - The page is updated automatically (gh-pages branch)"

        return advice
