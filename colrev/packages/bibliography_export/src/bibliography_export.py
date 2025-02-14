#! /usr/bin/env python
"""Export of references in different bibliographical formats as a data operation"""
from __future__ import annotations

import copy
from enum import Enum
from pathlib import Path

import inquirer
from pydantic import BaseModel
from pydantic import Field

import colrev.env.docker_manager
import colrev.env.utils
import colrev.package_manager.interfaces
import colrev.package_manager.package_manager
import colrev.package_manager.package_settings
import colrev.record.record
from colrev.constants import Fields
from colrev.constants import FieldSet
from colrev.constants import RecordState
from colrev.writer.write_utils import write_file


class BibFormats(Enum):
    """Enum of available bibliography formats"""

    # pylint: disable=invalid-name
    zotero = "zotero"
    jabref = "jabref"
    citavi = "citavi"
    BiBTeX = "BiBTeX"
    RIS = "RIS"
    CSV = "CSV"
    EXCEL = "EXCEL"
    # endnote = "endnote"
    # mendeley = "mendeley"
    # rdf_bibliontology = "rdf_bibliontology"


class BibliographyExportSettings(
    colrev.package_manager.package_settings.DefaultSettings, BaseModel
):
    """Settings for BibliographyExport"""

    endpoint: str
    version: str
    bib_format: BibFormats


class BibliographyExport(colrev.package_manager.interfaces.DataInterface):
    """Export the sample references in Endpoint format"""

    settings: BibliographyExportSettings
    settings_class = BibliographyExportSettings

    ci_supported: bool = Field(default=True)

    # A challenge for the incremental mode is that data is run every time
    # the status runs (potentially creating very small increments)

    def __init__(
        self,
        *,
        data_operation: colrev.ops.data.Data,
        settings: dict,
    ) -> None:
        self.review_manager = data_operation.review_manager

        if "bib_format" not in settings:
            settings["bib_format"] = "endnote"
        settings["bib_format"] = BibFormats[settings["bib_format"]]
        if "version" not in settings:
            settings["version"] = "0.1"

        self.settings = self.settings_class(**settings)
        self.endpoint_path = self.review_manager.paths.output

    def _export(self, *, selected_records: dict) -> None:
        self.review_manager.logger.info(f"Export {self.settings.bib_format.name}")

        if self.settings.bib_format is BibFormats.zotero:
            export_filepath = self.endpoint_path / Path("zotero.bib")

        elif self.settings.bib_format is BibFormats.jabref:
            export_filepath = self.endpoint_path / Path("jabref.bib")

        elif self.settings.bib_format is BibFormats.citavi:
            export_filepath = self.endpoint_path / Path("citavi.bib")

        elif self.settings.bib_format is BibFormats.BiBTeX:
            export_filepath = self.endpoint_path / Path("references.bib")

        elif self.settings.bib_format is BibFormats.RIS:
            export_filepath = self.endpoint_path / Path("references.ris")

        elif self.settings.bib_format is BibFormats.CSV:
            export_filepath = self.endpoint_path / Path("references.csv")

        elif self.settings.bib_format is BibFormats.EXCEL:
            export_filepath = self.endpoint_path / Path("references.xlsx")
        else:
            raise NotImplementedError

        write_file(records_dict=selected_records, filename=export_filepath)

        self.review_manager.dataset.add_changes(export_filepath)
        self.review_manager.dataset.create_commit(
            msg=f"Create {self.settings.bib_format.name} bibliography",
        )

    @classmethod
    def add_endpoint(cls, operation: colrev.ops.data.Data, params: str) -> None:
        """Add bibliography as an endpoint"""

        add_package = {
            "endpoint": "colrev.bibliography_export",
            "version": "0.1",
            "bib_format": "endnote",
        }

        if params:
            assert params in [b.value for b in BibFormats]
            add_package["bib_format"] = params
        else:
            questions = [
                inquirer.List(
                    "bib_format",
                    message="Select a bibliography format",
                    choices=[b.value for b in BibFormats],
                ),
            ]
            choice = inquirer.prompt(questions)["bib_format"]
            add_package["bib_format"] = choice

        operation.review_manager.settings.data.data_package_endpoints.append(
            add_package
        )
        operation.review_manager.save_settings()
        operation.review_manager.dataset.create_commit(
            msg=f"Add colrev.bibliography_export: {add_package['bib_format']}"
        )

        instance = cls(data_operation=operation, settings=add_package)
        records = operation.review_manager.dataset.load_records_dict()
        instance.update_data(records, {}, silent_mode=True)

    # pylint: disable=unused-argument
    def update_data(
        self,
        records: dict,
        synthesized_record_status_matrix: dict,
        silent_mode: bool,
    ) -> None:
        """Update the data/bibliography"""

        self.endpoint_path.mkdir(exist_ok=True, parents=True)

        selected_records_original = {
            ID: r
            for ID, r in records.items()
            if r[Fields.STATUS]
            in [
                RecordState.rev_included,
                RecordState.rev_synthesized,
            ]
        }
        selected_records = copy.deepcopy(selected_records_original)
        for record in selected_records.values():
            for key_candidate in list(record.keys()):
                if key_candidate not in FieldSet.IDENTIFYING_FIELD_KEYS + [
                    Fields.ENTRYTYPE,
                    Fields.ID,
                    Fields.FILE,
                    "link",
                    Fields.URL,
                ]:
                    del record[key_candidate]
            # TBD: maybe resolve file paths (symlinks to absolute paths)?

        try:

            self._export(selected_records=selected_records)

        except NotImplementedError:
            self.review_manager.logger.info(
                f"Not yet implemented ({self.settings.bib_format})"
            )

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

        data_endpoint = "Data operation [bibliography export data endpoint]: "

        advice = {
            "msg": f"{data_endpoint}"
            + f"\n    - The references are updated automatically ({self.endpoint_path})",
            "detailed_msg": "TODO",
        }
        return advice
