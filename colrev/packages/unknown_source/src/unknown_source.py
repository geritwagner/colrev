#! /usr/bin/env python
"""SearchSource: Unknown source (default for all other sources)"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

import pandas as pd
from pydantic import Field
from rapidfuzz import fuzz

import colrev.env.language_service
import colrev.exceptions as colrev_exceptions
import colrev.loader.load_utils
import colrev.package_manager.interfaces
import colrev.package_manager.package_manager
import colrev.package_manager.package_settings
import colrev.record.record
import colrev.record.record_prep
from colrev.constants import Colors
from colrev.constants import ENTRYTYPES
from colrev.constants import Fields
from colrev.constants import FieldSet
from colrev.constants import FieldValues
from colrev.constants import SearchSourceHeuristicStatus
from colrev.constants import SearchType

# pylint: disable=unused-argument
# pylint: disable=duplicate-code


class UnknownSearchSource(colrev.package_manager.interfaces.SearchSourceInterface):
    """Unknown SearchSource"""

    settings_class = colrev.package_manager.package_settings.DefaultSourceSettings
    endpoint = "colrev.unknown_source"

    source_identifier = "colrev.unknown_source"
    search_types = [
        SearchType.DB,
        SearchType.OTHER,
        SearchType.BACKWARD_SEARCH,
        SearchType.FORWARD_SEARCH,
        SearchType.TOC,
    ]

    ci_supported: bool = Field(default=False)
    heuristic_status = SearchSourceHeuristicStatus.na

    db_url = ""

    HTML_CLEANER = re.compile("<.*?>")
    _padding = 40

    def __init__(
        self, *, source_operation: colrev.process.operation.Operation, settings: dict
    ) -> None:
        self.search_source = self.settings_class(**settings)
        self.review_manager = source_operation.review_manager
        self.language_service = colrev.env.language_service.LanguageService()
        self.operation = source_operation

    @classmethod
    def heuristic(cls, filename: Path, data: str) -> dict:
        """Source heuristic for unknown sources"""

        result = {"confidence": 0.1}

        return result

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
        search_source = operation.create_db_source(
            search_source_cls=cls,
            params=params_dict,
        )
        operation.add_source_and_search(search_source)
        return search_source

    def search(self, rerun: bool) -> None:
        """Run a search of Crossref"""

        if self.search_source.search_type == SearchType.DB:
            self.operation.run_db_search(  # type: ignore
                search_source_cls=self.__class__, source=self.search_source
            )

    def prep_link_md(
        self,
        prep_operation: colrev.ops.prep.Prep,
        record: colrev.record.record.Record,
        save_feed: bool = True,
        timeout: int = 10,
    ) -> colrev.record.record.Record:
        """Not implemented"""
        return record

    def _rename_erroneous_extensions(self) -> None:
        if self.search_source.filename.suffix in [".xls", ".xlsx"]:
            return
        data = self.search_source.filename.read_text(encoding="utf-8")
        # # Correct the file extension if necessary
        if re.findall(
            r"^%0", data, re.MULTILINE
        ) and self.search_source.filename.suffix not in [".enl"]:
            new_filename = self.search_source.filename.with_suffix(".enl")
            self.review_manager.logger.info(
                f"{Colors.GREEN}Rename to {new_filename} "
                f"(because the format is .enl){Colors.END}"
            )
            shutil.move(str(self.search_source.filename), str(new_filename))
            self.review_manager.dataset.add_changes(
                self.search_source.filename, remove=True
            )
            self.search_source.filename = new_filename
            self.review_manager.dataset.add_changes(new_filename)
            self.review_manager.dataset.create_commit(
                msg=f"Rename {self.search_source.filename}"
            )
            return

        if re.findall(
            r"^TI ", data, re.MULTILINE
        ) and self.search_source.filename.suffix not in [".ris"]:
            new_filename = self.search_source.filename.with_suffix(".ris")
            self.review_manager.logger.info(
                f"{Colors.GREEN}Rename to {new_filename} "
                f"(because the format is .ris){Colors.END}"
            )
            shutil.move(str(self.search_source.filename), str(new_filename))
            self.review_manager.dataset.add_changes(
                self.search_source.filename, remove=True
            )
            self.search_source.filename = new_filename
            self.review_manager.dataset.add_changes(new_filename)
            self.review_manager.dataset.create_commit(
                msg=f"Rename {self.search_source.filename}"
            )

    def _load_ris(self, *, load_operation: colrev.ops.load.Load) -> dict:
        def entrytype_setter(record_dict: dict) -> None:
            # Based on https://github.com/aurimasv/translators/wiki/RIS-Tag-Map
            reference_types = {
                "JOUR": ENTRYTYPES.ARTICLE,
                "JFULL": ENTRYTYPES.ARTICLE,
                "ABST": ENTRYTYPES.ARTICLE,
                "INPR": ENTRYTYPES.ARTICLE,  # inpress
                "CONF": ENTRYTYPES.INPROCEEDINGS,
                "CPAPER": ENTRYTYPES.INPROCEEDINGS,
                "THES": ENTRYTYPES.PHDTHESIS,
                "REPT": ENTRYTYPES.TECHREPORT,
                "RPRT": ENTRYTYPES.TECHREPORT,
                "CHAP": ENTRYTYPES.INBOOK,
                "BOOK": ENTRYTYPES.BOOK,
                "NEWS": ENTRYTYPES.MISC,
                "BLOG": ENTRYTYPES.MISC,
            }
            if record_dict["TY"] in reference_types:
                record_dict[Fields.ENTRYTYPE] = reference_types[record_dict["TY"]]
            else:
                record_dict[Fields.ENTRYTYPE] = ENTRYTYPES.MISC

        def field_mapper(record_dict: dict) -> None:
            # Based on https://github.com/aurimasv/translators/wiki/RIS-Tag-Map
            key_maps = {
                ENTRYTYPES.ARTICLE: {
                    "PY": Fields.YEAR,
                    "AU": Fields.AUTHOR,
                    "TI": Fields.TITLE,
                    "T2": Fields.JOURNAL,
                    "AB": Fields.ABSTRACT,
                    "VL": Fields.VOLUME,
                    "IS": Fields.NUMBER,
                    "DO": Fields.DOI,
                    "PB": Fields.PUBLISHER,
                    "UR": Fields.URL,
                    "fulltext": Fields.FULLTEXT,
                    "PMID": Fields.PUBMED_ID,
                    "KW": Fields.KEYWORDS,
                    "SP": Fields.PAGES,
                },
                ENTRYTYPES.INPROCEEDINGS: {
                    "PY": Fields.YEAR,
                    "AU": Fields.AUTHOR,
                    "TI": Fields.TITLE,
                    # "secondary_title": Fields.BOOKTITLE,
                    "DO": Fields.DOI,
                    "UR": Fields.URL,
                    # "fulltext": Fields.FULLTEXT,
                    "PMID": Fields.PUBMED_ID,
                    "KW": Fields.KEYWORDS,
                    "SP": Fields.PAGES,
                },
                ENTRYTYPES.INBOOK: {
                    "PY": Fields.YEAR,
                    "AU": Fields.AUTHOR,
                    # "primary_title": Fields.CHAPTER,
                    # "secondary_title": Fields.TITLE,
                    "DO": Fields.DOI,
                    "PB": Fields.PUBLISHER,
                    # "edition": Fields.EDITION,
                    "UR": Fields.URL,
                    # "fulltext": Fields.FULLTEXT,
                    "KW": Fields.KEYWORDS,
                    "SP": Fields.PAGES,
                },
                ENTRYTYPES.BOOK: {
                    "PY": Fields.YEAR,
                    "AU": Fields.AUTHOR,
                    # "primary_title": Fields.CHAPTER,
                    # "secondary_title": Fields.TITLE,
                    "DO": Fields.DOI,
                    "PB": Fields.PUBLISHER,
                    # "edition": Fields.EDITION,
                    "UR": Fields.URL,
                    # "fulltext": Fields.FULLTEXT,
                    "KW": Fields.KEYWORDS,
                    "SP": Fields.PAGES,
                },
                ENTRYTYPES.PHDTHESIS: {
                    "PY": Fields.YEAR,
                    "AU": Fields.AUTHOR,
                    "TI": Fields.TITLE,
                    "UR": Fields.URL,
                },
                ENTRYTYPES.TECHREPORT: {
                    "PY": Fields.YEAR,
                    "AU": Fields.AUTHOR,
                    "TI": Fields.TITLE,
                    "UR": Fields.URL,
                    # "fulltext": Fields.FULLTEXT,
                    "KW": Fields.KEYWORDS,
                    "PB": Fields.PUBLISHER,
                    "SP": Fields.PAGES,
                },
                ENTRYTYPES.MISC: {
                    "PY": Fields.YEAR,
                    "AU": Fields.AUTHOR,
                    "TI": Fields.TITLE,
                    "UR": Fields.URL,
                    # "fulltext": Fields.FULLTEXT,
                    "KW": Fields.KEYWORDS,
                    "PB": Fields.PUBLISHER,
                    "SP": Fields.PAGES,
                },
            }

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

            record_dict.pop("TY", None)
            record_dict.pop("Y2", None)
            record_dict.pop("DB", None)
            record_dict.pop("C1", None)
            record_dict.pop("T3", None)
            record_dict.pop("AD", None)
            record_dict.pop("CY", None)
            record_dict.pop("M3", None)
            record_dict.pop("EP", None)
            record_dict.pop("ER", None)

            for key, value in record_dict.items():
                record_dict[key] = str(value)

        load_operation.ensure_append_only(self.search_source.filename)
        records = colrev.loader.load_utils.load(
            filename=self.search_source.filename,
            unique_id_field="INCREMENTAL",
            entrytype_setter=entrytype_setter,
            field_mapper=field_mapper,
            logger=self.review_manager.logger,
        )
        return records

    def _load_bib(self, *, load_operation: colrev.ops.load.Load) -> dict:
        records = colrev.loader.load_utils.load(
            filename=self.search_source.filename,
            logger=self.review_manager.logger,
            unique_id_field="ID",
        )
        return records

    # pylint: disable=colrev-missed-constant-usage
    def _table_drop_fields(self, *, record_dict: dict) -> None:
        for key in list(record_dict.keys()):
            if record_dict[key] in [f"no {key}", "", "nan"]:
                del record_dict[key]
        if (
            record_dict.get("number_of_cited_references", "NA")
            == "no Number-of-Cited-References"
        ):
            del record_dict["number_of_cited_references"]
        if "no file" in record_dict.get("file_name", "NA"):
            del record_dict["file_name"]

        if record_dict.get("cited_by", "NA") in [
            "no Times-Cited",
        ]:
            del record_dict["cited_by"]

        if "author_count" in record_dict:
            del record_dict["author_count"]
        if "citation_key" in record_dict:
            del record_dict["citation_key"]

    def _load_table(self, *, load_operation: colrev.ops.load.Load) -> dict:
        def entrytype_setter(record_dict: dict) -> None:
            if "type" in record_dict:
                record_dict[Fields.ENTRYTYPE] = record_dict.pop("type")

            if Fields.ENTRYTYPE not in record_dict:
                if record_dict.get(Fields.JOURNAL, "") != "":
                    record_dict[Fields.ENTRYTYPE] = ENTRYTYPES.ARTICLE
                elif record_dict.get(Fields.BOOKTITLE, "") != "":
                    record_dict[Fields.ENTRYTYPE] = ENTRYTYPES.INPROCEEDINGS
                else:
                    record_dict[Fields.ENTRYTYPE] = ENTRYTYPES.MISC

            if record_dict[Fields.ENTRYTYPE] == ENTRYTYPES.INPROCEEDINGS:
                if (
                    Fields.JOURNAL in record_dict
                    and Fields.BOOKTITLE not in record_dict
                ):
                    record_dict[Fields.BOOKTITLE] = record_dict.pop(Fields.JOURNAL)
            elif record_dict[Fields.ENTRYTYPE] == ENTRYTYPES.ARTICLE:
                if (
                    Fields.BOOKTITLE in record_dict
                    and Fields.JOURNAL not in record_dict
                ):
                    record_dict[Fields.JOURNAL] = record_dict.pop(Fields.BOOKTITLE)

        def field_mapper(record_dict: dict) -> None:
            # replace all keys with lower case
            record_dict = {k.lower(): v for k, v in record_dict.items()}

            if "id" in record_dict:
                record_dict[Fields.ID] = record_dict.pop("id")
            if "entrytype" in record_dict:
                record_dict[Fields.ENTRYTYPE] = record_dict.pop("entrytype")
            if "type" in record_dict:
                record_dict[Fields.ENTRYTYPE] = record_dict.pop("type")
            if "authors" in record_dict:
                record_dict[Fields.AUTHOR] = record_dict.pop("authors", "")
            if "publication" in record_dict:
                record_dict[Fields.JOURNAL] = record_dict.pop("publication", "")

            record_dict.pop("Category", None)
            record_dict.pop("Affiliations", None)

            if "issue" in record_dict and Fields.NUMBER not in record_dict:
                record_dict[Fields.NUMBER] = record_dict.pop("issue")
                if record_dict[Fields.NUMBER] == "no issue":
                    del record_dict[Fields.NUMBER]

            if "publication_year" in record_dict and Fields.YEAR not in record_dict:
                record_dict[Fields.YEAR] = record_dict.pop("publication_year")

            # Note: this is a simple heuristic:
            if (
                "journal/book" in record_dict
                and Fields.JOURNAL not in record_dict
                and Fields.DOI in record_dict
            ):
                record_dict[Fields.JOURNAL] = record_dict.pop("journal/book")

            if "author" in record_dict and ";" in record_dict["author"]:
                record_dict["author"] = record_dict["author"].replace("; ", " and ")

            self._table_drop_fields(record_dict=record_dict)

            for key in list(record_dict.keys()):
                value = record_dict[key]
                record_dict[key] = str(value)
                if value == "" or pd.isna(value):
                    del record_dict[key]

        def id_labeler(records: list) -> None:
            """Labeler for IDs."""
            for counter, record_dict in enumerate(records):
                if Fields.ID not in record_dict:
                    record_dict[Fields.ID] = str(counter + 1).zfill(6)

        load_operation.ensure_append_only(self.search_source.filename)

        records = colrev.loader.load_utils.load(
            filename=self.search_source.filename,
            id_labeler=id_labeler,
            entrytype_setter=entrytype_setter,
            field_mapper=field_mapper,
            logger=self.review_manager.logger,
        )

        return records

    def _load_md(self, *, load_operation: colrev.ops.load.Load) -> dict:
        load_operation.ensure_append_only(self.search_source.filename)

        records = colrev.loader.load_utils.load(
            filename=self.search_source.filename,
            logger=load_operation.review_manager.logger,
        )
        return records

    def _load_enl(self, *, load_operation: colrev.ops.load.Load) -> dict:
        def entrytype_setter(record_dict: dict) -> None:
            if "0" not in record_dict:
                keys_to_check = ["V", "N"]
                if any(k in record_dict for k in keys_to_check):
                    record_dict[Fields.ENTRYTYPE] = ENTRYTYPES.ARTICLE
                else:
                    record_dict[Fields.ENTRYTYPE] = ENTRYTYPES.INPROCEEDINGS
            else:
                if record_dict["0"] == "Journal Article":
                    record_dict[Fields.ENTRYTYPE] = ENTRYTYPES.ARTICLE
                elif record_dict["0"] == "Inproceedings":
                    record_dict[Fields.ENTRYTYPE] = ENTRYTYPES.INPROCEEDINGS
                else:
                    record_dict[Fields.ENTRYTYPE] = ENTRYTYPES.MISC

        def field_mapper(record_dict: dict) -> None:

            key_maps = {
                ENTRYTYPES.ARTICLE: {
                    "T": Fields.TITLE,
                    "A": Fields.AUTHOR,
                    "D": Fields.YEAR,
                    "B": Fields.JOURNAL,
                    "V": Fields.VOLUME,
                    "N": Fields.NUMBER,
                    "P": Fields.PAGES,
                    "X": Fields.ABSTRACT,
                    "U": Fields.URL,
                    "8": "date",
                    "0": "type",
                },
                ENTRYTYPES.INPROCEEDINGS: {
                    "T": Fields.TITLE,
                    "A": Fields.AUTHOR,
                    "D": Fields.YEAR,
                    "B": Fields.JOURNAL,
                    "V": Fields.VOLUME,
                    "N": Fields.NUMBER,
                    "P": Fields.PAGES,
                    "X": Fields.ABSTRACT,
                    "U": Fields.URL,
                    "8": "date",
                    "0": "type",
                },
            }

            key_map = key_maps[record_dict[Fields.ENTRYTYPE]]
            for ris_key in list(record_dict.keys()):
                if ris_key in key_map:
                    standard_key = key_map[ris_key]
                    record_dict[standard_key] = record_dict.pop(ris_key)

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

            record_dict.pop("type", None)

            for key, value in record_dict.items():
                record_dict[key] = str(value)

        records = colrev.loader.load_utils.load(
            filename=self.search_source.filename,
            unique_id_field="INCREMENTAL",
            entrytype_setter=entrytype_setter,
            field_mapper=field_mapper,
            logger=self.review_manager.logger,
        )

        return records

    def load(self, load_operation: colrev.ops.load.Load) -> dict:
        """Load the records from the SearchSource file"""

        if not self.search_source.filename.is_file():
            return {}

        self._rename_erroneous_extensions()

        __load_methods = {
            ".ris": self._load_ris,
            ".bib": self._load_bib,
            ".csv": self._load_table,
            ".xls": self._load_table,
            ".xlsx": self._load_table,
            ".md": self._load_md,
            ".enl": self._load_enl,
        }

        if self.search_source.filename.suffix not in __load_methods:
            raise NotImplementedError

        records = __load_methods[self.search_source.filename.suffix](
            load_operation=load_operation
        )
        for record_id in records:
            records[record_id] = {
                k: v
                for k, v in records[record_id].items()
                if k not in FieldSet.PROVENANCE_KEYS + [Fields.SCREENING_CRITERIA]
            }
        for record in records.values():
            for key in list(record.keys()):
                if key not in FieldSet.STANDARDIZED_FIELD_KEYS:
                    record[f"colrev.unknonwn_source.{key}"] = record.pop(key)

        return records

    def _heuristically_fix_entrytypes(
        self, *, record: colrev.record.record_prep.PrepRecord
    ) -> None:
        """Prepare the record by heuristically correcting erroneous ENTRYTYPEs"""

        # Journal articles should not have booktitles/series set.
        if record.data[Fields.ENTRYTYPE] == "article":
            if Fields.BOOKTITLE in record.data and Fields.JOURNAL not in record.data:
                record.update_field(
                    key=Fields.JOURNAL,
                    value=record.data[Fields.BOOKTITLE],
                    source="unkown_source_prep",
                )
                record.remove_field(key=Fields.BOOKTITLE)
            if Fields.SERIES in record.data and Fields.JOURNAL not in record.data:
                record.update_field(
                    key=Fields.JOURNAL,
                    value=record.data[Fields.SERIES],
                    source="unkown_source_prep",
                )
                record.remove_field(key=Fields.SERIES)

        if self.search_source.filename.suffix == ".md":
            if (
                record.data[Fields.ENTRYTYPE] == "misc"
                and Fields.PUBLISHER in record.data
            ):
                record.update_field(
                    key=Fields.ENTRYTYPE, value="book", source="unkown_source_prep"
                )
            if record.data.get(Fields.YEAR, Fields.YEAR) == record.data.get(
                "date", "date"
            ):
                record.remove_field(key="date")
            if (
                "inbook" == record.data[Fields.ENTRYTYPE]
                and Fields.CHAPTER not in record.data
                and Fields.TITLE in record.data
            ):
                record.rename_field(key=Fields.TITLE, new_key=Fields.CHAPTER)

        if (
            "dissertation" in record.data.get(Fields.FULLTEXT, "NA").lower()
            and record.data[Fields.ENTRYTYPE] != "phdthesis"
        ):
            prior_e_type = record.data[Fields.ENTRYTYPE]
            record.update_field(
                key=Fields.ENTRYTYPE, value="phdthesis", source="unkown_source_prep"
            )
            self.review_manager.report_logger.info(
                f" {record.data[Fields.ID]}".ljust(self._padding, " ")
                + f"Set from {prior_e_type} to phdthesis "
                '("dissertation" in fulltext link)'
            )

        if (
            "thesis" in record.data.get(Fields.FULLTEXT, "NA").lower()
            and record.data[Fields.ENTRYTYPE] != "phdthesis"
        ):
            prior_e_type = record.data[Fields.ENTRYTYPE]
            record.update_field(
                key=Fields.ENTRYTYPE, value="phdthesis", source="unkown_source_prep"
            )
            self.review_manager.report_logger.info(
                f" {record.data[Fields.ID]}".ljust(self._padding, " ")
                + f"Set from {prior_e_type} to phdthesis "
                '("thesis" in fulltext link)'
            )

        if (
            "this thesis" in record.data.get(Fields.ABSTRACT, "NA").lower()
            and record.data[Fields.ENTRYTYPE] != "phdthesis"
        ):
            prior_e_type = record.data[Fields.ENTRYTYPE]
            record.update_field(
                key=Fields.ENTRYTYPE, value="phdthesis", source="unkown_source_prep"
            )
            self.review_manager.report_logger.info(
                f" {record.data[Fields.ID]}".ljust(self._padding, " ")
                + f"Set from {prior_e_type} to phdthesis "
                '("thesis" in abstract)'
            )

    def _format_inproceedings(
        self, *, record: colrev.record.record_prep.PrepRecord
    ) -> None:
        if (
            record.data.get(Fields.BOOKTITLE, FieldValues.UNKNOWN)
            == FieldValues.UNKNOWN
        ):
            return

        if (
            FieldValues.UNKNOWN != record.data[Fields.BOOKTITLE]
            and "inbook" != record.data[Fields.ENTRYTYPE]
        ):
            # pylint: disable=colrev-missed-constant-usage
            record.format_if_mostly_upper(Fields.BOOKTITLE, case="title")

            stripped_btitle = re.sub(r"\d{4}", "", record.data[Fields.BOOKTITLE])
            stripped_btitle = re.sub(r"\d{1,2}th", "", stripped_btitle)
            stripped_btitle = re.sub(r"\d{1,2}nd", "", stripped_btitle)
            stripped_btitle = re.sub(r"\d{1,2}rd", "", stripped_btitle)
            stripped_btitle = re.sub(r"\d{1,2}st", "", stripped_btitle)
            stripped_btitle = re.sub(r"\([A-Z]{3,6}\)", "", stripped_btitle)
            stripped_btitle = stripped_btitle.replace("Proceedings of the", "").replace(
                "Proceedings", ""
            )
            stripped_btitle = stripped_btitle.lstrip().rstrip()
            record.update_field(
                key=Fields.BOOKTITLE,
                value=stripped_btitle,
                source="unkown_source_prep",
                keep_source_if_equal=True,
            )

    def _format_article(self, record: colrev.record.record_prep.PrepRecord) -> None:
        if (
            record.data.get(Fields.JOURNAL, FieldValues.UNKNOWN) != FieldValues.UNKNOWN
            and len(record.data[Fields.JOURNAL]) > 10
            and FieldValues.UNKNOWN != record.data[Fields.JOURNAL]
        ):
            # pylint: disable=colrev-missed-constant-usage
            record.format_if_mostly_upper(Fields.JOURNAL, case="title")

        if record.data.get(Fields.VOLUME, FieldValues.UNKNOWN) != FieldValues.UNKNOWN:
            record.update_field(
                key=Fields.VOLUME,
                value=record.data[Fields.VOLUME].replace("Volume ", ""),
                source="unkown_source_prep",
                keep_source_if_equal=True,
            )

    def _format_fields(self, *, record: colrev.record.record_prep.PrepRecord) -> None:
        """Format fields"""

        if record.data.get(Fields.ENTRYTYPE, "") == "inproceedings":
            self._format_inproceedings(record=record)
        elif record.data.get(Fields.ENTRYTYPE, "") == "article":
            self._format_article(record=record)

        if record.data.get(Fields.AUTHOR, FieldValues.UNKNOWN) != FieldValues.UNKNOWN:
            # fix name format
            if (1 == len(record.data[Fields.AUTHOR].split(" ")[0])) or (
                ", " not in record.data[Fields.AUTHOR]
            ):
                record.update_field(
                    key=Fields.AUTHOR,
                    value=colrev.record.record_prep.PrepRecord.format_author_field(
                        record.data[Fields.AUTHOR]
                    ),
                    source="unkown_source_prep",
                    keep_source_if_equal=True,
                )
            # Replace nicknames in parentheses
            record.data[Fields.AUTHOR] = re.sub(
                r"\([^)]*\)", "", record.data[Fields.AUTHOR]
            )
            record.data[Fields.AUTHOR] = (
                record.data[Fields.AUTHOR].replace("  ", " ").rstrip()
            )

        if record.data.get(Fields.TITLE, FieldValues.UNKNOWN) != FieldValues.UNKNOWN:
            record.format_if_mostly_upper(Fields.TITLE)

        if Fields.PAGES in record.data:
            record.unify_pages_field()
            if (
                not re.match(r"^\d*$", record.data[Fields.PAGES])
                and not re.match(r"^\d*--\d*$", record.data[Fields.PAGES])
                and not re.match(r"^[xivXIV]*--[xivXIV]*$", record.data[Fields.PAGES])
            ):
                self.review_manager.report_logger.info(
                    f" {record.data[Fields.ID]}:".ljust(self._padding, " ")
                    + f"Unusual pages: {record.data[Fields.PAGES]}"
                )

        if (
            Fields.URL in record.data
            and Fields.FULLTEXT in record.data
            and record.data[Fields.URL] == record.data[Fields.FULLTEXT]
        ):
            record.remove_field(key=Fields.FULLTEXT)

        if Fields.LANGUAGE in record.data:
            try:
                self.language_service.unify_to_iso_639_3_language_codes(record=record)
                record.update_field(
                    key=Fields.LANGUAGE,
                    value=record.data[Fields.LANGUAGE],
                    source="unkown_source_prep",
                    keep_source_if_equal=True,
                )
            except colrev_exceptions.InvalidLanguageCodeException:
                del record.data[Fields.LANGUAGE]

    def _remove_redundant_fields(
        self, *, record: colrev.record.record_prep.PrepRecord
    ) -> None:
        if (
            record.data[Fields.ENTRYTYPE] == "article"
            and Fields.JOURNAL in record.data
            and Fields.BOOKTITLE in record.data
        ):
            similarity_journal_booktitle = fuzz.partial_ratio(
                record.data[Fields.JOURNAL].lower(),
                record.data[Fields.BOOKTITLE].lower(),
            )
            if similarity_journal_booktitle / 100 > 0.9:
                record.remove_field(key=Fields.BOOKTITLE)

        if record.data.get(Fields.PUBLISHER, "") in ["researchgate.net"]:
            record.remove_field(key=Fields.PUBLISHER)

        if (
            record.data[Fields.ENTRYTYPE] == "inproceedings"
            and Fields.JOURNAL in record.data
            and Fields.BOOKTITLE in record.data
        ):
            similarity_journal_booktitle = fuzz.partial_ratio(
                record.data[Fields.JOURNAL].lower(),
                record.data[Fields.BOOKTITLE].lower(),
            )
            if similarity_journal_booktitle / 100 > 0.9:
                record.remove_field(key=Fields.JOURNAL)

    def _impute_missing_fields(
        self, *, record: colrev.record.record_prep.PrepRecord
    ) -> None:
        if "date" in record.data and Fields.YEAR not in record.data:
            year = re.search(r"\d{4}", record.data["date"])
            if year:
                record.update_field(
                    key=Fields.YEAR,
                    value=year.group(0),
                    source="unkown_source_prep",
                    keep_source_if_equal=True,
                )

    def _unify_special_characters(
        self, *, record: colrev.record.record_prep.PrepRecord
    ) -> None:
        # Remove html entities
        for field in list(record.data.keys()):
            if field in [Fields.TITLE, Fields.AUTHOR, Fields.JOURNAL, Fields.BOOKTITLE]:
                record.data[field] = re.sub(r"\s+", " ", record.data[field])
                record.data[field] = re.sub(self.HTML_CLEANER, "", record.data[field])

    def prepare(
        self,
        record: colrev.record.record_prep.PrepRecord,
        source: colrev.settings.SearchSource,
    ) -> colrev.record.record.Record:
        """Source-specific preparation for unknown sources"""

        if not record.has_quality_defects() or record.masterdata_is_curated():
            return record

        # we may assign fields heuristically (e.g., to colrev.pubmed.pubmedid)

        self._heuristically_fix_entrytypes(
            record=record,
        )

        self._impute_missing_fields(record=record)

        self._format_fields(record=record)

        self._remove_redundant_fields(record=record)

        self._unify_special_characters(record=record)

        return record
