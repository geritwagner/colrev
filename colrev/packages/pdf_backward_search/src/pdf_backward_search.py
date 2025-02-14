#! /usr/bin/env python
"""SearchSource: backward search (based on PDFs and GROBID)"""
from __future__ import annotations

import json
import typing
from pathlib import Path

import inquirer
import pandas as pd
import requests
from bib_dedupe.bib_dedupe import block
from bib_dedupe.bib_dedupe import cluster
from bib_dedupe.bib_dedupe import match
from bib_dedupe.bib_dedupe import prep
from bib_dedupe.merge import merge
from pydantic import Field
from rapidfuzz import fuzz
from tqdm import tqdm

import colrev.exceptions as colrev_exceptions
import colrev.package_manager.interfaces
import colrev.package_manager.package_manager
import colrev.package_manager.package_settings
import colrev.record.record
import colrev.record.record_prep
from colrev.constants import ENTRYTYPES
from colrev.constants import Fields
from colrev.constants import RecordState
from colrev.constants import SearchSourceHeuristicStatus
from colrev.constants import SearchType
from colrev.packages.crossref.src import crossref_api

# pylint: disable=unused-argument
# pylint: disable=duplicate-code


class BackwardSearchSource(colrev.package_manager.interfaces.SearchSourceInterface):
    """Backward search extracting references from PDFs using GROBID
    Scope: all included papers with colrev_status in (rev_included, rev_synthesized)
    """

    _api_url = "https://opencitations.net/index/coci/api/v1/references/"

    settings_class = colrev.package_manager.package_settings.DefaultSourceSettings
    endpoint = "colrev.pdf_backward_search"
    source_identifier = Fields.ID
    search_types = [SearchType.BACKWARD_SEARCH]

    ci_supported: bool = Field(default=False)
    heuristic_status = SearchSourceHeuristicStatus.supported

    def __init__(
        self, *, source_operation: colrev.process.operation.Operation, settings: dict
    ) -> None:
        self.review_manager = source_operation.review_manager
        if "min_intext_citations" not in settings["search_parameters"]:
            settings["search_parameters"]["min_intext_citations"] = 3

        self.search_source = self.settings_class(**settings)
        # Do not run in continuous-integration environment
        if not self.review_manager.in_ci_environment():
            self.grobid_service = self.review_manager.get_grobid_service()
            self.grobid_service.start()

        self.crossref_api = crossref_api.CrossrefAPI(params={})

    @classmethod
    def get_default_source(cls) -> colrev.settings.SearchSource:
        """Get the default SearchSource settings"""

        return colrev.settings.SearchSource(
            endpoint="colrev.pdf_backward_search",
            filename=Path("data/search/pdf_backward_search.bib"),
            search_type=SearchType.BACKWARD_SEARCH,
            search_parameters={
                "scope": {"colrev_status": "rev_included|rev_synthesized"},
                "min_intext_citations": 3,
            },
            comment="",
        )

    def _validate_source(self) -> None:
        """Validate the SearchSource (parameters etc.)"""
        source = self.search_source
        self.review_manager.logger.debug(f"Validate SearchSource {source.filename}")

        assert source.search_type == SearchType.BACKWARD_SEARCH

        if "scope" not in source.search_parameters:
            raise colrev_exceptions.InvalidQueryException(
                "Scope required in the search_parameters"
            )

        if source.search_parameters["scope"].get("file", "") == "paper.md":
            pass
        else:
            if (
                source.search_parameters["scope"]["colrev_status"]
                != "rev_included|rev_synthesized"
            ):
                raise colrev_exceptions.InvalidQueryException(
                    "search_parameters/scope/colrev_status must be rev_included|rev_synthesized"
                )

        self.review_manager.logger.debug(f"SearchSource {source.filename} validated")

    def _bw_search_condition(self, *, record: dict) -> bool:
        # rev_included/rev_synthesized required, but record not in rev_included/rev_synthesized
        if (
            "colrev_status" in self.search_source.search_parameters["scope"]
            and self.search_source.search_parameters["scope"]["colrev_status"]
            == "rev_included|rev_synthesized"
            and record[Fields.STATUS]
            not in [
                RecordState.rev_included,
                RecordState.rev_synthesized,
            ]
        ):
            return False

        # Note: this is for peer_reviews
        if "file" in self.search_source.search_parameters["scope"]:
            if (
                self.search_source.search_parameters["scope"]["file"] == "paper.pdf"
            ) and "data/pdfs/paper.pdf" != record.get(Fields.FILE, ""):
                return False

        if not (self.review_manager.path / Path(record[Fields.FILE])).is_file():
            self.review_manager.logger.error(f"File not found for {record[Fields.ID]}")
            return False

        return True

    def _get_reference_records_from_open_citations(self, *, record_dict: dict) -> list:
        references = []

        url = f"{self._api_url}{record_dict['doi']}"
        # headers = {"authorization": "YOUR-OPENCITATIONS-ACCESS-TOKEN"}
        headers: typing.Dict[str, str] = {}
        ret = requests.get(url, headers=headers, timeout=300)
        try:
            items = json.loads(ret.text)

            for doi in [x["cited"] for x in items]:
                try:
                    retrieved_record = self.crossref_api.query_doi(
                        doi=doi,
                    )
                    # if not crossref_query_return:
                    #     raise colrev_exceptions.RecordNotFoundInPrepSourceException()
                    retrieved_record.data[Fields.ID] = retrieved_record.data[Fields.DOI]
                    references.append(retrieved_record.data)
                except (
                    colrev_exceptions.RecordNotFoundInPrepSourceException,
                    colrev_exceptions.RecordNotParsableException,
                ):
                    pass
        except json.decoder.JSONDecodeError:
            self.review_manager.logger.info(
                f"Error retrieving citations from Opencitations for {record_dict['ID']}"
            )

        return references

    def _get_similarity(
        self, *, record: colrev.record.record.Record, retrieved_record_dict: dict
    ) -> float:
        title_similarity = fuzz.partial_ratio(
            retrieved_record_dict.get(Fields.TITLE, "").lower(),
            record.data.get(Fields.TITLE, "").lower(),
        )
        container_similarity = fuzz.partial_ratio(
            colrev.record.record_prep.PrepRecord(retrieved_record_dict)
            .get_container_title()
            .lower(),
            record.get_container_title().lower(),
        )
        weights = [0.6, 0.4]
        similarities = [title_similarity, container_similarity]

        similarity = sum(similarities[g] * weights[g] for g in range(len(similarities)))
        return similarity

    @classmethod
    def _deduplicate_all_references(cls, all_references: dict) -> pd.DataFrame:
        print("Resolving entities in citation network")
        # Flatten the list of lists into a single list of references, including the record ID
        all_references_flat = [
            {**ref, "record_id": record_id}
            for record_id, refs in all_references.items()
            for ref in refs
        ]
        if len(all_references_flat) == 0:
            return pd.DataFrame()

        for ref in all_references_flat:
            ref[Fields.ID] = ref["record_id"] + "_backward_search_" + ref[Fields.ID]

        # Create a DataFrame from the flattened list of references
        df_all_references = pd.DataFrame(all_references_flat)
        df_all_references["nr_references"] = 1

        def merge_into_list(values: list) -> str:
            """Concatenate all values into a single string, separated by commas."""
            merged_string = ",".join(str(value) for value in values)
            return merged_string

        def sum_nr_references(values: list) -> int:
            """Sum all integers in a list."""
            return sum(values)

        records_df = prep(df_all_references, verbosity_level=0)
        deduplication_pairs = block(records_df, verbosity_level=0)
        matched_df = match(deduplication_pairs, verbosity_level=0)
        duplicate_id_sets = cluster(matched_df, verbosity_level=0)
        df_all_references = merge(
            df_all_references,
            duplicate_id_sets=duplicate_id_sets,
            merge_functions={
                Fields.NR_INTEXT_CITATIONS: merge_into_list,
                "nr_references": sum_nr_references,
            },
        )
        df_all_references.rename(columns={"origin": "bw_search_origins"}, inplace=True)
        return df_all_references

    @classmethod
    def _export_crosstab_thresholds(cls, df_all_references: pd.DataFrame) -> None:
        cross_tabulated_data: typing.Dict[int, dict] = {}

        for in_text_citation_threshold in range(1, 20):
            for ref_freq_threshold in range(1, 20):

                df_all_references["meets_criteria"] = df_all_references[
                    Fields.NR_INTEXT_CITATIONS
                ].apply(
                    lambda x, threshold=in_text_citation_threshold, rft=ref_freq_threshold: len(
                        [
                            citation
                            for citation in x.split(",")
                            if int(citation) >= threshold
                        ]
                    )
                    >= rft
                )

                total_references = df_all_references["meets_criteria"].sum()

                if ref_freq_threshold not in cross_tabulated_data:
                    cross_tabulated_data[ref_freq_threshold] = {}
                cross_tabulated_data[ref_freq_threshold][
                    in_text_citation_threshold
                ] = total_references

        cross_tabulated_df = pd.DataFrame(cross_tabulated_data).T
        cross_tabulated_df.reset_index(inplace=True)
        cross_tabulated_df.columns = ["ref_freq_threshold"] + [
            "in_text_citation_threshold_" + str(i) for i in range(1, 20)
        ]
        cross_tabulated_df.to_csv(
            "cross_tabulated_evaluation.csv", header=True, index=False
        )
        print("Exported to cross_tabulated_evaluation.csv.")

    def _complement_with_open_citations_data(
        self,
        *,
        pdf_backward_search_feed: colrev.ops.search_api_feed.SearchAPIFeed,
        records: dict,
    ) -> None:
        self.review_manager.logger.info("Comparing records with open-citations data")

        for feed_record_dict in pdf_backward_search_feed.feed_records.values():
            parent_record = self._get_parent_record(feed_record_dict, records)
            if not parent_record:
                continue

            backward_references = self._get_reference_records_from_open_citations(
                record_dict=parent_record
            )
            self._update_feed_records_with_open_citations_data(
                feed_record_dict, backward_references
            )

    def _get_parent_record(self, feed_record_dict: dict, records: dict) -> dict:
        bw_search_origin = feed_record_dict["bw_search_origins"].split(";")[0]
        parent_record_id = bw_search_origin[
            : bw_search_origin.find("_backward_search_")
        ]
        return records.get(parent_record_id, {})

    def _update_feed_records_with_open_citations_data(
        self, feed_record_dict: dict, backward_references: list
    ) -> None:
        feed_record = colrev.record.record.Record(feed_record_dict)
        max_similarity, best_match = self._find_best_match(
            feed_record, backward_references
        )

        if max_similarity > 0.9:
            feed_record.data.update(**best_match)
            self.review_manager.logger.info(
                f"Updated record {feed_record.data[Fields.ID]} with OpenCitations data."
            )

    def _find_best_match(
        self, feed_record: colrev.record.record.Record, backward_references: list
    ) -> tuple:
        max_similarity = 0.0
        best_match = None
        for backward_reference in backward_references:
            similarity = self._get_similarity(
                record=feed_record, retrieved_record_dict=backward_reference
            )
            if similarity > max_similarity:
                best_match = backward_reference
                max_similarity = similarity
        return max_similarity, best_match

    def _get_new_record(
        self,
        *,
        item: dict,
        pdf_backward_search_feed: colrev.ops.search_api_feed.SearchAPIFeed,
    ) -> colrev.record.record.Record:
        item[Fields.ID] = "new"
        # Note: multiple source_identifiers are merged in origin field.
        for feed_record in pdf_backward_search_feed.feed_records.values():
            feed_record_origins = feed_record["bw_search_origins"].split(",")
            new_record_origins = item["bw_search_origins"].split(",")
            if set(feed_record_origins) & set(new_record_origins):
                item[Fields.ID] = feed_record[Fields.ID]
                break

        if item[Fields.ID] == "new":
            max_id = max(
                [
                    int(r[Fields.ID])
                    for r in pdf_backward_search_feed.feed_records.values()
                ]
                or [0]
            )
            item[Fields.ID] = str(max_id + 1).rjust(6, "0")

        fields_to_drop = [
            "meets_criteria",
            "record_id",
            "nr_references",
            "nr_intext_citations",
            "bwsearch_ref",
        ]
        for field in fields_to_drop:
            if field in item:
                del item[field]
        item = {
            k: v for k, v in item.items() if not pd.isna(v)
        }  # Drop fields where value is NaN
        return colrev.record.record.Record(item)

    def search(self, rerun: bool) -> None:
        """Run a search of PDFs (backward search based on GROBID)"""

        self._validate_source()

        # Do not run in continuous-integration environment
        if self.review_manager.in_ci_environment():
            raise colrev_exceptions.SearchNotAutomated(
                "PDF Backward Search not automated."
            )

        records = self.review_manager.dataset.load_records_dict()

        if not records:
            self.review_manager.logger.info(
                "No records imported. Cannot run backward search yet."
            )
            return
        min_intext_citations = self.search_source.search_parameters[
            "min_intext_citations"
        ]
        self.review_manager.logger.info(
            f"Set min_intext_citations={min_intext_citations}"
        )
        nr_references_threshold = self.search_source.search_parameters.get(
            "min_ref_freq", 1
        )
        self.review_manager.logger.info(
            f"Set nr_references_threshold={nr_references_threshold}"
        )

        selected_records = {
            rid: record
            for rid, record in records.items()
            if self._bw_search_condition(record=record)
        }

        all_references = self._get_all_references(
            selected_records=selected_records, review_manager=self.review_manager
        )

        df_all_references = self._deduplicate_all_references(all_references)

        df_all_references["meets_criteria"] = df_all_references[
            Fields.NR_INTEXT_CITATIONS
        ].apply(
            lambda x: len(
                [
                    citation
                    for citation in x.split(",")
                    if int(citation) >= int(min_intext_citations)
                ]
            )
            >= int(nr_references_threshold)
        )

        selected_references = df_all_references[df_all_references["meets_criteria"]]
        pdf_backward_search_feed = self.search_source.get_api_feed(
            review_manager=self.review_manager,
            source_identifier=self.source_identifier,
            update_only=(not rerun),
        )

        for item in selected_references.to_dict(orient="records"):
            new_record = self._get_new_record(
                item=item, pdf_backward_search_feed=pdf_backward_search_feed
            )

            pdf_backward_search_feed.add_update_record(
                retrieved_record=new_record,
            )

        self._complement_with_open_citations_data(
            pdf_backward_search_feed=pdf_backward_search_feed, records=records
        )

        pdf_backward_search_feed.save()

        if self.review_manager.dataset.has_record_changes():
            self.review_manager.dataset.create_commit(
                msg="Backward search", script_call="colrev search"
            )

    @classmethod
    def heuristic(cls, filename: Path, data: str) -> dict:
        """Source heuristic for PDF backward searches (GROBID)"""

        result = {"confidence": 0.0}
        if str(filename).endswith("_ref_list.pdf"):
            result["confidence"] = 1.0
            return result
        return result

    @classmethod
    def _get_all_references(
        cls,
        *,
        selected_records: dict,
        review_manager: colrev.review_manager.ReviewManager,
    ) -> dict:

        all_references = {}

        for record in tqdm(selected_records.values()):
            try:

                review_manager.logger.info(
                    f" run backward search for {record[Fields.ID]}"
                )

                pdf_path = review_manager.path / Path(record[Fields.FILE])
                tei = review_manager.get_tei(
                    pdf_path=pdf_path,
                    tei_path=colrev.record.record.Record(record).get_tei_filename(),
                )

                references = tei.get_references(add_intext_citation_count=True)
                for reference in references:
                    if "tei_id" in reference:
                        del reference["tei_id"]
                    reference["bwsearch_ref"] = (
                        record[Fields.ID] + "_backward_search_" + reference[Fields.ID]
                    )

                all_references[record[Fields.ID]] = references

            except colrev_exceptions.TEIException:
                review_manager.logger.info("Error accessing TEI")
            except KeyError as exc:
                review_manager.logger.info(exc)
        return all_references

    @classmethod
    def _get_settings_from_ui(
        cls, *, params: dict, review_manager: colrev.review_manager.ReviewManager
    ) -> None:

        question = "Do you want to create an overview for min_ref_freq and min_intext_citations?"
        create_overview = inquirer.confirm(question)

        if not create_overview:
            return

        print(
            "Calculating sample sizes for parameters min_ref_freq and min_intext_citations"
        )
        # Assuming there's a function to create an overview, it would be called here.
        # For example: cls.create_min_intext_citations_overview(params)

        records = review_manager.dataset.load_records_dict()
        selected_records = {
            record_id: record
            for record_id, record in records.items()
            if record[Fields.STATUS]
            in [
                RecordState.rev_included,
                RecordState.rev_synthesized,
            ]
        }

        all_references = cls._get_all_references(
            selected_records=selected_records, review_manager=review_manager
        )

        df_all_references = cls._deduplicate_all_references(all_references)

        cls._export_crosstab_thresholds(df_all_references)

        questions = [
            inquirer.Text(
                "in_text_citation_threshold", message="Enter in-text citation threshold"
            ),
            inquirer.Text(
                "ref_freq_threshold", message="Enter reference frequency threshold"
            ),
        ]
        answers = inquirer.prompt(questions)

        try:
            params["min_intext_citations"] = int(answers["in_text_citation_threshold"])
            params["min_ref_freq"] = int(answers["ref_freq_threshold"])
        except ValueError:
            print("Both thresholds must be integers. Please try again.")
            return

    @classmethod
    def add_endpoint(
        cls,
        operation: colrev.ops.search.Search,
        params: str,
    ) -> colrev.settings.SearchSource:
        """Add SearchSource as an endpoint (based on query provided to colrev search --add )"""

        params_dict = {}
        if params:
            for item in params.split(";"):
                key, value = item.split("=")
                params_dict[key] = value

        if "min_intext_citations" not in params_dict:
            cls._get_settings_from_ui(
                params=params_dict, review_manager=operation.review_manager
            )
        else:
            assert params_dict["min_intext_citations"].isdigit()
            assert params_dict["min_ref_freq"].isdigit()

        search_source = cls.get_default_source()
        if "min_intext_citations" in params_dict:
            search_source.search_parameters["min_intext_citations"] = int(
                params_dict["min_intext_citations"]
            )
        if "min_ref_freq" in params_dict:
            search_source.search_parameters["min_ref_freq"] = int(
                params_dict["min_ref_freq"]
            )

        operation.add_source_and_search(search_source)
        return search_source

    def load(self, load_operation: colrev.ops.load.Load) -> dict:
        """Load the records from the SearchSource file"""

        if self.search_source.filename.suffix == ".bib":
            records = colrev.loader.load_utils.load(
                filename=self.search_source.filename,
                logger=self.review_manager.logger,
            )
            for record_dict in records.values():
                record_dict.pop("bw_search_origins")
            return records

        raise NotImplementedError

    def prep_link_md(
        self,
        prep_operation: colrev.ops.prep.Prep,
        record: colrev.record.record.Record,
        save_feed: bool = True,
        timeout: int = 10,
    ) -> colrev.record.record.Record:
        """Not implemented"""
        return record

    def prepare(
        self,
        record: colrev.record.record_prep.PrepRecord,
        source: colrev.settings.SearchSource,
    ) -> colrev.record.record.Record:
        """Source-specific preparation for PDF backward searches (GROBID)"""

        record.format_if_mostly_upper(Fields.TITLE, case="sentence")
        record.format_if_mostly_upper(Fields.JOURNAL, case=Fields.TITLE)
        record.format_if_mostly_upper(Fields.BOOKTITLE, case=Fields.TITLE)
        record.format_if_mostly_upper(Fields.AUTHOR, case=Fields.TITLE)

        if (
            "multimedia appendix"
            in record.data.get(Fields.TITLE, "").lower()
            + record.data.get(Fields.JOURNAL, "").lower()
        ):
            record.prescreen_exclude(reason="grobid-error")

        if (
            record.data[Fields.ENTRYTYPE] == ENTRYTYPES.MISC
            and Fields.PUBLISHER in record.data
        ):
            record.data[Fields.ENTRYTYPE] = ENTRYTYPES.BOOK

        return record
