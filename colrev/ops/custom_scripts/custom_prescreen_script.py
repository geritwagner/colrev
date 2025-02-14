#! /usr/bin/env python
"""Template for a custom Prescreen PackageEndpoint"""
from __future__ import annotations

import random

import colrev.package_manager.interfaces
import colrev.package_manager.package_settings
import colrev.process.operation
import colrev.record.record


# pylint: disable=too-few-public-methods


class CustomPrescreen(colrev.package_manager.interfaces.PrescreenInterface):
    """Class for custom prescreen scripts"""

    settings_class = colrev.package_manager.package_settings.DefaultSettings

    def __init__(
        self,
        *,
        prescreen_operation: colrev.ops.prescreen.Prescreen,  # pylint: disable=unused-argument
        settings: dict,
    ) -> None:
        self.settings = self.settings_class(**settings)
        self.prescreen_operation = prescreen_operation

    def run_prescreen(
        self,
        records: dict,
        split: list,  # pylint: disable=unused-argument
    ) -> dict:
        """Prescreen the record"""

        for record in records.values():
            if random.random() < 0.5:  # nosec
                self.prescreen_operation.prescreen(
                    record=colrev.record.record.Record(record), prescreen_inclusion=True
                )

            else:
                self.prescreen_operation.prescreen(
                    record=colrev.record.record.Record(record),
                    prescreen_inclusion=False,
                )

        self.prescreen_operation.review_manager.dataset.save_records_dict(records)
        self.prescreen_operation.review_manager.dataset.create_commit(
            msg="Pre-screen (random)",
            manual_author=False,
            script_call="colrev prescreen",
        )

        return records
