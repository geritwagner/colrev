#! /usr/bin/env python
"""Creation of a PRISMA chart as part of the data operations"""
from __future__ import annotations

import os
import typing
from pathlib import Path

import docker
import pandas as pd
from docker.errors import DockerException
from pydantic import BaseModel
from pydantic import Field

import colrev.env.docker_manager
import colrev.env.utils
import colrev.exceptions as colrev_exceptions
import colrev.package_manager.interfaces
import colrev.package_manager.package_manager
import colrev.package_manager.package_settings


class PRISMA(colrev.package_manager.interfaces.DataInterface):
    """Create a PRISMA diagram"""

    ci_supported: bool = Field(default=False)

    class PRISMASettings(
        colrev.package_manager.package_settings.DefaultSettings, BaseModel
    ):
        """PRISMA settings"""

        endpoint: str
        version: str
        diagram_path: typing.List[Path] = Field(
            default_factory=lambda: [Path("PRISMA.png")]
        )

    settings_class = PRISMASettings
    PRISMA_IMAGE = "colrev/prisma:latest"

    def __init__(
        self,
        *,
        data_operation: colrev.ops.data.Data,  # pylint: disable=unused-argument
        settings: dict,
    ) -> None:
        self.review_manager = data_operation.review_manager
        self.data_operation = data_operation

        # Set default values (if necessary)
        if "version" not in settings:
            settings["version"] = "0.1"

        if "diagram_path" in settings:
            settings["diagram_path"] = [Path(path) for path in settings["diagram_path"]]
        else:
            settings["diagram_path"] = [Path("PRISMA.png")]

        self.settings = self.settings_class(**settings)

        output_dir = self.review_manager.paths.output
        self.csv_path = output_dir / Path("PRISMA.csv")

        self.settings.diagram_path = [
            output_dir / path for path in self.settings.diagram_path
        ]

        if not self.review_manager.in_ci_environment():
            colrev.env.docker_manager.DockerManager.build_docker_image(
                imagename=self.PRISMA_IMAGE
            )
        data_operation.docker_images_to_stop.append(self.PRISMA_IMAGE)

    # pylint: disable=unused-argument
    @classmethod
    def add_endpoint(cls, operation: colrev.ops.data.Data, params: str) -> None:
        """Add as an endpoint"""

        add_package = {
            "endpoint": "colrev.prisma",
            "version": "0.1",
            "diagram_path": ["PRISMA.png"],
        }
        operation.review_manager.settings.data.data_package_endpoints.append(
            add_package
        )

    def _export_csv(self, silent_mode: bool) -> None:
        csv_resource_path = Path("packages/prisma/prisma/PRISMA.csv")
        self.csv_path.parent.mkdir(exist_ok=True, parents=True)

        if self.csv_path.is_file():
            os.remove(self.csv_path)
        colrev.env.utils.retrieve_package_file(
            template_file=csv_resource_path, target=self.csv_path
        )

        status_stats = self.review_manager.get_status_stats()

        prisma_data = pd.read_csv(self.csv_path)
        prisma_data["ind"] = prisma_data["data"]
        prisma_data.set_index("ind", inplace=True)
        prisma_data.loc["database_results", "n"] = status_stats.overall.md_retrieved
        prisma_data.loc["duplicates", "n"] = status_stats.md_duplicates_removed
        prisma_data.loc["records_screened", "n"] = status_stats.overall.rev_prescreen
        prisma_data.loc["records_excluded", "n"] = (
            status_stats.overall.rev_prescreen_excluded
        )
        if status_stats.currently.exclusion:
            prisma_data.loc["dbr_excluded", "n"] = "; ".join(
                f"{key}, {val}" for key, val in status_stats.currently.exclusion.items()
            )
        else:
            prisma_data.loc["dbr_excluded", "n"] = (
                f"Overall, {status_stats.overall.rev_excluded}"
            )

        prisma_data.loc["dbr_assessed", "n"] = status_stats.overall.rev_screen
        prisma_data.loc["new_studies", "n"] = status_stats.overall.rev_included
        prisma_data.loc["dbr_notretrieved_reports", "n"] = (
            status_stats.overall.pdf_not_available
        )
        prisma_data.loc["dbr_sought_reports", "n"] = (
            status_stats.overall.rev_prescreen_included
        )

        prisma_data.to_csv(self.csv_path, index=False)
        self.review_manager.logger.debug(f"Exported {self.csv_path}")

        if not status_stats.completeness_condition and not silent_mode:
            self.review_manager.logger.info("Review not (yet) complete")

    def _export_diagram(self, silent_mode: bool) -> None:
        if not self.csv_path.is_file():
            self.review_manager.logger.error("File %s does not exist.", self.csv_path)
            self.review_manager.logger.info("Complete processing and use colrev data")
            return

        csv_relative_path = self.csv_path.relative_to(
            self.review_manager.path
        ).as_posix()

        if not silent_mode:
            self.review_manager.logger.info("Create PRISMA diagram")

        for diagram_path in self.settings.diagram_path:
            diagram_relative_path = diagram_path.relative_to(
                self.review_manager.path
            ).as_posix()

            script = (
                "Rscript "
                + "/prisma.R "
                + f"/data/{csv_relative_path} "
                + f"/data/{diagram_relative_path}"
            )
            # Users can place a custom script in src/prisma.R
            if (self.review_manager.path / Path("src/prisma.R")).is_file():
                script = (
                    "Rscript "
                    + "-e \"source('/data/src/prisma.R')\" "
                    + f"/data/{csv_relative_path} "
                    + f"/data/{diagram_relative_path}"
                )

            self._call_docker_build_process(script=script)
            self.csv_path.unlink()

    def _call_docker_build_process(self, *, script: str) -> None:
        try:
            settings_path = self.review_manager.paths.settings
            uid = os.stat(settings_path).st_uid
            gid = os.stat(settings_path).st_gid
            user = f"{uid}:{gid}"

            client = docker.from_env()

            msg = f"Running docker container created from image {self.PRISMA_IMAGE}"
            self.review_manager.report_logger.info(msg)

            client.containers.run(
                image=self.PRISMA_IMAGE,
                command=script,
                user=user,
                volumes=[os.getcwd() + ":/data"],
                detach=True,
            )
        except docker.errors.ImageNotFound:
            self.review_manager.logger.error("Docker image not found")
        except docker.errors.ContainerError as exc:
            if "Temporary failure in name resolution" in str(exc):
                raise colrev_exceptions.ServiceNotAvailableException(
                    "prisma service failed"
                ) from exc
            raise exc
        except DockerException as exc:
            raise colrev_exceptions.ServiceNotAvailableException(
                f"Docker service not available ({exc}). Please install/start Docker."
            ) from exc

    def update_data(
        self,
        records: dict,  # pylint: disable=unused-argument
        synthesized_record_status_matrix: dict,  # pylint: disable=unused-argument
        silent_mode: bool,
    ) -> None:
        """Update the data/prisma diagram"""

        self._export_csv(silent_mode=silent_mode)
        self._export_diagram(silent_mode=silent_mode)

    def update_record_status_matrix(
        self,
        synthesized_record_status_matrix: dict,
        endpoint_identifier: str,
    ) -> None:
        """Update the record_status_matrix"""

        # Note : automatically set all to True / synthesized
        for syn_id in list(synthesized_record_status_matrix.keys()):
            synthesized_record_status_matrix[syn_id][endpoint_identifier] = True

    def get_advice(
        self,
    ) -> dict:
        """Get advice on the next steps (for display in the colrev status)"""

        data_endpoint = "Data operation [prisma data endpoint]: "

        path_str = ",".join(
            [
                str(x.relative_to(self.review_manager.path))
                for x in self.settings.diagram_path
            ]
        )
        advice = {
            "msg": f"{data_endpoint}"
            + "\n    - The PRISMA diagram is created automatically "
            + f"({path_str})",
            "detailed_msg": "TODO",
        }
        return advice
