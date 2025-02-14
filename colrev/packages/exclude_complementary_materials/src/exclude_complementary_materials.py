#! /usr/bin/env python
"""Exclude complementary materials as a prep operation"""
from __future__ import annotations

from pydantic import Field

import colrev.package_manager.interfaces
import colrev.package_manager.package_manager
import colrev.package_manager.package_settings
import colrev.record.record
from colrev.constants import Fields

# pylint: disable=duplicate-code


# pylint: disable=too-few-public-methods


class ExcludeComplementaryMaterialsPrep(
    colrev.package_manager.interfaces.PrepInterface
):
    """Prepares records by excluding complementary materials
    (tables of contents, editorial boards, about our authors)"""

    settings_class = colrev.package_manager.package_settings.DefaultSettings

    ci_supported: bool = Field(default=True)

    source_correction_hint = "check with the developer"
    always_apply_changes = True

    def __init__(
        self,
        *,
        prep_operation: colrev.ops.prep.Prep,  # pylint: disable=unused-argument
        settings: dict,
    ) -> None:
        self.settings = self.settings_class(**settings)

        self.complementary_materials_keywords = (
            colrev.env.utils.load_complementary_material_keywords()
        )

        # for exact matches:
        self.complementary_materials_strings = (
            colrev.env.utils.load_complementary_material_strings()
        )

        # for prefixes:
        self.complementary_material_prefixes = (
            colrev.env.utils.load_complementary_material_prefixes()
        )

    def prepare(
        self, record: colrev.record.record_prep.PrepRecord
    ) -> colrev.record.record.Record:
        """Prepare the records by excluding complementary materials"""

        if (
            any(
                complementary_materials_keyword
                in record.data.get(Fields.TITLE, "").lower()
                for complementary_materials_keyword in self.complementary_materials_keywords
            )
            or any(
                complementary_materials_string
                == record.data.get(Fields.TITLE, "").lower()
                for complementary_materials_string in self.complementary_materials_strings
            )
            or any(
                record.data.get(Fields.TITLE, "").lower().startswith(prefix)
                for prefix in self.complementary_material_prefixes
            )
        ):
            record.prescreen_exclude(reason="complementary material")

        return record
