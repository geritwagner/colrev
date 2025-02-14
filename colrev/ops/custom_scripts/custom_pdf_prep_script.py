#! /usr/bin/env python
"""Template for a custom PDFPrep PackageEndpoint"""
from __future__ import annotations

import random

import colrev.package_manager.interfaces
import colrev.package_manager.package_settings
import colrev.process.operation
import colrev.record.record
from colrev.constants import Fields
from colrev.constants import RecordState


# pylint: disable=too-few-public-methods


class CustomPDFPrep(colrev.package_manager.interfaces.PDFPrepInterface):
    """Class for custom pdf-prep scripts"""

    settings_class = colrev.package_manager.package_settings.DefaultSettings

    def __init__(
        self,
        *,
        pdf_prep_operation: colrev.ops.pdf_prep.PDFPrep,
        settings: dict,
    ) -> None:
        self.settings = self.settings_class(**settings)
        self.pdf_prep_operation = pdf_prep_operation

    def prep_pdf(
        self,
        record: colrev.record.record.Record,
        pad: int,  # pylint: disable=unused-argument
    ) -> colrev.record.record.Record:
        """Prepare the PDF"""

        if random.random() < 0.8:  # nosec
            record.add_field_provenance_note(
                key=Fields.FILE, note="custom_issue_detected"
            )
            record.set_status(RecordState.pdf_needs_manual_preparation)

        return record
