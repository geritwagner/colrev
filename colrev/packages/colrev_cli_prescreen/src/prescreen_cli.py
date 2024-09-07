#! /usr/bin/env python
"""Prescreen based on CLI"""
from __future__ import annotations

import textwrap
from dataclasses import dataclass

import zope.interface
from dataclasses_jsonschema import JsonSchemaMixin

import colrev.package_manager.interfaces
import colrev.package_manager.package_manager
import colrev.package_manager.package_settings
import colrev.record.record
from colrev.constants import Colors
from colrev.constants import ENTRYTYPES
from colrev.constants import Fields


# pylint: disable=too-few-public-methods


@zope.interface.implementer(colrev.package_manager.interfaces.PrescreenInterface)
@dataclass
class CoLRevCLIPrescreen(JsonSchemaMixin):
    """CLI-based prescreen"""

    settings_class = colrev.package_manager.package_settings.DefaultSettings
    ci_supported: bool = False

    def __init__(
        self,
        *,
        prescreen_operation: colrev.ops.prescreen.Prescreen,
        settings: dict,
    ) -> None:
        self.settings = self.settings_class.load_settings(data=settings)
        self.prescreen_operation = prescreen_operation
        self.review_manager = prescreen_operation.review_manager

    def _print_prescreen_record(self, record: colrev.record.record.Record) -> None:
        """Print the record for prescreen operations"""

        ret_str = f"  ID: {record.data['ID']} ({record.data[Fields.ENTRYTYPE]})"
        ret_str += (
            f"\n  {Colors.GREEN}{record.data.get(Fields.TITLE, 'no title')}{Colors.END}"
            f"\n  {record.data.get(Fields.AUTHOR, 'no-author')}"
        )
        if record.data[Fields.ENTRYTYPE] == ENTRYTYPES.ARTICLE:
            ret_str += (
                f"\n  {record.data.get(Fields.JOURNAL, 'no-journal')} "
                f"({record.data.get(Fields.YEAR, 'no-year')}) "
                f"{record.data.get(Fields.VOLUME, 'no-volume')}"
                f"({record.data.get(Fields.NUMBER, '')})"
            )
        elif record.data[Fields.ENTRYTYPE] == ENTRYTYPES.INPROCEEDINGS:
            ret_str += f"\n  {record.data.get(Fields.BOOKTITLE, 'no-booktitle')}"
        if Fields.ABSTRACT in record.data:
            lines = textwrap.wrap(
                record.data[Fields.ABSTRACT], 100, break_long_words=False
            )
            if lines:
                ret_str += f"\n  Abstract: {lines.pop(0)}\n"
                ret_str += "\n  ".join(lines) + ""

        if Fields.URL in record.data:
            ret_str += f"\n  url: {record.data[Fields.URL]}"

        if Fields.FILE in record.data:
            ret_str += f"\n  file: {record.data[Fields.FILE]}"

        print(ret_str)

    def _fun_cli_prescreen(
        self,
        *,
        prescreen_data: dict,
        split: list,
        stat_len: int,
        padding: int,
    ) -> bool:
        self.review_manager.logger.debug("Start prescreen")

        if 0 == stat_len:
            self.review_manager.logger.info("No records to prescreen")

        i, quit_pressed = 0, False
        for record_dict in prescreen_data["items"]:
            if len(split) > 0:
                if record_dict[Fields.ID] not in split:
                    continue

            record = colrev.record.record.Record(record_dict)
            ret, inclusion_decision_str = "NA", "NA"
            i += 1

            print("\n\n")
            print(f"Record {i} (of {stat_len})\n")
            self._print_prescreen_record(record)

            while ret not in ["y", "n", "s", "q"]:
                ret = input(
                    "\nInclude this record "
                    "[enter y,n,s,q for yes, no, skip/decide later, quit-and-save]? "
                )
                if ret == "q":
                    quit_pressed = True
                elif ret == "s":
                    continue
                else:
                    inclusion_decision_str = ret.replace("y", "yes").replace("n", "no")

            if quit_pressed:
                self.review_manager.logger.info("Stop prescreen")
                break

            if ret == "s":
                continue

            inclusion_decision = "yes" == inclusion_decision_str
            self.prescreen_operation.prescreen(
                record=record,
                prescreen_inclusion=inclusion_decision,
                PAD=padding,
            )

        return i == stat_len

    def run_prescreen(
        self,
        records: dict,
        split: list,
    ) -> dict:
        """Prescreen records based on a cli"""

        if not split:
            split = []

        prescreen_data = self.prescreen_operation.get_data()
        stat_len = len(split) if len(split) > 0 else prescreen_data["nr_tasks"]
        padding = prescreen_data["PAD"]

        self._fun_cli_prescreen(
            prescreen_data=prescreen_data,
            split=split,
            stat_len=stat_len,
            padding=padding,
        )

        # Note : currently, it is easier to create a commit in all cases.
        # Upon continuing the prescreen, the scope-based prescreen commits the changes,
        # which is misleading.
        # Users can still squash commits.
        # Note: original: completed = self._fun_cli_prescreen(...
        # if not completed:
        #     if input("Create commit (y/n)?") != "y":
        #         return records

        self.review_manager.dataset.create_commit(
            msg="Pre-screen: manual screen (cli)", manual_author=True
        )
        return records
