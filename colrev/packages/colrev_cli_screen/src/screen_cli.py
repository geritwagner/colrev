#! /usr/bin/env python
"""Screen based on CLI"""
from __future__ import annotations

from inquirer import Checkbox
from inquirer import prompt
from pydantic import Field

import colrev.package_manager.interfaces
import colrev.package_manager.package_manager
import colrev.package_manager.package_settings
import colrev.packages.screen_utils as util_cli_screen
import colrev.record.record
import colrev.settings
from colrev.constants import Colors
from colrev.constants import Fields
from colrev.constants import ScreenCriterionType


class CoLRevCLIScreen(colrev.package_manager.interfaces.ScreenInterface):
    """Screen documents using a CLI"""

    # pylint: disable=too-many-instance-attributes
    # pylint: disable=too-few-public-methods

    settings_class = colrev.package_manager.package_settings.DefaultSettings

    ci_supported: bool = Field(default=False)

    def __init__(
        self,
        *,
        screen_operation: colrev.ops.screen.Screen,
        settings: dict,
    ) -> None:
        self.review_manager = screen_operation.review_manager
        self.screen_operation = screen_operation
        self.settings = self.settings_class(**settings)

        self._i = 0
        self._pad = 0
        self._stat_len = 0
        self.screening_criteria: dict = {}
        self.criteria_available = 0

    def _print_screening_criteria(self) -> None:
        if not self.review_manager.settings.screen.criteria:
            return
        print("\nIn the screen, the following criteria are applied:\n")
        for (
            criterion_name,
            criterion_settings,
        ) in self.review_manager.settings.screen.criteria.items():
            color = Colors.GREEN
            if (
                ScreenCriterionType.exclusion_criterion
                == criterion_settings.criterion_type
            ):
                color = Colors.RED
            print(
                f" - {criterion_name} "
                f"({color}{criterion_settings.criterion_type}{Colors.END}): "
                f"{criterion_settings.explanation}"
            )
            if criterion_settings.comment:
                print(f"   {criterion_settings.comment}")

    def _screen_with_criteria_print_overall_decision(
        self, *, record: colrev.record.record.Record, screen_inclusion: bool
    ) -> None:
        if screen_inclusion:
            print(
                f"Overall screening decision for {record.data['ID']}: "
                f"{Colors.GREEN}include{Colors.END}"
            )
        else:
            print(
                f"Overall screening decision for {record.data['ID']}: "
                f"{Colors.RED}exclude{Colors.END}"
            )

    # pylint: disable=too-many-branches
    def _screen_record_with_criteria(
        self,
        record: colrev.record.record.Record,
    ) -> str:
        choices = []
        for criterion_name, criterion_settings in self.screening_criteria.items():
            color = Colors.GREEN
            if (
                ScreenCriterionType.exclusion_criterion
                == criterion_settings.criterion_type
            ):
                color = Colors.RED
            choices.append(f"{color}{criterion_name}{Colors.END} violated")
        choices.append("Include (no criterion violated)")
        choices.append("Skip")
        choices.append("Quit")
        question = [
            Checkbox(
                "violated_criteria",
                message="Select the criteria that are violated "
                + "[use space to select (if any), use Enter to confirm]:",
                choices=choices,
            ),
        ]

        while True:
            answers = prompt(question)
            violated_criteria = answers["violated_criteria"]

            # can only select one of the options quit, skip, or include/no criterion violated
            if "Quit" in violated_criteria and len(violated_criteria) > 1:
                print(
                    "Contradiction: 'Quit' and other criteria selected. Please select again."
                )
                continue
            if "Skip" in violated_criteria and len(violated_criteria) > 1:
                print(
                    "Contradiction: 'Skip' and other criteria selected. Please select again."
                )
                continue
            if (
                "Include (no criterion violated)" in violated_criteria
                and len(violated_criteria) > 1
            ):
                print(
                    "Contradiction: 'Include (no criterion violated)'"
                    " and other criteria selected. Please select again."
                )
                continue
            # prevent contradiction (include and criterion violated)
            if "Include (no criterion violated)" in violated_criteria:
                violated_criteria.remove("Include (no criterion violated)")
                if violated_criteria:
                    print(
                        "Contradiction: 'Include (no criterion violated)' "
                        "and other criteria selected. Please select again."
                    )
                    continue
            break

        if "Skip" in violated_criteria:
            return "skip"
        if "Quit" in violated_criteria:
            return "quit"

        decisions = {c: "in" for c in self.screening_criteria.keys()}
        if "Include (no criterion violated)" not in violated_criteria:
            for criterion_name in violated_criteria:
                decisions[
                    criterion_name.replace(Colors.RED, "")
                    .replace(Colors.END, "")
                    .replace(Colors.GREEN, "")
                    .replace(" violated", "")
                ] = "out"

        c_field = ""
        for criterion_name, decision in decisions.items():
            c_field += f";{criterion_name}={decision}"
        c_field = c_field.replace(" ", "").lstrip(";")

        screen_inclusion = all(decision == "in" for _, decision in decisions.items())

        self._screen_with_criteria_print_overall_decision(
            record=record, screen_inclusion=screen_inclusion
        )

        self.screen_operation.screen(
            record=record,
            screen_inclusion=screen_inclusion,
            screening_criteria=c_field,
            PAD=self._pad,
        )
        return "screened"

    def _screen_record_without_criteria(
        self,
        record: colrev.record.record.Record,
    ) -> str:
        quit_pressed = False
        decision, ret = "NA", "NA"
        while ret not in ["y", "n", "q", "s"]:
            ret = input(
                f"({self._i}/{self._stat_len}) "
                "Include [y,n,q,s for yes, no, quit, skip/screen later]? "
            )
            if ret == "q":
                quit_pressed = True
            elif ret == "s":
                return "skip"
            elif ret in ["y", "n"]:
                decision = ret

        if quit_pressed:
            self.review_manager.logger.info("Stop screen")
            return "quit"

        if decision == "y":
            self.screen_operation.screen(
                record=record,
                screen_inclusion=True,
                screening_criteria="NA",
            )
        if decision == "n":
            self.screen_operation.screen(
                record=record,
                screen_inclusion=False,
                screening_criteria="NA",
                PAD=self._pad,
            )
        return "screened"

    def _screen_record(
        self,
        *,
        record_dict: dict,
    ) -> str:
        record = colrev.record.record.Record(record_dict)

        self._i += 1
        print("\n\n")
        print(f"Record {self._i} (of {self._stat_len})")
        print()
        print(record.data["ID"])
        print()
        record.print_citation_format()
        if "abstract" in record.data:
            print()
            print(record.data["abstract"])
        print()
        if self.criteria_available:
            ret = self._screen_record_with_criteria(record)

        else:
            ret = self._screen_record_without_criteria(record)

        return ret

    def _screen_cli(self, split: list) -> dict:
        screen_data = self.screen_operation.get_data()
        self._pad = screen_data["PAD"]
        self._stat_len = screen_data["nr_tasks"]

        if 0 == self._stat_len:
            self.review_manager.logger.info("No records to prescreen")

        records = self.review_manager.dataset.load_records_dict()

        self._print_screening_criteria()

        self.screening_criteria = (
            util_cli_screen.get_screening_criteria_from_user_input(
                screen_operation=self.screen_operation, records=records
            )
        )
        self.criteria_available = len(self.screening_criteria.keys())

        for record_dict in screen_data["items"]:
            if record_dict[Fields.ID] not in split:
                continue

            ret = self._screen_record(record_dict=record_dict)

            if ret == "skip":
                continue
            if ret == "quit":
                self.review_manager.logger.info("Stop screen")
                break

        if self._stat_len == 0:
            self.review_manager.logger.info("No records to screen")
            return records

        if self._i < self._stat_len and split:  # if records remain for screening
            if input("Create commit (y/n)?") != "y":
                return records

        self.review_manager.dataset.create_commit(
            msg="Screen: manual (cli)", manual_author=True
        )
        return records

    def run_screen(self, records: dict, split: list) -> dict:
        """Screen records based on a cli"""

        records = self._screen_cli(split)

        return records
