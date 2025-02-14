#! /usr/bin/env python
"""Genral polishing rules"""
from __future__ import annotations

import re

from pydantic import Field

import colrev.package_manager.interfaces
import colrev.package_manager.package_manager
import colrev.package_manager.package_settings
import colrev.record.record
from colrev.constants import Fields


# pylint: disable=too-few-public-methods
# pylint: disable=duplicate-code


class GeneralPolishPrep(colrev.package_manager.interfaces.PrepInterface):
    """Prepares records by applying polishing rules"""

    settings_class = colrev.package_manager.package_settings.DefaultSettings

    ci_supported: bool = Field(default=True)

    source_correction_hint = "check with the developer"
    always_apply_changes = False

    frequent_acronyms = [
        "MIS",
        "GSS",
        "DSS",
        "ICIS",
        "ECIS",
        "AMCIS",
        "PACIS",
        "BI",
        "CRM",
        "CIO",
        "CEO",
        "ERP",
        "ICT",
        "Twitter",
        "Facebook",
        "Wikipedia",
        "B2B",
        "C2C",
    ]

    def __init__(
        self,
        *,
        prep_operation: colrev.ops.prep.Prep,  # pylint: disable=unused-argument
        settings: dict,
    ) -> None:
        self.settings = self.settings_class(**settings)

    def prepare(
        self, record: colrev.record.record_prep.PrepRecord
    ) -> colrev.record.record.Record:
        """Prepare the record by applying polishing rules"""

        if Fields.TITLE in record.data:
            acronyms = [
                x
                for x in self.frequent_acronyms
                if x.lower() in record.data[Fields.TITLE].lower().split()
            ]
            for acronym in acronyms:
                record.data[Fields.TITLE] = re.sub(
                    acronym, acronym, record.data[Fields.TITLE], flags=re.I
                )

        return record
