#! /usr/bin/env python
"""Creation of TEI as a PDF preparation operation"""
from __future__ import annotations

from pathlib import Path

from pydantic import Field

import colrev.env.utils
import colrev.package_manager.interfaces
import colrev.package_manager.package_manager
import colrev.package_manager.package_settings
import colrev.record.record
from colrev.constants import Fields


# pylint: disable=too-few-public-methods


class GROBIDTEI(colrev.package_manager.interfaces.PDFPrepInterface):
    """Prepare PDFs by creating an annotated TEI document"""

    settings_class = colrev.package_manager.package_settings.DefaultSettings

    TEI_PATH_RELATIVE = Path("data/.tei/")
    ci_supported: bool = Field(default=False)

    def __init__(
        self, *, pdf_prep_operation: colrev.ops.pdf_prep.PDFPrep, settings: dict
    ) -> None:
        self.settings = self.settings_class(**settings)
        self.review_manager = pdf_prep_operation.review_manager

        if not pdf_prep_operation.review_manager.in_ci_environment():
            grobid_service = pdf_prep_operation.review_manager.get_grobid_service()
            grobid_service.start()
            self.tei_path = (
                pdf_prep_operation.review_manager.path / self.TEI_PATH_RELATIVE
            )
            self.tei_path.mkdir(exist_ok=True, parents=True)
            pdf_prep_operation.docker_images_to_stop.append(grobid_service.GROBID_IMAGE)

    def prep_pdf(
        self,
        record: colrev.record.record_pdf.PDFRecord,
        pad: int,  # pylint: disable=unused-argument
    ) -> colrev.record.record_pdf.PDFRecord:
        """Prepare the analysis of PDFs by creating a TEI (based on GROBID)"""

        if not record.data.get(Fields.FILE, "NA").endswith(".pdf"):
            return record

        if not record.get_tei_filename().is_file():
            self.review_manager.logger.debug(f" creating tei: {record.data['ID']}")
            _ = self.review_manager.get_tei(
                pdf_path=Path(record.data[Fields.FILE]),
                tei_path=record.get_tei_filename(),
            )

        return record
