#! /usr/bin/env python
"""Creation of an Obsidian database as part of the data operations"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from pydantic import BaseModel
from pydantic import Field

import colrev.env.utils
import colrev.package_manager.interfaces
import colrev.package_manager.package_manager
import colrev.package_manager.package_settings
import colrev.record.record
from colrev.constants import Fields


class Obsidian(colrev.package_manager.interfaces.DataInterface):
    """Export the sample into an Obsidian database"""

    ci_supported: bool = Field(default=False)

    class ObsidianSettings(
        colrev.package_manager.package_settings.DefaultSettings, BaseModel
    ):
        """Settings for Obsidian"""

        endpoint: str
        version: str
        config: dict

        # _details = {
        #     "config": {
        #         "tooltip": "TODO"
        #     },
        # }

    settings_class = ObsidianSettings

    OBSIDIAN_PATH_RELATIVE = Path("data/obsidian")
    OBSIDIAN_PAPER_PATH_RELATIVE = Path("data/obsidian/paper")
    OBSIDIAN_INBOX_PATH_RELATIVE = Path("data/obsidian/inbox.md")
    GITIGNORE_LIST = [
        "data/obsidian/.obsidian/core-plugins.json",
        "data/obsidian/.obsidian/workspace.json",
        "data/obsidian/.obsidian/core-plugins-migration.json",
        "data/obsidian/.obsidian/app.json",
        "data/obsidian/.obsidian/hotkeys.json",
        "data/obsidian/.obsidian/appearance.json",
    ]

    def __init__(
        self,
        *,
        data_operation: colrev.ops.data.Data,
        settings: dict,
    ) -> None:
        self.review_manager = data_operation.review_manager
        self.data_operation = data_operation

        # Set default values (if necessary)
        if "version" not in settings:
            settings["version"] = "0.1"
        if "config" not in settings:
            settings["config"] = {}

        self.settings = self.settings_class(**settings)

        self.endpoint_path = self.review_manager.path / self.OBSIDIAN_PATH_RELATIVE
        self.endpoint_paper_path = (
            self.review_manager.path / self.OBSIDIAN_PAPER_PATH_RELATIVE
        )
        self.endpoint_inbox_path = (
            self.review_manager.path / self.OBSIDIAN_INBOX_PATH_RELATIVE
        )
        if hasattr(self.review_manager, "dataset"):
            self.review_manager.dataset.update_gitignore(add=self.GITIGNORE_LIST)

    # pylint: disable=unused-argument
    @classmethod
    def add_endpoint(cls, operation: colrev.ops.data.Data, params: str) -> None:
        """Add as an endpoint"""

        add_source = {
            "endpoint": "colrev.obsidian",
            "version": "0.1",
            "config": {},
        }

        operation.review_manager.settings.data.data_package_endpoints.append(add_source)

    def _get_obsidian_missing(self, *, included: list) -> list:
        in_obsidian = []
        for md_file in self.endpoint_paper_path.glob("*.md"):
            # missing: if todo in file
            if "#todo" not in md_file.read_text():
                in_obsidian.append(str(md_file.name).replace(".md", ""))
        return [x for x in included if x not in in_obsidian]

    def _get_keywords(self, *, record_dict: dict) -> list:
        keywords = []

        try:
            tei_file = (
                self.review_manager.path
                / colrev.record.record.Record(record_dict).get_tei_filename()
            )

            if tei_file.is_file():
                tei = self.review_manager.get_tei(tei_path=tei_file)
                keywords = [
                    x.lower().replace(" ", "-") for x in tei.get_paper_keywords()
                ]
        except Exception as exc:  # pylint: disable=broad-except
            print(exc)

        if int(record_dict.get(Fields.CITED_BY, 0)) > 100:
            keywords.append("highly_cited")

        return keywords

    def _append_missing_records(self, *, records: dict, silent_mode: bool) -> None:
        included = self.data_operation.get_record_ids_for_synthesis(records)
        missing_records = self._get_obsidian_missing(included=included)
        if len(missing_records) == 0:
            if not silent_mode:
                self.review_manager.logger.info(
                    "All records included. Nothing to export."
                )
            return

        inbox_text = ""
        if self.endpoint_inbox_path.is_file():
            inbox_text = self.endpoint_inbox_path.read_text()
        self.endpoint_inbox_path.parent.mkdir(exist_ok=True)
        if not self.endpoint_inbox_path.is_file():
            with open(self.endpoint_inbox_path, "w", encoding="utf-8") as inbox_file:
                inbox_file.write("Papers to synthesize:\n\n")

        missing_record_entities = {}
        with open(self.endpoint_inbox_path, "a", encoding="utf-8") as inbox_file:
            for missing_record in missing_records:
                if missing_record not in inbox_text:
                    inbox_file.write(f"- [[{missing_record}]]\n")
        for missing_record in missing_records:
            paper_summary_path = self.endpoint_paper_path / Path(f"{missing_record}.md")

            missing_record_entities[paper_summary_path] = {
                Fields.KEYWORDS: self._get_keywords(record_dict=records[missing_record])
            }

        all_keywords = [x[Fields.KEYWORDS] for x in missing_record_entities.values()]
        all_keywords = [item for sublist in all_keywords for item in sublist]

        cnt = Counter(all_keywords)
        frequent_keywords = [k for k, v in cnt.items() if v > 2]

        # Drop research-methods related keywords:
        frequent_keywords = [
            x
            for x in frequent_keywords
            if x
            not in [
                "case-study",
                "design-science",
                "design-science-research",
                "research-agenda",
                "design-theory",
                "mixed-methods",
                "multilevel-analysis",
                "pls",
                "text-minig",
                "associate-editor",
                "chang",
                "ethnography",
                "empirical-research",
                "qualitative-study",
                "ramesh",
                "natural-experiment",
                "simulation",
                "structural-equation-modeling",
                "longitudinal-study",
            ]
        ]

        # for (
        #     paper_summary_path,
        #     missing_record_entity,
        # ) in missing_record_entities.items():
        #     if not paper_summary_path.is_file():
        #         paper_summary_path.parent.mkdir(exist_ok=True, parents=True)
        #         with open(paper_summary_path, "w", encoding="utf-8") as paper_summary:
        #             selected_keywords = [
        #                 x
        #                 for x in missing_record_entity[Fields.KEYWORDS]
        #                 if x in frequent_keywords and x not in ["highly_cited"]
        #             ]
        #             # paper_summary.write(f"#paper {' #'.join(selected_keywords)} #todo\n\n")
        #             paper_summary.write(f"#{' #'.join(selected_keywords)}\n\n")
        #             if "highly_cited" in missing_record_entity[Fields.KEYWORDS]:
        #                 paper_summary.write("highly_cited")

        # later : export to csl-json (based on bibliography_export)
        # (absolute PDF paths, read-only/hidden/gitignored, no provenance fields)

        # self.review_manager.dataset.add_changes(self.OBSIDIAN_INBOX_PATH_RELATIVE)

    def update_data(
        self,
        records: dict,  # pylint: disable=unused-argument
        synthesized_record_status_matrix: dict,  # pylint: disable=unused-argument
        silent_mode: bool,
    ) -> None:
        """Update the obsidian vault"""

        self.review_manager.logger.debug("Export to obsidian endpoint")

        self._append_missing_records(records=records, silent_mode=silent_mode)

    def update_record_status_matrix(
        self,
        synthesized_record_status_matrix: dict,
        endpoint_identifier: str,
    ) -> None:
        """Update the record_status_matrix"""

        missing_records = self._get_obsidian_missing(
            included=list(synthesized_record_status_matrix.keys())
        )

        # Note : automatically set all to True / synthesized
        for syn_id in list(synthesized_record_status_matrix.keys()):
            if syn_id in missing_records:
                synthesized_record_status_matrix[syn_id][endpoint_identifier] = False
            else:
                synthesized_record_status_matrix[syn_id][endpoint_identifier] = True

    def get_advice(
        self,
    ) -> dict:
        """Get advice on the next steps (for display in the colrev status)"""

        data_endpoint = "Data operation [obisdian data endpoint]: "

        advice = {
            "msg": f"{data_endpoint}"
            + "\n    - New records are added to the obsidian vault (data/obsidian)",
            "detailed_msg": "TODO",
        }
        return advice
