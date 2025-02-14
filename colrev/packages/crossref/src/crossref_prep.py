#! /usr/bin/env python
"""Consolidation of metadata based on Crossref API as a prep operation"""
from __future__ import annotations

from pydantic import Field

import colrev.package_manager.interfaces
import colrev.package_manager.package_manager
import colrev.package_manager.package_settings
import colrev.packages.crossref.src.crossref_search_source as crossref_connector
import colrev.record.record
from colrev.constants import Fields


# pylint: disable=too-few-public-methods
# pylint: disable=duplicate-code


class CrossrefMetadataPrep(colrev.package_manager.interfaces.PrepInterface):
    """Prepares records based on crossref.org metadata"""

    settings_class = colrev.package_manager.package_settings.DefaultSettings

    ci_supported: bool = Field(default=True)

    source_correction_hint = (
        "ask the publisher to correct the metadata"
        + " (see https://www.crossref.org/blog/"
        + "metadata-corrections-updates-and-additions-in-metadata-manager/"
    )
    always_apply_changes = False

    def __init__(
        self,
        *,
        prep_operation: colrev.ops.prep.Prep,
        settings: dict,
    ) -> None:
        self.settings = self.settings_class(**settings)
        self.prep_operation = prep_operation
        self.crossref_source = crossref_connector.CrossrefSearchSource(
            source_operation=prep_operation
        )

        self.crossref_prefixes = [
            s.get_origin_prefix()
            for s in prep_operation.review_manager.settings.sources
            if s.endpoint == "colrev.crossref"
        ]

    def check_availability(
        self, *, source_operation: colrev.process.operation.Operation
    ) -> None:
        """Check status (availability) of the Crossref API"""
        self.crossref_source.check_availability(source_operation=source_operation)

    def prepare(
        self, record: colrev.record.record_prep.PrepRecord
    ) -> colrev.record.record.Record:
        """Prepare a record based on Crossref metadata"""

        if any(
            crossref_prefix in o
            for crossref_prefix in self.crossref_prefixes
            for o in record.data[Fields.ORIGIN]
        ):
            # Already linked to a crossref record
            return record

        self.crossref_source.prep_link_md(
            prep_operation=self.prep_operation, record=record
        )
        return record
