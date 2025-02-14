#! /usr/bin/env python
"""Template for a custom Screen PackageEndpoint"""
from __future__ import annotations

import random
import typing

import colrev.package_manager.interfaces
import colrev.package_manager.package_settings
import colrev.process.operation
import colrev.record.record
from colrev.constants import Fields

if typing.TYPE_CHECKING:  # pragma: no cover
    import colrev.screen.Screen

# pylint: disable=too-few-public-methods


class CustomScreen(colrev.package_manager.interfaces.ScreenInterface):
    """Class for custom screen scripts"""

    settings_class = colrev.package_manager.package_settings.DefaultSettings

    def __init__(
        self,
        *,
        screen_operation: colrev.screen.Screen,  # pylint: disable=unused-argument
        settings: dict,
    ) -> None:
        self.settings = self.settings_class(**settings)
        self.screen_operation = screen_operation

    def run_screen(self, records: dict, split: list) -> dict:
        """Screen a record"""

        screen_data = self.screen_operation.get_data()
        screening_criteria = (
            self.screen_operation.review_manager.settings.screen.criteria
        )

        screening_criteria_available = bool(screening_criteria)

        for record_dict in screen_data["items"]:
            if len(split) > 0:
                if record_dict[Fields.ID] not in split:
                    continue

            record = colrev.record.record.Record(record_dict)

            if random.random() < 0.5:  # nosec
                if screening_criteria_available:
                    # record criteria
                    pass
                self.screen_operation.screen(
                    record=record,
                    screen_inclusion=True,
                    screening_criteria="...",
                )

            else:
                if screening_criteria_available:
                    # record criteria
                    pass
                self.screen_operation.screen(
                    record=record,
                    screen_inclusion=False,
                    screening_criteria="...",
                )

        self.screen_operation.review_manager.dataset.save_records_dict(records)
        self.screen_operation.review_manager.dataset.add_record_changes()
        self.screen_operation.review_manager.dataset.create_commit(
            msg="Screen (random)", manual_author=False, script_call="colrev screen"
        )
        return records
