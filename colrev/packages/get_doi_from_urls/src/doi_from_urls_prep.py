#! /usr/bin/env python
"""Retrieving DOIs from a papers website/url as a prep operation"""
from __future__ import annotations

import collections
import re
from sqlite3 import OperationalError

import requests
from pydantic import Field

import colrev.exceptions as colrev_exceptions
import colrev.package_manager.interfaces
import colrev.package_manager.package_manager
import colrev.package_manager.package_settings
import colrev.packages.doi_org.src.doi_org as doi_connector
import colrev.record.record
import colrev.record.record_prep
import colrev.record.record_similarity
from colrev.constants import Fields

# pylint: disable=too-few-public-methods
# pylint: disable=duplicate-code


class DOIFromURLsPrep(colrev.package_manager.interfaces.PrepInterface):
    """Prepares records by retrieving its DOI from the website (URL)"""

    settings_class = colrev.package_manager.package_settings.DefaultSettings

    ci_supported: bool = Field(default=True)

    source_correction_hint = "check with the developer"
    always_apply_changes = False

    # https://www.crossref.org/blog/dois-and-matching-regular-expressions/
    doi_regex = re.compile(r"10\.\d{4,9}/[-._;/:A-Za-z0-9]*")

    def __init__(
        self,
        *,
        prep_operation: colrev.ops.prep.Prep,
        settings: dict,
    ) -> None:
        self.settings = self.settings_class(**settings)
        self.prep_operation = prep_operation
        self.review_manager = prep_operation.review_manager
        self.same_record_type_required = (
            prep_operation.review_manager.settings.is_curated_masterdata_repo()
        )
        try:
            self.session = prep_operation.review_manager.get_cached_session()
        except OperationalError as exc:
            raise colrev_exceptions.ServiceNotAvailableException(
                dep="sqlite-requests-cache"
            ) from exc
        _, self.email = prep_operation.review_manager.get_committer()

    def prepare(
        self, record: colrev.record.record_prep.PrepRecord
    ) -> colrev.record.record.Record:
        """Prepare the record by retrieving its DOI from the website (url) if available"""

        if (Fields.URL not in record.data and Fields.FULLTEXT not in record.data) or (
            Fields.DOI in record.data
        ):
            return record

        try:
            url = record.data.get(Fields.URL, record.data.get(Fields.FULLTEXT, "NA"))
            headers = {"user-agent": f"{__name__}  " f"(mailto:{self.email})"}
            ret = self.session.request(
                "GET", url, headers=headers, timeout=self.prep_operation.timeout
            )
            ret.raise_for_status()
            res = re.findall(self.doi_regex, ret.text)
            if not res:
                return record

            if len(res) == 1:
                ret_dois = [(res[0], 1)]
            else:
                counter = collections.Counter(res)
                ret_dois = counter.most_common()

            if not ret_dois:
                return record

            doi, _ = ret_dois[0]

            retrieved_record_dict = {
                Fields.DOI: doi.upper(),
                Fields.ID: record.data[Fields.ID],
            }
            retrieved_record = colrev.record.record_prep.PrepRecord(
                retrieved_record_dict
            )
            doi_connector.DOIConnector.retrieve_doi_metadata(
                review_manager=self.review_manager,
                record=retrieved_record,
                timeout=self.prep_operation.timeout,
            )

            if not colrev.record.record_similarity.matches(record, retrieved_record):
                return record

            record.merge(retrieved_record, default_source=url)

        except (
            requests.exceptions.RequestException,
            colrev_exceptions.RecordNotParsableException,
        ):
            pass
        return record
