#! /usr/bin/env python
"""Simple literature review"""
from pydantic import Field

import colrev.ops.search
import colrev.package_manager.interfaces
import colrev.package_manager.package_manager
import colrev.package_manager.package_settings
import colrev.record.record

# pylint: disable=unused-argument
# pylint: disable=duplicate-code
# pylint: disable=too-few-public-methods


# # @zope.interface.implementer(colrev.package_manager.interfaces.ReviewTypeInterface)
class LiteratureReview(colrev.package_manager.interfaces.ReviewTypeInterface):
    """Literature review (simple)"""

    ci_supported: bool = Field(default=True)
    settings: colrev.package_manager.package_settings.DefaultSettings
    settings_class = colrev.package_manager.package_settings.DefaultSettings

    def __init__(
        self, *, operation: colrev.process.operation.Operation, settings: dict
    ) -> None:
        self.settings = self.settings_class(**settings)

    def __str__(self) -> str:
        return "literature review"

    def initialize(
        self, settings: colrev.settings.Settings
    ) -> colrev.settings.Settings:
        """Initialize a literature review"""

        settings.data.data_package_endpoints = [
            {
                "endpoint": "colrev.paper_md",
                "version": "1.0",
                "word_template": "APA-7.docx",
            }
        ]
        return settings
