#! /usr/bin/env python
"""SearchSource: ABI/INFORM (ProQuest)"""
from __future__ import annotations

import re
from pathlib import Path

from pydantic import Field

import colrev.package_manager.interfaces
import colrev.package_manager.package_manager
import colrev.package_manager.package_settings
import colrev.record.record
from colrev.constants import ENTRYTYPES
from colrev.constants import Fields
from colrev.constants import SearchSourceHeuristicStatus
from colrev.constants import SearchType
from colrev.writer.write_utils import write_file

# pylint: disable=unused-argument
# pylint: disable=duplicate-code


class ABIInformProQuestSearchSource(
    colrev.package_manager.interfaces.SearchSourceInterface
):
    """ABI/INFORM (ProQuest)"""

    settings_class = colrev.package_manager.package_settings.DefaultSourceSettings
    endpoint = "colrev.abi_inform_proquest"
    source_identifier = "{{ID}}"
    search_types = [SearchType.DB]

    ci_supported: bool = Field(default=False)
    heuristic_status = SearchSourceHeuristicStatus.supported

    db_url = "https://search.proquest.com/abicomplete/advanced"

    def __init__(
        self, *, source_operation: colrev.process.operation.Operation, settings: dict
    ) -> None:
        self.review_manager = source_operation.review_manager
        self.search_source = self.settings_class(**settings)
        self.source_operation = source_operation
        self.quality_model = self.review_manager.get_qm()

    @classmethod
    def heuristic(cls, filename: Path, data: str) -> dict:
        """Source heuristic for ABI/INFORM (ProQuest)"""

        result = {"confidence": 0.0}

        if "proquest.com" in data:  # nosec
            if data.count("proquest.com") >= data.count("\n@"):
                result["confidence"] = 1.0
            if data.count("proquest.com") >= data.count("TY  -"):
                result["confidence"] = 1.0

        return result

    @classmethod
    def add_endpoint(
        cls,
        operation: colrev.ops.search.Search,
        params: str,
    ) -> colrev.settings.SearchSource:
        """Add SearchSource as an endpoint"""

        search_source = operation.create_db_source(
            search_source_cls=cls,
            params={},
        )
        operation.add_source_and_search(search_source)
        return search_source

    def search(self, rerun: bool) -> None:
        """Run a search of ABI/INFORM"""

        if self.search_source.search_type == SearchType.DB:
            self.source_operation.run_db_search(  # type: ignore
                search_source_cls=self.__class__,
                source=self.search_source,
            )

    def _remove_duplicates(self, records: dict) -> None:
        to_delete = []
        for record in records.values():
            if re.search(r"-\d{1,2}$", record[Fields.ID]):
                original_record_id = re.sub(r"-\d{1,2}$", "", record[Fields.ID])
                if original_record_id not in records:
                    continue
                original_record = records[original_record_id]

                # Note: between duplicate records,
                # there are variations in spelling and completeness
                if (
                    colrev.record.record.Record.get_record_similarity(
                        record_a=colrev.record.record.Record(record),
                        record_b=colrev.record.record.Record(original_record),
                    )
                    < 0.9
                ):
                    continue

                if original_record_id not in records:
                    continue
                to_delete.append(record[Fields.ID])
        if to_delete:
            for rid in to_delete:
                self.review_manager.logger.info(f" remove duplicate {rid}")
                del records[rid]

            write_file(records_dict=records, filename=self.search_source.filename)

    def prep_link_md(
        self,
        prep_operation: colrev.ops.prep.Prep,
        record: colrev.record.record.Record,
        save_feed: bool = True,
        timeout: int = 10,
    ) -> colrev.record.record.Record:
        """Not implemented"""
        return record

    def _load_ris(self) -> dict:

        def id_labeler(records: list) -> None:
            for record_dict in records:
                record_dict[Fields.ID] = record_dict["AN"]

        def entrytype_setter(record_dict: dict) -> None:
            if record_dict["TY"] == "JOUR":
                record_dict[Fields.ENTRYTYPE] = ENTRYTYPES.ARTICLE
            elif record_dict["TY"] == "BOOK":
                record_dict[Fields.ENTRYTYPE] = ENTRYTYPES.BOOK
            elif record_dict["TY"] == "THES":
                record_dict[Fields.ENTRYTYPE] = ENTRYTYPES.PHDTHESIS
            else:
                record_dict[Fields.ENTRYTYPE] = ENTRYTYPES.MISC

        def field_mapper(record_dict: dict) -> None:

            key_maps = {
                ENTRYTYPES.ARTICLE: {
                    "PY": Fields.YEAR,
                    "AU": Fields.AUTHOR,
                    "TI": Fields.TITLE,
                    "JF": Fields.JOURNAL,
                    "AB": Fields.ABSTRACT,
                    "VL": Fields.VOLUME,
                    "IS": Fields.NUMBER,
                    "KW": Fields.KEYWORDS,
                    "DO": Fields.DOI,
                    "PB": Fields.PUBLISHER,
                    "SP": Fields.PAGES,
                    "PMID": Fields.PUBMED_ID,
                    "SN": Fields.ISSN,
                    "AN": f"{self.endpoint}.accession_number",
                    "LA": Fields.LANGUAGE,
                    "L2": Fields.FULLTEXT,
                    "UR": Fields.URL,
                },
                ENTRYTYPES.PHDTHESIS: {
                    "PY": Fields.YEAR,
                    "AU": Fields.AUTHOR,
                    "T1": Fields.TITLE,
                    "UR": Fields.URL,
                    "PB": Fields.SCHOOL,
                    "KW": Fields.KEYWORDS,
                    "AN": f"{self.endpoint}.accession_number",
                    "AB": Fields.ABSTRACT,
                    "LA": Fields.LANGUAGE,
                    "CY": Fields.ADDRESS,
                    "L2": Fields.FULLTEXT,
                    "A3": f"{self.endpoint}.supervisor",
                },
            }

            if record_dict[Fields.ENTRYTYPE] == ENTRYTYPES.ARTICLE:
                if "T1" in record_dict and "TI" not in record_dict:
                    record_dict["TI"] = record_dict.pop("T1")

            key_map = key_maps[record_dict[Fields.ENTRYTYPE]]
            for ris_key in list(record_dict.keys()):
                if ris_key in key_map:
                    standard_key = key_map[ris_key]
                    record_dict[standard_key] = record_dict.pop(ris_key)

            if "SP" in record_dict and "EP" in record_dict:
                record_dict[Fields.PAGES] = (
                    f"{record_dict.pop('SP')}--{record_dict.pop('EP')}"
                )

            if Fields.AUTHOR in record_dict and isinstance(
                record_dict[Fields.AUTHOR], list
            ):
                record_dict[Fields.AUTHOR] = " and ".join(record_dict[Fields.AUTHOR])
            if Fields.EDITOR in record_dict and isinstance(
                record_dict[Fields.EDITOR], list
            ):
                record_dict[Fields.EDITOR] = " and ".join(record_dict[Fields.EDITOR])
            if Fields.KEYWORDS in record_dict and isinstance(
                record_dict[Fields.KEYWORDS], list
            ):
                record_dict[Fields.KEYWORDS] = ", ".join(record_dict[Fields.KEYWORDS])

            keys_to_remove = [
                "TY",
                "Y2",
                "DB",
                "C1",
                "T3",
                "DA",
                "JF",
                "L1",
                "SP",
                "Y1",
                "M1",
                "M3",
                "N1",
                "PP",
                "CY",
                "SN",
                "ER",
                "AN",
            ]

            for key in keys_to_remove:
                record_dict.pop(key, None)

            for key, value in record_dict.items():
                record_dict[key] = str(value)

        records = colrev.loader.load_utils.load(
            filename=self.search_source.filename,
            id_labeler=id_labeler,
            entrytype_setter=entrytype_setter,
            field_mapper=field_mapper,
            logger=self.review_manager.logger,
        )

        return records

    def load(self, load_operation: colrev.ops.load.Load) -> dict:
        """Load the records from the SearchSource file"""

        if self.search_source.filename.suffix == ".bib":
            records = colrev.loader.load_utils.load(
                filename=self.search_source.filename,
                logger=self.review_manager.logger,
                unique_id_field="ID",
            )
            self._remove_duplicates(records)
            return records

        if self.search_source.filename.suffix == ".ris":
            return self._load_ris()

        raise NotImplementedError

    def prepare(
        self, record: colrev.record.record.Record, source: colrev.settings.SearchSource
    ) -> colrev.record.record.Record:
        """Source-specific preparation for ABI/INFORM (ProQuest)"""

        if (
            record.data.get(Fields.JOURNAL, "")
            .lower()
            .endswith("conference proceedings.")
        ):
            record.change_entrytype(
                new_entrytype="inproceedings", qm=self.quality_model
            )

        if Fields.LANGUAGE in record.data:
            if record.data[Fields.LANGUAGE] in ["ENG", "English"]:
                record.update_field(
                    key=Fields.LANGUAGE,
                    value="eng",
                    source="prep_abi_inform_proquest_source",
                )

        return record
