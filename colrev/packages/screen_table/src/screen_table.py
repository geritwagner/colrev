#! /usr/bin/env python
"""Screen based on a table"""
from __future__ import annotations

import csv
import typing
from pathlib import Path

import pandas as pd
from pydantic import Field

import colrev.package_manager.interfaces
import colrev.package_manager.package_manager
import colrev.package_manager.package_settings
import colrev.packages.screen_utils as util_cli_screen
import colrev.record.record
import colrev.settings
from colrev.constants import Fields
from colrev.constants import RecordState


class TableScreen(colrev.package_manager.interfaces.ScreenInterface):
    """Screen documents using tables (exported and imported)"""

    settings_class = colrev.package_manager.package_settings.DefaultSettings
    ci_supported: bool = Field(default=False)
    export_todos_only: bool = True

    screen_table_path = Path("screen/screen.csv")

    def __init__(
        self,
        *,
        screen_operation: colrev.ops.screen.Screen,
        settings: dict,
    ) -> None:
        self.review_manager = screen_operation.review_manager
        self.screen_operation = screen_operation
        self.settings = self.settings_class(**settings)

    def _create_screening_table(self, *, records: dict, split: list) -> list:
        # pylint: disable=too-many-branches
        self.review_manager.logger.info("Loading records for export")

        screening_criteria = util_cli_screen.get_screening_criteria_from_user_input(
            screen_operation=self.screen_operation, records=records
        )

        tbl = []
        for record in records.values():
            if record[Fields.STATUS] not in [
                RecordState.pdf_prepared,
            ]:
                continue

            if len(split) > 0:
                if record[Fields.ID] not in split:
                    continue

            inclusion_2 = "NA"

            if RecordState.pdf_prepared == record[Fields.STATUS]:
                inclusion_2 = "TODO"
            elif self.export_todos_only:
                continue
            if RecordState.rev_excluded == record[Fields.STATUS]:
                inclusion_2 = "out"
            if record[Fields.STATUS] in [
                RecordState.rev_included,
                RecordState.rev_synthesized,
            ]:
                inclusion_2 = "in"

            # pylint: disable=duplicate-code
            row = {
                Fields.ID: record[Fields.ID],
                Fields.AUTHOR: record.get(Fields.AUTHOR, ""),
                Fields.TITLE: record.get(Fields.TITLE, ""),
                Fields.JOURNAL: record.get(Fields.JOURNAL, ""),
                Fields.BOOKTITLE: record.get(Fields.BOOKTITLE, ""),
                Fields.YEAR: record.get(Fields.YEAR, ""),
                Fields.VOLUME: record.get(Fields.VOLUME, ""),
                Fields.NUMBER: record.get(Fields.NUMBER, ""),
                Fields.PAGES: record.get(Fields.PAGES, ""),
                Fields.DOI: record.get(Fields.DOI, ""),
                Fields.ABSTRACT: record.get(Fields.ABSTRACT, ""),
            }

            if len(screening_criteria) == 0:
                # No criteria: code inclusion directly
                row["screen_inclusion"] = inclusion_2

            else:
                # Code criteria
                screening_criteria_field = record.get(Fields.SCREENING_CRITERIA, "")
                if screening_criteria_field == "":
                    # and inclusion_2 == "in"
                    for criterion_name in screening_criteria.keys():
                        row[criterion_name] = "TODO (in/out)"
                else:
                    for criterion_name, decision in screening_criteria_field.split(";"):
                        row[criterion_name] = decision

            tbl.append(row)

        return tbl

    def export_table(
        self,
        records: dict,
        split: list,
        export_table_format: str = "csv",
    ) -> None:
        """Export a screening table"""

        # gh_issue https://github.com/CoLRev-Environment/colrev/issues/73
        # add delta (records not yet in the table)
        # instead of overwriting
        # export_table_format as a settings parameter

        if self.screen_table_path.is_file():
            print("File already exists. Please rename it.")
            return

        tbl = self._create_screening_table(records=records, split=split)

        self.screen_table_path.parents[0].mkdir(parents=True, exist_ok=True)

        if export_table_format.lower() == "csv":
            screen_df = pd.DataFrame(tbl)
            screen_df.to_csv(self.screen_table_path, index=False, quoting=csv.QUOTE_ALL)
            self.review_manager.logger.info(f"Created {self.screen_table_path}")

        if export_table_format.lower() == "xlsx":
            screen_df = pd.DataFrame(tbl)
            screen_df.to_excel(
                self.screen_table_path.with_suffix(".xlsx"),
                index=False,
                sheet_name="screen",
            )
            self.review_manager.logger.info(
                f"Created {self.screen_table_path.with_suffix('.xlsx')}"
            )

        return

    def import_table(
        self,
        records: dict,
        import_table_path: typing.Optional[Path] = None,
    ) -> None:
        """Import a screening table"""

        # pylint: disable=duplicate-code
        if import_table_path is None:
            import_table_path = self.screen_table_path

        if not Path(import_table_path).is_file():
            self.review_manager.logger.error(
                f"Did not find {import_table_path} - exiting."
            )
            return

        screen_df = pd.read_csv(import_table_path)
        screen_df.fillna("", inplace=True)
        screened_records = screen_df.to_dict("records")

        screening_criteria = self.review_manager.settings.screen.criteria

        for screened_record in screened_records:
            if screened_record.get(Fields.ID, "") in records:
                record_dict = records[screened_record.get(Fields.ID, "")]
                record = colrev.record.record.Record(record_dict)
                if "screen_inclusion" in screened_record:
                    if screened_record["screen_inclusion"] == "in":
                        record.set_status(RecordState.rev_included)
                    elif screened_record["screen_inclusion"] == "out":
                        record.set_status(RecordState.rev_excluded)
                    else:
                        print(
                            f"Invalid choice: {screened_record['screen_inclusion']} "
                            f"({screened_record['ID']})"
                        )
                    continue
                screening_criteria_field = ""
                for screening_criterion in screening_criteria.keys():
                    assert screened_record[screening_criterion] in ["in", "out"]
                    screening_criteria_field += (
                        screening_criterion
                        + "="
                        + screened_record[screening_criterion]
                        + ";"
                    )
                screening_criteria_field = screening_criteria_field.rstrip(";")
                record.data[Fields.SCREENING_CRITERIA] = screening_criteria_field
                if "=out" in screening_criteria_field:
                    record.set_status(RecordState.rev_excluded)
                else:
                    record.set_status(RecordState.rev_included)

        self.review_manager.dataset.save_records_dict(records)

    def run_screen(self, records: dict, split: list) -> dict:
        """Screen records based on screening tables"""

        if input("create screen table [y,n]?") == "y":
            self.export_table(records, split)

        if input("import screen table [y,n]?") == "y":
            self.import_table(records)

        if self.review_manager.dataset.has_record_changes():
            if input("create commit [y,n]?") == "y":
                self.review_manager.dataset.create_commit(
                    msg="Screen", manual_author=True
                )
        return records
