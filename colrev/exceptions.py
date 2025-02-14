#! /usr/bin/env python
"""Exceptions of CoLRev."""
from __future__ import annotations

import typing
from pathlib import Path

from colrev.constants import Colors


class CoLRevException(Exception):
    """
    Base class for all exceptions raised by this package
    """


class RepoSetupError(CoLRevException):
    """
    The project files are not properly set up as a CoLRev project.
    """

    lr_docs = (
        "https://colrev-environment.github.io/colrev/manual/problem_formulation.html"
    )

    def __init__(self, msg: typing.Optional[str] = None) -> None:
        try:
            Path(".report.log").unlink(missing_ok=True)
        except PermissionError:
            pass
        if msg:
            self.message = f" {msg}"
        elif any(Path(Path.cwd()).iterdir()):
            self.message = (
                "Not a CoLRev repository containing the required files "
                "(settings.json, etc.)."
            )

        else:
            self.message = (
                "Not yet a CoLRev repository. "
                "To initialize a CoLRev repository (project), run:\n\n"
                f"   {Colors.ORANGE}colrev init --type {Colors.END}literature_review\n\n"
                f"Instead of {Colors.ORANGE}literature_review{Colors.END},"
                " you can use any of the following review type:\n\n"
                "  - narrative_review              : "
                "includes a manuscript\n"
                "  - scoping_review                : "
                "includes a manuscript, and a prisma diagram\n"
                "  - descriptive_review            : "
                "includes a manuscript, and a prisma diagram\n"
                "  - critical_review               : "
                "includes a manuscript, and a prisma diagram\n"
                "  - theoretical_review            : "
                "includes a manuscript\n"
                "  - conceptual_review             : "
                "includes a manuscript\n"
                "  - qualitative_systematic_review : "
                "includes a manuscript, data extraction tables, and a prisma diagram\n"
                "  - meta_analysis                 : "
                "includes a manuscript, data extraction tables, and a prisma diagram\n"
                "  - scientometric                 : "
                "includes a manuscript\n"
                "\nMore details about the differences between review types "
                f"are available at\n{self.lr_docs}"
            )

        super().__init__(self.message)


class CoLRevUpgradeError(CoLRevException):
    """
    The version of the local CoLRev package does not match with the CoLRev version
    used to create the latest commit in the project.
    An explicit upgrade of the data structures is needed.
    """

    def __init__(self, old: str, new: str) -> None:
        self.message = (
            f"Detected upgrade from {old} to {new}. To upgrade use\n     "
            f"{Colors.ORANGE}colrev upgrade{Colors.END}"
        )
        super().__init__(self.message)


class ReviewManagerNotNotifiedError(CoLRevException):
    """
    The ReviewManager was not notified about the operation.
    """

    def __init__(self) -> None:
        self.message = (
            "Create an operation and inform the review manager in advance"
            + " to avoid conflicts."
        )
        super().__init__(self.message)


class ParameterError(CoLRevException):
    """
    An invalid parameter was passed to CoLRev.
    """

    def __init__(self, *, parameter: str, value: str, options: list) -> None:
        options_string = "\n  - ".join(sorted(options))
        self.message = f"Invalid parameter {parameter}: {value}."
        if options:
            self.message += f"\n Options:\n  - {options_string}"
        super().__init__(self.message)


class InvalidSettingsError(CoLRevException):
    """
    Invalid value in SETTINGS_FILE.
    """

    def __init__(self, *, msg: str, fix_per_upgrade: bool = True) -> None:
        msg = f"Error in SETTINGS_FILE: {msg}"
        if fix_per_upgrade:
            msg += (
                "\nTo solve this, use\n  " f"{Colors.ORANGE}colrev upgrade{Colors.END}"
            )
        self.message = msg
        super().__init__(self.message)


# Valid commits, data structures, and repo states


class UnstagedGitChangesError(CoLRevException):
    """
    Unstaged git changes were found although a clean repository is required.
    """

    def __init__(self, changedFiles: list) -> None:
        self.message = (
            f"changes not yet staged: {changedFiles} (use git add . or stash)"
        )
        super().__init__(self.message)


class CleanRepoRequiredError(CoLRevException):
    """
    A clean git repository would be required.
    """

    def __init__(self, changedFiles: list, ignore_pattern: str) -> None:
        self.message = (
            "clean repository required (use git commit, discard or stash "
            + f"{changedFiles}; ignore_pattern={ignore_pattern})."
        )
        super().__init__(self.message)


class GitConflictError(CoLRevException):
    """
    There are git conflicts to be resolved before resuming operations.
    """

    def __init__(self, path: Path) -> None:
        self.message = f"please resolve git conflict in {path}"
        super().__init__(self.message)


class DirtyRepoAfterProcessingError(CoLRevException):
    """
    The git repository was not clean after completing the operation.
    """

    def __init__(self, msg: str) -> None:
        self.message = msg
        super().__init__(self.message)


class GitNotAvailableError(CoLRevException):
    """
    Git is currently not available.
    """

    def __init__(self) -> None:
        self.message = "Git is currently not available (remove .git/index.lock exists)."
        super().__init__(self.message)


class AppendOnlyViolation(Exception):
    """Invalid changes to a file in append-only mode."""

    def __init__(self, msg: str) -> None:
        self.message = msg
        super().__init__(self.message)


class ProcessOrderViolation(CoLRevException):
    """The process triggered dooes not have priority"""

    def __init__(
        self,
        operations_type: str,
        required_state: str,
        violating_records: list,
    ) -> None:
        self.message = (
            f" {operations_type}() requires all records to have at least "
            + f"'{required_state}', but there are records with {violating_records}."
        )
        super().__init__(self.message)


class StatusTransitionError(CoLRevException):
    """An invalid status transition was observed"""

    def __init__(self, msg: str) -> None:
        self.message = f" {msg}"
        super().__init__(self.message)


class NoRecordsError(CoLRevException):
    """The operation cannot be started because no records have been imported yet."""

    def __init__(self) -> None:
        self.message = "no records imported yet"
        super().__init__(self.message)


class FieldValueError(CoLRevException):
    """An error in field values was detected (in the main records)."""

    def __init__(self, msg: str) -> None:
        self.message = f" {msg}"
        super().__init__(self.message)


class MissingRecordQualityRuleSpecification(CoLRevException):
    """A quality rule is missing."""

    def __init__(self, msg: str) -> None:
        self.message = msg
        super().__init__(self.message)


class StatusFieldValueError(CoLRevException):
    """An error in the status field values was detected."""

    def __init__(self, record: str, status_type: str, status_value: str) -> None:
        self.message = f"{status_type} set to '{status_value}' in {record}."
        super().__init__(self.message)


class OriginError(CoLRevException):
    """An error in the colrev_origin field values was detected."""

    def __init__(self, msg: str) -> None:
        self.message = f" {msg}"
        super().__init__(self.message)


class DuplicateIDsError(CoLRevException):
    """Duplicate IDs were detected."""

    def __init__(self, msg: str) -> None:
        self.message = f" {msg}"
        super().__init__(self.message)


class NotEnoughDataToIdentifyException(CoLRevException):
    """The meta-data is not sufficiently complete to identify the record."""

    def __init__(
        self,
        *,
        msg: typing.Optional[str] = None,
        missing_fields: typing.Optional[list] = None,
    ) -> None:
        self.message = msg
        self.missing_fields = missing_fields
        super().__init__(self.message)


class NotTOCIdentifiableException(CoLRevException):
    """The record cannot be identified through table-of-contents.
    Either the table-of-contents key is not implemented or
    the ENTRYTPE is not organized in tables-of-contents (e.g., online)."""

    def __init__(self, msg: typing.Optional[str] = None) -> None:
        self.message = msg
        super().__init__(self.message)


class RecordNotInTOCException(CoLRevException):
    """The record is not part of the table-of-contents (TOC)."""

    def __init__(self, *, record_id: str, toc_key: str) -> None:
        self.record_id = record_id
        self.toc_key = toc_key
        self.message = f"{record_id} not part of toc: {toc_key}"
        super().__init__(self.message)


class PropagatedIDChange(CoLRevException):
    """Changes in propagated records ID detected."""

    def __init__(self, notifications: list) -> None:
        self.message = "\n    ".join(notifications)
        super().__init__("Attempt to change propagated IDs:" + self.message)


# Init


class NonEmptyDirectoryError(CoLRevException):
    """Trying to initialize CoLRev in a non-empty directory."""

    def __init__(self, *, filepath: Path, content: list) -> None:
        if len(content) > 3:
            content = content[0:5] + ["..."]
        self.message = (
            f"Directory {filepath} not empty "
            + f"(files: {', '.join(content)}). "
            + "\nPlease change to an empty directory to initialize a project."
        )
        super().__init__(self.message)


class RepoInitError(CoLRevException):
    """Error during initialization of CoLRev project."""

    def __init__(self, *, msg: str) -> None:
        self.message = msg
        super().__init__(self.message)


# Search


class SearchNotAutomated(CoLRevException):
    """The search cannot be completed automatically."""

    def __init__(self, msg: str) -> None:
        self.message = msg
        super().__init__(self.message)


class InvalidQueryException(CoLRevException):
    """The query format is not valid."""

    def __init__(self, msg: str) -> None:
        self.message = msg
        super().__init__(self.message)


class RecordNotParsableException(CoLRevException):
    """The record could not be parsed."""

    def __init__(self, msg: str) -> None:
        self.message = msg
        super().__init__(self.message)


class NotFeedIdentifiableException(CoLRevException):
    """The record does not contain the required source_identifier (cannot be added to the feed)."""

    def __init__(self, msg: typing.Optional[str] = None) -> None:
        self.message = msg
        super().__init__(self.message)


class SearchSourceException(CoLRevException):
    """Records cannot be retrieved from the SearchSource."""

    def __init__(self, msg: str) -> None:
        self.message = msg
        super().__init__(self.message)


class RecordNotFoundException(CoLRevException):
    """Record not found in the main records file."""

    def __init__(self, msg: str) -> None:
        self.message = msg
        super().__init__(self.message)


# Load


class ImportException(CoLRevException):
    """An error occured in the import functions."""

    def __init__(
        self,
        msg: str,
    ) -> None:
        self.message = msg
        super().__init__(self.message)


class NoRecordsToImport(CoLRevException):
    """No records to import."""

    def __init__(
        self,
        msg: str,
    ) -> None:
        self.message = msg
        super().__init__(self.message)


class UnsupportedImportFormatError(CoLRevException):
    """The file format is not supported."""

    def __init__(
        self,
        import_path: Path,
    ) -> None:
        self.import_path = import_path
        self.message = (
            f"Format of SearchSource file not supported ({self.import_path.name}) "
        )
        super().__init__(self.message)


# Prep


class RecordNotFoundInPrepSourceException(CoLRevException):
    """The record was not found in the prep search source."""

    def __init__(
        self,
        *,
        msg: str,
    ) -> None:
        self.message = msg
        super().__init__(self.message)


# Dedupe


class DedupeError(CoLRevException):
    """An exception in the dedupe operation"""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(self.message)


# Data


class DataException(CoLRevException):
    """Exception in the data operation"""

    def __init__(self, *, msg: str) -> None:
        self.message = msg
        super().__init__("DataException: " + self.message)


# Push


class RecordNotInRepoException(CoLRevException):
    """The record was not found in the main records."""

    def __init__(self, record_id: str) -> None:
        if id is not None:
            self.message = f"Record not in repository ({record_id})"
        else:
            self.message = "Record not in repository"
        super().__init__(self.message)


class CorrectionPreconditionException(CoLRevException):
    """Precondition for corrections not given (clean git repository)."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(self.message)


# PDF Hash service


class InvalidPDFException(CoLRevException):
    """The PDF is invalid (empty, encrypted or broken)."""

    def __init__(self, path: Path) -> None:
        self.message = f"Invalid PDF (empty/broken): {path}"
        super().__init__(self.message)


class PDFHashError(CoLRevException):
    """An error occurred during PDF hashing."""

    def __init__(self, path: Path) -> None:
        self.message = f"Error during PDF hashing: {path}"
        super().__init__(self.message)


# Environment services


class MissingDependencyError(CoLRevException):
    """The required dependency is not available."""

    def __init__(self, dep: str) -> None:
        self.message = f"{dep}"
        super().__init__(self.message)


class PackageParameterError(CoLRevException):
    """The parameter for the package are not correct."""

    def __init__(self, dep: str) -> None:
        self.message = f"{dep}"
        super().__init__(self.message)


class DependencyConfigurationError(CoLRevException):
    """The required dependency is not configured correctly."""

    def __init__(self, dep: str) -> None:
        self.message = f"{dep}"
        super().__init__(self.message)


class ServiceNotAvailableException(CoLRevException):
    """An environment service is not available."""

    def __init__(self, dep: str, detailed_trace: str = "") -> None:
        self.dep = dep
        self.detailed_trace = detailed_trace
        super().__init__(f"Service not available: {self.dep}")


class PortAlreadyRegisteredException(CoLRevException):
    """The port (localhost) is already registered."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(self.message)


class TEITimeoutException(CoLRevException):
    """A timeout occurred during TEI generation"""


class TEIException(CoLRevException):
    """An exception related to the TEI format"""


class RecordNotInIndexException(CoLRevException):
    """The requested record was not found in the LocalIndex."""

    def __init__(self, record_id: str) -> None:
        if id is not None:
            self.message = f"Record not in index ({record_id})"
        else:
            self.message = "Record not in index"
        super().__init__(self.message)


class RecordNotIndexableException(CoLRevException):
    """The requested record could not be added to the LocalIndex."""

    def __init__(
        self,
        record_id: typing.Optional[str] = None,
        missing_key: typing.Optional[str] = None,
    ) -> None:
        self.missing_key = missing_key
        if missing_key is None:
            missing_key = "-"
        if record_id is not None:
            self.message = f"Record cannot be indexed ({record_id}): {missing_key}"
        else:
            self.message = f"Record cannot be indexed: {missing_key}"
        super().__init__(self.message)


class TOCNotAvailableException(CoLRevException):
    """Tables of contents (toc) are not available for the requested item."""

    def __init__(self, msg: typing.Optional[str] = None) -> None:
        self.message = msg
        super().__init__(self.message)


class CuratedOutletNotUnique(CoLRevException):
    """The outlets (journals or conferences) with curated metadata are not unique."""

    def __init__(self, msg: typing.Optional[str] = None) -> None:
        self.message = msg
        super().__init__(self.message)


class InvalidLanguageCodeException(CoLRevException):
    """Language code field does not comply with the required standard."""

    def __init__(self, invalid_language_codes: list) -> None:
        self.invalid_language_codes = invalid_language_codes

        super().__init__(f"Invalid language codes: {', '.join(invalid_language_codes)}")


class PackageSettingMustStartWithPackagesException(CoLRevException):
    """package settings must start with `packages` key"""

    def __init__(self, invalid_key: str) -> None:
        self.invalid_key = invalid_key
        super().__init__(
            f"Package settings must start with `packages` key. {invalid_key}"
        )


class TemplateNotAvailableError(CoLRevException):
    """The requested template is not available."""

    def __init__(self, template_path: str) -> None:
        self.message = f"Template not available: {template_path}"
        super().__init__(self.message)
