#! /usr/bin/env python
"""SearchSource: CoLRev project"""
from __future__ import annotations

import shutil
import tempfile
from copy import deepcopy
from pathlib import Path

import pandas as pd
import pandasql as ps
from git import Repo
from pandasql.sqldf import PandaSQLException
from pydantic import Field
from tqdm import tqdm

import colrev.exceptions as colrev_exceptions
import colrev.package_manager.interfaces
import colrev.package_manager.package_manager
import colrev.package_manager.package_settings
import colrev.record.record
from colrev.constants import Fields
from colrev.constants import FieldSet
from colrev.constants import SearchSourceHeuristicStatus
from colrev.constants import SearchType

# pylint: disable=unused-argument
# pylint: disable=duplicate-code


class ColrevProjectSearchSource(
    colrev.package_manager.interfaces.SearchSourceInterface
):
    """CoLRev projects"""

    settings_class = colrev.package_manager.package_settings.DefaultSourceSettings

    source_identifier = "colrev_project_identifier"
    search_types = [SearchType.API]
    endpoint = "colrev.colrev_project"

    ci_supported: bool = Field(default=True)
    heuristic_status = SearchSourceHeuristicStatus.supported

    def __init__(
        self, *, source_operation: colrev.process.operation.Operation, settings: dict
    ) -> None:
        self.search_source = self.settings_class(**settings)
        self.review_manager = source_operation.review_manager

    # pylint: disable=colrev-missed-constant-usage
    def _validate_source(self) -> None:
        """Validate the SearchSource (parameters etc.)"""
        source = self.search_source

        self.review_manager.logger.debug(f"Validate SearchSource {source.filename}")

        if "scope" not in source.search_parameters:
            raise colrev_exceptions.InvalidQueryException(
                "scope required in search_parameters"
            )
        if "url" not in source.search_parameters["scope"]:
            raise colrev_exceptions.InvalidQueryException(
                "url field required in search_parameters"
            )

        self.review_manager.logger.debug(f"SearchSource {source.filename} validated")

    # pylint: disable=colrev-missed-constant-usage
    @classmethod
    def add_endpoint(
        cls,
        operation: colrev.ops.search.Search,
        params: str,
    ) -> colrev.settings.SearchSource:
        """Add SearchSource as an endpoint (based on query provided to colrev search --add )"""

        # Always API search

        filename = operation.get_unique_filename(file_path_string=params.split("/")[-1])
        search_source = colrev.settings.SearchSource(
            endpoint=cls.endpoint,
            filename=filename,
            search_type=SearchType.OTHER,
            search_parameters={"scope": {"url": params}},
            comment="",
        )
        operation.add_source_and_search(search_source)
        return search_source

    def _load_records_to_import(self, *, project_url: str, project_name: str) -> dict:
        temp_path = tempfile.gettempdir() / Path(project_name)
        temp_path.mkdir()
        Repo.clone_from(project_url, temp_path, depth=1)

        try:
            project_review_manager = self.review_manager.get_connecting_review_manager(
                path_str=str(temp_path)
            )
        except colrev_exceptions.RepoSetupError as exc:
            raise colrev_exceptions.ServiceNotAvailableException(
                f"Error retrieving records from colrev project {project_url} ({exc})"
            ) from exc

        # remote_url = project_review_manager.dataset.get_remote_url()
        # if remote_url != "NA":
        #     project_identifier = remote_url.rstrip(".git")

        project_review_manager.get_load_operation(
            notify_state_transition_operation=False,
        )
        # pylint: disable=colrev-missed-constant-usage
        self.review_manager.logger.info(
            f'Loading records from {self.search_source.search_parameters["scope"]["url"]}'
        )
        records = project_review_manager.dataset.load_records_dict()
        shutil.rmtree(temp_path)
        return records

    def _save_field_dict(self, *, input_dict: dict, input_key: str) -> list:
        list_to_return = []
        assert input_key in [Fields.MD_PROV, Fields.D_PROV]
        if input_key == Fields.MD_PROV:
            for key, value in input_dict.items():
                if isinstance(value, dict):
                    formated_node = ",".join(
                        sorted(e for e in value["note"].split(",") if "" != e)
                    )
                    list_to_return.append(f"{key}:{value['source']};{formated_node};")

        elif input_key == Fields.D_PROV:
            for key, value in input_dict.items():
                if isinstance(value, dict):
                    list_to_return.append(f"{key}:{value['source']};{value['note']};")

        return list_to_return

    def _get_stringified_record(self, *, record: dict) -> dict:
        data_copy = deepcopy(record)

        def list_to_str(*, val: list) -> str:
            return ("\n" + " " * 36).join([f.rstrip() for f in val])

        for key in [Fields.ORIGIN]:
            if key in data_copy:
                if key in [Fields.ORIGIN]:
                    data_copy[key] = sorted(list(set(data_copy[key])))
                for ind, val in enumerate(data_copy[key]):
                    if len(val) > 0:
                        if val[-1] != ";":
                            data_copy[key][ind] = val + ";"
                data_copy[key] = list_to_str(val=data_copy[key])

        for key in [Fields.MD_PROV, Fields.D_PROV]:
            if key in data_copy:
                if isinstance(data_copy[key], dict):
                    data_copy[key] = self._save_field_dict(
                        input_dict=data_copy[key], input_key=key
                    )
                if isinstance(data_copy[key], list):
                    data_copy[key] = list_to_str(val=data_copy[key])

        return data_copy

    def search(self, rerun: bool) -> None:
        """Run a search of a CoLRev project"""

        # pylint: disable=too-many-locals
        # pdf_get_operation =
        # self.review_manager.get_pdf_get_operation(notify_state_transition_operation=False)

        self._validate_source()

        colrev_project_search_feed = self.search_source.get_api_feed(
            review_manager=self.review_manager,
            source_identifier=self.source_identifier,
            update_only=(not rerun),
        )
        # pylint: disable=colrev-missed-constant-usage
        project_url = self.search_source.search_parameters["scope"]["url"]
        project_name = project_url.split("/")[-1].rstrip(".git")
        records_to_import = self._load_records_to_import(
            project_url=project_url, project_name=project_name
        )

        keys_to_drop = [
            Fields.MD_PROV,
            Fields.D_PROV,
            "colrev_id",
            Fields.STATUS,
            Fields.ORIGIN,
            Fields.SCREENING_CRITERIA,
            Fields.GROBID_VERSION,
        ]

        self.review_manager.logger.info("Importing selected records")
        for record_to_import in tqdm(list(records_to_import.values())):
            if "condition" in self.search_source.search_parameters["scope"]:
                res = []
                try:
                    stringified_copy = self._get_stringified_record(
                        record=record_to_import
                    )
                    stringified_copy = {k: str(v) for k, v in stringified_copy.items()}
                    # pylint: disable=possibly-unused-variable
                    rec_df = pd.DataFrame.from_records([stringified_copy])
                    query_select = "SELECT * FROM rec_df WHERE"
                    query = (
                        f"{query_select} "
                        + f"{self.search_source.search_parameters['scope']['condition']}"
                    )
                    res = ps.sqldf(query, locals())
                except PandaSQLException:
                    pass

                if len(res) == 0:
                    continue

            # Note : we need local paths for the PDFs
            # to get local_paths, we need to lookup in the registry.json
            # otherwise, we may also consider retrieving PDFs from local_index automatically
            # if Fields.FILE in record_to_import:
            #     record_to_import[Fields.FILE] = (
            #         Path(self.search_source.search_parameters["scope"][Fields.URL])
            #         / record_to_import[Fields.FILE]
            #     )

            #     pdf_get_operation.import_pdf(
            #         record=colrev.record.record.Record(record_to_import)
            #     )

            record_to_import["colrev_project_identifier"] = (
                f"{project_url}#{record_to_import['ID']}"
            )
            record_to_import = {
                k: v for k, v in record_to_import.items() if k not in keys_to_drop
            }

            try:
                colrev_project_search_feed.add_update_record(
                    retrieved_record=colrev.record.record.Record(record_to_import),
                )

            except colrev_exceptions.NotFeedIdentifiableException:
                print("not identifiable")
                continue

        colrev_project_search_feed.save()

    def prep_link_md(
        self,
        prep_operation: colrev.ops.prep.Prep,
        record: colrev.record.record.Record,
        save_feed: bool = True,
        timeout: int = 10,
    ) -> colrev.record.record.Record:
        """Not implemented"""
        return record

    @classmethod
    def heuristic(cls, filename: Path, data: str) -> dict:
        """Source heuristic for CoLRev projects"""

        result = {"confidence": 0.0}
        if "colrev_project" in data:
            result["confidence"] = 1.0

        return result

    def load(self, load_operation: colrev.ops.load.Load) -> dict:
        """Load the records from the SearchSource file"""

        if self.search_source.filename.suffix == ".bib":
            records = colrev.loader.load_utils.load(
                filename=self.search_source.filename,
                logger=self.review_manager.logger,
            )
            for record_id in records:
                records[record_id] = {
                    k: v
                    for k, v in records[record_id].items()
                    if k not in FieldSet.PROVENANCE_KEYS + [Fields.SCREENING_CRITERIA]
                }

            return records

        raise NotImplementedError

    def prepare(
        self, record: colrev.record.record.Record, source: colrev.settings.SearchSource
    ) -> colrev.record.record.Record:
        """Source-specific preparation for CoLRev projects"""

        return record
