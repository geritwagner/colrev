#! /usr/bin/env python
"""Creation of a markdown paper as part of the data operations"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
import typing
from collections import Counter
from pathlib import Path
from threading import Timer

import docker
import requests
from docker.errors import DockerException
from pydantic import BaseModel
from pydantic import Field

import colrev.env.docker_manager
import colrev.env.utils
import colrev.exceptions as colrev_exceptions
import colrev.ops.check
import colrev.package_manager.interfaces
import colrev.package_manager.package_manager
import colrev.package_manager.package_settings
import colrev.record.record
from colrev.constants import Colors
from colrev.constants import Fields
from colrev.constants import Filepaths
from colrev.writer.write_utils import write_file


class PaperMarkdownSettings(BaseModel):
    """Paper settings"""

    endpoint: str
    version: str
    word_template: Path
    paper_path: Path = Field(
        default=Path("paper.md"),
        description="Path for the paper (markdown source document)",
    )
    paper_output: Path = Field(
        default=Path("paper.docx"),
        description="Path for the output (e.g., paper.docx/pdf/latex/html)",
    )

    # _details = {
    #     "word_template": {"tooltip": "Path to the word template (for Pandoc)"},
    #     "paper_path": {"tooltip": "Path for the paper (markdown source document)"},
    #     "paper_output": {
    #         "tooltip": "Path for the output (e.g., paper.docx/pdf/latex/html)"
    #     },
    # }


# pylint: disable=too-many-instance-attributes
class PaperMarkdown(colrev.package_manager.interfaces.DataInterface):
    """Synthesize the literature in a markdown paper

    The paper (paper.md) is created automatically.
    Records are added for synthesis after the <!-- NEW_RECORD_SOURCE -->
    Once records are moved to other parts of the paper (cited or in comments)
    they are assumed to be synthesized in the paper.
    Once they are synthesized in all data endpoints,
    CoLRev sets their status to rev_synthesized.
    The data operation also builds the paper (using pandoc, csl and a template).
    """

    NEW_RECORD_SOURCE_TAG = "<!-- NEW_RECORD_SOURCE -->"
    """Tag for appending new records in paper.md

    In the paper.md, the IDs of new records marked for synthesis
    will be appended after this tag.

    If IDs are moved to other parts of the paper,
    the corresponding record will be marked as rev_synthesized."""

    NON_SAMPLE_REFERENCES_RELATIVE = Path("non_sample_references.bib")
    SAMPLE_REFERENCES_RELATIVE = Path("sample_references.bib")

    settings_class = PaperMarkdownSettings

    ci_supported: bool = Field(default=False)

    _temp_path = Filepaths.LOCAL_ENVIRONMENT_DIR / Path(".colrev_temp")

    def __init__(
        self,
        *,
        data_operation: colrev.ops.data.Data,
        settings: dict,
    ) -> None:
        self.data_operation = data_operation
        self.review_manager = data_operation.review_manager

        # Set default values (if necessary)
        if "version" not in settings:
            settings["version"] = "0.1"

        if "word_template" not in settings:
            settings["word_template"] = Path("data/APA-7.docx")

        if "paper_output" not in settings:
            settings["paper_output"] = Path("paper.docx")

        self.settings = self.settings_class(**settings)

        self.data_dir = self.review_manager.paths.data
        self.settings.paper_path = self.data_dir / self.settings.paper_path
        self.settings.word_template = self.data_dir / self.settings.word_template
        self.non_sample_references = self.data_dir / self.NON_SAMPLE_REFERENCES_RELATIVE
        self.sample_references = self.data_dir / self.SAMPLE_REFERENCES_RELATIVE
        self.data_operation = data_operation

        output_dir = self.review_manager.paths.output
        self.settings.paper_output = output_dir / self.settings.paper_output

        self._create_non_sample_references_bib()

        if not self.review_manager.in_ci_environment():
            self.pandoc_image = "pandoc/latex:3.2.0"
            colrev.env.docker_manager.DockerManager.build_docker_image(
                imagename=self.pandoc_image
            )

        self.paper_relative_path = self.settings.paper_path.relative_to(
            self.review_manager.path
        )
        self._temp_path.mkdir(exist_ok=True, parents=True)

        self.review_manager = self.review_manager

    # pylint: disable=unused-argument
    @classmethod
    def add_endpoint(cls, operation: colrev.ops.data.Data, params: str) -> None:
        """Add as an endpoint"""

        add_source = {
            "endpoint": "colrev.paper_md",
            "version": "0.1",
            "word_template": Path("data/APA-7.docx"),
        }

        operation.review_manager.settings.data.data_package_endpoints.append(add_source)

    def _retrieve_default_word_template(self, word_template: Path) -> bool:

        if word_template.is_file():
            return True

        template_name = self.data_dir / Path("APA-7.docx")

        filedata = colrev.env.utils.get_package_file_content(
            module="colrev.packages.paper_md.paper_md", filename=Path("APA-7.docx")
        )

        if filedata:
            with open(template_name, "wb") as file:
                file.write(filedata)
        else:
            self.review_manager.logger.error(
                f"Could not retrieve {template_name} from the package"
            )
            return False
        self.review_manager.dataset.add_changes(template_name)
        return True

    def _retrieve_default_csl(self) -> None:
        csl_link = ""
        with open(self.settings.paper_path, encoding="utf-8") as file:
            for line in file:
                csl_match = re.match(r"csl: ?\"([^\"\n]*)\"\n", line)
                if csl_match:
                    csl_link = csl_match.group(1)

        if "http" in csl_link:
            ret = requests.get(csl_link, allow_redirects=True, timeout=30)
            csl_filename = self.review_manager.paths.DATA_DIR / Path(csl_link).name
            with open(csl_filename, "wb") as file:
                file.write(ret.content)
            colrev.env.utils.inplace_change(
                filename=self.settings.paper_path,
                old_string=f'csl: "{csl_link}"',
                new_string=f'csl: "{csl_filename}"',
            )
            self.review_manager.dataset.add_changes(self.settings.paper_path)
            self.review_manager.dataset.add_changes(Path(csl_filename))
            self.review_manager.logger.debug("Downloaded csl file for offline use")

    def _check_new_record_source_tag(
        self,
    ) -> None:
        with open(self.settings.paper_path, encoding="utf-8") as file:
            for line in file:
                if self.NEW_RECORD_SOURCE_TAG in line:
                    return
        raise PaperMarkdownRecordSourceTagError(
            f"Did not find {self.NEW_RECORD_SOURCE_TAG} tag in {self.settings.paper_path}"
        )

    def _authorship_heuristic(self) -> str:
        git_repo = self.review_manager.dataset.get_repo()
        try:
            commits_list = list(git_repo.iter_commits())
            commits_authors = []

            for commit in commits_list:
                committer = git_repo.git.show("-s", "--format=%cn", commit.hexsha)
                if committer == "GitHub":
                    continue
                commits_authors.append(committer)
                # author = git_repo.git.show("-s", "--format=%an", commit.hexsha)
                # mail = git_repo.git.show("-s", "--format=%ae", commit.hexsha)
            author = ", ".join(dict(Counter(commits_authors)))
        except ValueError:
            author, _ = self.review_manager.get_committer()
        return author

    def _get_data_page_missing(self, *, paper: Path, record_id_list: list) -> list:
        available = []
        with open(paper, encoding="utf-8") as file:
            line = file.read()
            for record in record_id_list:
                if record in line:
                    available.append(record)

        return list(set(record_id_list) - set(available))

    # pylint: disable=too-many-arguments
    def _create_new_records_source_section(
        self,
        *,
        writer: typing.IO,
        missing_records: list,
        paper_path: Path,
        silent_mode: bool,
        line: str,
    ) -> None:
        msg = (
            f"Marker {self.NEW_RECORD_SOURCE_TAG} not found in "
            + f"{paper_path.name}. Add records at the end of "
            + "the document."
        )
        self.review_manager.report_logger.warning(msg)
        self.review_manager.logger.warning(msg)
        if line != "\n":
            writer.write("\n")
        marker = f"{self.NEW_RECORD_SOURCE_TAG}_Records to synthesize_:\n\n"
        writer.write(marker)
        for missing_record in missing_records:
            writer.write(missing_record)
            self.review_manager.report_logger.info(
                # f" {missing_record}".ljust(self._PAD, " ") + " added"
                f" {missing_record} added"
            )
            if not silent_mode:
                self.review_manager.logger.info(
                    # f" {missing_record}".ljust(self._PAD, " ") + " added"
                    f" {missing_record} added"
                )

    # pylint: disable=too-many-arguments
    def _update_new_records_source_section(
        self,
        *,
        writer: typing.IO,
        missing_records: list,
        paper_path: Path,
        silent_mode: bool,
        reader: typing.IO,
        line: str,
    ) -> None:
        if "_Records to synthesize" not in line:
            line = "_Records to synthesize_:" + line + "\n"
            writer.write(line)
        else:
            writer.write(line)
            writer.write("\n")

        paper_ids_added = []
        for missing_record in missing_records:
            writer.write("\n- @" + missing_record + "\n")
            paper_ids_added.append(missing_record)

        for paper_id in paper_ids_added:
            self.review_manager.report_logger.info(
                # f" {missing_record}".ljust(self._PAD, " ")
                f" {paper_id}"
                + f" added to {paper_path.name}"
            )
        nr_records_added = len(missing_records)
        self.review_manager.report_logger.info(
            f"{nr_records_added} records added to {self.settings.paper_path.name}"
        )

        for paper_id_added in paper_ids_added:
            if not silent_mode:
                self.review_manager.logger.info(
                    f" {Colors.GREEN}{paper_id_added}".ljust(45)
                    + f"add to paper{Colors.END}"
                )

        if not silent_mode:
            self.review_manager.logger.info(
                f"Added to {paper_path.name}".ljust(24)
                + f"{nr_records_added}".rjust(15, " ")
                + " records"
            )

        # skip empty lines between to connect lists
        line = reader.readline()
        if line != "\n":
            writer.write(line)

    def _add_missing_records_to_paper(
        self,
        *,
        missing_records: list,
        silent_mode: bool,
    ) -> None:
        # pylint: disable=consider-using-with

        paper_path = self.settings.paper_path
        _, temp_filepath = tempfile.mkstemp(dir=self._temp_path)
        Path(temp_filepath).unlink(missing_ok=True)
        shutil.move(str(paper_path), str(temp_filepath))
        with open(temp_filepath, encoding="utf-8") as reader, open(
            paper_path, "w", encoding="utf-8"
        ) as writer:
            appended, completed = False, False
            line = reader.readline()
            while line:
                if self.NEW_RECORD_SOURCE_TAG in line:
                    self._update_new_records_source_section(
                        writer=writer,
                        missing_records=missing_records,
                        paper_path=paper_path,
                        silent_mode=silent_mode,
                        reader=reader,
                        line=line,
                    )
                    appended = True

                elif appended and not completed:
                    if line[:3] == "- @":
                        writer.write(line)
                    else:
                        if line != "\n":
                            writer.write("\n")
                        writer.write(line)
                        completed = True
                else:
                    writer.write(line)
                line = reader.readline()

            if not appended:
                self._create_new_records_source_section(
                    writer=writer,
                    missing_records=missing_records,
                    paper_path=paper_path,
                    silent_mode=silent_mode,
                    line=line,
                )

    def _create_paper(self, silent_mode: bool) -> None:
        if not silent_mode:
            self.review_manager.report_logger.info("Create paper")
            self.review_manager.logger.info("Create paper")

        title = "Paper template"
        readme_file = self.review_manager.paths.readme
        if readme_file.is_file():
            with open(readme_file, encoding="utf-8") as file:
                title = file.readline()
                title = title.replace("# ", "").replace("\n", "")

        author = self._authorship_heuristic()

        review_type = self.review_manager.settings.project.review_type

        # package_manager = self.review_manager.get_package_manager()
        # check_operation = colrev.ops.check.CheckOperation(self.review_manager)

        # review_type_class = package_manager.get_package_endpoint_class(
        #     package_type=EndpointType.review_type,
        #     package_identifier=self.review_type,
        # )
        # check_operation = colrev.ops.check.CheckOperation(self.review_manager)
        # review_type_object =
        # review_type_class(operation=check_operation, settings={"endpoint": review_type})

        # review_type_endpoint = package_manager.load_packages(
        #     package_type=EndpointType.review_type,
        #     selected_packages=[{"endpoint": review_type}],
        #     operation=check_operation,
        #     ignore_not_available=False,
        # )
        # r_type_suffix = str(review_type_endpoint[review_type])
        paper_resource_path = Path(f"packages/{review_type}/") / Path("paper.md")
        try:
            colrev.env.utils.retrieve_package_file(
                template_file=paper_resource_path, target=self.settings.paper_path
            )
        except colrev_exceptions.TemplateNotAvailableError:
            paper_resource_path = Path("packages/paper_md/paper_md") / Path("paper.md")
            colrev.env.utils.retrieve_package_file(
                template_file=paper_resource_path, target=self.settings.paper_path
            )

        colrev.env.utils.inplace_change(
            filename=self.settings.paper_path,
            old_string="{{review_type}}",
            new_string=review_type,
        )
        colrev.env.utils.inplace_change(
            filename=self.settings.paper_path,
            old_string="{{project_title}}",
            new_string=title,
        )
        colrev.env.utils.inplace_change(
            filename=self.settings.paper_path,
            old_string="{{colrev_version}}",
            new_string=str(self.review_manager.get_colrev_versions()[1]),
        )
        colrev.env.utils.inplace_change(
            filename=self.settings.paper_path,
            old_string="{{author}}",
            new_string=author,
        )

    def _exclude_marked_records(
        self,
        *,
        synthesized_record_status_matrix: dict,
        records: typing.Dict,
    ) -> None:
        # pylint: disable=consider-using-with

        temp = tempfile.NamedTemporaryFile(dir=self._temp_path)
        paper_path = self.settings.paper_path
        Path(temp.name).unlink(missing_ok=True)
        self._temp_path.mkdir(exist_ok=True, parents=True)
        shutil.move(str(paper_path), str(temp.name))

        screen_operation = self.review_manager.get_screen_operation(
            notify_state_transition_operation=False
        )

        with open(temp.name, encoding="utf-8") as reader, open(
            paper_path, "w", encoding="utf-8"
        ) as writer:
            line = reader.readline()
            while line:
                if not line.startswith("EXCLUDE "):
                    writer.write(line)
                    line = reader.readline()
                    continue
                # TBD: how to cover reasons? (add a screening_criteria string in the first round?)
                # EXCLUDE Wagner2022
                # replaced by
                # EXCLUDE Wagner2022 because () digital () knowledge_work () contract
                # users: mark / add criteria

                record_id = (
                    line.replace("EXCLUDE ", "").replace("@", "").rstrip().lstrip()
                )
                if (
                    record_id in synthesized_record_status_matrix
                    and record_id in records
                ):
                    del synthesized_record_status_matrix[record_id]
                    screen_operation.screen(
                        record=colrev.record.record.Record(records[record_id]),
                        screen_inclusion=False,
                        screening_criteria="NA",
                    )

                    self.review_manager.logger.info(f"Excluded {record_id}")
                    self.review_manager.report_logger.info(f"Excluded {record_id}")
                else:
                    self.review_manager.logger.error(f"Did not find ID {record_id}")
                    writer.write(line)
                    line = reader.readline()
                    continue
                line = reader.readline()

    def _add_missing_records(
        self,
        *,
        synthesized_record_status_matrix: dict,
        silent_mode: bool,
    ) -> None:
        missing_records = self._get_data_page_missing(
            paper=self.settings.paper_path,
            record_id_list=list(synthesized_record_status_matrix.keys()),
        )
        missing_records = sorted(missing_records)
        # review_manager.logger.debug(f"missing_records: {missing_records}")

        self._check_new_record_source_tag()

        if 0 == len(missing_records):
            if not silent_mode:
                self.review_manager.report_logger.info(
                    f"All records included in {self.settings.paper_path.name}"
                )
            # review_manager.logger.debug(
            #     f"All records included in {self.settings.paper_path.name}"
            # )
        else:
            if not silent_mode:
                self.review_manager.report_logger.info("Update paper")
                self.review_manager.logger.info(
                    f"Update paper ({self.settings.paper_path.name})"
                )
            self._add_missing_records_to_paper(
                missing_records=missing_records,
                silent_mode=silent_mode,
            )

    def _append_to_non_sample_references(self, *, module: str, filepath: Path) -> None:
        filedata = colrev.env.utils.get_package_file_content(
            module=module, filename=filepath
        )

        if filedata:

            non_sample_records = colrev.loader.load_utils.load(
                filename=self.non_sample_references,
                logger=self.review_manager.logger,
            )

            records_to_add = colrev.loader.load_utils.loads(
                load_string=filedata.decode("utf-8"),
                implementation="bib",
                logger=self.review_manager.logger,
            )

            # maybe prefix "non_sample_NameYear"? (also avoid conflicts with records.bib)
            duplicated_keys = [
                k for k in records_to_add.keys() if k in non_sample_records.keys()
            ]
            duplicated_records = [
                item
                for item in records_to_add.values()
                if item[Fields.ID] in non_sample_records.keys()
            ]
            records_to_add = {
                k: v for k, v in records_to_add.items() if k not in non_sample_records
            }
            if duplicated_keys:
                self.review_manager.logger.error(
                    f"{Colors.RED}Cannot add {duplicated_keys} to "
                    f"{self.NON_SAMPLE_REFERENCES_RELATIVE}, "
                    f"please change ID and add manually:{Colors.END}"
                )
                for duplicated_record in duplicated_records:
                    print(colrev.record.record.Record(duplicated_record))

            non_sample_records = {**non_sample_records, **records_to_add}

            write_file(
                records_dict=non_sample_records, filename=self.non_sample_references
            )

            self.review_manager.dataset.add_changes(
                Path("data/data/") / self.NON_SAMPLE_REFERENCES_RELATIVE
            )

    def _add_prisma_if_available(self, *, silent_mode: bool) -> None:
        prisma_endpoint_l = [
            d
            for d in self.review_manager.settings.data.data_package_endpoints
            if d["endpoint"] == "colrev.prisma"
        ]
        if prisma_endpoint_l:
            if "PRISMA.png" not in self.settings.paper_path.read_text(encoding="UTF-8"):
                if not silent_mode:
                    self.review_manager.logger.info("Add PRISMA diagram to paper")
                self._append_to_non_sample_references(
                    module="colrev.packages.prisma",
                    filepath=Path("prisma/prisma-refs.bib"),
                )

                # pylint: disable=consider-using-with
                temp = tempfile.NamedTemporaryFile(dir=self._temp_path)
                paper_path = self.settings.paper_path
                Path(temp.name).unlink(missing_ok=True)
                shutil.move(str(paper_path), str(temp.name))
                with open(temp.name, encoding="utf-8") as reader, open(
                    paper_path, "w", encoding="utf-8"
                ) as writer:
                    line = reader.readline()
                    while line:
                        if "# Method" not in line:
                            writer.write(line)
                            line = reader.readline()
                            continue

                        writer.write(line)

                        filedata = colrev.env.utils.get_package_file_content(
                            module="colrev.packages.prisma",
                            filename=Path("prisma/prisma_text.md"),
                        )
                        if filedata:
                            writer.write(filedata.decode("utf-8"))

                        line = reader.readline()
                if not silent_mode:
                    print()

    def update_paper(
        self,
        *,
        records: typing.Dict,
        synthesized_record_status_matrix: dict,
        silent_mode: bool,
    ) -> typing.Dict:
        """Update the paper (add new records after the NEW_RECORD_SOURCE_TAG)"""
        review_manager = self.review_manager

        if not self.settings.paper_path.is_file():
            self._create_paper(silent_mode=silent_mode)

        self._add_missing_records(
            synthesized_record_status_matrix=synthesized_record_status_matrix,
            silent_mode=silent_mode,
        )

        self._exclude_marked_records(
            synthesized_record_status_matrix=synthesized_record_status_matrix,
            records=records,
        )

        self._add_prisma_if_available(silent_mode=silent_mode)

        review_manager.dataset.add_changes(self.settings.paper_path)

        return records

    def _create_non_sample_references_bib(self) -> None:

        if not self.non_sample_references.is_file():
            try:
                retrieval_path = Path(
                    "packages/paper_md/paper_md/non_sample_references.bib"
                )
                colrev.env.utils.retrieve_package_file(
                    template_file=retrieval_path,
                    target=self.non_sample_references,
                )
                self.review_manager.dataset.add_changes(self.non_sample_references)
            except AttributeError:
                pass

    def _copy_references_bib(self) -> None:
        records = self.review_manager.dataset.load_records_dict()
        for record_id, record_dict in records.items():
            record_dict = {k.replace(".", "_"): v for k, v in record_dict.items()}
            records[record_id] = record_dict

        write_file(records_dict=records, filename=self.sample_references)
        self.review_manager.dataset.add_changes(self.sample_references)

    def _call_docker_build_process(self, *, script: str) -> None:
        try:
            uid = os.stat(self.review_manager.paths.records).st_uid
            gid = os.stat(self.review_manager.paths.records).st_gid
            user = f"{uid}:{gid}"

            client = docker.from_env()
            msg = f"Running docker container created from image {self.pandoc_image}"
            self.review_manager.report_logger.info(msg)

            container = client.containers.run(
                image=self.pandoc_image,
                command=script,
                user=user,
                volumes=[self.review_manager.path.as_posix() + ":/data"],
                detach=True,
            )
            # Wait for the container to finish
            container.wait()
            container.stop()
            container.remove()

        except docker.errors.ImageNotFound:
            self.review_manager.logger.error("Docker image not found")
        except docker.errors.ContainerError as exc:
            if "Temporary failure in name resolution" in str(exc):
                raise colrev_exceptions.ServiceNotAvailableException(
                    "pandoc service failed (tried to fetch csl without Internet connection)"
                ) from exc
            raise exc
        except DockerException as exc:
            raise colrev_exceptions.ServiceNotAvailableException(
                f"Docker service not available ({exc}). Please install/start Docker."
            ) from exc

    def build_paper(self) -> None:
        """Build the paper (based on pandoc)"""

        if not self.review_manager.paths.records.is_file():
            self.review_manager.paths.records.touch()

        if not self.settings.paper_path.is_file():
            self.review_manager.logger.error(
                "File %s does not exist.", self.settings.paper_path
            )
            self.review_manager.logger.info("Complete processing and use colrev data")
            return

        self._retrieve_default_csl()
        self._create_non_sample_references_bib()
        self._copy_references_bib()

        word_template = self.settings.word_template

        if not self._retrieve_default_word_template(word_template):
            self.review_manager.logger.error(f"Word template {word_template} not found")
            return

        output_relative_path = self.settings.paper_output.relative_to(
            self.review_manager.path
        )

        if (
            not self.review_manager.dataset.has_changes(self.paper_relative_path)
            and self.settings.paper_output.is_file()
        ):
            self.review_manager.logger.debug("Skipping paper build (no changes)")
            return

        if self.review_manager.verbose_mode:
            self.review_manager.logger.info("Build paper")

        script = (
            f"{self.paper_relative_path.as_posix()} --filter pandoc-crossref --citeproc "
            + f"--reference-doc {word_template.relative_to(self.review_manager.path).as_posix()} "
            + f"--output {output_relative_path.as_posix()}"
        )

        Timer(
            1,
            lambda: self._call_docker_build_process(script=script),
        ).start()

    def update_data(
        self,
        records: dict,
        synthesized_record_status_matrix: dict,
        silent_mode: bool,
    ) -> None:
        """Update the data/paper"""

        if (
            self.review_manager.dataset.repo_initialized()
            and self.review_manager.dataset.has_changes(
                self.paper_relative_path, change_type="unstaged"
            )
        ):
            self.review_manager.logger.warning(
                f"{Colors.RED}Skipping updates of "
                f"{self.paper_relative_path} due to unstaged changes{Colors.END}"
            )
        else:
            records = self.update_paper(
                records=records,
                synthesized_record_status_matrix=synthesized_record_status_matrix,
                silent_mode=silent_mode,
            )

        if not self.review_manager.in_ci_environment() and not silent_mode:
            self.build_paper()

    def _get_to_synthesize(self, *, paper: Path, records_for_synthesis: list) -> list:
        if not paper.is_file():
            return records_for_synthesis

        to_synthesize = []
        with open(paper, encoding="utf-8") as file:
            for line in file:
                if self.NEW_RECORD_SOURCE_TAG in line:
                    while line:
                        line = file.readline()
                        if re.search(r"- @.*", line):
                            record_id = re.findall(r"- @(.*)$", line)
                            to_synthesize.append(record_id[0])
                            if line == "\n":
                                break

        to_synthesize = [x for x in to_synthesize if x in records_for_synthesis]
        return to_synthesize

    def _get_synthesized_papers(
        self, *, paper: Path, synthesized_record_status_matrix: dict
    ) -> list:
        to_synthesize = self._get_to_synthesize(
            paper=paper,
            records_for_synthesis=list(synthesized_record_status_matrix.keys()),
        )
        # Assuming that all records have been added to the paper before
        synthesized = [
            x
            for x in list(synthesized_record_status_matrix.keys())
            if x not in to_synthesize
        ]

        return synthesized

    def update_record_status_matrix(
        self,
        synthesized_record_status_matrix: dict,
        endpoint_identifier: str,
    ) -> None:
        """Update the record_status_matrix"""
        # Update status / synthesized_record_status_matrix
        synthesized = self._get_synthesized_papers(
            paper=self.settings.paper_path,
            synthesized_record_status_matrix=synthesized_record_status_matrix,
        )
        for syn_id in synthesized:
            if syn_id in synthesized_record_status_matrix:
                synthesized_record_status_matrix[syn_id][endpoint_identifier] = True
            else:
                print(f"Error: {syn_id} not int {synthesized}")

    def get_advice(
        self,
    ) -> dict:
        """Get advice on the next steps (for display in the colrev status)"""

        advice = {
            "msg": "Data operation [paper_md endpoint]: "
            + "\n    1. Edit the paper (data/data/paper.md)"
            + "\n    2. To build the paper (output/paper.docx), run: colrev data"
            + "\n    3. To create a version, run: git add data/data/paper.md && "
            + "git commit -m 'update paper'",
            "detailed_msg": "... with a link to the docs etc.",
        }
        return advice


class PaperMarkdownRecordSourceTagError(Exception):
    """NEW_RECORD_SOURCE_TAG not found in paper.md"""

    def __init__(self, msg: str) -> None:
        self.message = f" {msg}"
        super().__init__(self.message)
