#! /usr/bin/env python
"""Retrieval of PDFs from the LocalIndex"""
from __future__ import annotations

import shutil
from pathlib import Path

from pydantic import Field

import colrev.env.local_index
import colrev.exceptions as colrev_exceptions
import colrev.package_manager.interfaces
import colrev.package_manager.package_manager
import colrev.package_manager.package_settings
import colrev.record.record
from colrev.constants import Fields

# pylint: disable=duplicate-code
# pylint: disable=too-few-public-methods


class LocalIndexPDFGet(colrev.package_manager.interfaces.PDFGetInterface):
    """Get PDFs from LocalIndex"""

    settings_class = colrev.package_manager.package_settings.DefaultSettings
    ci_supported: bool = Field(default=False)

    def __init__(
        self,
        *,
        pdf_get_operation: colrev.ops.pdf_get.PDFGet,  # pylint: disable=unused-argument
        settings: dict,
    ) -> None:
        self.settings = self.settings_class(**settings)
        self.pdf_get_operation = pdf_get_operation
        self.review_manager = pdf_get_operation.review_manager

    def get_pdf(
        self, record: colrev.record.record.Record
    ) -> colrev.record.record.Record:
        """Get PDFs from the local-index"""

        local_index = colrev.env.local_index.LocalIndex(
            verbose_mode=self.review_manager.verbose_mode
        )

        try:
            retrieved_record = local_index.retrieve(record.data, include_file=True)
        except colrev_exceptions.RecordNotInIndexException:
            return record

        if Fields.FILE in retrieved_record.data:
            record.update_field(
                key=Fields.FILE,
                value=str(retrieved_record.data[Fields.FILE]),
                source="local_index",
            )
            self.pdf_get_operation.import_pdf(record)
            if Fields.FULLTEXT in retrieved_record.data:
                try:
                    record.get_tei_filename().write_text(
                        retrieved_record.data[Fields.FULLTEXT]
                    )
                except FileNotFoundError:
                    pass
                del retrieved_record.data[Fields.FULLTEXT]
            else:
                tei_ext_path = Path(
                    retrieved_record.data[Fields.FILE]
                    .replace("pdfs/", ".tei/")
                    .replace(".pdf", ".tei.xml")
                )
                if tei_ext_path.is_file():
                    new_path = record.get_tei_filename()
                    new_path.resolve().parent.mkdir(exist_ok=True, parents=True)
                    shutil.copy(tei_ext_path, new_path)

        return record
