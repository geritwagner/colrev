#! /usr/bin/env python
"""Structured data extraction as part of the data operations"""
from __future__ import annotations

import csv
import typing
from dataclasses import asdict
from pathlib import Path

import pandas as pd
from git.exc import GitCommandError
from pydantic import BaseModel
from pydantic import Field

import colrev.env.utils
import colrev.exceptions as colrev_exceptions
import colrev.package_manager.interfaces
import colrev.package_manager.package_manager
import colrev.package_manager.package_settings
import colrev.record.record
from colrev.constants import Colors
from colrev.constants import Fields
from colrev.constants import RecordState


# pylint: disable=too-few-public-methods


# an option: https://pypi.org/project/csv-schema/
class DataField(BaseModel):
    """Field definition"""

    name: str
    explanation: str
    data_type: str


class StructuredDataSettings(BaseModel):
    """Settings for StructuredData"""

    endpoint: str
    version: str
    fields: typing.List[DataField]
    data_path_relative: Path = Path("data.csv")

    _details = {
        "fields": {"tooltip": "Fields for the structured data extraction"},
    }


class StructuredData(colrev.package_manager.interfaces.DataInterface):
    """Summarize the literature in a structured data extraction (a table)"""

    settings: StructuredDataSettings
    settings_class = StructuredDataSettings

    _FULL_DATA_FIELD_EXPLANATION = """Explanation: Data fields are used in the coding tables.
    Example 1:
    - name           : summary
    - explanation    : Brief summary of the principal findings
    - data_type      : str

    Example 2:
    - name           : sample_size
    - explanation    : Sample size of the study
    - data_type      : int
    """
    ci_supported: bool = Field(default=False)

    def __init__(
        self,
        *,
        data_operation: colrev.ops.data.Data,
        settings: dict,
    ) -> None:
        self.review_manager = data_operation.review_manager

        if "version" not in settings:
            settings["version"] = "0.1"

        if "fields" not in settings:
            settings["fields"] = []
        if "data_path_relative" not in settings:
            settings["data_path_relative"] = Path("data/data/data.csv")

        self.settings = self.settings_class(**settings)
        self.data_path = self.review_manager.path / self.settings.data_path_relative
        self.review_manager = self.review_manager

    # pylint: disable=unused-argument
    @classmethod
    def add_endpoint(cls, operation: colrev.ops.data.Data, params: str) -> None:
        """Add as an endpoint"""

        add_source = {
            "endpoint": "colrev.structured",
            "version": "0.1",
            "fields": [],
            "data_path_relative": "data/data/data.csv",
        }
        operation.review_manager.settings.data.data_package_endpoints.append(add_source)

    def validate_structured_data(self) -> None:
        """Validate the extracted data"""

        if not self.data_path.is_file():
            return

        data_df = pd.read_csv(self.data_path, dtype=str)

        # Check for duplicate IDs
        if not data_df[Fields.ID].is_unique:
            raise colrev_exceptions.DataException(
                msg=f"duplicates in {self.settings.data_path_relative}: "
                + ",".join(data_df[data_df.duplicated([Fields.ID])].ID.tolist())
            )

        # Check consistency: data -> inclusion_2
        data_ids = data_df[Fields.ID].tolist()
        records = self.review_manager.dataset.load_records_dict()
        for data_id in data_ids:
            if data_id not in records:
                raise colrev_exceptions.DataException(
                    msg=f"{data_id} in {self.settings.data_path_relative} not in records"
                )
            if records[data_id][Fields.STATUS] not in [
                RecordState.rev_included,
                RecordState.rev_synthesized,
            ]:
                raise colrev_exceptions.DataException(
                    msg=f"{data_id} in {self.settings.data_path_relative} "
                    + "not in [rev_included, rev_synthesized]"
                )

        # Note : missing IDs are added through update_data

    def _set_fields(self) -> None:
        self.review_manager.logger.info("Add fields for data extraction")
        try:
            _ = self.review_manager.dataset.get_repo()
        except GitCommandError:
            return

        print(self._FULL_DATA_FIELD_EXPLANATION)
        while "y" == input("Add a data field [y,n]?"):
            short_name = input("Provide a short name: ")
            explanation = input("Provide a short explanation: ")
            data_type = input("Provide the data type (str, int, double):")

            self.settings.fields.append(
                Field(
                    **{
                        "name": short_name,
                        "explanation": explanation,
                        "data_type": data_type,
                    }
                )
            )

            print()

        # Note : the following should be easier...
        for i, candidate in enumerate(
            self.review_manager.settings.data.data_package_endpoints
        ):
            if candidate.get("data_path_relative", "NA") == str(
                self.settings.data_path_relative
            ):
                self.review_manager.settings.data.data_package_endpoints[i] = asdict(
                    self.settings, dict_factory=colrev.env.utils.custom_asdict_factory
                )
        self.review_manager.save_settings()

    def update_data(
        self,
        records: dict,
        synthesized_record_status_matrix: dict,
        silent_mode: bool,
    ) -> None:
        """Update the data/structured data extraction"""

        def update_structured_data(
            *,
            review_manager: colrev.review_manager.ReviewManager,
            synthesized_record_status_matrix: dict,
        ) -> typing.Dict:
            if silent_mode:
                return synthesized_record_status_matrix
            if not self.data_path.is_file():
                self._set_fields()

                field_names = [f.name for f in self.settings.fields]
                data_df = pd.DataFrame([], columns=[Fields.ID] + field_names)
                data_df.sort_values(by=[Fields.ID], inplace=True)

                data_df.to_csv(self.data_path, index=False, quoting=csv.QUOTE_ALL)

            nr_records_added = 0

            if not silent_mode:
                self.review_manager.report_logger.info("Update structured data")
                self.review_manager.logger.info(
                    f"Update structured data ({self.settings.data_path_relative})"
                )

            data_df = pd.read_csv(self.data_path, dtype=str)

            for record_id in list(synthesized_record_status_matrix.keys()):
                # skip when already available
                if 0 < len(data_df[data_df[Fields.ID].str.startswith(record_id)]):
                    continue

                add_record = pd.DataFrame({Fields.ID: [record_id]})
                add_record = add_record.reindex(
                    columns=data_df.columns, fill_value="TODO"
                )
                data_df = pd.concat([data_df, add_record], axis=0, ignore_index=True)
                review_manager.logger.info(
                    f" {Colors.GREEN}{record_id}".ljust(45)
                    + f"add to structured_data{Colors.END}"
                )
                nr_records_added = nr_records_added + 1

            data_df.sort_values(by=[Fields.ID], inplace=True)

            data_df.to_csv(self.data_path, index=False, quoting=csv.QUOTE_ALL)

            if not (0 == nr_records_added and silent_mode):
                review_manager.logger.info(
                    f"Added to {self.settings.data_path_relative}".ljust(24)
                    + f"{nr_records_added}".rjust(15, " ")
                    + " records"
                )

                review_manager.logger.info(
                    f"Added to {self.settings.data_path_relative}".ljust(24)
                    + f"{nr_records_added}".rjust(15, " ")
                    + " records"
                )
            return records

        self.validate_structured_data()
        records = update_structured_data(
            review_manager=self.review_manager,
            synthesized_record_status_matrix=synthesized_record_status_matrix,
        )

        self.review_manager.dataset.add_changes(
            self.settings.data_path_relative, ignore_missing=True
        )

    def update_record_status_matrix(
        self,
        synthesized_record_status_matrix: dict,
        endpoint_identifier: str,
    ) -> None:
        """Update the record_status_matrix"""

        def get_data_extracted(
            data_path: Path, records_for_data_extraction: list
        ) -> list:
            data_extracted = []
            data_df = pd.read_csv(data_path)

            for record in records_for_data_extraction:
                drec = data_df.loc[data_df[Fields.ID] == record]
                if 1 == drec.shape[0]:
                    if "TODO" not in drec.iloc[0].tolist():
                        data_extracted.append(drec.loc[drec.index[0], Fields.ID])

            data_extracted = [
                x for x in data_extracted if x in records_for_data_extraction
            ]
            return data_extracted

        def get_structured_data_extracted(
            *, synthesized_record_status_matrix: typing.Dict, data_path: Path
        ) -> list:
            if not data_path.is_file():
                return []

            data_extracted = get_data_extracted(
                data_path, list(synthesized_record_status_matrix.keys())
            )
            data_extracted = [
                x
                for x in data_extracted
                if x in list(synthesized_record_status_matrix.keys())
            ]
            return data_extracted

        structured_data_extracted = get_structured_data_extracted(
            synthesized_record_status_matrix=synthesized_record_status_matrix,
            data_path=self.data_path,
        )

        for syn_id in structured_data_extracted:
            if syn_id in synthesized_record_status_matrix:
                synthesized_record_status_matrix[syn_id][endpoint_identifier] = True
            else:
                print(f"Error: {syn_id} not int " f"{synthesized_record_status_matrix}")

    def get_advice(
        self,
    ) -> dict:
        """Get advice on the next steps (for display in the colrev status)"""

        data_endpoint = "Data operation [structured data endpoint]: "

        if self.settings.data_path_relative.is_file():
            advice = {
                "msg": f"{data_endpoint}"
                + f"\n    - Complete the data extraction ({self.settings.data_path_relative})",
                "detailed_msg": "TODO",
            }
        else:
            advice = {}
        return advice
