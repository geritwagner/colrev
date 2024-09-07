#! /usr/bin/env python
"""CoLRev prescreen operation: Prescreen records (metadata)."""
from __future__ import annotations

import math
from pathlib import Path

import colrev.packages.conditional_prescreen.src.conditional_prescreen
import colrev.packages.prescreen_table.src.prescreen_table
import colrev.process.operation
import colrev.record.record
from colrev.constants import Colors
from colrev.constants import EndpointType
from colrev.constants import Fields
from colrev.constants import OperationsType
from colrev.constants import RecordState

ConditionalPrescreen = (
    colrev.packages.conditional_prescreen.src.conditional_prescreen.ConditionalPrescreen
)


class Prescreen(colrev.process.operation.Operation):
    """Prescreen records (based on metadata)"""

    type = OperationsType.prescreen

    def __init__(
        self,
        *,
        review_manager: colrev.review_manager.ReviewManager,
        notify_state_transition_operation: bool = True,
    ) -> None:
        super().__init__(
            review_manager=review_manager,
            operations_type=self.type,
            notify_state_transition_operation=notify_state_transition_operation,
        )

        self.verbose = True

    def export_table(self, *, export_table_format: str = "csv") -> None:
        """Export a table with records to prescreen"""

        endpoint = colrev.packages.prescreen_table.src.prescreen_table.TablePrescreen(
            prescreen_operation=self, settings={"endpoint": "export_table"}
        )
        records = self.review_manager.dataset.load_records_dict()
        endpoint.export_table(
            records=records,
            split=[],
            export_table_format=export_table_format,
        )

    def import_table(self, *, import_table_path: str) -> None:
        """Import a table with prescreened records"""

        endpoint = colrev.packages.prescreen_table.src.prescreen_table.TablePrescreen(
            prescreen_operation=self, settings={"endpoint": "import_table"}
        )
        records = self.review_manager.dataset.load_records_dict()
        endpoint.import_table(
            records=records,
            import_table_path=import_table_path,
        )

    def _include_all_in_prescreen_precondition(self, records: dict) -> bool:
        if not [
            r for r in records.values() if r[Fields.STATUS] == RecordState.md_processed
        ]:
            if [
                r
                for r in records.values()
                if r[Fields.STATUS] == RecordState.pdf_prepared
            ]:
                self.review_manager.logger.warning(
                    "No records to prescreen. Use "
                    f"{Colors.ORANGE}colrev screen --include_all{Colors.END} instead"
                )
            else:
                self.review_manager.logger.warning("No records to prescreen.")
            return False
        return True

    @colrev.process.operation.Operation.decorate()
    def include_all_in_prescreen(self, *, persist: bool) -> None:
        """Include all records in the prescreen"""

        if persist:
            self.review_manager.settings.prescreen.prescreen_package_endpoints = []
            self.review_manager.save_settings()

        records = self.review_manager.dataset.load_records_dict()
        if not self._include_all_in_prescreen_precondition(records):
            return

        selected_record_ids = [
            r[Fields.ID]
            for r in records.values()
            if RecordState.md_processed == r[Fields.STATUS]
        ]

        endpoint = ConditionalPrescreen(
            prescreen_operation=self, settings={"endpoint": "include_all"}
        )
        endpoint.run_prescreen(records, [])
        self._print_stats(selected_record_ids=selected_record_ids)

    def include_records(self, *, ids: str) -> None:
        """Include records in the prescreen"""

        self._prescreen_records(ids=ids, include=True)

    def exclude_records(self, *, ids: str) -> None:
        """Exclude records in the prescreen"""

        self._prescreen_records(ids=ids, include=False)

    def _prescreen_records(self, *, ids: str, include: bool) -> None:
        records = self.review_manager.dataset.load_records_dict()
        for record_id in ids.split(","):
            if record_id not in records:
                self.review_manager.logger.info(f" not found: {record_id}")
                continue
            record = colrev.record.record.Record(records[record_id])
            if (
                record.data[Fields.STATUS] != RecordState.md_processed
                and not self.review_manager.force_mode
            ):
                self.review_manager.logger.info(
                    f" record not md_processed / cannot prescreen: {record_id}"
                )
                continue
            if include:
                record.set_status(RecordState.rev_prescreen_included)
            else:
                record.set_status(RecordState.rev_prescreen_excluded)

        self.review_manager.dataset.save_records_dict(records)

        msg = f"Prescreen: exclude {ids}"
        if include:
            msg = f"Prescreen: include {ids}"

        self.review_manager.dataset.create_commit(
            msg=msg,
            manual_author=False,
        )

    def get_data(self) -> dict:
        """Get the data for prescreen"""

        # pylint: disable=duplicate-code

        records_headers = self.review_manager.dataset.load_records_dict(
            header_only=True
        )
        record_header_list = list(records_headers.values())
        nr_tasks = len(
            [
                x
                for x in record_header_list
                if RecordState.md_processed == x[Fields.STATUS]
            ]
        )
        pad = 0
        if record_header_list:
            pad = min((max(len(x[Fields.ID]) for x in record_header_list) + 2), 40)
        items = self.review_manager.dataset.read_next_record(
            conditions=[{Fields.STATUS: RecordState.md_processed}]
        )
        prescreen_data = {"nr_tasks": nr_tasks, "PAD": pad, "items": items}

        return prescreen_data

    def create_prescreen_split(self, *, create_split: int) -> list:
        """Split the prescreen between researchers"""

        prescreen_splits = []

        data = self.get_data()
        nrecs = math.floor(data["nr_tasks"] / create_split)

        self.review_manager.report_logger.info(
            f"Creating prescreen splits for {create_split} researchers "
            f"({nrecs} each)"
        )

        for _ in range(0, create_split):
            added: list[str] = []
            while len(added) < nrecs:
                added.append(next(data["items"])[Fields.ID])
            prescreen_splits.append("colrev prescreen --split " + ",".join(added))

        return prescreen_splits

    def setup_custom_script(self) -> None:
        """Setup a custom prescreen script"""

        filedata = colrev.env.utils.get_package_file_content(
            module="colrev.ops",
            filename=Path("custom_scripts/custom_prescreen_script.py"),
        )

        if filedata:
            with open("custom_prescreen_script.py", "w", encoding="utf8") as file:
                file.write(filedata.decode("utf-8"))

        self.review_manager.dataset.add_changes(Path("custom_prescreen_script.py"))

        self.review_manager.settings.prescreen.prescreen_package_endpoints.append(
            {"endpoint": "custom_prescreen_script"}
        )
        self.review_manager.save_settings()

    def _prescreen_include_all(self, records: dict) -> None:
        # pylint: disable=duplicate-code
        self.review_manager.logger.info("Prescreen-including all records")
        for record_dict in records.values():
            if record_dict[Fields.STATUS] == RecordState.md_processed:
                record = colrev.record.record.Record(record_dict)
                record.set_status(RecordState.rev_prescreen_included)
        self.review_manager.dataset.save_records_dict(records)
        self.review_manager.dataset.create_commit(
            msg="Prescreen: include all",
            manual_author=False,
        )

    def _print_stats(self, *, selected_record_ids: list) -> None:
        records_headers = self.review_manager.dataset.load_records_dict(
            header_only=True
        )
        prescreen_excluded = [
            r[Fields.ID]
            for r in records_headers.values()
            if RecordState.rev_prescreen_excluded == r[Fields.STATUS]
            and r[Fields.ID] in selected_record_ids
        ]
        prescreen_included = [
            r[Fields.ID]
            for r in records_headers.values()
            if RecordState.rev_prescreen_included == r[Fields.STATUS]
            and r[Fields.ID] in selected_record_ids
        ]

        if not prescreen_excluded and not prescreen_included:
            return

        print()
        self.review_manager.logger.info("Statistics")
        for record_dict in records_headers.values():
            if record_dict[Fields.ID] in prescreen_excluded:
                self.review_manager.logger.info(
                    f" {record_dict['ID']}".ljust(41)
                    + "md_processed → rev_prescreen_excluded"
                )
            elif record_dict[Fields.ID] in prescreen_included:
                self.review_manager.logger.info(
                    f"{Colors.GREEN}"
                    + f" {record_dict['ID']}".ljust(41)
                    + f"md_processed → rev_prescreen_included{Colors.END}"
                )

        nr_prescreen_excluded = len(prescreen_excluded)
        nr_prescreen_included = len(prescreen_included)

        self.review_manager.logger.info(
            "Prescreen excluded".ljust(30)
            + f"{nr_prescreen_excluded}".rjust(10, " ")
            + " records"
        )
        self.review_manager.logger.info(
            "Prescreen included".ljust(30)
            + f"{nr_prescreen_included}".rjust(10, " ")
            + " records"
        )

    def prescreen(
        self,
        *,
        record: colrev.record.record.Record,
        prescreen_inclusion: bool,
        PAD: int = 40,
    ) -> None:
        """Save the prescreen decision"""
        if prescreen_inclusion:
            self.review_manager.report_logger.info(
                f" {record.data['ID']}".ljust(PAD, " ") + "Included in prescreen"
            )
            record.set_status(RecordState.rev_prescreen_included)
            self.review_manager.dataset.save_records_dict(
                {record.data[Fields.ID]: record.get_data()}, partial=True
            )

        else:
            self.review_manager.report_logger.info(
                f" {record.data['ID']}".ljust(PAD, " ") + "Excluded in prescreen"
            )
            record.set_status(RecordState.rev_prescreen_excluded)
            self.review_manager.dataset.save_records_dict(
                {record.data[Fields.ID]: record.get_data()}, partial=True
            )

    def _auto_include(self, records: dict) -> list:
        selected_auto_include_ids = [
            r[Fields.ID]
            for r in records.values()
            if RecordState.md_processed == r[Fields.STATUS]
            and r.get("include_flag", "0") == "1"
        ]
        if not selected_auto_include_ids:
            return selected_auto_include_ids
        self.review_manager.logger.info(
            f"{Colors.GREEN}Automatically including records with include_flag{Colors.END}"
        )
        for record_dict in records.values():
            if record_dict[Fields.ID] not in selected_auto_include_ids:
                continue
            self.prescreen(
                record=colrev.record.record.Record(record_dict),
                prescreen_inclusion=True,
            )
        return selected_auto_include_ids

    @colrev.process.operation.Operation.decorate()
    def main(self, *, split_str: str = "NA") -> None:
        """Prescreen records (main entrypoint)"""

        if self.review_manager.settings.prescreen.explanation == "":
            print(
                f"\n{Colors.ORANGE}Provide a short explanation of the prescreen{Colors.END} "
                "(why should particular papers be included?):"
            )
            print(
                'Example objective: "Include papers that focus on digital technology."'
            )
            self.review_manager.settings.prescreen.explanation = input("")
            self.review_manager.save_settings()
        else:
            print("\nIn the prescreen, the following process is followed:\n")
            print("   " + self.review_manager.settings.prescreen.explanation)
            print()

        # pylint: disable=duplicate-code
        split = []
        if split_str != "NA":
            split = split_str.split(",")
            if "" in split:
                split.remove("")

        records = self.review_manager.dataset.load_records_dict()

        package_manager = self.review_manager.get_package_manager()

        prescreen_package_endpoints = (
            self.review_manager.settings.prescreen.prescreen_package_endpoints
        )
        if not prescreen_package_endpoints:
            self._prescreen_include_all(records)
            return

        for prescreen_package_endpoint in prescreen_package_endpoints:
            self.review_manager.logger.debug(
                f"Run {prescreen_package_endpoint['endpoint']}"
            )

            prescreen_class = package_manager.get_package_endpoint_class(
                package_type=EndpointType.prescreen,
                package_identifier=prescreen_package_endpoint["endpoint"],
            )
            endpoint = prescreen_class(
                prescreen_operation=self, settings=prescreen_package_endpoint
            )

            selected_record_ids = [
                r[Fields.ID]
                for r in records.values()
                if RecordState.md_processed == r[Fields.STATUS]
                and not r.get("include_flag", "0") == "1"
            ]
            endpoint.run_prescreen(records, split)  # type: ignore

            selected_auto_include_ids = self._auto_include(records)

            self._print_stats(
                selected_record_ids=selected_record_ids + selected_auto_include_ids
            )

        self.review_manager.logger.info(
            "%sCompleted prescreen operation%s", Colors.GREEN, Colors.END
        )
