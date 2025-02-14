#! /usr/bin/env python
"""Consolidation of metadata based on the Pubmed API as a prep operation"""
from __future__ import annotations

from pydantic import Field

import colrev.package_manager.interfaces
import colrev.package_manager.package_manager
import colrev.package_manager.package_settings
import colrev.packages.pubmed.src.pubmed as pubmed_connector
import colrev.record.record
from colrev.constants import Fields

# pylint: disable=duplicate-code


# pylint: disable=too-few-public-methods
# pylint: disable=duplicate-code


class PubmedMetadataPrep(colrev.package_manager.interfaces.PrepInterface):
    """Prepares records based on Pubmed metadata"""

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

        self.pubmed_source = pubmed_connector.PubMedSearchSource(
            source_operation=prep_operation
        )

        self.pubmed_prefixes = [
            s.get_origin_prefix()
            for s in prep_operation.review_manager.settings.sources
            if s.endpoint == "colrev.pubmed"
        ]

    def check_availability(
        self, *, source_operation: colrev.process.operation.Operation
    ) -> None:
        """Check status (availability) of the Pubmed API"""
        self.pubmed_source.check_availability(source_operation=source_operation)

    def prepare(
        self, record: colrev.record.record_prep.PrepRecord
    ) -> colrev.record.record.Record:
        """Prepare a record based on Pubmed metadata"""

        if any(
            pubmed_prefix in o
            for pubmed_prefix in self.pubmed_prefixes
            for o in record.data[Fields.ORIGIN]
        ):
            # Already linked to a pubmed record
            return record

        self.pubmed_source.prep_link_md(
            prep_operation=self.prep_operation, record=record
        )
        return record
