#! /usr/bin/env python
"""Scientometric study"""
from pydantic import Field

import colrev.ops.search
import colrev.package_manager.interfaces
import colrev.package_manager.package_manager
import colrev.package_manager.package_settings
import colrev.record.record

# pylint: disable=unused-argument
# pylint: disable=duplicate-code
# pylint: disable=too-few-public-methods


# @zope.interface.implementer(colrev.package_manager.interfaces.ReviewTypeInterface)
class ScientometricReview(colrev.package_manager.interfaces.ReviewTypeInterface):
    """Scientometric study"""

    settings_class = colrev.package_manager.package_settings.DefaultSettings
    ci_supported: bool = Field(default=True)

    def __init__(
        self, *, operation: colrev.process.operation.Operation, settings: dict
    ) -> None:
        self.settings = self.settings_class(**settings)

    def __str__(self) -> str:
        return "scientometric study"

    def initialize(
        self, settings: colrev.settings.Settings
    ) -> colrev.settings.Settings:
        """Initialize a scientometric study"""

        settings.data.data_package_endpoints = [
            {
                "endpoint": "colrev.paper_md",
                "version": "1.0",
                "word_template": "APA-7.docx",
            }
        ]
        settings.pdf_get.pdf_required_for_screen_and_synthesis = False
        return settings
