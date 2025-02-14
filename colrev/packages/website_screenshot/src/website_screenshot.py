#! /usr/bin/env python
"""Creation of screenshots (PDFs) for online ENTRYTYPES"""
from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

import docker
import requests
from docker.errors import DockerException
from pydantic import Field

import colrev.env.docker_manager
import colrev.exceptions as colrev_exceptions
import colrev.package_manager.interfaces
import colrev.package_manager.package_manager
import colrev.package_manager.package_settings
import colrev.record.record
from colrev.constants import Fields
from colrev.constants import RecordState

# pylint: disable=duplicate-code
# pylint: disable=too-few-public-methods


class WebsiteScreenshot(colrev.package_manager.interfaces.PDFGetInterface):
    """Get PDFs from website screenshot (for "online" ENTRYTYPES)"""

    settings_class = colrev.package_manager.package_settings.DefaultSettings
    ci_supported: bool = Field(default=False)
    CHROME_BROWSERLESS_IMAGE = "browserless/chrome:latest"

    def __init__(
        self,
        *,
        pdf_get_operation: colrev.ops.pdf_get.PDFGet,
        settings: dict,
    ) -> None:
        self.settings = self.settings_class(**settings)
        self.review_manager = pdf_get_operation.review_manager
        self.pdf_get_operation = pdf_get_operation
        colrev.env.docker_manager.DockerManager.build_docker_image(
            imagename=self.CHROME_BROWSERLESS_IMAGE
        )
        pdf_get_operation.docker_images_to_stop.append(self.CHROME_BROWSERLESS_IMAGE)

    def _start_screenshot_service(self) -> None:
        """Start the screenshot service"""

        # pylint: disable=duplicate-code

        if self.screenshot_service_available():
            return

        self.review_manager.environment_manager.register_ports(["3000"])

        try:
            client = docker.from_env()

            running_containers = [
                str(container.image) for container in client.containers.list()
            ]
            if self.CHROME_BROWSERLESS_IMAGE not in running_containers:
                client.containers.run(
                    self.CHROME_BROWSERLESS_IMAGE,
                    ports={"3000/tcp": ("127.0.0.1", 3000)},
                    auto_remove=True,
                    detach=True,
                )
        except DockerException as exc:
            raise colrev_exceptions.ServiceNotAvailableException(
                f"Docker service not available ({exc}). Please install/start Docker."
            ) from exc

        i = 0
        while i < 45:
            if self.screenshot_service_available():
                break
            time.sleep(1)
            i += 1
        return

    def screenshot_service_available(self) -> bool:
        """Check if the screenshot service is available"""

        content_type_header = {"Content-type": "text/plain"}

        browserless_chrome_available = False
        try:
            ret = requests.get(
                "http://127.0.0.1:3000/",
                headers=content_type_header,
                timeout=30,
            )
            browserless_chrome_available = ret.status_code == 200

        except requests.exceptions.ConnectionError:
            pass

        if browserless_chrome_available:
            return True
        return False

    def _add_screenshot(
        self, *, record: colrev.record.record.Record, pdf_filepath: Path
    ) -> colrev.record.record.Record:
        """Add a PDF screenshot to the record"""

        if Fields.URL not in record.data:
            return record

        urldate = datetime.today().strftime("%Y-%m-%d")

        json_val = {
            Fields.URL: record.data[Fields.URL],
            "options": {
                "displayHeaderFooter": True,
                "printBackground": False,
                "format": "A2",
            },
        }

        ret = requests.post("http://127.0.0.1:3000/pdf", json=json_val, timeout=30)

        if 200 == ret.status_code:
            with open(pdf_filepath, "wb") as file:
                file.write(ret.content)

            record.update_field(
                key=Fields.FILE,
                value=str(pdf_filepath),
                source="chrome (browserless) screenshot",
            )
            # pylint: disable=colrev-direct-status-assign
            record.data.update(colrev_status=RecordState.rev_prescreen_included)
            record.update_field(
                key="urldate", value=urldate, source="chrome (browserless) screenshot"
            )

        else:
            print(
                "URL screenshot retrieval error "
                f"{ret.status_code}/{record.data['url']}"
            )

        return record

    def get_pdf(
        self, record: colrev.record.record.Record
    ) -> colrev.record.record.Record:
        """Get a PDF of the website (screenshot)"""

        if record.data[Fields.ENTRYTYPE] != "online":
            return record

        self._start_screenshot_service()

        pdf_filepath = self.review_manager.paths.pdf / Path(f"{record.data['ID']}.pdf")
        record = self._add_screenshot(record=record, pdf_filepath=pdf_filepath)

        if Fields.FILE in record.data:
            self.pdf_get_operation.import_pdf(record)

        return record
