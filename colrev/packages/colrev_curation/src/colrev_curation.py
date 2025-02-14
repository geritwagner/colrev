#! /usr/bin/env python
"""Colrev curated data as part of the data operations"""
from __future__ import annotations

import collections
import os
import typing
from pathlib import Path

import pandas as pd
from pydantic import BaseModel
from pydantic import Field

import colrev.env.utils
import colrev.exceptions as colrev_exceptions
import colrev.package_manager.interfaces
import colrev.package_manager.package_manager
import colrev.package_manager.package_settings
import colrev.record.record
from colrev.constants import Fields
from colrev.constants import RecordState


class ColrevCurationSettings(
    colrev.package_manager.package_settings.DefaultSettings, BaseModel
):
    """Colrev Curation settings"""

    endpoint: str
    version: str
    curation_url: str
    curated_masterdata: bool
    masterdata_restrictions: dict
    curated_fields: list


class ColrevCuration(colrev.package_manager.interfaces.DataInterface):
    """CoLRev Curation"""

    settings: ColrevCurationSettings
    ci_supported: bool = Field(default=True)

    settings_class = ColrevCurationSettings

    def __init__(
        self,
        *,
        data_operation: colrev.ops.data.Data,
        settings: dict,
    ) -> None:
        # Set default values (if necessary)
        if "version" not in settings:
            settings["version"] = "0.1"

        self.settings = ColrevCurationSettings(**settings)
        self.review_manager = data_operation.review_manager

        self.data_operation = data_operation

    # pylint: disable=unused-argument
    @classmethod
    def add_endpoint(cls, operation: colrev.ops.data.Data, params: str) -> None:
        """Add as an endpoint"""

        add_source = {
            "endpoint": "colrev.colrev_curation",
            "version": "0.1",
            "curation_url": "TODO",
            "curated_masterdata": True,
            "masterdata_restrictions": {
                1900: {
                    Fields.ENTRYTYPE: "article",
                    Fields.JOURNAL: "TODO",
                    Fields.VOLUME: True,
                    Fields.NUMBER: True,
                }
            },
            "curated_fields": [Fields.DOI, Fields.URL],
        }

        operation.review_manager.settings.data.data_package_endpoints.append(add_source)

    def _get_stats(
        self,
        *,
        records: dict,
        sources: list,
    ) -> dict:
        # pylint: disable=too-many-branches

        stats: dict = {}
        for record_dict in records.values():
            r_status = str(record_dict[Fields.STATUS])
            if r_status == "rev_prescreen_excluded":
                continue
            if record_dict[Fields.STATUS] in RecordState.get_post_x_states(
                state=RecordState.md_processed
            ):
                r_status = str(RecordState.md_processed)
            elif record_dict[Fields.STATUS] in RecordState.get_post_x_states(
                state=RecordState.pdf_prepared
            ):
                r_status = str(RecordState.pdf_prepared)
            else:
                r_status = str(RecordState.md_imported)

            if Fields.JOURNAL in record_dict:
                key = (
                    f"{record_dict.get('year', '-')}-"
                    f"{record_dict.get('volume', '-')}-"
                    f"{record_dict.get('number', '-')}"
                )
            elif Fields.BOOKTITLE in record_dict:
                key = record_dict.get(Fields.YEAR, "-")
            else:
                self.review_manager.logger.error(f"TOC not supported: {record_dict}")
                continue
            if not all(
                source in [o.split("/")[0] for o in record_dict[Fields.ORIGIN]]
                for source in sources
            ):
                if key in stats:
                    if "all_merged" in stats[key]:
                        stats[key]["all_merged"] = "NO"
                    else:
                        stats[key]["all_merged"] = "NO"
                else:
                    stats[key] = {"all_merged": "NO"}

            for origin in record_dict[Fields.ORIGIN]:
                source = origin.split("/")[0]
                if key in stats:
                    if source in stats[key]:
                        if r_status in stats[key][source]:
                            stats[key][source][r_status] += 1
                        else:
                            stats[key][source][r_status] = 1
                    else:
                        stats[key][source] = {r_status: 1}
                else:
                    stats[key] = {source: {r_status: 1}}
        return stats

    def _get_stats_markdown_table(self, *, stats: dict, sources: list) -> str:
        cell_width = 16
        sources += ["all_merged"]
        output = "|TOC".ljust(cell_width - 1, " ") + "|"
        sub_header_lines = "|".ljust(cell_width - 1, "-") + "|"
        for source in sources:
            output += f"{source}".ljust(cell_width, " ") + "|"
            sub_header_lines += "".ljust(cell_width, "-") + "|"

        output += "\n" + sub_header_lines
        ordered_stats = collections.OrderedDict(sorted(stats.items(), reverse=True))

        output += self._get_stats_markdown_table_cell(
            ordered_stats=ordered_stats, sources=sources, cell_width=cell_width
        )

        output += "\n\nLegend: *md_imported*, md_processed, **pdf_prepared**"
        return output

    def _get_stats_markdown_table_cell(
        self, *, ordered_stats: collections.OrderedDict, sources: list, cell_width: int
    ) -> str:
        output = ""
        for key, row in ordered_stats.items():
            output += f"\n|{key}".ljust(cell_width, " ") + "|"
            for source in sources:
                if source != "all_merged":
                    if source in row:
                        cell_text = ""
                        if "md_imported" in row[source]:
                            cell_text += f"*{row[source]['md_imported']}*,"
                        else:
                            cell_text += "-,"
                        if "md_processed" in row[source]:
                            cell_text += f"{row[source]['md_processed']}"
                        else:
                            cell_text += "-"
                        if "pdf_prepared" in row[source]:
                            cell_text += f",**{row[source]['pdf_prepared']}**"
                        else:
                            cell_text += ",-"

                        output += cell_text.rjust(cell_width, " ") + "|"
                    else:
                        output += "-".rjust(cell_width, " ") + "|"
                else:
                    output += row.get("all_merged", "").rjust(cell_width, " ") + "|"
        return output

    def _update_table_in_readme(
        self,
        *,
        markdown_output: str,
    ) -> None:
        table_summary_tag = "<!-- TABLE_SUMMARY -->"
        readme_path = self.review_manager.paths.readme
        with open(readme_path, "r+b") as file:
            appended = False
            seekpos = file.tell()
            line = file.readline()
            while line:
                if table_summary_tag.encode("utf-8") in line:
                    line = file.readline()
                    while (
                        b"Legend: *md_imported*, md_processed" not in line and line
                    ):  # replace: drop the current record
                        line = file.readline()

                    remaining = file.read()
                    file.seek(seekpos)
                    file.write(table_summary_tag.encode("utf-8"))
                    file.write(b"\n\n")
                    file.write(markdown_output.encode("utf-8"))
                    file.write(b"\n")
                    seekpos = file.tell()
                    file.flush()
                    os.fsync(file)
                    file.write(remaining)
                    file.truncate()  # if the replacement is shorter...
                    file.seek(seekpos)
                    appended = True

                seekpos = file.tell()
                line = file.readline()
            if not appended:
                file.write(b"\n")
                file.write(table_summary_tag.encode("utf-8"))
                file.write(b"\n\n")
                file.write(markdown_output.encode("utf-8"))
                file.write(b"\n")

    def _update_stats_in_readme(
        self,
        *,
        records: dict,
        silent_mode: bool,
    ) -> None:
        if not silent_mode:
            self.review_manager.logger.info("Calculate statistics for readme")

        # alternatively: get sources from search_sources.filename (name/stem?)
        sources = []
        for record_dict in records.values():
            for origin in record_dict[Fields.ORIGIN]:
                source = origin.split("/")[0]
                if source not in sources:
                    sources.append(source)

        stats = self._get_stats(records=records, sources=sources)
        markdown_output = self._get_stats_markdown_table(stats=stats, sources=sources)
        self._update_table_in_readme(markdown_output=markdown_output)
        self.review_manager.dataset.add_changes(self.review_manager.paths.README_FILE)

    def _source_comparison(self, *, silent_mode: bool) -> None:
        """Exports a table to support analyses of records that are not
        in all sources (for curated repositories)"""
        dedupe_dir = self.review_manager.paths.dedupe
        dedupe_dir.mkdir(exist_ok=True, parents=True)
        source_comparison_xlsx = dedupe_dir / Path("source_comparison.xlsx")

        source_filenames = [
            str(x.filename) for x in self.review_manager.settings.sources
        ]
        if not silent_mode:
            print("sources: " + ",".join([str(x) for x in source_filenames]))

        records = self.review_manager.dataset.load_records_dict()
        records = {
            k: v
            for k, v in records.items()
            if not all(x in ";".join(v[Fields.ORIGIN]) for x in str(source_filenames))
        }
        if len(records) == 0:
            if not silent_mode:
                print("No records unmatched")
            return

        for record in records.values():
            origins = record[Fields.ORIGIN]
            for source_filename in source_filenames:
                if not any(source_filename in origin for origin in origins):
                    record[source_filename] = ""
                else:
                    record[source_filename] = [
                        origin for origin in origins if source_filename in origin
                    ][0]
            record["merge_with"] = ""

        records_df = pd.DataFrame.from_records(list(records.values()))
        records_df.to_excel(source_comparison_xlsx, index=False)
        if not silent_mode:
            print(f"Exported {source_comparison_xlsx}")

    def update_data(
        self,
        records: dict,
        synthesized_record_status_matrix: dict,  # pylint: disable=unused-argument
        silent_mode: bool,
    ) -> None:
        """Update the CoLRev curation"""

        if self.settings.curated_masterdata:
            self._update_stats_in_readme(
                records=records,
                silent_mode=silent_mode,
            )
            self._source_comparison(silent_mode=silent_mode)

    def update_record_status_matrix(
        self,
        synthesized_record_status_matrix: dict,
        endpoint_identifier: str,
    ) -> None:
        """Update the record_status_matrix"""

        for item in synthesized_record_status_matrix:
            synthesized_record_status_matrix[item][endpoint_identifier] = True

    def get_advice(
        self,
    ) -> dict:
        """Get advice on the next steps (for display in the colrev status)"""

        records = self.review_manager.dataset.load_records_dict()
        advice = {
            "msg": "TODO (add curation-specific advice...)",
            "detailed_msg": "TODO",
        }

        records_missing_languages = [
            r[Fields.ID] for r in records.values() if Fields.LANGUAGE not in r
        ]
        if records_missing_languages:
            advice = {
                "msg": "Curation: Add language field to all records",
                "detailed_msg": "records missing language field: "
                + f"({','.join(records_missing_languages)})",
            }

        identical_colrev_ids: typing.Dict[str, list] = {}
        non_identifiable_records = []
        for record_dict in records.values():
            try:
                if record_dict[Fields.STATUS] not in RecordState.get_post_x_states(
                    state=RecordState.md_prepared
                ):
                    continue
                if record_dict[Fields.STATUS] == RecordState.rev_prescreen_excluded:
                    continue
                cid = colrev.record.record.Record(record_dict).get_colrev_id(
                    assume_complete=True
                )
                if cid in identical_colrev_ids:
                    identical_colrev_ids[cid] = identical_colrev_ids[cid] + [
                        record_dict[Fields.ID]
                    ]
                else:
                    identical_colrev_ids[cid] = [record_dict[Fields.ID]]
            except colrev_exceptions.NotEnoughDataToIdentifyException:
                non_identifiable_records.append(record_dict[Fields.ID])

        identical_colrev_ids = {
            k: v for k, v in identical_colrev_ids.items() if len(v) > 1
        }
        if identical_colrev_ids:
            advice = {
                "msg": "Curation: resolve records with identical colrev_ids:\n      - "
                + "\n      - ".join(",".join(x) for x in identical_colrev_ids.values()),
                "detailed_msg": "records missing language field: ",
            }

        if not self.settings.masterdata_restrictions:
            advice = {
                "msg": "Curation: masterdata_restrictions not set. See "
                + "https://github.com/CoLRev-Environment/colrev/blob/main/"
                + "colrev/packages/data/colrev_curation.md for details.",
                "detailed_msg": "records missing language field: ",
            }

        return advice
