#! /usr/bin/env python
"""Importer"""
from pathlib import Path

import inquirer
import pandas as pd
from bib_dedupe.bib_dedupe import merge

import colrev.review_manager
from colrev.constants import Fields
from colrev.constants import RecordState


def _get_import_type() -> str:
    questions = [
        inquirer.List(
            "decision",
            message="Select a decision type",
            choices=["prescreening decisions", "screening decisions"],
        ),
    ]

    answers = inquirer.prompt(questions)
    import_type = answers["decision"]
    return import_type


def _get_import_path() -> Path:
    def validate_path(_, path: str) -> bool:  # type: ignore
        # pylint: disable=broad-exception-caught
        if not Path(path).is_dir() and not Path(path).is_symlink():
            print("No directory found at the specified path.")
            return False

        try:
            colrev.review_manager.ReviewManager(path_str=path)
        except Exception as e:
            print(e)
            return False

        return True

    path_question = [
        inquirer.Path(
            "path",
            message="Enter the path to import data from",
            validate=validate_path,
        ),
    ]

    path_answer = inquirer.prompt(path_question)
    return Path(path_answer["path"])


def _get_mapping(records: dict, *, other_records: dict) -> dict:

    records_df = pd.DataFrame(records.values())
    other_records_df = pd.DataFrame(other_records.values())

    other_records_df[Fields.ID] = "other_" + other_records_df[Fields.ID].astype(str)

    # set search_set column to prevent duplicates within sets
    records_df["search_set"] = "original"
    other_records_df["search_set"] = "other"

    combined_records_df = pd.concat([records_df, other_records_df], ignore_index=True)

    merged_df = merge(combined_records_df)
    merged_df = merged_df[merged_df["origin"].str.contains(";")]
    origins = merged_df["origin"].tolist()

    # id: other_id
    mapping = {}
    for origin in origins:
        if origin.count(";") != 1:
            print(origin)
            continue
        o_1, o_2 = origin.split(";")
        if o_1.startswith("other_") and not o_2.startswith("other_"):
            mapping[o_2] = o_1.replace("other_", "")
        elif o_2.startswith("other_") and not o_1.startswith("other_"):
            mapping[o_1] = o_2.replace("other_", "")
        else:
            print(origin)
    return mapping


def _import_prescreening_decisions(
    review_manager: colrev.review_manager.ReviewManager,
    *,
    other_review_manager: colrev.review_manager.ReviewManager,
) -> None:
    colrev.ops.check.CheckOperation(other_review_manager)
    other_records = other_review_manager.dataset.load_records_dict()
    review_manager.get_prescreen_operation()
    records = review_manager.dataset.load_records_dict()

    print(f"Records in current repository: {len(records)}")

    print("Matching strategy: bib-dedupe match")

    # TODO : allow strategies: same include/exclude decisions, only include / only exclude

    mapping = _get_mapping(records, other_records=other_records)
    for original_id, other_id in mapping.items():
        other_prescreen_included = other_records[other_id][Fields.STATUS] not in [
            RecordState.rev_prescreen_excluded,
            RecordState.md_retrieved,
            RecordState.md_imported,
            RecordState.md_needs_manual_preparation,
            RecordState.md_prepared,
            RecordState.md_processed,
        ]
        if other_prescreen_included:
            records[original_id][Fields.STATUS] = RecordState.rev_prescreen_included
        else:
            records[original_id][Fields.STATUS] = RecordState.rev_prescreen_excluded

    print(f"Import from {len(other_records)} records")
    print(f"Prescreening decisions available: {len(mapping)}")
    print(f"Matching rate: {len(mapping)/len(records)}")

    review_manager.dataset.save_records_dict(records)
    review_manager.dataset.create_commit(
        msg=f"Import prescreening decisions from repository ({other_review_manager.path.name})",
        manual_author=False,
    )


def main() -> None:
    """Main function for import"""
    review_manager = colrev.review_manager.ReviewManager()
    import_type = _get_import_type()
    import_path = _get_import_path()

    # import_type = 'prescreening decisions'
    # import_path = Path("...")

    other_review_manager = colrev.review_manager.ReviewManager(
        path_str=import_path.as_posix()
    )

    print(f"Import {import_type} from {import_path}")

    if import_type == "prescreening decisions":
        _import_prescreening_decisions(
            review_manager, other_review_manager=other_review_manager
        )
