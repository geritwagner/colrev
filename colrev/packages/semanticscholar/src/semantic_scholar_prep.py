#! /usr/bin/env python
"""Consolidation of metadata based on SemanticScholar API as a prep operation"""
from __future__ import annotations

import json

import requests
from pydantic import Field

import colrev.package_manager.interfaces
import colrev.package_manager.package_manager
import colrev.package_manager.package_settings
import colrev.record.record
import colrev.record.record_prep
import colrev.record.record_similarity
from colrev.constants import Fields
from colrev.packages.semanticscholar.src import record_transformer

# pylint: disable=too-few-public-methods
# pylint: disable=duplicate-code


class SemanticScholarPrep(colrev.package_manager.interfaces.PrepInterface):
    """Prepares records based on SemanticScholar metadata"""

    settings_class = colrev.package_manager.package_settings.DefaultSettings
    ci_supported: bool = Field(default=True)

    source_correction_hint = (
        "fill out the online form: "
        + "https://www.semanticscholar.org/faq#correct-error"
    )
    always_apply_changes = False

    def __init__(
        self,
        *,
        prep_operation: colrev.ops.prep.Prep,
        settings: dict,
    ) -> None:
        self.settings = self.settings_class(**settings)
        self.prep_operation = prep_operation
        self.review_manager = prep_operation.review_manager
        _, email = prep_operation.review_manager.get_committer()
        self.headers = {"user-agent": f"{__name__} (mailto:{email})"}
        self.session = prep_operation.review_manager.get_cached_session()

    def _retrieve_record_from_semantic_scholar(
        self,
        record_in: colrev.record.record_prep.PrepRecord,
    ) -> colrev.record.record_prep.PrepRecord:
        """Prepare the record metadata based on SemanticScholar"""

        search_api_url = "https://api.semanticscholar.org/graph/v1/paper/search?query="
        url = search_api_url + record_in.data.get(Fields.TITLE, "").replace(" ", "+")

        # prep_operation.review_manager.logger.debug(url)
        ret = self.session.request(
            "GET", url, headers=self.headers, timeout=self.prep_operation.timeout
        )
        ret.raise_for_status()

        data = json.loads(ret.text)
        items = data["data"]
        if len(items) == 0:
            return record_in
        if "paperId" not in items[0]:
            return record_in

        paper_id = items[0]["paperId"]
        record_retrieval_url = "https://api.semanticscholar.org/v1/paper/" + paper_id
        # prep_operation.review_manager.logger.debug(record_retrieval_url)
        ret_ent = self.session.request(
            "GET",
            record_retrieval_url,
            headers=self.headers,
            timeout=self.prep_operation.timeout,
        )
        ret_ent.raise_for_status()
        item = json.loads(ret_ent.text)

        retrieved_record = record_transformer.dict_to_record(item=item)
        retrieved_record.add_provenance_all(source=record_retrieval_url)

        return retrieved_record.copy_prep_rec()

    def prepare(
        self, record: colrev.record.record_prep.PrepRecord
    ) -> colrev.record.record.Record:
        """Prepare a record based on metadata from SemanticScholar"""

        try:
            retrieved_record = self._retrieve_record_from_semantic_scholar(record)
            if Fields.SEMANTIC_SCHOLAR_ID not in retrieved_record.data:
                return record

            # Remove fields that are not/rarely available before
            # calculating similarity metrics
            orig_record = record.copy_prep_rec()
            for key in [Fields.VOLUME, Fields.NUMBER, Fields.NUMBER, Fields.PAGES]:
                if key in orig_record.data:
                    record.remove_field(key=key)

            if not colrev.record.record_similarity.matches(record, retrieved_record):
                return record

            record.merge(
                retrieved_record,
                default_source=retrieved_record.data[Fields.SEMANTIC_SCHOLAR_ID],
            )

        except (requests.exceptions.RequestException,):
            pass
        return record
