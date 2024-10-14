#! /usr/bin/env python
"""Qualitative systematic review"""
import zope.interface
from pydantic import Field

import colrev.ops.search
import colrev.package_manager.interfaces
import colrev.package_manager.package_manager
import colrev.package_manager.package_settings
import colrev.record.record
from colrev.packages.open_citations_forward_search.src.open_citations_forward_search import (
    OpenCitationsSearchSource,
)
from colrev.packages.pdf_backward_search.src.pdf_backward_search import (
    BackwardSearchSource,
)

# pylint: disable=unused-argument
# pylint: disable=duplicate-code
# pylint: disable=too-few-public-methods


@zope.interface.implementer(colrev.package_manager.interfaces.ReviewTypeInterface)
class QualitativeSystematicReview:
    """Qualitative systematic review"""

    settings_class = colrev.package_manager.package_settings.DefaultSettings

    ci_supported: bool = Field(default=True)

    def __init__(
        self, *, operation: colrev.process.operation.Operation, settings: dict
    ) -> None:
        self.settings = self.settings_class(**settings)

    def __str__(self) -> str:
        return "qualitative systematic review"

    def initialize(
        self, settings: colrev.settings.Settings
    ) -> colrev.settings.Settings:
        """Initialize a qualitative systematic review"""

        settings.sources.append(OpenCitationsSearchSource.get_default_source())
        settings.sources.append(BackwardSearchSource.get_default_source())

        settings.data.data_package_endpoints = [
            {"endpoint": "colrev_prisma", "version": "1.0"},
            {
                "endpoint": "colrev_structured",
                "version": "1.0",
                "fields": [],
            },
            {
                "endpoint": "colrev_paper_md",
                "version": "1.0",
                "word_template": "APA-7.docx",
            },
        ]
        return settings
