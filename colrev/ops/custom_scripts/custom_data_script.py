#! /usr/bin/env python
"""Template for a custom data PackageEndpoint"""
from __future__ import annotations

import colrev.package_manager.interfaces
import colrev.package_manager.package_settings
import colrev.process.operation


class CustomData(colrev.package_manager.interfaces.DataInterface):
    """Class for custom data scripts"""

    settings_class = colrev.package_manager.package_settings.DefaultSettings

    def __init__(
        self,
        *,
        data_operation: colrev.ops.data.Data,  # pylint: disable=unused-argument
        settings: dict,
    ) -> None:
        self.settings = self.settings_class(**settings)
        self.data_operation = data_operation

    @classmethod
    def add_endpoint(cls, operation: colrev.ops.data.Data, params: str) -> None:
        """Add as an endpoint"""

    def update_data(
        self,
        records: dict,  # pylint: disable=unused-argument
        synthesized_record_status_matrix: dict,  # pylint: disable=unused-argument
        silent_mode: bool,
    ) -> None:
        """Update the data"""

    def update_record_status_matrix(
        self,
        synthesized_record_status_matrix: dict,
        endpoint_identifier: str,
    ) -> None:
        """Update the record_status matrix"""

        # Note : automatically set all to True / synthesized
        for syn_id in list(synthesized_record_status_matrix.keys()):
            synthesized_record_status_matrix[syn_id][endpoint_identifier] = True
