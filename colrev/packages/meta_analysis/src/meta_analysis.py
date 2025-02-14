#! /usr/bin/env python
"""Meta-analysis"""
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


# @zope.interface.implementer(colrev.package_manager.interfaces.ReviewTypeInterface)
class MetaAnalysis(colrev.package_manager.interfaces.ReviewTypeInterface):
    """Meta-analysis"""

    settings_class = colrev.package_manager.package_settings.DefaultSettings
    ci_supported: bool = Field(default=True)

    def __init__(
        self, *, operation: colrev.process.operation.Operation, settings: dict
    ) -> None:
        self.settings = self.settings_class(**settings)

    def __str__(self) -> str:
        return "meta-analysis"

    def initialize(
        self, settings: colrev.settings.Settings
    ) -> colrev.settings.Settings:
        """Initialize a meta-analysis"""

        settings.sources.append(OpenCitationsSearchSource.get_default_source())
        settings.sources.append(BackwardSearchSource.get_default_source())

        settings.data.data_package_endpoints = [
            {"endpoint": "colrev.prisma", "version": "1.0"},
            {
                "endpoint": "colrev.structured",
                "version": "1.0",
                "fields": [],
            },
            {
                "endpoint": "colrev.paper_md",
                "version": "1.0",
                "word_template": "APA-7.docx",
            },
        ]
        return settings
