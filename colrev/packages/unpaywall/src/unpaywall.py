#! /usr/bin/env python
"""Retrieval of PDFs from the unpaywall API"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pymupdf
import requests
from pydantic import Field

import colrev.package_manager.interfaces
import colrev.package_manager.package_manager
import colrev.package_manager.package_settings
import colrev.record.record
from colrev.constants import Fields
from colrev.packages.unpaywall.src import utils

# pylint: disable=duplicate-code
# pylint: disable=too-few-public-methods


class Unpaywall(colrev.package_manager.interfaces.PDFGetInterface):
    """Get PDFs from unpaywall.org"""

    settings_class = colrev.package_manager.package_settings.DefaultSettings
    ci_supported: bool = Field(default=False)

    SETTINGS = {
        "email": "packages.pdf_get.colrev.unpaywall.email",
    }

    def __init__(
        self,
        *,
        pdf_get_operation: colrev.ops.pdf_get.PDFGet,
        settings: dict,
    ) -> None:
        self.settings = self.settings_class(**settings)
        self.review_manager = pdf_get_operation.review_manager
        self.pdf_get_operation = pdf_get_operation

        self.email = utils.get_email()

    def _unpaywall(
        self,
        *,
        doi: str,
        retry: int = 0,
        pdfonly: bool = True,
    ) -> str:
        url = f"https://api.unpaywall.org/v2/{doi}"

        try:
            ret = requests.get(url, params={"email": self.email}, timeout=30)
            if ret.status_code == 500 and retry < 3:
                return self._unpaywall(doi=doi, retry=retry + 1)

            if ret.status_code in [404, 500]:
                return "NA"

            best_loc = None
            best_loc = ret.json()["best_oa_location"]

            assert ret.json()["is_oa"]
            assert best_loc is not None
            assert not (pdfonly and best_loc["url_for_pdf"] is None)

        except (
            json.decoder.JSONDecodeError,
            KeyError,
            requests.exceptions.RequestException,
            AssertionError,
        ):
            return "NA"

        return best_loc["url_for_pdf"]

    def _is_pdf(self, *, path_to_file: Path) -> bool:
        with pymupdf.open(path_to_file) as doc:
            doc.load_page(0).get_text()
        return True

    def get_pdf(
        self, record: colrev.record.record.Record
    ) -> colrev.record.record.Record:
        """Get PDFs from unpaywall"""

        if Fields.DOI not in record.data:
            return record

        pdf_filepath = self.pdf_get_operation.get_target_filepath(record)

        url = self._unpaywall(doi=record.data[Fields.DOI])
        if url == "NA":
            return record
        if "Invalid/unknown DOI" in url:
            return record

        try:
            res = requests.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_1) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/39.0.2171.95 Safari/537.36"
                },
                stream=True,
                timeout=30,
            )

            if 200 == res.status_code:
                pdf_filepath.parents[0].mkdir(exist_ok=True, parents=True)
                with open(pdf_filepath, "wb") as file:
                    file.write(res.content)
                if self._is_pdf(path_to_file=pdf_filepath):
                    self.review_manager.report_logger.debug(
                        "Retrieved pdf (unpaywall):" f" {pdf_filepath.name}"
                    )
                    source = (
                        f"https://api.unpaywall.org/v2/{record.data['doi']}"
                        + f"?email={self.email}"
                    )
                    record.update_field(
                        key=Fields.FILE, value=str(pdf_filepath), source=source
                    )
                    self.pdf_get_operation.import_pdf(record)

                else:
                    os.remove(pdf_filepath)
            else:
                if Fields.FULLTEXT not in record.data:
                    record.data[Fields.FULLTEXT] = url
                if self.review_manager.verbose_mode:
                    self.review_manager.logger.info(
                        "Unpaywall retrieval error " f"{res.status_code} - {url}"
                    )
        except (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
        ):
            pass

        return record
