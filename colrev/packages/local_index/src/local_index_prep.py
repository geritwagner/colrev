#! /usr/bin/env python
"""Conslidation of metadata based on LocalIndex as a prep operation"""
from __future__ import annotations

from pydantic import Field

import colrev.package_manager.interfaces
import colrev.package_manager.package_manager
import colrev.package_manager.package_settings
import colrev.packages.local_index.src.local_index as local_index_connector
import colrev.record.record
from colrev.constants import Fields

# pylint: disable=duplicate-code


# pylint: disable=too-few-public-methods


class LocalIndexPrep(colrev.package_manager.interfaces.PrepInterface):
    """Prepares records based on LocalIndex metadata"""

    settings_class = colrev.package_manager.package_settings.DefaultSettings

    ci_supported: bool = Field(default=True)

    source_correction_hint = (
        "correct the metadata in the source "
        + "repository (as linked in the provenance field)"
    )
    always_apply_changes = True

    def __init__(self, *, prep_operation: colrev.ops.prep.Prep, settings: dict) -> None:
        self.settings = self.settings_class(**settings)

        self.local_index_source = local_index_connector.LocalIndexSearchSource(
            source_operation=prep_operation
        )
        self.prep_operation = prep_operation

    def prepare(
        self, record: colrev.record.record_prep.PrepRecord
    ) -> colrev.record.record.Record:
        """Prepare the record metadata based on local-index"""

        # don't move to  jour_iss_number_year prep
        # because toc-retrieval relies on adequate toc items!
        if (
            Fields.VOLUME in record.data
            and Fields.NUMBER in record.data
            and not record.masterdata_is_curated()
        ):
            # Note : cannot use local_index as an attribute of PrepProcess
            # because it creates problems with multiprocessing
            fields_to_remove = self.local_index_source.local_index.get_fields_to_remove(
                record.get_data()
            )
            for field_to_remove in fields_to_remove:
                if field_to_remove in record.data:
                    record.remove_field(
                        key=field_to_remove,
                        not_missing_note=True,
                        source="local_index",
                    )

        self.local_index_source.prep_link_md(
            prep_operation=self.prep_operation, record=record
        )

        return record
