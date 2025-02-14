#! /usr/bin/env python
"""Prescreen based on a table"""
from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd
from pydantic import Field

import colrev.package_manager.interfaces
import colrev.package_manager.package_manager
import colrev.package_manager.package_settings
import colrev.record.record
from colrev.constants import Colors
from colrev.constants import Fields
from colrev.constants import RecordState


# pylint: disable=too-few-public-methods
# pylint: disable=duplicate-code


class TablePrescreen(colrev.package_manager.interfaces.PrescreenInterface):
    """Table-based prescreen (exported and imported)"""

    settings_class = colrev.package_manager.package_settings.DefaultSettings
    ci_supported: bool = Field(default=False)
    export_todos_only: bool = True

    def __init__(
        self,
        *,
        prescreen_operation: colrev.ops.prescreen.Prescreen,
        settings: dict,
    ) -> None:
        self.review_manager = prescreen_operation.review_manager
        self.settings = self.settings_class(**settings)

    def export_table(
        self,
        *,
        records: dict,
        split: list,
        export_table_format: str = "csv",
    ) -> None:
        """Export a prescreen table"""

        # gh_issue https://github.com/CoLRev-Environment/colrev/issues/73
        # add delta (records not yet in the table)
        # instead of overwriting
        # export_table_format as a settings parameter

        self.review_manager.logger.info("Loading records for export")

        tbl = []
        for record in records.values():
            if record[Fields.STATUS] not in [
                RecordState.md_processed,
                RecordState.rev_prescreen_excluded,
                RecordState.rev_prescreen_included,
                RecordState.pdf_needs_manual_retrieval,
                RecordState.pdf_imported,
                RecordState.pdf_not_available,
                RecordState.pdf_needs_manual_preparation,
                RecordState.pdf_prepared,
                RecordState.rev_excluded,
                RecordState.rev_included,
                RecordState.rev_synthesized,
            ]:
                continue

            if len(split) > 0:
                if record[Fields.ID] not in split:
                    continue

            if RecordState.md_processed == record[Fields.STATUS]:
                inclusion_1 = "TODO"
            elif self.export_todos_only:
                continue
            elif RecordState.rev_prescreen_excluded == record[Fields.STATUS]:
                inclusion_1 = "out"
            else:
                inclusion_1 = "in"

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
                "presceen_inclusion": inclusion_1,
            }
            tbl.append(row)

        if export_table_format.lower() == "csv":
            screen_df = pd.DataFrame(tbl)
            screen_df.to_csv("prescreen.csv", index=False, quoting=csv.QUOTE_ALL)
            self.review_manager.logger.info("Created prescreen.csv")

        if export_table_format.lower() == "xlsx":
            screen_df = pd.DataFrame(tbl)
            screen_df.to_excel("prescreen.xlsx", index=False, sheet_name="screen")
            self.review_manager.logger.info("Created prescreen.xlsx")

        self.review_manager.logger.info(
            f"To prescreen records, {Colors.ORANGE}enter [in|out] "
            f"in the presceen_inclusion column.{Colors.END}"
        )
        self.review_manager.logger.info(
            f"Afterwards, run {Colors.ORANGE}colrev prescreen --import_table "
            f"prescreen.{export_table_format.lower()}{Colors.END}"
        )

    def import_table(
        self,
        *,
        records: dict,
        import_table_path: str = "prescreen.csv",
    ) -> None:
        """Import a prescreen table"""

        # pylint: disable=too-many-branches

        self.review_manager.logger.info(f"Load {import_table_path}")

        # pylint: disable=duplicate-code
        if not Path(import_table_path).is_file():
            self.review_manager.logger.error(
                f"Did not find {import_table_path} - exiting."
            )
            return

        if import_table_path.endswith(".csv"):
            prescreen_df = pd.read_csv(import_table_path)
        elif import_table_path.endswith(".xlsx") or import_table_path.endswith(".xls"):
            prescreen_df = pd.read_excel(import_table_path)
        else:
            raise ValueError(f"Unsupported file format: {import_table_path}")
        prescreen_df.fillna("", inplace=True)
        prescreened_records = prescreen_df.to_dict("records")

        if "presceen_inclusion" not in prescreened_records[0]:
            self.review_manager.logger.warning("presceen_inclusion column missing")
            return

        prescreen_included = 0
        prescreen_excluded = 0
        nr_todo = 0
        self.review_manager.logger.info("Update prescreen results")
        for prescreened_record in prescreened_records:
            if prescreened_record.get(Fields.ID, "") in records:
                record = colrev.record.record.Record(
                    records[prescreened_record.get(Fields.ID, "")]
                )
                if record.data[Fields.STATUS] in RecordState.get_post_x_states(
                    state=RecordState.rev_prescreen_included
                ):
                    if (
                        "in" == prescreened_record.data.get("presceen_inclusion", "")
                        and RecordState.rev_prescreen_excluded
                        != record.data[Fields.STATUS]
                    ):
                        continue

                if prescreened_record.get("presceen_inclusion", "") == "out":
                    if record.data[Fields.STATUS] != RecordState.rev_prescreen_excluded:
                        prescreen_excluded += 1
                    record.set_status(RecordState.rev_prescreen_excluded)

                elif prescreened_record.get("presceen_inclusion", "") == "in":
                    if record.data[Fields.STATUS] != RecordState.rev_prescreen_included:
                        prescreen_included += 1
                    record.set_status(RecordState.rev_prescreen_included)
                elif prescreened_record.get("presceen_inclusion", "") == "TODO":
                    nr_todo += 1
                else:
                    self.review_manager.logger.warning(
                        "Invalid value in prescreen_inclusion: "
                        f"{prescreened_record.get('presceen_inclusion', '')} "
                        f"({prescreened_record.get('ID', 'NO_ID')})"
                    )

            else:
                self.review_manager.logger.warning(
                    f"ID not in records: {prescreened_record.get('ID', '')}"
                )

        self.review_manager.logger.info(
            f" {Colors.GREEN}{prescreen_included} records prescreen_included{Colors.END}"
        )
        self.review_manager.logger.info(
            f" {Colors.RED}{prescreen_excluded} records prescreen_excluded{Colors.END}"
        )

        self.review_manager.logger.info(
            f" {Colors.ORANGE}{nr_todo} records to prescreen{Colors.END}"
        )

        self.review_manager.dataset.save_records_dict(records)
        self.review_manager.logger.info("Completed import")

    def run_prescreen(
        self,
        records: dict,
        split: list,
    ) -> dict:
        """Prescreen records based on screening tables"""

        if input("create prescreen table [y,n]?") == "y":
            self.export_table(records=records, split=split)

        if input("import prescreen table [y,n]?") == "y":
            self.import_table(records=records)

        if self.review_manager.dataset.has_record_changes():
            if input("create commit [y,n]?") == "y":
                self.review_manager.dataset.create_commit(
                    msg="Pre-screen (table)",
                    manual_author=True,
                )
        return records
