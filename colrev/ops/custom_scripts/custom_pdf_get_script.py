#! /usr/bin/env python
"""Template for a custom PDFGet PackageEndpoint"""
from __future__ import annotations

import colrev.package_manager.interfaces
import colrev.package_manager.package_settings
import colrev.process.operation
from colrev.constants import Fields


# pylint: disable=too-few-public-methods


class CustomPDFGet(colrev.package_manager.interfaces.PDFGetInterface):
    """Class for custom pdf-get scripts"""

    settings_class = colrev.package_manager.package_settings.DefaultSettings

    def __init__(
        self,
        *,
        pdf_get_operation: colrev.ops.pdf_get.PDFGet,  # pylint: disable=unused-argument
        settings: dict,
    ) -> None:
        self.settings = self.settings_class(**settings)
        self.pdf_get_operation = pdf_get_operation

    def get_pdf(
        self,
        record: colrev.record.record.Record,
    ) -> colrev.record.record.Record:
        """Get the PDF"""

        record.data[Fields.FILE] = "filepath"
        self.pdf_get_operation.import_pdf(record)

        return record
