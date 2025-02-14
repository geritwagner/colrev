#! /usr/bin/env python
"""Dedupe functionality dedicated to curated metadata repositories"""
from __future__ import annotations

import numpy as np
import pandas as pd
from pydantic import BaseModel
from pydantic import Field
from rapidfuzz import fuzz
from tqdm import tqdm

import colrev.package_manager.interfaces
import colrev.package_manager.package_manager
import colrev.package_manager.package_settings
import colrev.record.record
from colrev.constants import Colors
from colrev.constants import Fields
from colrev.constants import RecordState


# pylint: disable=too-many-arguments
# pylint: disable=too-few-public-methods
# pylint: disable=duplicate-code


class CurationDedupeSettings(BaseModel):
    """Settings for CurationDedupe"""

    endpoint: str
    selected_source: str


class CurationDedupe(colrev.package_manager.interfaces.DedupeInterface):
    """Deduplication endpoint for curations with full journals/proceedings
    retrieved from different sources (identifying duplicates in groups of
    volumes/issues or years)"""

    settings_class = CurationDedupeSettings
    settings: CurationDedupeSettings
    ci_supported: bool = Field(default=True)

    def __init__(
        self,
        *,
        dedupe_operation: colrev.ops.dedupe.Dedupe,
        settings: dict,
    ):
        self.settings = self.settings_class(**settings)
        self.dedupe_operation = dedupe_operation
        self.review_manager = dedupe_operation.review_manager

        self.pdf_qm = self.review_manager.get_pdf_qm()

    def _has_overlapping_colrev_id(
        self,
        record_a: colrev.record.record.Record,
        record_b: colrev.record.record.Record,
    ) -> bool:
        """Check if a record has an overlapping colrev_id with the other record"""
        own_colrev_ids = record_a.get_colrev_id()
        other_colrev_ids = record_b.get_colrev_id()
        if len(own_colrev_ids) > 0 and len(other_colrev_ids) > 0:
            if any(cid in own_colrev_ids for cid in other_colrev_ids):
                return True
        return False

    def _get_similarity(self, *, df_a: pd.Series, df_b: pd.Series) -> float:
        author_similarity = fuzz.ratio(df_a[Fields.AUTHOR], df_b[Fields.AUTHOR]) / 100

        title_similarity = (
            fuzz.ratio(df_a[Fields.TITLE].lower(), df_b[Fields.TITLE].lower()) / 100
        )

        # Note : the toc-based processing means that we are robust against
        # outlet, year, volume, number variations!
        weights = [0.4, 0.6]
        similarities = [
            author_similarity,
            title_similarity,
        ]

        weighted_average = sum(
            similarities[g] * weights[g] for g in range(len(similarities))
        )

        similarity_score = round(weighted_average, 4)

        return similarity_score

    def _calculate_similarities(
        self,
        *,
        similarity_array: np.ndarray,
        references: pd.DataFrame,
        min_similarity: float,
    ) -> tuple:
        # Fill out the similarity matrix first
        for base_entry_i in range(1, references.shape[0]):
            for comparison_entry_i in range(1, references.shape[0]):
                if base_entry_i > comparison_entry_i:
                    if -1 != similarity_array[base_entry_i, comparison_entry_i]:
                        similarity_array[base_entry_i, comparison_entry_i] = (
                            self._get_similarity(
                                df_a=references.iloc[base_entry_i],
                                df_b=references.iloc[comparison_entry_i],
                            )
                        )

        tuples_to_process = []
        maximum_similarity = 1
        while True:
            maximum_similarity = np.amax(similarity_array)
            if maximum_similarity < min_similarity:
                break
            result = np.where(similarity_array == np.amax(similarity_array))
            list_of_coordinates = list(zip(result[0], result[1]))
            for cord in list_of_coordinates:
                similarity_array[cord] = 0  # ie., has been processed
                tuples_to_process.append(
                    [
                        references.iloc[cord[0]][Fields.ID],
                        references.iloc[cord[1]][Fields.ID],
                        maximum_similarity,
                        "not_processed",
                    ]
                )

        return similarity_array, tuples_to_process

    def _get_toc_items(self, *, records_list: list) -> list:
        toc_items = []
        for record in records_list:
            toc_item = {}
            if record[Fields.ENTRYTYPE] == "article":
                if Fields.JOURNAL in record:
                    toc_item[Fields.JOURNAL] = record[Fields.JOURNAL]
                if Fields.VOLUME in record:
                    toc_item[Fields.VOLUME] = record[Fields.VOLUME]
                if Fields.NUMBER in record:
                    toc_item[Fields.NUMBER] = record[Fields.NUMBER]

            if record[Fields.ENTRYTYPE] == "inproceedings":
                if Fields.BOOKTITLE in record:
                    toc_item[Fields.BOOKTITLE] = record[Fields.BOOKTITLE]
                    toc_item[Fields.YEAR] = record[Fields.YEAR]
            if len(toc_item) > 0:
                toc_items.append(toc_item)

        temp = {tuple(sorted(sub.items())) for sub in toc_items}
        toc_items = list(map(dict, temp))  # type: ignore
        return toc_items

    def _warn_on_missing_sources(self, *, first_source: bool) -> None:
        # warn if not all SOURCE.filenames are included in a dedupe script
        if first_source:
            available_sources = [
                str(s.filename)
                for s in self.review_manager.settings.sources
                if "md_" not in str(s.filename)
            ]
            dedupe_sources = [
                s["selected_source"]
                for s in self.review_manager.settings.dedupe.dedupe_package_endpoints
                if "colrev.curation_full_outlet_dedupe" == s["endpoint"]
            ]
            sources_missing_in_dedupe = [
                x for x in available_sources if x not in dedupe_sources
            ]
            if len(sources_missing_in_dedupe) > 0:
                self.review_manager.logger.warning(
                    f"{Colors.ORANGE}Sources missing in "
                    "dedupe.scripts.colrev.curation_full_outlet_dedupe: "
                    f"{','.join(sources_missing_in_dedupe)}{Colors.END}"
                )
                if input("Add sources [y,n]?") == "y":
                    for source_missing_in_dedupe in sources_missing_in_dedupe:
                        dedupe_package_endpoints = (
                            self.review_manager.settings.dedupe.dedupe_package_endpoints
                        )
                        penultimate_position = len(dedupe_package_endpoints) - 1
                        dedupe_script_to_add = {
                            "endpoint": "colrev.curation_full_outlet_dedupe",
                            "selected_source": source_missing_in_dedupe,
                        }
                        dedupe_package_endpoints.insert(
                            penultimate_position, dedupe_script_to_add
                        )
                        self.review_manager.save_settings()
                        self.review_manager.logger.info(
                            f"{Colors.GREEN}Added {source_missing_in_dedupe} "
                            f"to dedupe.scripts{Colors.END}"
                        )

    def _add_first_source_if_deduplicated(self, *, records: dict) -> None:
        self.review_manager.logger.info(
            f"Starting with records from {self.settings.selected_source}"
            " (setting to md_processed as the initial records)"
        )

        source_records = [
            r
            for r in records.values()
            if r[Fields.STATUS] == RecordState.md_prepared
            and any(
                self.settings.selected_source.replace("data/search/", "") in co
                for co in r[Fields.ORIGIN]
            )
        ]

        toc_items = self._get_toc_items(records_list=source_records)

        for toc_item in toc_items:
            # Note : these would be potential errors (duplicates)
            # because they have the same selected_source
            processed_same_toc_same_source_records = [
                r
                for r in records.values()
                if all(r.get(k, "NA") == v for k, v in toc_item.items())
                and r[Fields.STATUS]
                not in [
                    RecordState.md_prepared,
                    RecordState.md_needs_manual_preparation,
                    RecordState.md_imported,
                    RecordState.rev_prescreen_excluded,
                ]
                and any(
                    self.settings.selected_source.replace("data/search/", "") in co
                    for co in r[Fields.ORIGIN]
                )
            ]
            if 0 == len(processed_same_toc_same_source_records):
                print("\n\n")
                print(toc_item)

                for source_record_dict in sorted(
                    source_records, key=lambda d: d[Fields.AUTHOR]
                ):
                    if all(
                        source_record_dict.get(k, "NA") == v
                        for k, v in toc_item.items()
                    ):
                        # Record(sr).print_citation_format()
                        print(
                            f"{source_record_dict.get('author', 'NO_AUTHOR')} : "
                            f"{source_record_dict.get('title', 'NO_TITLE')}"
                        )
                recs_unique = self.review_manager.force_mode
                if not recs_unique:
                    recs_unique = "y" == input(
                        "No existing records (md_processed*) found. "
                        "All records unique? Set to md_processed [y]? "
                    )
                if recs_unique:
                    for source_record_dict in source_records:
                        if all(
                            source_record_dict.get(k, "NA") == v
                            for k, v in toc_item.items()
                        ):
                            source_record = colrev.record.record.Record(
                                data=source_record_dict
                            )
                            source_record.set_status(
                                target_state=RecordState.md_processed
                            )
            else:
                print(toc_item)
                print("Pre-imported records found for this toc_item (skipping)")
                # print(processed_same_toc_same_source_records)

        for record in records.values():
            record.pop(Fields.CONTAINER_TITLE)
        self.review_manager.dataset.save_records_dict(records)

        if self.review_manager.dataset.has_record_changes():
            self.review_manager.logger.info(f"{Colors.GREEN}Commit changes{Colors.END}")
            self.review_manager.dataset.create_commit(
                msg=(
                    "Merge duplicate records (set unique records from "
                    f"{self.settings.selected_source} "
                    "to md_processed)"
                ),
            )
        else:
            self.review_manager.logger.info(
                f"{Colors.GREEN}No duplicates found{Colors.END}"
            )

    def _prep_records(self, *, records: dict) -> dict:
        required_fields = [
            Fields.TITLE,
            Fields.AUTHOR,
            Fields.YEAR,
            Fields.JOURNAL,
            Fields.VOLUME,
            Fields.NUMBER,
            Fields.PAGES,
            Fields.BOOKTITLE,
        ]
        for record in records.values():
            if Fields.CONTAINER_TITLE not in record:
                record[Fields.CONTAINER_TITLE] = (
                    record.get(Fields.JOURNAL, "")
                    + record.get(Fields.BOOKTITLE, "")
                    + record.get(Fields.SERIES, "")
                )

            for required_field in required_fields:
                if required_field not in record:
                    record[required_field] = ""
        return records

    def _dedupe_source(self, *, records: dict) -> list[list]:
        self.review_manager.logger.info(
            "Processing as a non-pdf source (matching exact colrev_ids)"
        )

        source_records = [
            r
            for r in records.values()
            if r[Fields.STATUS] == RecordState.md_prepared
            and any(
                self.settings.selected_source.replace("data/search/", "") in co
                for co in r[Fields.ORIGIN]
            )
        ]

        toc_items = self._get_toc_items(records_list=source_records)

        decision_list: list[list] = []
        # decision_list =[{'ID1': ID1, 'ID2': ID2, 'decision': 'duplicate'}]

        # match based on overlapping  colrev_ids
        for toc_item in tqdm(toc_items):
            processed_same_toc_records = [
                r
                for r in records.values()
                if all(r.get(k, "NA") == v for k, v in toc_item.items())
                and r[Fields.STATUS]
                not in [
                    RecordState.md_imported,
                    RecordState.md_needs_manual_preparation,
                    RecordState.md_prepared,
                    RecordState.rev_prescreen_excluded,
                ]
                and not any(
                    self.settings.selected_source.replace("data/search/", "") in co
                    for co in r[Fields.ORIGIN]
                )
            ]
            new_same_toc_records = [
                r
                for r in source_records
                if all(r.get(k, "NA") == v for k, v in toc_item.items())
            ]
            if len(new_same_toc_records) > 0:
                # print(new_same_toc_records)
                for new_same_toc_record in new_same_toc_records:
                    for rec2 in processed_same_toc_records:
                        overlapping_colrev_ids = self._has_overlapping_colrev_id(
                            colrev.record.record.Record(new_same_toc_record),
                            colrev.record.record.Record(rec2),
                        )
                        if overlapping_colrev_ids:
                            decision_list.append(
                                [new_same_toc_record[Fields.ID], rec2[Fields.ID]]
                            )
                            print("TODO : validate whether it merges correctly:")
                            input(decision_list)

        return decision_list

    def _validate_potential_merge(self, *, rec1: dict, rec2: dict) -> bool:
        if Fields.FILE in rec2:
            updated_record_dict = rec1.copy()
            updated_record_dict[Fields.FILE] = rec2[Fields.FILE]
        elif Fields.FILE in rec1:
            updated_record_dict = rec2.copy()
            updated_record_dict[Fields.FILE] = rec1[Fields.FILE]
        else:  # None of the records is curated
            raise FileNotFoundError

        updated_record = colrev.record.record.Record(updated_record_dict)
        updated_record.run_pdf_quality_model(self.pdf_qm)
        return updated_record.has_pdf_defects()

    def _process_pdf_tuple(
        self,
        *,
        tuple_to_process: tuple,
        records: dict,
        decision_list: list,
        curated_record_ids: list,
        pdf_record_ids: list,
    ) -> None:
        rec1 = records[tuple_to_process[0]]
        rec2 = records[tuple_to_process[1]]

        # Note : Focus on merges between
        # curated_records and pdf_same_toc_records
        # Note : this should also ensure that pdf groups are not merged
        # until a corresponding curated record group is available.
        if (
            rec1[Fields.ID] in curated_record_ids
            and rec2[Fields.ID] in curated_record_ids
        ) or (rec1[Fields.ID] in pdf_record_ids and rec2[Fields.ID] in pdf_record_ids):
            return

        try:
            validated = self._validate_potential_merge(rec1=rec1, rec2=rec2)
        except FileNotFoundError:
            return

        overlapping_colrev_ids = self._has_overlapping_colrev_id(
            colrev.record.record.Record(rec1), colrev.record.record.Record(rec2)
        )
        if validated or overlapping_colrev_ids:
            decision_list.append([rec1[Fields.ID], rec2[Fields.ID]])

    def _dedupe_pdf_toc_item(
        self,
        *,
        decision_list: list[list],
        toc_item: dict,
        records: dict,
        source_records: list,
    ) -> None:
        processed_same_toc_records = [
            r
            for r in records.values()
            if all(r.get(k, "NA") == v for k, v in toc_item.items())
            and r[Fields.STATUS]
            not in [
                RecordState.md_imported,
                RecordState.md_needs_manual_preparation,
                RecordState.md_prepared,
                RecordState.rev_prescreen_excluded,
            ]
            and not any(
                self.settings.selected_source.replace("data/search/", "") in co
                for co in r[Fields.ORIGIN]
            )
        ]
        pdf_same_toc_records = [
            r
            for r in source_records
            if all(r.get(k, "NA") == v for k, v in toc_item.items())
        ]

        references = pd.DataFrame.from_records(
            processed_same_toc_records + pdf_same_toc_records
        )

        nr_entries = references.shape[0]
        if nr_entries == 0:
            return
        similarity_array = np.zeros([nr_entries, nr_entries])

        # Note : min_similarity only means that the PDF will be considered
        # for validates_based_on_metadata(...), which is the acutal test!
        similarity_array, tuples_to_process = self._calculate_similarities(
            similarity_array=similarity_array,
            references=references,
            min_similarity=0.7,
        )

        curated_record_ids = [r[Fields.ID] for r in processed_same_toc_records]
        pdf_record_ids = [r[Fields.ID] for r in pdf_same_toc_records]
        for tuple_to_process in tuples_to_process:
            self._process_pdf_tuple(
                tuple_to_process=tuple_to_process,
                records=records,
                decision_list=decision_list,
                curated_record_ids=curated_record_ids,
                pdf_record_ids=pdf_record_ids,
            )

    def _dedupe_pdf_source(self, *, records: dict) -> list[list]:
        self.review_manager.logger.info("Processing as a pdf source")

        source_records = [
            r
            for r in records.values()
            if r[Fields.STATUS] == RecordState.md_prepared
            and any(
                self.settings.selected_source.replace("data/search/", "") in co
                for co in r[Fields.ORIGIN]
            )
        ]

        decision_list: list[list] = []
        # decision_list =[{'ID1': ID1, 'ID2': ID2, 'decision': 'duplicate'}]

        for toc_item in tqdm(self._get_toc_items(records_list=source_records)):
            self._dedupe_pdf_toc_item(
                decision_list=decision_list,
                toc_item=toc_item,
                records=records,
                source_records=source_records,
            )

        return decision_list

    def _pdf_source_selected(self) -> bool:
        pdf_source = False
        relevant_source = [
            s
            for s in self.review_manager.settings.sources
            if str(s.filename) == self.settings.selected_source
        ]
        if len(relevant_source) > 0:
            pdf_source = "colrev.files_dir" == relevant_source[0].endpoint
        return pdf_source

    def _first_source_selected(self) -> bool:
        return (
            self.settings.selected_source
            == self.review_manager.settings.dedupe.dedupe_package_endpoints[0][
                "selected_source"
            ]
        )

    def run_dedupe(self) -> None:
        """Run the curation dedupe procedure"""

        self.dedupe_operation.merge_based_on_global_ids(apply=True)

        records = self.review_manager.dataset.load_records_dict()
        records = self._prep_records(records=records)

        # first_source should be the highest quality source
        # (which moves to md_processed first)
        first_source = self._first_source_selected()

        self._warn_on_missing_sources(first_source=first_source)

        if first_source:
            self._add_first_source_if_deduplicated(records=records)
            return

        self.review_manager.logger.info(
            "Identify duplicates between "
            f"curated_records and {self.settings.selected_source} (within toc_items)"
        )

        decision_list: list[list] = []
        # decision_list =[['ID1', 'ID2'], ...]
        if not self._pdf_source_selected():
            decision_list = self._dedupe_source(records=records)
        else:
            decision_list = self._dedupe_pdf_source(records=records)

        # Note : dedupe.apply_merges reloads the records and
        # thereby discards previous changes
        if len(decision_list) == 0:
            self.review_manager.logger.info(
                f"{Colors.GREEN}No merge-candidates identified between sets{Colors.END}"
            )
            return

        self.review_manager.logger.info(
            f"{Colors.GREEN}Duplicates identified{Colors.END}"
        )

        preferred_masterdata_sources = [
            s
            for s in self.review_manager.settings.sources
            if s.endpoint != "colrev.files_dir"
        ]
        self.dedupe_operation.apply_merges(
            id_sets=decision_list,
            preferred_masterdata_sources=preferred_masterdata_sources,
        )
        self.review_manager.dataset.create_commit(
            msg="Merge duplicate records",
        )
