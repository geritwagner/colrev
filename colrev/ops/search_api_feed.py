#! /usr/bin/env python
"""CoLRev search feed: store and update origin records and update main records."""
from __future__ import annotations

import json
import time
from copy import deepcopy
from random import randint

import colrev.exceptions as colrev_exceptions
import colrev.loader.load_utils
import colrev.loader.load_utils_formatter
import colrev.record.record_merger
from colrev.constants import Colors
from colrev.constants import DefectCodes
from colrev.constants import ENTRYTYPES
from colrev.constants import Fields
from colrev.constants import FieldSet
from colrev.constants import FieldValues
from colrev.writer.write_utils import to_string
from colrev.writer.write_utils import write_file


# Keep in mind the need for lock-mechanisms, e.g., in concurrent prep operations
class SearchAPIFeed:
    """A feed managing results from API searches"""

    # pylint: disable=too-many-instance-attributes
    # pylint: disable=too-many-arguments

    _nr_added: int = 0
    _nr_changed: int = 0

    def __init__(
        self,
        *,
        review_manager: colrev.review_manager.ReviewManager,
        source_identifier: str,
        search_source: colrev.settings.SearchSource,
        update_only: bool,
        prep_mode: bool = False,
    ):
        self.source = search_source
        self.feed_file = search_source.filename

        # Note: the source_identifier identifies records in the search feed.
        # This could be a doi or link or database-specific ID (like WOS accession numbers)
        # The source_identifier can be stored in the main records.bib (it does not have to)
        # The record source_identifier (feed-specific) is used in search
        # or other operations (like prep)
        # In search operations, records are added/updated based on available_ids
        # (which maps source_identifiers to IDs used to generate the colrev_origin)
        # In other operations, records are linked through colrev_origins,
        # i.e., there is no need to store the source_identifier in the main records (redundantly)
        self.source_identifier = source_identifier

        # Note: corresponds to rerun (in search.main() and run_search())
        self.update_only = update_only
        # if update_only, we do not update time_variant_fields
        # (otherwise, fields in recent records would be more up-to-date)

        self.review_manager = review_manager
        self.logger = review_manager.logger
        self.load_formatter = colrev.loader.load_utils_formatter.LoadFormatter()

        self.origin_prefix = self.source.get_origin_prefix()

        self._load_feed()

        self.prep_mode = prep_mode
        if not prep_mode:
            self.records = self.review_manager.dataset.load_records_dict()

    @property
    def source_identifier(self) -> str:
        """Get the source identifier"""
        return self._source_identifier

    # TODO : check where to use validation (all colrev classes?
    # just those that are used by external/new packages!?)
    # Note: the problem was caused by a package directly setting
    # the source_identifier to a non-supported type/value
    @source_identifier.setter
    def source_identifier(self, value: str) -> None:
        if not isinstance(value, str):
            raise ValueError("source_identifier must be a string")
        if not len(value) > 1:
            raise ValueError("source_identifier must be at least 2 characters")
        self._source_identifier = value

    def get_last_updated(self) -> str:
        """Returns the date of the last update (if available) in YYYY-MM-DD format"""
        file = self.feed_file
        if not file.is_file():
            return ""
        return self.review_manager.dataset.get_last_commit_date(self.feed_file)

    def _load_feed(self) -> None:
        if not self.feed_file.is_file():
            self._available_ids = {}
            self._next_incremental_id = 1
            self.feed_records = {}
            return
        self.feed_records = colrev.loader.load_utils.loads(
            load_string=self.feed_file.read_text(encoding="utf8"),
            implementation="bib",
            logger=self.review_manager.logger,
        )
        self._available_ids = {
            x[self.source_identifier]: x[Fields.ID]
            for x in self.feed_records.values()
            if self.source_identifier in x
        }
        self._next_incremental_id = (
            max(
                [
                    int(x[Fields.ID])
                    for x in self.feed_records.values()
                    if x[Fields.ID].isdigit()
                ]
                + [1]
            )
            + 1
        )

    def _set_id(self, record: colrev.record.record.Record) -> None:
        """Set incremental record ID
        If self.source_identifier is in record_dict, it is updated, otherwise added as a new record.
        """

        if self.source_identifier not in record.data:
            raise colrev_exceptions.NotFeedIdentifiableException()

        if record.data[self.source_identifier] in self._available_ids:
            record.data[Fields.ID] = self._available_ids[
                record.data[self.source_identifier]
            ]
        else:
            record.data[Fields.ID] = str(self._next_incremental_id).rjust(6, "0")

    def add_record_to_feed(
        self,
        record: colrev.record.record.Record,
        prev_feed_record: colrev.record.record.Record,
    ) -> bool:
        """Add a record to the feed and set its colrev_origin"""

        self._set_id(record)

        feed_record_dict = record.data.copy()
        added_new = True
        if feed_record_dict[self.source_identifier] in self._available_ids:
            added_new = False
        else:
            self._next_incremental_id += 1
            self._nr_added += 1

        frid = feed_record_dict[Fields.ID]
        self._available_ids[feed_record_dict[self.source_identifier]] = frid

        self._notify_record_forthcoming(
            record=record, prev_feed_record=prev_feed_record
        )

        if self.update_only:
            for key in FieldSet.TIME_VARIANT_FIELDS:
                if frid in self.feed_records:
                    feed_record_dict.pop(key, None)
                    if key in self.feed_records[frid]:
                        feed_record_dict[key] = self.feed_records[frid][key]

        self.feed_records[frid] = feed_record_dict
        if added_new:
            if not self.prep_mode:
                self.logger.info(f"  add record: {record.data[self.source_identifier]}")
            elif (
                self.prep_mode and self.review_manager.verbose_mode
            ):  # pragma: no cover
                self.logger.info(
                    f"  link record: {record.data[self.source_identifier]}"
                )
        return added_new

    def _have_changed(
        self,
        record_a: colrev.record.record.Record,
        record_b: colrev.record.record.Record,
    ) -> bool:

        def tostr_and_load(record: colrev.record.record.Record) -> dict:
            record_dict = deepcopy(record.data)
            bibtex_str = to_string(
                records_dict={record_dict[Fields.ID]: record_dict}, implementation="bib"
            )
            record_dict = list(
                colrev.loader.load_utils.loads(
                    load_string=bibtex_str,
                    implementation="bib",
                    logger=self.review_manager.logger,
                ).values()
            )[0]
            return record_dict

        # To ignore changes introduced by saving/loading the feed-records,
        # we parse and load them in the following.
        record_a_dict = tostr_and_load(record_a)
        record_b_dict = tostr_and_load(record_b)

        # Note : record_a can have more keys (that's ok)
        changed = False
        for key, value in record_b_dict.items():
            if key in FieldSet.PROVENANCE_KEYS + [Fields.ID, Fields.CURATION_ID]:
                continue
            if key not in record_a_dict or record_a_dict[key] != value:
                return True
        return changed

    def _update_record_retract(
        self,
        *,
        record: colrev.record.record.Record,
        main_record: colrev.record.record.Record,
    ) -> bool:
        if record.is_retracted():
            self.review_manager.logger.info(
                f"{Colors.RED}Found paper retract: "
                f"{main_record.data['ID']}{Colors.END}"
            )
            main_record.prescreen_exclude(
                reason=FieldValues.RETRACTED, print_warning=True
            )
            main_record.remove_field(key="warning")
            return True
        return False

    def _notify_record_forthcoming(
        self,
        *,
        record: colrev.record.record.Record,
        prev_feed_record: colrev.record.record.Record,
    ) -> None:

        if self._forthcoming_published(record=record, prev_record=prev_feed_record):
            self.review_manager.logger.info(
                f"{Colors.GREEN}Update published forthcoming paper: "
                f"{record.data['ID']}{Colors.END}"
            )

    def _missing_ignored_field(
        self, main_record: colrev.record.record.Record, key: str
    ) -> bool:
        source = main_record.get_field_provenance_source(key)
        notes = main_record.get_field_provenance_notes(key)
        if (
            source == "colrev_curation.masterdata_restrictions"
            and f"IGNORE:{DefectCodes.MISSING}" in notes
        ):
            return True
        return False

    def _update_record_fields(
        self,
        *,
        record: colrev.record.record.Record,
        main_record: colrev.record.record.Record,
    ) -> None:

        self._update_record_retract(record=record, main_record=main_record)

        if main_record.masterdata_is_curated() and not self.source.is_curated_source():
            return

        for key in list(record.data.keys()):
            if self.update_only and key in FieldSet.TIME_VARIANT_FIELDS:
                continue

            if key in FieldSet.PROVENANCE_KEYS + [Fields.ID, Fields.CURATION_ID]:
                continue

            if key not in main_record.data:
                if self._missing_ignored_field(main_record, key):
                    continue
                colrev.record.record_merger.fuse_fields(
                    main_record, merging_record=record, key=key
                )

            else:
                # Ignore minor changes
                if record.data[key].replace(" - ", ": ") == main_record.data[
                    key
                ].replace(" - ", ": "):
                    continue
                colrev.record.record_merger.fuse_fields(
                    main_record, merging_record=record, key=key
                )

    def _forthcoming_published(
        self,
        *,
        record: colrev.record.record.Record,
        prev_record: colrev.record.record.Record,
    ) -> bool:
        if (
            record.data[Fields.ENTRYTYPE] != ENTRYTYPES.ARTICLE
            or Fields.YEAR not in record.data
            or Fields.YEAR not in prev_record.data
        ):
            return False

        # Option 1: Forthcoming paper published if year is assigned
        if (
            "forthcoming" == prev_record.data[Fields.YEAR]
            and "forthcoming" != record.data[Fields.YEAR]
        ):
            return True

        # Option 2: Forthcoming paper published if volume and number are assigned
        # i.e., no longer UNKNOWN
        if (
            record.data.get(Fields.VOLUME, FieldValues.UNKNOWN) != FieldValues.UNKNOWN
            and prev_record.data.get(Fields.VOLUME, FieldValues.UNKNOWN)
            == FieldValues.UNKNOWN
            and record.data.get(Fields.NUMBER, FieldValues.UNKNOWN)
            != FieldValues.UNKNOWN
            and prev_record.data.get(Fields.VOLUME, FieldValues.UNKNOWN)
            == FieldValues.UNKNOWN
        ):
            return True
        return False

    def _get_main_record(self, colrev_origin: str) -> colrev.record.record.Record:

        main_record_dict: dict = {}
        for record_dict in self.records.values():
            if colrev_origin in record_dict[Fields.ORIGIN]:
                main_record_dict = record_dict
                break

        if main_record_dict == {}:
            raise colrev_exceptions.RecordNotFoundException(
                f"Could not find/update {colrev_origin}"
            )
        return colrev.record.record.Record(main_record_dict)

    def _update_record(
        self,
        *,
        retrieved_record: colrev.record.record.Record,
        prev_feed_record: colrev.record.record.Record,
    ) -> bool:
        """Convenience function to update existing records (main data/records.bib)"""

        colrev_origin = f"{self.origin_prefix}/{retrieved_record.data['ID']}"
        main_record = self._get_main_record(colrev_origin)

        # For consistency (with ops/load):
        self.load_formatter.run(retrieved_record)

        self._update_record_fields(
            record=retrieved_record,
            main_record=main_record,
        )

        if self._forthcoming_published(
            record=retrieved_record, prev_record=prev_feed_record
        ):
            # (notified when updating feed record)
            return True

        if self._have_changed(retrieved_record, prev_feed_record):
            similarity_score = colrev.record.record.Record.get_record_similarity(
                retrieved_record,
                prev_feed_record,
            )
            self._nr_changed += 1
            if similarity_score > 0.98:
                self.review_manager.logger.info(f" check/update {colrev_origin}")
            else:
                dict_diff = retrieved_record.get_diff(prev_feed_record)
                self.review_manager.logger.info(
                    f" {Colors.RED} check/update {colrev_origin} leads to substantial changes "
                    f"({similarity_score}) in {main_record.data['ID']}:{Colors.END}"
                )
                self.review_manager.logger.info(
                    self.review_manager.p_printer.pformat(
                        [x for x in dict_diff if "change" == x[0]]
                    )
                )
            return True
        return False

    def _print_post_run_search_infos(self) -> None:
        """Print the search infos (after running the search)"""
        if self._nr_added > 0:
            self.review_manager.logger.info(
                f"{Colors.GREEN}Retrieved {self._nr_added} records{Colors.END}"
            )
        else:
            self.review_manager.logger.info(
                f"{Colors.GREEN}No additional records retrieved{Colors.END}"
            )

        if self.prep_mode:  # pragma: no cover
            # No need to print the following in prep mode
            # because the main records are not updated/saved
            return

        if self._nr_changed > 0:  # pragma: no cover
            self.review_manager.logger.info(
                f"{Colors.GREEN}Updated {self._nr_changed} records{Colors.END}"
            )
        else:
            if self.records:
                self.review_manager.logger.info(
                    f"{Colors.GREEN}Records ({self.review_manager.paths.RECORDS_FILE})"
                    f" up-to-date{Colors.END}"
                )

    def get_prev_feed_record(
        self, record: colrev.record.record.Record
    ) -> colrev.record.record.Record:
        """Get the previous record dict version"""
        record = deepcopy(record)
        self._set_id(record)
        prev_feed_record_dict = {}
        if record.data[Fields.ID] in self.feed_records:
            prev_feed_record_dict = deepcopy(self.feed_records[record.data[Fields.ID]])
        return colrev.record.record.Record(prev_feed_record_dict)

    def _prep_retrieved_record(
        self, retrieved_record: colrev.record.record.Record
    ) -> None:
        """Prepare the retrieved record for the search feed"""
        for provenance_key in FieldSet.PROVENANCE_KEYS:
            if provenance_key in retrieved_record.data:
                del retrieved_record.data[provenance_key]

    def add_update_record(self, retrieved_record: colrev.record.record.Record) -> bool:
        """Add or update a record in the api_search_feed and records"""
        self._prep_retrieved_record(retrieved_record)
        prev_feed_record = self.get_prev_feed_record(retrieved_record)

        added = self.add_record_to_feed(retrieved_record, prev_feed_record)
        updated = False
        if not self.prep_mode:
            try:
                updated = self._update_record(
                    retrieved_record=retrieved_record.copy(),
                    prev_feed_record=prev_feed_record.copy(),
                )
            except colrev_exceptions.RecordNotFoundException:
                pass

        if self.prep_mode:
            retrieved_record.data[Fields.ORIGIN] = [
                f"{self.origin_prefix}/{retrieved_record.data['ID']}"
            ]
        return added or updated

    def save(self, *, skip_print: bool = False) -> None:
        """Save the feed file and records, printing post-run search infos."""

        if not skip_print and not self.prep_mode:
            self._print_post_run_search_infos()

        if len(self.feed_records) > 0:
            self.feed_file.parents[0].mkdir(parents=True, exist_ok=True)
            write_file(records_dict=self.feed_records, filename=self.feed_file)

            while True:
                try:
                    self.review_manager.load_settings()
                    if self.source.filename.name not in [
                        s.filename.name for s in self.review_manager.settings.sources
                    ]:
                        self.review_manager.settings.sources.append(self.source)
                        self.review_manager.save_settings()

                    self.review_manager.dataset.add_changes(self.feed_file)
                    break
                except (
                    FileExistsError,
                    OSError,
                    json.decoder.JSONDecodeError,
                ):  # pragma: no cover
                    self.review_manager.logger.debug("Wait for git")
                    time.sleep(randint(1, 15))  # nosec

        if not self.prep_mode:
            self.review_manager.dataset.save_records_dict(self.records)
        if not skip_print:
            self._nr_added = 0
            self._nr_changed = 0
