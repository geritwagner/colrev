#! /usr/bin/env python
"""SearchSource: Scopus"""
from __future__ import annotations

from pathlib import Path

from pydantic import Field

import colrev.loader.bib
import colrev.package_manager.interfaces
import colrev.package_manager.package_manager
import colrev.package_manager.package_settings
import colrev.record.record
from colrev.constants import ENTRYTYPES
from colrev.constants import Fields
from colrev.constants import SearchSourceHeuristicStatus
from colrev.constants import SearchType

# pylint: disable=unused-argument
# pylint: disable=duplicate-code


class ScopusSearchSource(colrev.package_manager.interfaces.SearchSourceInterface):
    """Scopus"""

    settings_class = colrev.package_manager.package_settings.DefaultSourceSettings
    endpoint = "colrev.scopus"
    # pylint: disable=colrev-missed-constant-usage
    source_identifier = "url"
    search_types = [SearchType.DB]

    ci_supported: bool = Field(default=False)
    heuristic_status = SearchSourceHeuristicStatus.supported

    db_url = "https://www.scopus.com/search/form.uri?display=advanced"

    def __init__(
        self, *, source_operation: colrev.process.operation.Operation, settings: dict
    ) -> None:
        self.review_manager = source_operation.review_manager
        self.search_source = self.settings_class(**settings)
        self.quality_model = self.review_manager.get_qm()
        self.operation = source_operation

    @classmethod
    def heuristic(cls, filename: Path, data: str) -> dict:
        """Source heuristic for Scopus"""

        result = {"confidence": 0.0}
        if "source={Scopus}," in data:
            result["confidence"] = 1.0
            return result

        if "www.scopus.com" in data:
            if data.count("www.scopus.com") >= data.count("\n@"):
                result["confidence"] = 1.0

        return result

    @classmethod
    def add_endpoint(
        cls,
        operation: colrev.ops.search.Search,
        params: str,
    ) -> colrev.settings.SearchSource:
        """Add SearchSource as an endpoint (based on query provided to colrev search --add )"""

        search_source = operation.create_db_source(
            search_source_cls=cls,
            params={},
        )
        operation.add_source_and_search(search_source)
        return search_source

    def search(self, rerun: bool) -> None:
        """Run a search of Scopus"""

        if self.search_source.search_type == SearchType.DB:
            self.operation.run_db_search(  # type: ignore
                search_source_cls=self.__class__,
                source=self.search_source,
            )
            return

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

    def _load_bib(self) -> dict:

        def entrytype_setter(record_dict: dict) -> None:
            if "document_type" in record_dict:
                if record_dict["document_type"] == "Conference Paper":
                    record_dict[Fields.ENTRYTYPE] = ENTRYTYPES.INPROCEEDINGS

                elif record_dict["document_type"] == "Conference Review":
                    record_dict[Fields.ENTRYTYPE] = ENTRYTYPES.PROCEEDINGS

                elif record_dict["document_type"] == "Article":
                    record_dict[Fields.ENTRYTYPE] = ENTRYTYPES.ARTICLE

        def field_mapper(record_dict: dict) -> None:

            if record_dict[Fields.ENTRYTYPE] in [
                ENTRYTYPES.INPROCEEDINGS,
                ENTRYTYPES.PROCEEDINGS,
            ]:
                record_dict[Fields.BOOKTITLE] = record_dict.pop(Fields.JOURNAL, None)

            if record_dict[Fields.ENTRYTYPE] == ENTRYTYPES.BOOK:
                if (
                    Fields.JOURNAL in record_dict
                    and Fields.BOOKTITLE not in record_dict
                ):
                    record_dict[Fields.BOOKTITLE] = record_dict.pop(Fields.TITLE, None)
                    record_dict[Fields.TITLE] = record_dict.pop(Fields.JOURNAL, None)

            if "art_number" in record_dict:
                record_dict[f"{self.endpoint}.art_number"] = record_dict.pop(
                    "art_number"
                )
            if "note" in record_dict:
                record_dict[f"{self.endpoint}.note"] = record_dict.pop("note")
            if "document_type" in record_dict:
                record_dict[f"{self.endpoint}.document_type"] = record_dict.pop(
                    "document_type"
                )
            if "source" in record_dict:
                record_dict[f"{self.endpoint}.source"] = record_dict.pop("source")

            if "Start_Page" in record_dict and "End_Page" in record_dict:
                if (
                    record_dict["Start_Page"] != "nan"
                    and record_dict["End_Page"] != "nan"
                ):
                    record_dict[Fields.PAGES] = (
                        record_dict["Start_Page"] + "--" + record_dict["End_Page"]
                    )
                    record_dict[Fields.PAGES] = record_dict[Fields.PAGES].replace(
                        ".0", ""
                    )
                    del record_dict["Start_Page"]
                    del record_dict["End_Page"]

        colrev.loader.bib.run_fix_bib_file(
            self.search_source.filename, logger=self.review_manager.logger
        )
        records = colrev.loader.load_utils.load(
            filename=self.search_source.filename,
            unique_id_field="ID",
            entrytype_setter=entrytype_setter,
            field_mapper=field_mapper,
            logger=self.review_manager.logger,
        )

        return records

    def load(self, load_operation: colrev.ops.load.Load) -> dict:
        """Load the records from the SearchSource file"""

        if self.search_source.filename.suffix == ".bib":
            return self._load_bib()

        raise NotImplementedError

    def prepare(
        self, record: colrev.record.record.Record, source: colrev.settings.SearchSource
    ) -> colrev.record.record.Record:
        """Source-specific preparation for Scopus"""

        return record
