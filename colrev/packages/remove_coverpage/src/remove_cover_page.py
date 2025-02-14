#! /usr/bin/env python
"""Cover-page removal as a PDF preparation operation"""
from __future__ import annotations

import shutil
import typing
from pathlib import Path

import pymupdf
from pydantic import Field

import colrev.package_manager.interfaces
import colrev.package_manager.package_manager
import colrev.package_manager.package_settings
from colrev.constants import Fields
from colrev.constants import Filepaths

# pylint: disable=duplicate-code


# pylint: disable=too-few-public-methods


class PDFCoverPage(colrev.package_manager.interfaces.PDFPrepInterface):
    """Prepare PDFs by removing unnecessary cover pages (e.g. researchgate, publishers)"""

    settings_class = colrev.package_manager.package_settings.DefaultSettings

    ci_supported: bool = Field(default=False)

    def __init__(
        self,
        *,
        pdf_prep_operation: colrev.ops.pdf_prep.PDFPrep,
        settings: dict,
    ) -> None:
        self.settings = self.settings_class(**settings)
        self.review_manager = pdf_prep_operation.review_manager

    def _check_scholarworks_first_page(self, *, page0: str, coverpages: list) -> None:
        if "followthisandadditionalworksat:https://scholarworks" in page0:
            coverpages.append(0)

    def _check_researchgate_first_page(self, *, page0: str, coverpages: list) -> None:
        if (
            "discussions,stats,andauthorprofilesforthispublicationat:"
            + "https://www.researchgate.net/publication"
            in page0
            or "discussions,stats,andauthorproﬁlesforthispublicationat:"
            + "https://www.researchgate.net/publication"
            in page0
        ):
            coverpages.append(0)

    def _check_jstor_first_page(self, *, page0: str, coverpages: list) -> None:
        if (
            "pleasecontactsupport@jstor.org.youruseofthejstorarchiveindicatesy"
            + "ouracceptanceoftheterms&conditionsofuse"
            in page0
            or "formoreinformationregardingjstor,pleasecontactsupport@jstor.org"
            in page0
        ):
            coverpages.append(0)

    def _check_emerald_first_page(self, *, page0: str, coverpages: list) -> None:
        if (
            "emeraldisbothcounter4andtransfercompliant.theorganizationisapartnero"
            "fthecommitteeonpublicationethics(cope)andalsoworkswithporticoandthe"
            "lockssinitiativefordigitalarchivepreservation.*relatedcontentand"
            "downloadinformationcorrectattimeofdownload" in page0
        ):
            coverpages.append(0)

    def _check_informs_first_page(
        self, *, page0: str, page1: str, coverpages: list
    ) -> None:
        if (
            "thisarticlewasdownloadedby" in page0
            and "fulltermsandconditionsofuse:" in page0
        ):
            coverpages.append(0)
        if (
            "thisarticlemaybeusedonlyforthepurposesofresearch" in page0
            and "abstract" not in page0
            and "keywords" not in page0
            and "abstract" in page1
            and "keywords" in page1
        ):
            coverpages.append(0)

    def _check_ais_first_page(self, *, page0: str, coverpages: list) -> None:
        if (
            "associationforinformationsystemsaiselectroniclibrary(aisel)" in page0
            and "abstract" not in page0
            and "keywords" not in page0
        ):
            coverpages.append(0)

    def _check_tandf_first_page(
        self, *, page0: str, page1: str, coverpages: list
    ) -> None:
        if ("pleasescrolldownforarticle" in page0) or ("viewrelatedarticles" in page0):
            if "abstract" not in page0 and "keywords" not in page0:
                coverpages.append(0)
                if (
                    "terms-and-conditions" in page1
                    and "abstract" not in page1
                    and "keywords" not in page1
                ):
                    coverpages.append(1)

    def _get_coverpages(
        self, record: colrev.record.record_pdf.PDFRecord
    ) -> typing.List[int]:
        coverpages: typing.List[int] = []

        doc = pymupdf.Document(str(record.data[Fields.FILE]))

        if doc.page_count == 1:
            return coverpages

        first_page_average_hash_16 = record.get_pdf_hash(page_nr=1, hash_size=16)

        # Note : to generate hashes from a directory containing single-page PDFs:
        # colrev pdf-prep --get_hashes path
        first_page_hashes = [
            "ffff83ff81ff81ffc3ff803f81ff80ffc03fffffffffffffffff96ff9fffffff",
            "ffffffffc0ffc781c007c007cfffc7ffffffffffffffc03fc007c003c827ffff",
            "84ff847ffeff83ff800783ff801f800180038fffffffffffbfff8007bffff83f",
            "83ff03ff03ff83ffffff807f807f9fff87ffffffffffffffffff809fbfffffff",
            "ffffffffc0ffc781c03fc01fffffffffffffffffffffc03fc01fc003ffffffff",
            "ffffffffc0ffc781c007c007cfffc7ffffffffffffffc03fc007c003ce27ffff",
            "ffffe7ffe3ffc3fffeff802780ff8001c01fffffffffffffffff80079ffffe3f",
            "ffffffffc0ffc781c00fc00fc0ffc7ffffffffffffffc03fc007c003cf27ffff",
            "ffffffffc0ffc781c007c003cfffcfffffffffffffffc03fc003c003cc27ffff",
            "ffffe7ffe3ffc3ffffff80e780ff80018001ffffffffffffffff93ff83ff9fff",
        ]

        if str(first_page_average_hash_16) in first_page_hashes:
            coverpages.append(0)

        res = doc.load_page(0).get_text()
        page0 = res.replace(" ", "").replace("\n", "").lower()

        res = doc.load_page(1).get_text()
        page1 = res.replace(" ", "").replace("\n", "").lower()

        # input(page0)

        self._check_scholarworks_first_page(page0=page0, coverpages=coverpages)
        self._check_researchgate_first_page(page0=page0, coverpages=coverpages)
        self._check_jstor_first_page(page0=page0, coverpages=coverpages)
        self._check_emerald_first_page(page0=page0, coverpages=coverpages)
        self._check_informs_first_page(page0=page0, page1=page1, coverpages=coverpages)
        self._check_ais_first_page(page0=page0, coverpages=coverpages)
        self._check_tandf_first_page(page0=page0, page1=page1, coverpages=coverpages)

        return list(set(coverpages))

    def prep_pdf(
        self,
        record: colrev.record.record_pdf.PDFRecord,
        pad: int,  # pylint: disable=unused-argument
    ) -> colrev.record.record_pdf.PDFRecord:
        """Prepare the PDF by removing coverpages (if any)"""

        if not record.data[Fields.FILE].endswith(".pdf"):
            return record

        cp_path = Filepaths.LOCAL_ENVIRONMENT_DIR / Path(".coverpages")
        cp_path.mkdir(exist_ok=True)

        coverpages = self._get_coverpages(record)
        if not coverpages:
            return record
        if coverpages:
            original = self.review_manager.path / Path(record.data[Fields.FILE])
            file_copy = self.review_manager.path / Path(
                record.data[Fields.FILE].replace(".pdf", "_with_cp.pdf")
            )
            shutil.copy(original, file_copy)
            record.extract_pages(
                pages=coverpages,
                save_to_path=cp_path,
            )
            self.review_manager.report_logger.info(
                f"removed cover page for ({record.data[Fields.ID]})"
            )
        return record
