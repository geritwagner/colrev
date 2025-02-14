#! /usr/bin/env python
"""Functionality to identify records."""
from __future__ import annotations

import logging
import os
import re
import tempfile
import typing
from pathlib import Path

import imagehash
import pymupdf
from nameparser import HumanName
from PIL import Image

import colrev.env.utils
import colrev.exceptions as colrev_exceptions
from colrev.constants import Colors
from colrev.constants import ENTRYTYPES
from colrev.constants import Fields
from colrev.constants import FieldSet
from colrev.constants import FieldValues
from colrev.constants import RecordState

if typing.TYPE_CHECKING:  # pragma: no cover
    import colrev.record.record


def _format_author_field_for_cid(input_string: str) -> str:
    input_string = input_string.replace("\n", " ").replace("'", "")
    names = input_string.replace("; ", " and ").split(" and ")
    author_list = []
    for name in names:
        if name.rstrip()[-1:] == ",":
            # if last-names only (eg, "Webster, and Watson, ")
            if len(name[:-2]) > 1:
                author_list.append(str(name.rstrip()[:-1]))
        else:
            parsed_name = HumanName(name)
            # Note: do not set parsed_name.string_format as a global constant
            # to preserve consistent creation of identifiers
            parsed_name.string_format = "{last} "
            if len(parsed_name.middle) > 0:
                parsed_name.middle = parsed_name.middle[:1]
            if len(parsed_name.first) > 0:
                parsed_name.first = parsed_name.first[:1]
            if len(parsed_name.nickname) > 0:
                parsed_name.nickname = ""

            if len(str(parsed_name)) > 1:
                author_list.append(str(parsed_name))

    return " ".join(author_list)


def _get_container_title(record: colrev.record.record.Record) -> str:
    # Note: custom __get_container_title for the colrev_id

    # school as the container title for theses
    if record.data[Fields.ENTRYTYPE] in ["phdthesis", "masterthesis"]:
        container_title = record.data[Fields.SCHOOL]
    # for technical reports
    elif record.data[Fields.ENTRYTYPE] == ENTRYTYPES.TECHREPORT:
        container_title = record.data["institution"]
    elif record.data[Fields.ENTRYTYPE] == ENTRYTYPES.INPROCEEDINGS:
        container_title = record.data[Fields.BOOKTITLE]
    elif record.data[Fields.ENTRYTYPE] == ENTRYTYPES.ARTICLE:
        container_title = record.data[Fields.JOURNAL]
    elif Fields.SERIES in record.data:
        container_title = record.data[Fields.SERIES]
    elif Fields.URL in record.data:
        container_title = record.data[Fields.URL]
    else:  # pragma: no cover
        raise KeyError

    return container_title


def _robust_append(input_string: str, *, to_append: str) -> str:
    input_string = str(input_string)
    to_append = str(to_append).replace("\n", " ").replace("/", " ")
    to_append = to_append.rstrip().lstrip().replace("–", " ")
    to_append = to_append.replace("emph{", "")
    to_append = to_append.replace("&amp;", "and")
    to_append = to_append.replace(" & ", " and ")
    to_append = colrev.env.utils.remove_accents(to_append)
    to_append = re.sub("[^0-9a-zA-Z -]+", "", to_append)
    to_append = re.sub(r"\s+", "-", to_append)
    to_append = re.sub(r"-+", "-", to_append)
    to_append = to_append.lower()
    if len(to_append) > 1:
        to_append = to_append.rstrip("-")
    input_string = input_string + "|" + to_append
    return input_string


def _check_colrev_id_preconditions(
    record: colrev.record.record.Record,
    *,
    assume_complete: bool,
) -> None:
    if assume_complete:
        return
    if record.data.get(Fields.STATUS, "NA") in [
        RecordState.md_imported,
        RecordState.md_needs_manual_preparation,
    ]:
        raise colrev_exceptions.NotEnoughDataToIdentifyException(
            msg="cannot determine field requirements "
            "(e.g., volume/number for journal articles)",
            missing_fields=["colrev_status/field_requirements"],
        )
    # Make sure that colrev_ids are not generated when
    # identifying_field_keys are UNKNOWN but possibly required
    for identifying_field_key in FieldSet.IDENTIFYING_FIELD_KEYS:
        if record.data.get(identifying_field_key, "") == FieldValues.UNKNOWN:
            raise colrev_exceptions.NotEnoughDataToIdentifyException(
                msg=f"{identifying_field_key} unknown (maybe required)",
                missing_fields=[identifying_field_key],
            )


def _get_colrev_id_from_record(record: colrev.record.record.Record) -> str:
    try:
        # Including the version of the identifier prevents cases
        # in which almost all identifiers are identical
        # (and very few identifiers change)
        # when updating the identifier function function
        # (this may look like an anomaly and be hard to identify)
        srep = "colrev_id1:"
        if record.data[Fields.ENTRYTYPE].lower() == ENTRYTYPES.ARTICLE:
            srep = _robust_append(srep, to_append="a")
        elif record.data[Fields.ENTRYTYPE].lower() == "inproceedings":
            srep = _robust_append(srep, to_append="p")
        else:
            srep = _robust_append(
                input_string=srep, to_append=record.data[Fields.ENTRYTYPE].lower()
            )
        srep = _robust_append(
            input_string=srep,
            to_append=_get_container_title(record),
        )
        if record.data[Fields.ENTRYTYPE] == ENTRYTYPES.ARTICLE:
            # Note: volume/number may not be required.
            srep = _robust_append(
                input_string=srep, to_append=record.data.get(Fields.VOLUME, "-")
            )
            srep = _robust_append(
                input_string=srep, to_append=record.data.get(Fields.NUMBER, "-")
            )
        srep = _robust_append(srep, to_append=record.data[Fields.YEAR])
        author = _format_author_field_for_cid(record.data[Fields.AUTHOR])
        if author.replace("-", "") == "":
            raise colrev_exceptions.NotEnoughDataToIdentifyException(
                msg="Missing field:", missing_fields=[Fields.AUTHOR]
            )
        srep = _robust_append(srep, to_append=author)
        srep = _robust_append(srep, to_append=record.data[Fields.TITLE])

        srep = srep.replace(";", "")  # ";" is the separator in colrev_id list
        # Note : pages not needed.
        # pages = record_dict.get(Fields.PAGES, "")
        # srep = _robust_append(srep, pages)
    except KeyError as exc:
        if Fields.ENTRYTYPE in str(exc):
            print(f"Missing ENTRYTYPE in {record.data.get(Fields.ID, record.data)}")
        key = "unknown"
        if exc.args:
            key = exc.args[0]
        raise colrev_exceptions.NotEnoughDataToIdentifyException(
            msg="Missing field:" + str(exc), missing_fields=[key]
        )
    return srep


def get_colrev_id(record: colrev.record.record.Record, *, assume_complete: bool) -> str:
    """Create the colrev_id"""

    _check_colrev_id_preconditions(
        record,
        assume_complete=assume_complete,
    )
    srep = _get_colrev_id_from_record(record)

    # Safeguard against titles that are rarely distinct
    if any(x in srep for x in ["|minitrack-introduction"]):
        raise colrev_exceptions.NotEnoughDataToIdentifyException(
            msg="Title typically non-distinct", missing_fields=[Fields.TITLE]
        )

    return srep


def _get_colrev_pdf_id_cpid2(pdf_path: Path, custom_page: int) -> str:
    with tempfile.NamedTemporaryFile(suffix=".png") as temp_file:
        file_name = temp_file.name
        try:
            doc: pymupdf.Document = pymupdf.open(pdf_path)
            # TODO : select custom_page
            page = next(iter(doc))  # get the first page
            pix = page.get_pixmap(dpi=200)
            pix.save(file_name)  # store image as a PNG
            with Image.open(file_name) as img:
                average_hash = imagehash.average_hash(img, hash_size=32)
                average_hash_str = str(average_hash).replace("\n", "")
                if len(average_hash_str) * "0" == average_hash_str:
                    raise colrev_exceptions.PDFHashError(path=pdf_path)
                return "cpid2:" + average_hash_str
        except StopIteration as exc:  # pragma: no cover
            raise colrev_exceptions.PDFHashError(path=pdf_path) from exc
        except pymupdf.FileDataError as exc:
            raise colrev_exceptions.InvalidPDFException(path=pdf_path) from exc
        except RuntimeError as exc:
            raise colrev_exceptions.PDFHashError(path=pdf_path) from exc


def get_colrev_pdf_id(
    pdf_path: Path, *, cpid_version: str = "cpid2", custom_page: int
) -> str:
    """Get the PDF hash"""

    pdf_path = pdf_path.resolve()
    if 0 == os.path.getsize(pdf_path):
        logging.error("%sPDF with size 0: %s %s", Colors.RED, pdf_path, Colors.END)
        raise colrev_exceptions.InvalidPDFException(path=pdf_path)

    if cpid_version == "cpid2":
        return _get_colrev_pdf_id_cpid2(pdf_path, custom_page=custom_page)

    raise NotImplementedError


def get_toc_key(record: colrev.record.record.Record) -> str:
    """Get the record's toc-key"""

    try:
        if record.data[Fields.ENTRYTYPE] == ENTRYTYPES.ARTICLE:
            toc_key = (
                record.data[Fields.JOURNAL]
                .replace(" ", "-")
                .replace("\\", "")
                .replace("&", "and")
                .lower()
            )
            toc_key += (
                f"|{record.data[Fields.VOLUME]}"
                if (
                    FieldValues.UNKNOWN
                    != record.data.get(Fields.VOLUME, FieldValues.UNKNOWN)
                )
                else "|-"
            )
            toc_key += (
                f"|{record.data[Fields.NUMBER]}"
                if (
                    FieldValues.UNKNOWN
                    != record.data.get(Fields.NUMBER, FieldValues.UNKNOWN)
                )
                else "|-"
            )

        elif record.data[Fields.ENTRYTYPE] == ENTRYTYPES.INPROCEEDINGS:
            toc_key = (
                record.data[Fields.BOOKTITLE]
                .replace(" ", "-")
                .replace("\\", "")
                .replace("&", "and")
                .lower()
                + f"|{record.data.get(Fields.YEAR, '')}"
            )
        else:
            msg = (
                f"ENTRYTYPE {record.data[Fields.ENTRYTYPE]} "
                + f"({record.data[Fields.ID]}) not toc-identifiable"
            )
            raise colrev_exceptions.NotTOCIdentifiableException(msg)
    except KeyError as exc:
        raise colrev_exceptions.NotTOCIdentifiableException(
            f"missing key {exc}"
        ) from exc

    return toc_key
