#! /usr/bin/env python
"""SearchSource: GoogleScholar"""
from __future__ import annotations

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

# pylint: disable=unused-argument
# pylint: disable=duplicate-code


class GoogleScholarSearchSource(
    colrev.package_manager.interfaces.SearchSourceInterface
):
    """GoogleScholar"""

    settings_class = colrev.package_manager.package_settings.DefaultSourceSettings
    endpoint = "colrev.google_scholar"
    # pylint: disable=colrev-missed-constant-usage
    source_identifier = "url"
    search_types = [SearchType.DB]

    ci_supported: bool = Field(default=False)
    heuristic_status = SearchSourceHeuristicStatus.supported

    db_url = "https://scholar.google.de/"

    def __init__(
        self, *, source_operation: colrev.process.operation.Operation, settings: dict
    ) -> None:
        self.search_source = self.settings_class(**settings)
        self.source_operation = source_operation
        self.review_manager = source_operation.review_manager

    @classmethod
    def heuristic(cls, filename: Path, data: str) -> dict:
        """Source heuristic for GoogleScholar"""

        result = {"confidence": 0.0}
        if data.count("https://scholar.google.com/scholar?q=relat") > 0.9 * data.count(
            "\n@"
        ):
            result["confidence"] = 1.0
            return result

        if data.count("{pop0") > 0.9 * data.count("\n@"):
            result["confidence"] = 1.0
            return result

        if (
            data.count("https://scholar.google.com/scholar?q=relat")
            == data.count('"uid": "GS:')
            and data.count('"uid": "GS:') > 0
        ):
            result["confidence"] = 1.0
            return result

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
        """Run a search of GoogleScholar"""

        if self.search_source.search_type == SearchType.DB:
            self.source_operation.run_db_search(  # type: ignore
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

    def load(self, load_operation: colrev.ops.load.Load) -> dict:
        """Load the records from the SearchSource file"""

        if self.search_source.filename.suffix == ".bib":

            def bib_field_mapper(record_dict: dict) -> None:
                if "related" in record_dict:
                    record_dict[f"{self.endpoint}.related"] = record_dict.pop("related")
                if "note" in record_dict:
                    record_dict[f"{self.endpoint}.note"] = record_dict.pop("note")
                if "type" in record_dict:
                    record_dict[f"{self.endpoint}.type"] = record_dict.pop("type")

            records = colrev.loader.load_utils.load(
                filename=self.search_source.filename,
                field_mapper=bib_field_mapper,
                logger=self.review_manager.logger,
            )
            return records

        if self.search_source.filename.suffix == ".json":
            # pylint: disable=too-many-branches
            def json_field_mapper(record_dict: dict) -> None:
                if "related" in record_dict:
                    record_dict[f"{self.endpoint}.related"] = record_dict.pop("related")
                if "note" in record_dict:
                    record_dict[f"{self.endpoint}.note"] = record_dict.pop("note")
                if "type" in record_dict:
                    record_dict[f"{self.endpoint}.type"] = record_dict.pop("type")
                if "article_url" in record_dict:
                    record_dict[f"{self.endpoint}.article_url"] = record_dict.pop(
                        "article_url"
                    )
                if "cites_url" in record_dict:
                    record_dict[f"{self.endpoint}.cites_url"] = record_dict.pop(
                        "cites_url"
                    )
                if "related_url" in record_dict:
                    record_dict[f"{self.endpoint}.related_url"] = record_dict.pop(
                        "related_url"
                    )
                if "fulltext_url" in record_dict:
                    record_dict[f"{self.endpoint}.fulltext_url"] = record_dict.pop(
                        "fulltext_url"
                    )

                if "uid" in record_dict:
                    record_dict[f"{self.endpoint}.uid"] = record_dict.pop("uid")
                if "source" in record_dict:
                    record_dict[Fields.JOURNAL] = record_dict.pop("source")
                if "cites" in record_dict:
                    record_dict[f"{self.endpoint}.cites"] = record_dict.pop("cites")

                record_dict.pop("volume", None)
                record_dict.pop("issue", None)
                record_dict.pop("startpage", None)
                record_dict.pop("endpage", None)
                record_dict.pop("ecc", None)
                record_dict.pop("use", None)
                record_dict.pop("rank", None)
                if "authors" in record_dict:
                    authors = record_dict.pop("authors")
                    for i, author in enumerate(authors):
                        names = author.split(" ")
                        if len(names) > 1:
                            first_name, last_name = names[0], " ".join(names[1:])
                            authors[i] = f"{last_name}, {first_name}"
                        else:
                            authors[i] = names[0]

                    record_dict[Fields.AUTHOR] = " and ".join(authors)

                for key, value in record_dict.items():
                    record_dict[key] = str(value)

            def json_entrytype_setter(record_dict: dict) -> None:
                record_dict[Fields.ENTRYTYPE] = ENTRYTYPES.MISC

            records = colrev.loader.load_utils.load(
                filename=self.search_source.filename,
                entrytype_setter=json_entrytype_setter,
                field_mapper=json_field_mapper,
                # Note: uid not always available.
                unique_id_field="INCREMENTAL",
                logger=self.review_manager.logger,
            )

            return records

        raise NotImplementedError

    def prepare(
        self, record: colrev.record.record.Record, source: colrev.settings.SearchSource
    ) -> colrev.record.record.Record:
        """Source-specific preparation for GoogleScholar"""
        if "cites: https://scholar.google.com/scholar?cites=" in record.data.get(
            "note", ""
        ):
            note = record.data["note"]
            source_field = record.get_field_provenance_source("note")
            record.rename_field(key="note", new_key=Fields.CITED_BY)
            record.update_field(
                key=Fields.CITED_BY,
                value=record.data[Fields.CITED_BY][
                    : record.data[Fields.CITED_BY].find(" cites: ")
                ],
                source="replace_link",
            )
            record.update_field(
                key="cited_by_link",
                value=note[note.find("cites: ") + 7 :],
                append_edit=False,
                source=source_field + "|extract-from-note",
            )
        if Fields.ABSTRACT in record.data:
            # Note: abstracts provided by GoogleScholar are very incomplete
            record.remove_field(key=Fields.ABSTRACT)

        return record
