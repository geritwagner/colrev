#! /usr/bin/env python
"""CLI interface for manual retrieval of PDFs"""
from __future__ import annotations

import shutil
import urllib.parse
from pathlib import Path

from pydantic import Field

import colrev.env.utils
import colrev.ops.pdf_get
import colrev.package_manager.interfaces
import colrev.package_manager.package_manager
import colrev.package_manager.package_settings
import colrev.record.record
from colrev.constants import Colors
from colrev.constants import Fields
from colrev.constants import RecordState


# pylint: disable=too-few-public-methods
# pylint: disable=unused-argument


class CoLRevCLIPDFGetMan(colrev.package_manager.interfaces.PDFGetManInterface):
    """Get PDFs manually based on a CLI"""

    settings_class = colrev.package_manager.package_settings.DefaultSettings
    ci_supported: bool = Field(default=False)

    def __init__(
        self,
        *,
        pdf_get_man_operation: colrev.ops.pdf_get_man.PDFGetMan,
        settings: dict,
    ) -> None:
        self.settings = self.settings_class(**settings)
        self.review_manager = pdf_get_man_operation.review_manager
        self.pdf_get_man_operation = pdf_get_man_operation

        self._get_from_downloads_folder = False
        self.pdf_dir = self.review_manager.paths.pdf

    def _get_pdf_from_google(
        self, record: colrev.record.record.Record
    ) -> colrev.record.record.Record:
        # import webbrowser

        title = record.data.get(Fields.TITLE, "no title")
        title = urllib.parse.quote_plus(title)
        url = f"  google:   https://www.google.com/search?q={title}+filetype%3Apdf"
        # webbrowser.open_new_tab(url)
        print(url)
        return record

    def _ask_authors_for_pdf(
        self, record: colrev.record.record.Record
    ) -> colrev.record.record.Record:
        # get the recipient email(s) from the local author index
        recipient = "TODO"
        subject = f"Copy of a PDF ({record.data['ID']})"

        author_name = record.data.get(Fields.AUTHOR, "").split(",")[0]
        signed, _ = self.review_manager.get_committer()

        template = colrev.env.utils.get_template(
            "packages/colrev_cli_pdf_get_man/src/pdf_get_man_mail.txt"
        )

        content = template.render(record=record, author_name=author_name, signed=signed)

        print("\n\n")
        print(recipient)
        print(subject)
        print("\n\n")
        print(content)
        print("\n\n")

        # next steps: better integration with email clients

        return record

    def _get_filepath(self, *, record: colrev.record.record.Record) -> Path:
        filepath = (
            self.pdf_dir / f"{record.data.get('year', 'NA')}/{record.data['ID']}.pdf"
        )
        if filepath.is_file():
            return filepath

        if Fields.VOLUME in record.data:
            filepath = self.pdf_dir / f"{record.data['volume']}/{record.data['ID']}.pdf"
            if filepath.is_file():
                return filepath

        if Fields.VOLUME in record.data and Fields.NUMBER in record.data:
            filepath = (
                self.pdf_dir
                / f"{record.data['volume']}_{record.data['number']}/{record.data['ID']}.pdf"
            )
            if filepath.is_file():
                return filepath

            filepath = (
                self.pdf_dir
                / f"{record.data['volume']}/{record.data['number']}/{record.data['ID']}.pdf"
            )
            if filepath.is_file():
                return filepath

        filepath = self.pdf_dir / f"{record.data['ID']}.pdf"

        return filepath

    def _retrieve_record_from_downloads_folder(
        self,
        *,
        record: colrev.record.record.Record,
    ) -> None:
        downloads_folder = Path.home() / Path("Downloads")
        pdfs_in_downloads_folder = list(downloads_folder.glob("*.pdf"))

        if len(pdfs_in_downloads_folder) == 0:
            print("No PDF found in downloads_folder")
            return
        if (
            len(pdfs_in_downloads_folder) > 1
            and not (downloads_folder / Path(f"{record.data['ID']}.pdf")).is_file()
        ):
            print("Multiple PDFs found in downloads_folder (skipping)")
            return

        if Path(f"{record.data['ID']}.pdf").is_file():
            pdf_in_downloads_folder = downloads_folder / Path(
                f"{record.data['ID']}.pdf"
            )
        else:
            pdf_in_downloads_folder = pdfs_in_downloads_folder[0]

        # simple heuristics:
        vol_slash_nr_path = self.pdf_dir / Path(
            f"{record.data.get('volume', 'NA')}/{record.data.get('number', 'NA')}"
        )
        if vol_slash_nr_path.is_dir():
            shutil.move(
                str(pdf_in_downloads_folder),
                str(vol_slash_nr_path / Path(f"{record.data['ID']}.pdf")),
            )
            return

        vol_underscore_nr_path = self.pdf_dir / Path(
            f"{record.data.get('volume', 'NA')}_{record.data.get('number', 'NA')}"
        )
        if vol_underscore_nr_path.is_dir():
            shutil.move(
                str(pdf_in_downloads_folder),
                str(vol_underscore_nr_path / Path(f"{record.data['ID']}.pdf")),
            )
            return

        vol_path = self.pdf_dir / Path(f"{record.data.get('volume', 'NA')}")
        if vol_path.is_dir():
            shutil.move(
                str(pdf_in_downloads_folder),
                str(vol_path / Path(f"{record.data['ID']}.pdf")),
            )
            return

        year_path = self.pdf_dir / Path(f"{record.data.get('year', 'NA')}")
        if year_path.is_dir():
            shutil.move(
                str(pdf_in_downloads_folder),
                str(year_path / Path(f"{record.data['ID']}.pdf")),
            )
            return

        shutil.move(
            str(pdf_in_downloads_folder),
            str(self.pdf_dir / Path(f"{record.data['ID']}.pdf")),
        )

    def print_record(self, *, record_dict: dict) -> None:
        """Print the record for pdf-get-man (cli)"""

        ret_str = f"  ID:       {record_dict['ID']} ({record_dict['ENTRYTYPE']})"
        ret_str += (
            f"\n  title:    {Colors.GREEN}{record_dict.get('title', 'no title')}{Colors.END}"
            f"\n  author:   {record_dict.get('author', 'no-author')}"
        )
        if record_dict[Fields.ENTRYTYPE] == "article":
            ret_str += (
                f"\n  outlet: {record_dict.get('journal', 'no-journal')} "
                f"({record_dict.get('year', 'no-year')}) "
                f"{record_dict.get('volume', 'no-volume')}"
                f"({record_dict.get('number', '')})"
            )
        elif record_dict[Fields.ENTRYTYPE] == "inproceedings":
            ret_str += f"\n  {record_dict.get('booktitle', 'no-booktitle')}"
        if Fields.FULLTEXT in record_dict:
            ret_str += (
                f"\n  fulltext: {Colors.ORANGE}{record_dict['fulltext']}{Colors.END}"
            )

        if Fields.URL in record_dict:
            ret_str += f"\n  url:      {record_dict['url']}"

        print(ret_str)

    def _pdf_get_man_record_cli(
        self,
        *,
        record: colrev.record.record.Record,
    ) -> None:
        # self.review_manager.logger.debug(
        #     f"called pdf_get_man_cli for {record}"
        # )

        # to print only the essential information
        self.print_record(record_dict=record.get_data())

        if RecordState.pdf_needs_manual_retrieval != record.data[Fields.STATUS]:
            return

        retrieval_scripts = {
            "get_pdf_from_google": self._get_pdf_from_google,
            "ask_authors": self._ask_authors_for_pdf,
            # 'get_pdf_from_researchgate': get_pdf_from_researchgate,
        }

        filepath = self._get_filepath(record=record)
        for retrieval_script in retrieval_scripts.values():
            # self.review_manager.logger.debug(
            #     f'{script_name}({record.data[Fields.ID]}) called'
            # )
            record = retrieval_script(record)

            if input("Retrieved (y/n)?") == "y":
                if self._get_from_downloads_folder:
                    self._retrieve_record_from_downloads_folder(record=record)
                filepath = self._get_filepath(record=record)
                if not filepath.is_file():
                    print(f"File does not exist: {record.data[Fields.ID]}.pdf")
                else:
                    filepath = self._get_filepath(record=record)
                    self.pdf_get_man_operation.pdf_get_man_record(
                        record=record,
                        filepath=filepath,
                    )
                    break

        if not filepath.is_file():
            if input("Is the PDF available (y/n)?") == "n":
                self.pdf_get_man_operation.pdf_get_man_record(
                    record=record,
                    filepath=None,
                )

        self.review_manager.update_status_yaml()

    def pdf_get_man(self, records: dict) -> dict:
        """Get the PDF manually based on a cli"""

        self.review_manager.logger.info("Retrieve PDFs manually")
        pdf_get_operation = self.review_manager.get_pdf_get_operation()
        pdf_dir = self.pdf_dir

        records = self.review_manager.dataset.load_records_dict()
        if input("Check existing unlinked PDFs (y/n)?") == "y":
            records = pdf_get_operation.check_existing_unlinked_pdfs(records)

        if input("Get PDF from Downloads folder (y/n)?") == "y":
            self._get_from_downloads_folder = True

        for record_dict in records.values():
            record = colrev.record.record.Record(record_dict)
            pdf_get_operation.link_pdf(record).get_data()

        self.pdf_get_man_operation.export_retrieval_table(records)
        pdf_get_man_data = self.pdf_get_man_operation.get_data()
        if pdf_get_man_data["nr_tasks"] == 0:
            self.review_manager.logger.info(
                "No tasks for PDF retrieval (run colrev pdf-get )."
            )
            return records
        print(
            "\nInstructions\n\n      "
            "Get the pdfs, rename them (ID.pdf) and store them in the pdfs directory.\n"
        )
        input("Enter to start.")

        for i, item in enumerate(pdf_get_man_data["items"]):
            stat = str(i + 1) + "/" + str(pdf_get_man_data["nr_tasks"])

            record = colrev.record.record.Record(records[item[Fields.ID]])

            print(f"\n\n{stat}")

            self._pdf_get_man_record_cli(record=record)

        if self.review_manager.dataset.has_record_changes():
            if input("Create commit (y/n)?") == "y":
                self.review_manager.dataset.create_commit(
                    msg="Retrieve PDFs manually",
                    manual_author=True,
                )
        else:
            self.review_manager.logger.info(
                "Retrieve PDFs manually and copy the files to "
                f"the {pdf_dir}. Afterwards, use "
                "colrev pdf-get-man"
            )

        return records
