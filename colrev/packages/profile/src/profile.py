#! /usr/bin/env python
"""Creation of a profile of studies as part of the data operations"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from pydantic import BaseModel
from pydantic import Field

import colrev.env.docker_manager
import colrev.env.utils
import colrev.package_manager.interfaces
import colrev.package_manager.package_manager
import colrev.package_manager.package_settings
from colrev.constants import Fields
from colrev.constants import FieldValues
from colrev.constants import RecordState


class Profile(colrev.package_manager.interfaces.DataInterface):
    """Create a profile"""

    ci_supported: bool = Field(default=False)

    class ProfileSettings(
        colrev.package_manager.package_settings.DefaultSettings, BaseModel
    ):
        """Profile settings"""

        endpoint: str
        version: str

    settings_class = ProfileSettings

    def __init__(
        self,
        *,
        data_operation: colrev.ops.data.Data,  # pylint: disable=unused-argument
        settings: dict,
    ) -> None:
        self.review_manager = data_operation.review_manager
        self.data_operation = data_operation

        # Set default values (if necessary)
        if "version" not in settings:
            settings["version"] = "0.1"

        self.settings = self.settings_class(**settings)

        # output_dir = self.review_manager.get_path(Filepaths.OUTPUT_DIR)

    # pylint: disable=unused-argument
    @classmethod
    def add_endpoint(cls, operation: colrev.ops.data.Data, params: str) -> None:
        """Add as an endpoint"""

        add_package = {
            "endpoint": "colrev.profile",
            "version": "0.1",
        }
        operation.review_manager.settings.data.data_package_endpoints.append(
            add_package
        )

    def _update_profile(self, silent_mode: bool) -> None:
        """Create a profile of the sample"""

        self.review_manager.logger.info("Create sample profile")

        def prep_records(*, records: dict) -> pd.DataFrame:
            for record in records.values():
                record["outlet"] = record.get(
                    Fields.JOURNAL, record.get(Fields.BOOKTITLE, "NA")
                )

            records_df = pd.DataFrame.from_records(list(records.values()))

            required_cols = [
                Fields.ID,
                Fields.ENTRYTYPE,
                Fields.AUTHOR,
                Fields.TITLE,
                Fields.JOURNAL,
                Fields.BOOKTITLE,
                "outlet",
                Fields.YEAR,
                Fields.VOLUME,
                Fields.NUMBER,
                Fields.PAGES,
                Fields.DOI,
            ]
            available_cols = records_df.columns.intersection(list(set(required_cols)))
            cols = [x for x in required_cols if x in available_cols]
            records_df = records_df[cols]
            return records_df

        def prep_observations(
            *, prepared_records_df: pd.DataFrame, records: dict
        ) -> pd.DataFrame:
            included_papers = [
                ID
                for ID, record in records.items()
                if record[Fields.STATUS]
                in [
                    RecordState.rev_synthesized,
                    RecordState.rev_included,
                ]
                and record.get(Fields.YEAR, FieldValues.UNKNOWN).isdigit()
            ]
            observations = prepared_records_df[
                prepared_records_df[Fields.ID].isin(included_papers)
            ].copy()
            observations.year = observations.year.astype(int)
            missing_outlet = observations[observations["outlet"].isnull()][
                Fields.ID
            ].tolist()
            if len(missing_outlet) > 0:
                self.review_manager.logger.info(f"No outlet: {missing_outlet}")
            return observations

        # if not status.get_completeness_condition():
        #     self.review_manager.logger.warning(
        #  f"{Colors.RED}Sample not completely processed!{Colors.END}")

        records = self.review_manager.dataset.load_records_dict()

        output_dir = self.review_manager.path / Path("output")
        output_dir.mkdir(exist_ok=True)

        prepared_records_df = prep_records(records=records)  # .values()
        observations = prep_observations(
            prepared_records_df=prepared_records_df, records=records
        )

        if observations.empty:
            self.review_manager.logger.info("No sample/observations available")
            return

        self.review_manager.logger.info("Generate output/sample.csv")
        observations.to_csv(output_dir / Path("sample.csv"), index=False)

        tabulated = pd.pivot_table(
            observations[["outlet", Fields.YEAR]],
            index=["outlet"],
            columns=[Fields.YEAR],
            aggfunc=len,
            fill_value=0,
            margins=True,
        )
        # Fill missing years with 0 columns
        years = range(
            min(e for e in tabulated.columns if isinstance(e, int)),
            max(e for e in tabulated.columns if isinstance(e, int)) + 1,
        )
        for year in years:
            if year not in tabulated.columns:
                tabulated[year] = 0
        year_list = list(years)
        year_list.extend(["All"])  # type: ignore
        tabulated = tabulated[year_list]
        tabulated.sort_values(by=("All"), ascending=True, inplace=True)

        self.review_manager.logger.info("Generate profile output/journals_years.csv")
        tabulated.to_csv(output_dir / Path("journals_years.csv"))

        tabulated = pd.pivot_table(
            observations[[Fields.ENTRYTYPE, Fields.YEAR]],
            index=[Fields.ENTRYTYPE],
            columns=[Fields.YEAR],
            aggfunc=len,
            fill_value=0,
            margins=True,
        )
        self.review_manager.logger.info("Generate output/ENTRYTYPES.csv")
        tabulated.to_csv(output_dir / Path("ENTRYTYPES.csv"))

        self.review_manager.logger.info(f"Files are available in {output_dir.name}")

    def update_data(
        self,
        records: dict,  # pylint: disable=unused-argument
        synthesized_record_status_matrix: dict,  # pylint: disable=unused-argument
        silent_mode: bool,
    ) -> None:
        """Update the data/profile"""

        self._update_profile(silent_mode=silent_mode)

    def update_record_status_matrix(
        self,
        synthesized_record_status_matrix: dict,
        endpoint_identifier: str,
    ) -> None:
        """Update the record_status_matrix"""

        # Note : automatically set all to True / synthesized
        for syn_id in list(synthesized_record_status_matrix.keys()):
            synthesized_record_status_matrix[syn_id][endpoint_identifier] = True

    def get_advice(
        self,
    ) -> dict:
        """Get advice on the next steps (for display in the colrev status)"""

        data_endpoint = "Data operation [profile data endpoint]: "

        advice = {
            "msg": f"{data_endpoint}" + "\n    - The profile is created automatically ",
            "detailed_msg": "TODO",
        }
        return advice
