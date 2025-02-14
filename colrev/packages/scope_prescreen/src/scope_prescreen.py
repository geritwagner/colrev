#! /usr/bin/env python
"""Prescreen based on specified scope"""
from __future__ import annotations

import typing

from pydantic import BaseModel
from pydantic import Field

import colrev.env.language_service
import colrev.env.local_index
import colrev.exceptions as colrev_exceptions
import colrev.package_manager.interfaces
import colrev.package_manager.package_manager
import colrev.package_manager.package_settings
import colrev.record.record
from colrev.constants import Fields
from colrev.constants import RecordState


# pylint: disable=too-few-public-methods
# pylint: disable=duplicate-code

# to check: https://asistdl.onlinelibrary.wiley.com/doi/full/10.1002/asi.24816


class ScopePrescreenSettings(
    colrev.package_manager.package_settings.DefaultSettings, BaseModel
):
    """Settings for ScopePrescreen"""

    # pylint: disable=invalid-name
    # pylint: disable=too-many-instance-attributes

    endpoint: str
    ExcludePredatoryJournals: typing.Optional[bool] = True
    TimeScopeFrom: typing.Optional[int] = None
    TimeScopeTo: typing.Optional[int] = None
    LanguageScope: typing.Optional[list] = None
    ExcludeComplementaryMaterials: typing.Optional[bool] = None
    OutletInclusionScope: typing.Optional[dict] = None
    OutletExclusionScope: typing.Optional[dict] = None
    ENTRYTYPEScope: typing.Optional[list] = None
    RequireRankedJournals: typing.Optional[list] = None

    _details = {
        "TimeScopeFrom": {
            "tooltip": "Lower bound for the time scope",
            "min": 1900,
            "max": 2050,
        },
        "TimeScopeTo": {
            "tooltip": "Upper bound for the time scope",
            "min": 1900,
            "max": 2050,
        },
        "LanguageScope": {"tooltip": "Language scope"},
        "ExcludeComplementaryMaterials": {
            "tooltip": "Whether complementary materials (coverpages etc.) are excluded"
        },
        "OutletInclusionScope": {
            "tooltip": "Particular outlets that should be included (exclusively)"
        },
        "OutletExclusionScope": {
            "tooltip": "Particular outlets that should be excluded"
        },
        "ExcludePredatoryJournals": {"tooltip": "Exclude predatory journals"},
        "ENTRYTYPEScope": {
            "tooltip": "Particular ENTRYTYPEs that should be included (exclusively)"
        },
    }


class ScopePrescreen(colrev.package_manager.interfaces.PrescreenInterface):
    """Rule-based prescreen (scope)"""

    settings: ScopePrescreenSettings
    ci_supported: bool = Field(default=True)

    settings_class = ScopePrescreenSettings

    def __init__(
        self,
        *,
        prescreen_operation: colrev.ops.prescreen.Prescreen,
        settings: dict,
    ) -> None:
        if "TimeScopeFrom" in settings:
            settings["TimeScopeFrom"] = int(settings["TimeScopeFrom"])
            assert settings["TimeScopeFrom"] > 1900
            assert settings["TimeScopeFrom"] < 2100
        if "TimeScopeTo" in settings:
            settings["TimeScopeTo"] = int(settings["TimeScopeTo"])
            assert settings["TimeScopeTo"] > 1900
            assert settings["TimeScopeTo"] < 2100
        if "LanguageScope" in settings:
            self.language_service = colrev.env.language_service.LanguageService()
            try:
                self.language_service.validate_iso_639_3_language_codes(
                    lang_code_list=settings["LanguageScope"]
                )
            except colrev_exceptions.InvalidLanguageCodeException as exc:
                raise colrev_exceptions.InvalidSettingsError(
                    msg=f"Invalid LanguageScope in scope_prescreen: {settings['LanguageScope']}"
                    + " (should be iso_639_3 language code)",
                    fix_per_upgrade=False,
                ) from exc

        if "ExcludePredatoryJournals" not in settings:
            settings["ExcludePredatoryJournals"] = True

        self.review_manager = prescreen_operation.review_manager
        self.settings = self.settings_class(**settings)
        self.local_index = colrev.env.local_index.LocalIndex()

        self.title_complementary_materials_keywords = (
            colrev.env.utils.load_complementary_material_keywords()
        )

    def _conditional_prescreen_entrytypes(
        self, record: colrev.record.record.Record
    ) -> None:
        # pylint: disable=unsupported-membership-test
        if self.settings.ENTRYTYPEScope:
            if record.data[Fields.ENTRYTYPE] not in self.settings.ENTRYTYPEScope:
                record.prescreen_exclude(reason="not in ENTRYTYPEScope")

    def _predatory_journal_exclusion(self, record: colrev.record.record.Record) -> None:
        if not self.settings.ExcludePredatoryJournals:
            return
        if Fields.JOURNAL not in record.data:
            return

        rankings = self.local_index.get_journal_rankings(record.data[Fields.JOURNAL])
        if any(x["predatory"] == "yes" for x in rankings):
            record.prescreen_exclude(reason="predatory_journals_beal")

    def _conditional_prescreen_outlets_exclusion(
        self, record: colrev.record.record.Record
    ) -> None:
        if not self.settings.OutletExclusionScope:
            return
        # pylint: disable=unsupported-membership-test
        if "values" not in self.settings.OutletExclusionScope:
            return

        # pylint: disable=unsubscriptable-object
        for resource in self.settings.OutletExclusionScope["values"]:
            for key, value in resource.items():
                if key in record.data and record.data.get(key, "") == value:
                    record.prescreen_exclude(reason="in OutletExclusionScope")

    def _conditional_prescreen_outlets_inclusion(
        self, record: colrev.record.record.Record
    ) -> None:
        if not self.settings.OutletInclusionScope:
            return

        in_outlet_scope = False
        # pylint: disable=unsubscriptable-object
        # pylint: disable=unsupported-membership-test
        if self.settings.OutletInclusionScope:
            if "values" in self.settings.OutletInclusionScope:
                for outlet in self.settings.OutletInclusionScope["values"]:
                    for key, value in outlet.items():
                        if key in record.data and record.data.get(key, "") == value:
                            in_outlet_scope = True
        if not in_outlet_scope:
            record.prescreen_exclude(reason="not in OutletInclusionScope")

    def _conditional_prescreen_timescope(
        self, record: colrev.record.record.Record
    ) -> None:
        if self.settings.TimeScopeFrom:
            if int(record.data.get(Fields.YEAR, 0)) < self.settings.TimeScopeFrom:
                record.prescreen_exclude(
                    reason="not in TimeScopeFrom " f"(>{self.settings.TimeScopeFrom})"
                )

        if self.settings.TimeScopeTo:
            if int(record.data.get(Fields.YEAR, 5000)) > self.settings.TimeScopeTo:
                record.prescreen_exclude(
                    reason="not in TimeScopeTo " f"(<{self.settings.TimeScopeTo})"
                )

    def _conditional_prescreen_complementary_materials(
        self, record: colrev.record.record.Record
    ) -> None:
        if not self.settings.ExcludeComplementaryMaterials:
            return

        if Fields.TITLE in record.data:
            if (
                record.data[Fields.TITLE].lower()
                in self.title_complementary_materials_keywords
            ):
                record.prescreen_exclude(reason="complementary material")

    def _conditional_presecreen_not_in_ranking(
        self, record: colrev.record.record.Record
    ) -> None:
        if not self.settings.RequireRankedJournals:
            return

        if record.data["journal_ranking"] == "not included in a ranking":
            record.set_status(RecordState.rev_prescreen_excluded)

    def _conditional_presecreen_languages(
        self, record: colrev.record.record.Record
    ) -> None:
        if not self.settings.LanguageScope:
            return

        if Fields.LANGUAGE not in record.data:
            return

        # pylint: disable=unsupported-membership-test
        if record.data[Fields.LANGUAGE] not in self.settings.LanguageScope:
            record.prescreen_exclude(reason="not in LanguageScope")

    def _conditional_prescreen(
        self,
        *,
        record_dict: dict,
    ) -> None:
        if record_dict[Fields.STATUS] != RecordState.md_processed:
            return

        # Note : LanguageScope is covered in prep
        # because dedupe cannot handle merges between languages
        record = colrev.record.record.Record(record_dict)

        self._predatory_journal_exclusion(record=record)
        self._conditional_prescreen_entrytypes(record=record)
        self._conditional_prescreen_outlets_inclusion(record=record)
        self._conditional_prescreen_outlets_exclusion(record=record)
        self._conditional_prescreen_timescope(record=record)
        self._conditional_prescreen_complementary_materials(record=record)
        self._conditional_presecreen_not_in_ranking(record=record)
        self._conditional_presecreen_languages(record=record)

        if record.data[Fields.STATUS] == RecordState.rev_prescreen_excluded:
            self.review_manager.report_logger.info(
                f" {record.data[Fields.ID]}".ljust(50, " ")
                + "Prescreen excluded (automatically)"
            )
        elif (
            len(self.review_manager.settings.prescreen.prescreen_package_endpoints) == 1
        ):
            record.set_status(RecordState.rev_prescreen_included)
            self.review_manager.report_logger.info(
                f" {record.data[Fields.ID]}".ljust(50, " ")
                + "Prescreen included (automatically)"
            )

    @classmethod
    def add_endpoint(cls, *, operation: colrev.ops.search.Search, params: str) -> None:
        """Add  the scope_prescreen as an endpoint"""

        if not params:
            print("Interactive mode not yet implemented.")
            return

        def parse_value(
            key: str, value: str
        ) -> typing.Union[str, int, bool, list, dict]:
            if key == "ExcludePredatoryJournals":
                return_value = value == "True"
            elif key in ["TimeScopeTo", "TimeScopeFrom"]:
                return_value = int(value)  # type: ignore
            elif key == "LanguageScope":
                return_value = value.split(",")  # type: ignore
            elif key == "ExcludeComplementaryMaterials":
                return_value = value == "True"
            elif key == "OutletInclusionScope" or key == "OutletExclusionScope":
                return_value = {  # type: ignore
                    x.split(":")[0]: x.split(":")[1] for x in value.split(",")
                }
            elif key == "ENTRYTYPEScope":
                return_value = value.split(",")  # type: ignore
            elif key == "RequireRankedJournals":
                return_value = value.split(",")  # type: ignore
            else:
                return_value = value  # type: ignore
            return return_value

        params_dict: dict[str, typing.Any] = {}
        for p_el in params.split(";"):
            key, value = p_el.split("=")
            params_dict[key] = parse_value(key, value)

        for (
            existing_scope_prescreen
        ) in operation.review_manager.settings.prescreen.prescreen_package_endpoints:
            if existing_scope_prescreen["endpoint"] != "colrev.scope_prescreen":
                continue
            operation.review_manager.logger.info(
                "Integrating into existing colrev.scope_prescreen"
            )
            for key, value in params_dict.items():
                if (
                    key in existing_scope_prescreen
                    and existing_scope_prescreen[key] != value
                ):
                    operation.review_manager.logger.info(
                        f"Replacing {key} ({existing_scope_prescreen[key]} -> {value})"
                    )

                existing_scope_prescreen[key] = parse_value(key, value)
            return

        # Insert (if not added before)
        operation.review_manager.settings.prescreen.prescreen_package_endpoints.insert(
            0, {**{"endpoint": "colrev.scope_prescreen"}, **params_dict}
        )

    def run_prescreen(
        self,
        records: dict,
        split: list,  # pylint: disable=unused-argument
    ) -> dict:
        """Prescreen records based on the scope parameters"""

        for record_dict in records.values():
            self._conditional_prescreen(
                record_dict=record_dict,
            )

        self.review_manager.dataset.save_records_dict(records)
        self.review_manager.dataset.create_commit(
            msg="Pre-screen (scope)",
            manual_author=False,
        )
        return records
