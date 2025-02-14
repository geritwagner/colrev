#! /usr/bin/env python
"""Consolidation of metadata based on DBLP API as a prep operation"""
from __future__ import annotations

from pydantic import Field

import colrev.package_manager.interfaces
import colrev.package_manager.package_manager
import colrev.package_manager.package_settings
import colrev.packages.dblp.src.dblp as dblp_connector
import colrev.record.record
from colrev.constants import Fields


# pylint: disable=too-few-public-methods
# pylint: disable=duplicate-code


class DBLPMetadataPrep(colrev.package_manager.interfaces.PrepInterface):
    """Prepares records based on dblp.org metadata"""

    ci_supported: bool = Field(default=True)
    settings_class = colrev.package_manager.package_settings.DefaultSettings

    source_correction_hint = (
        "send and email to dblp@dagstuhl.de"
        + " (see https://dblp.org/faq/How+can+I+correct+errors+in+dblp.html)"
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
        self.dblp_source = dblp_connector.DBLPSearchSource(
            source_operation=prep_operation
        )

        self.dblp_prefixes = [
            s.get_origin_prefix()
            for s in prep_operation.review_manager.settings.sources
            if s.endpoint == "colrev.dblp"
        ]

    def check_availability(
        self, *, source_operation: colrev.process.operation.Operation
    ) -> None:
        """Check status (availability) of the Crossref API"""
        self.dblp_source.check_availability(source_operation=source_operation)

    def prepare(
        self, record: colrev.record.record_prep.PrepRecord
    ) -> colrev.record.record.Record:
        """Prepare a record by retrieving its metadata from DBLP"""

        if any(
            dblp_prefix in o
            for dblp_prefix in self.dblp_prefixes
            for o in record.data[Fields.ORIGIN]
        ):
            # Already linked to a dblp record
            return record

        self.dblp_source.prep_link_md(prep_operation=self.prep_operation, record=record)

        return record
