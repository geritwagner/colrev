#! /usr/bin/env python
"""Default deduplication module for CoLRev"""
from __future__ import annotations

import shutil
from pathlib import Path

import bib_dedupe.cluster
import bib_dedupe.maybe_cases
import pandas as pd
from bib_dedupe.bib_dedupe import block
from bib_dedupe.bib_dedupe import export_maybe
from bib_dedupe.bib_dedupe import import_maybe
from bib_dedupe.bib_dedupe import match
from pydantic import Field

import colrev.package_manager.interfaces
import colrev.package_manager.package_manager
import colrev.package_manager.package_settings
import colrev.record.record
from colrev.constants import Fields
from colrev.constants import RecordState

# pylint: disable=too-few-public-methods


class Dedupe(colrev.package_manager.interfaces.DedupeInterface):
    """Default deduplication"""

    settings_class = colrev.package_manager.package_settings.DefaultSettings
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

    def _move_maybe_file(self) -> None:
        # Note : temporary until we can pass a target path to bib_dedupe
        maybe_file = self.review_manager.path / Path(
            bib_dedupe.maybe_cases.MAYBE_CASES_FILEPATH
        )
        target_path = self.review_manager.paths.dedupe / Path(
            bib_dedupe.maybe_cases.MAYBE_CASES_FILEPATH
        )
        if not maybe_file.is_file():
            return
        shutil.move(str(maybe_file), str(target_path))

    def run_dedupe(self) -> None:
        """Run default dedupe"""

        records = self.review_manager.dataset.load_records_dict()
        records_df = pd.DataFrame.from_dict(records, orient="index")
        records_df = records_df[
            ~(
                records_df[Fields.STATUS].isin(
                    [
                        "md_imported",
                        "md_needs_manual_preparation",
                    ]
                )
            )
        ]
        verbosity_level = 0
        if self.review_manager.verbose_mode:
            verbosity_level = 1
        records_df.loc[
            records_df[Fields.STATUS].isin(
                RecordState.get_post_x_states(state=RecordState.md_processed)
            ),
            "search_set",
        ] = "old_search"

        records_df = self.dedupe_operation.get_records_for_dedupe(
            records_df=records_df, verbosity_level=verbosity_level
        )

        if 0 == records_df.shape[0]:
            return

        deduplication_pairs = block(records_df, verbosity_level=verbosity_level)
        matched_df = match(deduplication_pairs, verbosity_level=verbosity_level)
        matched_df = import_maybe(matched_df)

        if self.dedupe_operation.debug:
            return

        duplicate_id_sets = bib_dedupe.cluster.get_connected_components(matched_df)

        self.dedupe_operation.apply_merges(
            id_sets=duplicate_id_sets, complete_dedupe=True
        )

        self.review_manager.dataset.create_commit(
            msg="Dedupe: merge duplicate records",
        )

        export_maybe(records_df, matched_df=matched_df)
        self._move_maybe_file()
