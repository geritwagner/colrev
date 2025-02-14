#!/usr/bin/env python3
"""Template for a custom Prep PackageEndpoint"""
from __future__ import annotations

import colrev.package_manager.interfaces
import colrev.package_manager.package_settings
import colrev.process.operation
from colrev.constants import Fields


# pylint: disable=too-few-public-methods


class CustomPrep(colrev.package_manager.interfaces.PrepInterface):
    """Class for custom prep scripts"""

    settings_class = colrev.package_manager.package_settings.DefaultSettings
    source_correction_hint = "check with the developer"
    always_apply_changes = True

    def __init__(
        self,
        *,
        prep_operation: colrev.ops.prep.Prep,  # pylint: disable=unused-argument
        settings: dict,
    ) -> None:
        self.settings = self.settings_class(**settings)

    def prepare(
        self,
        record: colrev.record.record.Record,
    ) -> colrev.record.record.Record:
        """Update record (metadata)"""

        if Fields.JOURNAL in record.data:
            if record.data[Fields.JOURNAL] == "MISQ":
                record.update_field(
                    key=Fields.JOURNAL, value="MIS Quarterly", source="custom_prep"
                )

        return record
