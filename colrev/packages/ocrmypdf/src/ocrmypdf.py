#! /usr/bin/env python
"""OCR as a PDF preparation operation"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import docker
from pydantic import Field

import colrev.env.docker_manager
import colrev.env.utils
import colrev.package_manager.interfaces
import colrev.package_manager.package_manager
import colrev.package_manager.package_settings
import colrev.record.record
from colrev.constants import Fields
from colrev.constants import PDFDefectCodes

# pylint: disable=too-few-public-methods
# pylint: disable=duplicate-code


class OCRMyPDF(colrev.package_manager.interfaces.PDFPrepInterface):
    """Prepare PDFs by applying OCR based on OCRmyPDF"""

    settings_class = colrev.package_manager.package_settings.DefaultSettings
    ci_supported: bool = Field(default=False)
    OCRMYPDF_IMAGE = "jbarlow83/ocrmypdf:latest"

    def __init__(
        self,
        *,
        pdf_prep_operation: colrev.ops.pdf_prep.PDFPrep,
        settings: dict,
    ) -> None:
        self.settings = self.settings_class(**settings)
        self.review_manager = pdf_prep_operation.review_manager

        if not self.review_manager.in_ci_environment():
            colrev.env.docker_manager.DockerManager.build_docker_image(
                imagename=self.OCRMYPDF_IMAGE
            )
        pdf_prep_operation.docker_images_to_stop.append(self.OCRMYPDF_IMAGE)

    def _apply_ocr(
        self,
        *,
        record: colrev.record.record_pdf.PDFRecord,
    ) -> colrev.record.record_pdf.PDFRecord:
        pdf_path = self.review_manager.path / Path(record.data[Fields.FILE])
        non_ocred_filename = Path(str(pdf_path).replace(".pdf", "_no_ocr.pdf"))
        shutil.move(str(pdf_path), str(non_ocred_filename))
        orig_path = (
            pdf_path.parents[0] if pdf_path.is_file() else self.review_manager.paths.pdf
        )

        # options = ""
        # if rotate:
        #     options = options + '--rotate-pages '
        # if deskew:
        #     options = options + '--deskew '
        docker_home_path = Path("/home/docker")

        non_ocr_fname = docker_home_path / non_ocred_filename.name
        docker_output_fname = docker_home_path / pdf_path.name
        args = (
            f"--force-ocr --jobs 4 -l eng {non_ocr_fname.as_posix()} "
            f"{docker_output_fname.as_posix()}"
        )

        client = docker.from_env(timeout=120)
        client.containers.run(
            image=self.OCRMYPDF_IMAGE,
            command=args,
            auto_remove=True,
            user=f"{os.geteuid()}:{os.getegid()}",
            volumes=[f"{orig_path}:/home/docker"],
        )

        record.add_field_provenance_note(
            key=Fields.FILE, note="pdf_processed with OCRMYPDF"
        )
        record.set_text_from_pdf()
        return record

    def prep_pdf(
        self,
        record: colrev.record.record_pdf.PDFRecord,
        pad: int,  # pylint: disable=unused-argument
    ) -> colrev.record.record_pdf.PDFRecord:
        """Prepare the PDF by applying OCR"""

        if (
            Fields.FILE not in record.data
            or not record.data[Fields.FILE].endswith(".pdf")
            or PDFDefectCodes.NO_TEXT_IN_PDF not in record.defects("file")
        ):
            return record

        self.review_manager.report_logger.info(f"apply_ocr({record.data[Fields.ID]})")
        record = self._apply_ocr(record=record)

        return record
