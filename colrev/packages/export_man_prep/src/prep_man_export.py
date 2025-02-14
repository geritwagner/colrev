#! /usr/bin/env python
"""Export of bib/pdfs as a prep-man operation"""
from __future__ import annotations

import platform
import typing
from pathlib import Path

import pandas as pd
import pymupdf
from pydantic import BaseModel
from pydantic import Field

import colrev.env.utils
import colrev.package_manager.interfaces
import colrev.package_manager.package_manager
import colrev.package_manager.package_settings
import colrev.record.record
from colrev.constants import Colors
from colrev.constants import DefectCodes
from colrev.constants import Fields
from colrev.constants import FieldValues
from colrev.constants import RecordState
from colrev.writer.write_utils import write_file

# pylint: disable=duplicate-code
# pylint: disable=too-few-public-methods
# pylint: disable=too-many-instance-attributes


class ExportManPrepSettings(
    colrev.package_manager.package_settings.DefaultSettings, BaseModel
):
    """Settings for ExportManPrep"""

    endpoint: str
    pdf_handling_mode: str = "symlink"

    _details = {
        "pdf_handling_mode": {
            "tooltip": "Indicates how linked PDFs are handled (symlink/copy_first_page)"
        },
    }


class ExportManPrep(colrev.package_manager.interfaces.PrepManInterface):
    """Manual preparation based on exported and imported metadata (and PDFs if any)"""

    settings: ExportManPrepSettings
    ci_supported: bool = Field(default=False)

    RELATIVE_PREP_MAN_PATH = Path("records_prep_man.bib")
    RELATIVE_PREP_MAN_INFO_PATH = Path("records_prep_man_info.csv")
    RELATIVE_PREP_MAN_INFO_PATH_XLS = Path("records_prep_man_info.xlsx")

    _FIELDS_TO_KEEP = [
        Fields.ENTRYTYPE,
        Fields.AUTHOR,
        Fields.TITLE,
        Fields.YEAR,
        Fields.JOURNAL,
        Fields.BOOKTITLE,
        Fields.STATUS,
        Fields.VOLUME,
        Fields.NUMBER,
        Fields.PAGES,
        Fields.DOI,
        Fields.FILE,
    ]

    settings_class = ExportManPrepSettings

    def __init__(
        self,
        *,
        prep_man_operation: colrev.ops.prep_man.PrepMan,
        settings: dict,
    ) -> None:
        if "pdf_handling_mode" not in settings:
            settings["pdf_handling_mode"] = "symlink"
        assert settings["pdf_handling_mode"] in ["symlink", "copy_first_page"]

        self.settings = self.settings_class(**settings)

        self.review_manager = prep_man_operation.review_manager
        self.quality_model = self.review_manager.get_qm()
        self.prep_dir = self.review_manager.paths.prep
        self.prep_dir.mkdir(exist_ok=True, parents=True)
        self.prep_man_bib_path = self.prep_dir / self.RELATIVE_PREP_MAN_PATH
        self.prep_man_csv_path = self.prep_dir / self.RELATIVE_PREP_MAN_INFO_PATH
        self.prep_man_xlsx_path = self.prep_dir / self.RELATIVE_PREP_MAN_INFO_PATH_XLS

    def _copy_files_for_man_prep(self, *, records: dict) -> None:
        prep_man_path_pdfs = self.prep_dir / Path("pdfs")
        if prep_man_path_pdfs.is_dir():
            input(f"Remove {prep_man_path_pdfs} and press Enter.")
        prep_man_path_pdfs.mkdir(exist_ok=True, parents=True)

        for record in records.values():
            if Fields.FILE in record:
                target_path = self.prep_dir / Path(record[Fields.FILE])
                target_path.parents[0].mkdir(exist_ok=True, parents=True)

                if self.settings.pdf_handling_mode == "symlink":
                    try:
                        target_path.symlink_to(Path(record[Fields.FILE]).resolve())
                    except FileExistsError:
                        pass

                if self.settings.pdf_handling_mode == "copy_first_page":
                    doc1 = pymupdf.Document(str(record[Fields.FILE]))
                    if doc1.page_count > 0:
                        doc2 = pymupdf.Document()
                        doc2.insert_pdf(doc1, to_page=0)
                        doc2.save(str(target_path))

    def _export_prep_man(
        self,
        *,
        records: typing.Dict[str, typing.Dict],
    ) -> None:
        man_prep_recs = {
            k: v
            for k, v in records.items()
            if RecordState.md_needs_manual_preparation == v[Fields.STATUS]
        }

        # Filter out fields that are not needed for manual preparation
        filtered_man_prep_recs = {}
        for citation, fields in man_prep_recs.copy().items():
            for key in fields.copy():
                if key not in self._FIELDS_TO_KEEP:
                    del fields[key]
            filtered_man_prep_recs.update({citation: fields})

        write_file(records_dict=filtered_man_prep_recs, filename=self.prep_man_bib_path)

        if any(Fields.FILE in r for r in man_prep_recs.values()):
            self._copy_files_for_man_prep(records=man_prep_recs)

    def _create_info_dataframe(
        self,
        *,
        records: typing.Dict[str, typing.Dict],
    ) -> None:
        man_prep_recs = [
            v
            for _, v in records.items()
            if RecordState.md_needs_manual_preparation == v[Fields.STATUS]
        ]

        man_prep_info = []
        for record in man_prep_recs:
            for field, value in record[Fields.MD_PROV].items():
                if value["note"] and value["note"] != f"IGNORE:{DefectCodes.MISSING}":
                    man_prep_info.append(
                        {
                            Fields.ID: record[Fields.ID],
                            "field": field,
                            "note": value["note"],
                        }
                    )

        man_prep_info_df = pd.DataFrame(man_prep_info)
        if platform.system() == "Windows":
            # until https://github.com/pylint-dev/pylint/issues/3060 is resolved
            # pylint: disable=abstract-class-instantiated
            with pd.ExcelWriter(self.prep_man_xlsx_path) as writer:
                man_prep_info_df.to_excel(writer, index=False)
        else:
            man_prep_info_df.to_csv(self.prep_man_csv_path, index=False)

    def _drop_unnecessary_provenance_fiels(
        self, *, record: colrev.record.record.Record
    ) -> None:
        colrev_data_provenance_keys_to_drop = []
        for key, items in record.data.get(Fields.D_PROV, {}).items():
            if (
                key not in record.data
                and f"IGNORE:{DefectCodes.MISSING}" not in items["note"]
            ):
                colrev_data_provenance_keys_to_drop.append(key)
        for colrev_data_provenance_key_to_drop in colrev_data_provenance_keys_to_drop:
            del record.data[Fields.D_PROV][colrev_data_provenance_key_to_drop]

        md_prov_keys_to_drop = []
        for key, items in record.data.get(Fields.MD_PROV, {}).items():
            if (
                key not in record.data
                and f"IGNORE:{DefectCodes.MISSING}" not in items["note"]
            ):
                md_prov_keys_to_drop.append(key)
        for md_prov_key_to_drop in md_prov_keys_to_drop:
            del record.data[Fields.MD_PROV][md_prov_key_to_drop]

    def _update_original_record_based_on_man_prepped(
        self,
        *,
        original_record: colrev.record.record.Record,
        man_prepped_record_dict: dict,
    ) -> None:
        dropped_keys = [
            k
            for k in original_record.data
            if (k not in man_prepped_record_dict) and k in self._FIELDS_TO_KEEP
        ]

        if (
            original_record.data[Fields.ENTRYTYPE]
            != man_prepped_record_dict[Fields.ENTRYTYPE]
        ):
            original_record.change_entrytype(
                new_entrytype=man_prepped_record_dict[Fields.ENTRYTYPE],
                qm=self.quality_model,
            )

        if (
            man_prepped_record_dict[Fields.ENTRYTYPE]
            != original_record.data[Fields.ENTRYTYPE]
        ):
            original_record.data[Fields.ENTRYTYPE] = man_prepped_record_dict[
                Fields.ENTRYTYPE
            ]
            original_record.run_quality_model(self.quality_model)

        for key, value in man_prepped_record_dict.items():
            if key in [Fields.STATUS]:
                continue
            if (
                value != original_record.data.get(key, "")
                and value != FieldValues.UNKNOWN
            ):
                original_record.update_field(
                    key=key, value=value, source="man_prep", append_edit=False
                )
                original_record.remove_field_provenance_note(key=key, note="missing")

        for dropped_key in dropped_keys:
            original_record.remove_field(
                key=dropped_key, not_missing_note=True, source="man_prep"
            )

    def _print_stats(self, *, original_record: colrev.record.record.Record) -> None:
        if original_record.data[Fields.STATUS] == RecordState.rev_prescreen_excluded:
            self.review_manager.logger.info(
                f" {Colors.RED}{original_record.data['ID']}".ljust(46)
                + "md_needs_manual_preparation →  rev_prescreen_excluded"
                + f"{Colors.END}"
            )
        elif original_record.data[Fields.STATUS] == RecordState.md_prepared:
            self.review_manager.logger.info(
                f" {Colors.GREEN}{original_record.data['ID']}".ljust(46)
                + "md_needs_manual_preparation →  md_prepared"
                + f"{Colors.END}"
            )
        else:
            man_prep_note = ", ".join(
                k + ":" + v["note"]
                for k, v in original_record.data[Fields.MD_PROV].items()
                if v["note"] != ""
            )
            self.review_manager.logger.info(
                f" {Colors.ORANGE}{original_record.data['ID']}".ljust(46)
                + f"{man_prep_note}"
                + f"{Colors.END}"
            )

    def _import_record(
        self,
        *,
        man_prepped_record_dict: dict,
        original_record: colrev.record.record.Record,
        imported_records: list,
    ) -> None:
        imported_records.append(original_record.data[Fields.ID])
        override = man_prepped_record_dict[Fields.STATUS] == RecordState.md_prepared

        self._update_original_record_based_on_man_prepped(
            original_record=original_record,
            man_prepped_record_dict=man_prepped_record_dict,
        )

        self._drop_unnecessary_provenance_fiels(record=original_record)
        if man_prepped_record_dict[Fields.STATUS] == RecordState.rev_prescreen_excluded:
            original_record.set_status(
                target_state=RecordState.rev_prescreen_excluded,
                force=True,
            )

        else:
            original_record.run_quality_model(self.quality_model, set_prepared=True)

        if override:
            original_record.set_status(RecordState.md_prepared, force=True)

        self._print_stats(original_record=original_record)

    def _import_prep_man(self) -> None:
        self.review_manager.logger.info(
            "Load import changes from "
            f"{self.prep_man_bib_path.relative_to(self.review_manager.path)}"
        )

        man_prep_recs = colrev.loader.load_utils.load(
            filename=self.prep_man_bib_path,
            logger=self.review_manager.logger,
        )

        imported_records: typing.List[dict] = []
        records = self.review_manager.dataset.load_records_dict()
        for record_id, record_dict in records.items():
            if (
                record_dict[Fields.STATUS]
                == RecordState.rev_prescreen_excluded
                # or record_id not in man_prep_recs
            ):
                records[record_id][  # pylint: disable=colrev-direct-status-assign
                    Fields.STATUS
                ] = RecordState.rev_prescreen_excluded
                self.review_manager.logger.info(
                    f" {Colors.RED}{record_id}".ljust(46)
                    + "md_needs_manual_preparation →  rev_prescreen_excluded"
                    + f"{Colors.END}"
                )

        for record_id, man_prepped_record_dict in man_prep_recs.items():
            if record_id not in records:
                print(f"ID no longer in records: {record_id}")
                continue
            original_record = colrev.record.record.Record(
                records[man_prepped_record_dict[Fields.ID]]
            )
            self._import_record(
                man_prepped_record_dict=man_prepped_record_dict,
                original_record=original_record,
                imported_records=imported_records,
            )

        self.review_manager.dataset.save_records_dict(records)
        self.review_manager.dataset.create_commit(msg="Prep-man (ExportManPrep)")
        self.review_manager.dataset.set_ids(selected_ids=imported_records)
        self.review_manager.dataset.create_commit(msg="Set IDs")

    def _print_export_prep_man_instructions(self) -> None:
        print("Created two files:")
        if platform.system() == "Windows":
            print(
                f" - {self.prep_man_xlsx_path.relative_to(self.review_manager.path)}  (EXCEL file)"
            )
        else:
            print(
                f" - {self.prep_man_csv_path.relative_to(self.review_manager.path)}  (CSV file)"
            )
        print(
            f" - {self.prep_man_bib_path.relative_to(self.review_manager.path)}       (BIB file)"
        )
        print()
        print("To prepare records:")
        print("- check the defect codes in the CSV file")
        print(
            "- edit the BIB file and change the fields "
            "(e.g., add missing volume/number or remove all-caps)"
        )
        print(
            "- if a record should be exluded in the prescreen, simply remove it from the BIB file"
        )
        print()

        print(f"Once completed, run {Colors.ORANGE}colrev prep-man{Colors.END} again.")

    def prepare_manual(self, records: dict) -> dict:
        """Prepare records manually by extracting the subset of records to a separate BiBTex file"""

        if not self.prep_man_bib_path.is_file():
            self._create_info_dataframe(records=records)
            self._export_prep_man(records=records)
            self._print_export_prep_man_instructions()
        else:
            selected_path = self.prep_man_bib_path.relative_to(self.review_manager.path)
            if input(f"Import changes from {selected_path} [y,n]?") == "y":
                self._import_prep_man()

        return records
