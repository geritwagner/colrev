#! /usr/bin/env python
"""Consolidation of metadata based on Europe PMC API as a prep operation"""
from __future__ import annotations

from pydantic import Field

import colrev.package_manager.interfaces
import colrev.package_manager.package_manager
import colrev.package_manager.package_settings
import colrev.packages.europe_pmc.src.europe_pmc as europe_pmc_connector
import colrev.record.record


# pylint: disable=too-few-public-methods
# pylint: disable=duplicate-code


class EuropePMCMetadataPrep(colrev.package_manager.interfaces.PrepInterface):
    """Prepares records based on Europe PCM metadata"""

    settings_class = colrev.package_manager.package_settings.DefaultSettings

    ci_supported: bool = Field(default=True)

    source_correction_hint = "ask the publisher to correct the metadata"
    always_apply_changes = False

    def __init__(
        self,
        *,
        prep_operation: colrev.ops.prep.Prep,
        settings: dict,
    ) -> None:
        self.settings = self.settings_class(**settings)
        self.prep_operation = prep_operation
        self.review_manager = prep_operation.review_manager
        self.epmc_source = europe_pmc_connector.EuropePMCSearchSource(
            source_operation=self.prep_operation
        )

    def prepare(
        self, record: colrev.record.record_prep.PrepRecord
    ) -> colrev.record.record.Record:
        """Prepare a record based on Europe PMC metadata"""

        self.epmc_source.prep_link_md(prep_operation=self.prep_operation, record=record)
        return record
