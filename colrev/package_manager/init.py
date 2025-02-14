#! /usr/bin/env python
"""Package init."""
from __future__ import annotations

import inspect
import json
import os
import re
import subprocess
from datetime import datetime
from importlib import import_module
from importlib.metadata import distributions
from pathlib import Path
from typing import Type

import git
import inquirer

from colrev.constants import Colors
from colrev.package_manager.interfaces import BASECLASS_MAP
from colrev.package_manager.interfaces import DataInterface
from colrev.package_manager.interfaces import DedupeInterface
from colrev.package_manager.interfaces import PDFGetInterface
from colrev.package_manager.interfaces import PDFGetManInterface
from colrev.package_manager.interfaces import PDFPrepInterface
from colrev.package_manager.interfaces import PDFPrepManInterface
from colrev.package_manager.interfaces import PrepInterface
from colrev.package_manager.interfaces import PrepManInterface
from colrev.package_manager.interfaces import PrescreenInterface
from colrev.package_manager.interfaces import ReviewTypeInterface
from colrev.package_manager.interfaces import ScreenInterface
from colrev.package_manager.interfaces import SearchSourceInterface


def _get_default_author() -> dict:
    try:
        name = (
            subprocess.check_output(["git", "config", "--global", "user.name"])
            .decode()
            .strip()
        )
        email = (
            subprocess.check_output(["git", "config", "--global", "user.email"])
            .decode()
            .strip()
        )
        return {"name": name, "email": email}
    except subprocess.CalledProcessError:
        return {}


DEFAULT_AUTHOR = _get_default_author()

AUTHOR_PATTERN = r"([a-zA-Z ]+)<([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})>"


# Function to create the pyproject.toml file
def _create_pyproject_toml(data: dict) -> None:

    plugins = []
    package_location = data["name"]
    if data["built_in"]:
        package_location = data["name"].replace("colrev.", "colrev.packages.")
    for key, value in data["plugins"].items():
        formatted_string = (
            f"{key} = \"{package_location}.src.{value['module']}:{value['class']}\""
        )
        plugins.append(formatted_string)
    plugins_string = "\n".join(plugins)

    content = f"""
[tool.poetry]
name = "{data['name']}"
description = "{data['description']}"
version = "{data['version']}"
license = "{data['license']}"
authors = ["{data['author']['name']} <{data['author']['email']}>"]
repository = "{data['repository']}"

[[tool.poetry.packages]]
include = "src"

[tool.poetry.dependencies]
python = ">=3.9, <4"

[tool.colrev]
colrev_doc_description = "{data['doc_description']}"
colrev_doc_link = "docs/README.md"
search_types = []

[tool.poetry.plugins.colrev]
{plugins_string}

[build-system]
requires = ["poetry-core>=1.0.0", "cython<3.0"]
build-backend = "poetry.core.masonry.api"
"""
    with open("pyproject.toml", "w", encoding="utf-8") as file:
        file.write(content.strip())


def _create_git_repo() -> None:
    repo_path = os.getcwd()
    repo = git.Repo.init(repo_path)
    repo.git.add(all=True)
    repo.index.commit("Initial commit")


def _create_built_in_package() -> bool:
    questions = [
        inquirer.List(
            "package_type",
            message="Select the package type",
            choices=["Standalone", "Built-in"],
        )
    ]
    data = inquirer.prompt(questions)
    return data["package_type"] == "Built-in"


# pylint: disable=unused-argument
def validate_version(answers: list, version: str) -> bool:
    """Validate the version"""
    # return false if the version is not a valid version number
    if version == "":
        return True
    if not re.match(r"^\d+\.\d+\.\d+$", version):
        print(f"  {Colors.RED}The version number is not valid.{Colors.END}")
        return False
    return True


# pylint: disable=unused-argument
def validate_module_name(answers: list, name: str) -> bool:
    """Validate the module name"""
    if name == "":  # Accept default module name
        return True
    # return false if the name is not a valid python module name
    if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", name):
        print(
            f"  {Colors.RED}The module name is not a valid python module name.{Colors.END}"
        )
        return False
    return True


# pylint: disable=unused-argument
# pylint: disable=too-many-locals
# pylint: disable=too-many-return-statements
# pylint: disable=too-many-branches
# pylint: disable=too-many-statements
def _get_package_data(default_package_name: str, built_in: bool) -> dict:

    default_package_name_str = ""
    if default_package_name:
        default_package_name_str = (
            f" [{Colors.GREEN}{default_package_name}{Colors.END}]"
        )

    default_author_str = (
        f"[{Colors.GREEN}{DEFAULT_AUTHOR['name']} "
        + f"<{DEFAULT_AUTHOR['email']}>{Colors.END}]"
    )

    def validate_author(answers: list, name: str) -> bool:
        if name == "":
            return True
        if not re.match(AUTHOR_PATTERN, name):
            print(
                f"\n  {Colors.RED}The format of the author name and e-mail is not valid."
                "\n It should be like `Max Mustermann <max.mustermann@uni-bamberg.de>`."
                f"{Colors.END}"
            )
            return False
        return True

    def validate_name(answers: list, name: str) -> bool:
        if name == "":  # Accept default package name
            return True

        installed_packages = {dist.metadata["Name"].lower() for dist in distributions()}
        # Check if the name corresponds to a currently installed python package
        if name in installed_packages:
            print(f"  {Colors.RED}The package name is already installed.{Colors.END}")
            return False

        if built_in:
            if not name.startswith("colrev."):
                print(
                    f"  {Colors.RED}The built-in package name must start with 'colrev.'{Colors.END}"
                )
                return False
            if not re.match(r"^[a-zA-Z_]*\.[a-zA-Z0-9_]*$", name):
                print(
                    f"  {Colors.RED}"
                    "The package name is not a valid python package name."
                    f"{Colors.END}"
                )
                return False
            return True

        # Check if the name is a valid python package name
        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", name):
            print(
                f"  {Colors.RED}The package name is not a valid python package name.{Colors.END}"
            )
            return False

        return True

    questions = [
        inquirer.Text(
            "name",
            message=f"Enter the package name, e.g., {default_package_name_str}",
            validate=validate_name,
        ),
        inquirer.Text("description", message="Enter the package description"),
        inquirer.Text(
            "doc_description",
            message="Enter short description string for the CoLRev docs list",
        ),
        inquirer.Text(
            "version",
            message=f"Enter the package version number [{Colors.GREEN}0.1.0{Colors.END}]",
            validate=validate_version,
        ),
        inquirer.Text(
            "license",
            message=f"Enter the package license [{Colors.GREEN}MIT{Colors.END}]",
        ),
        inquirer.Text(
            "author",
            message=f"Enter the author name and e-mail {default_author_str}",
            validate=validate_author,
        ),
    ]
    if not built_in:
        questions.append(
            inquirer.Text("repository", message="Enter the URL of the repository"),
        )

    questions.append(
        inquirer.Checkbox(
            "plugins",
            message="Select the plugin types (use SPACE to select)",
            choices=list(BASECLASS_MAP.keys()),
        )
    )

    package_data = inquirer.prompt(questions)

    def validate_class_name(answers: list, name: str) -> bool:
        if name == "":  # Accept default class name
            return True
        # return false if the name is not a valid python class name
        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", name):
            print(
                f"  {Colors.RED}The class name is not a valid python class name.{Colors.END}"
            )
            return False
        return True

    def to_camel_case(snake_str: str) -> str:
        components = snake_str.split("_")
        # Capitalize the first letter of each component and join them together
        return "".join(x.capitalize() for x in components)

    if built_in:
        package_data["repository"] = (
            f"https://github.com/CoLRev-Environment/colrev/tree/"
            f"main/colrev/packages/{package_data['name'].replace('colrev.', '')}"
        )

    if not package_data["name"]:
        package_data["name"] = default_package_name
    if not package_data["version"]:
        package_data["version"] = "0.1.0"
    if not package_data["license"]:
        package_data["license"] = "MIT"
    # pylint: disable=colrev-missed-constant-usage
    if not package_data["author"]:
        package_data["author"] = DEFAULT_AUTHOR
    else:
        match = re.match(AUTHOR_PATTERN, package_data.pop("author"))
        if not match or len(match.groups()) != 2:
            raise ValueError(
                "Author name and e-mail must be in the format 'Name <email>'"
            )
        package_data["author"] = {}
        package_data["author"]["name"] = match.group(1).strip()
        package_data["author"]["email"] = match.group(2)
    if not package_data["repository"]:
        package_data["repository"] = "TODO"

    package_data["doc_description"] = "TODO"

    # Example: package_data["plugins"] = ["data", "screen"]
    plugin_data = {}
    for plugin in package_data["plugins"]:
        p_name = package_data["name"].replace("colrev.", "")
        default_module_name = f"{p_name}_{plugin}"
        default_class_name = to_camel_case(
            f"{p_name.capitalize()}_{plugin.capitalize()}"
        )
        plugin_questions = [
            inquirer.Text(
                "module",
                message=f"Enter the module name for {plugin} "
                + f"[{Colors.GREEN}{default_module_name}{Colors.END}]",
                validate=validate_module_name,
            ),
            inquirer.Text(
                "class",
                message=f"Enter the class name for {plugin} "
                + f"[{Colors.GREEN}{default_class_name}{Colors.END}]",
                validate=validate_class_name,
            ),
        ]

        data = inquirer.prompt(plugin_questions)

        if data["module"] == "":
            data["module"] = default_module_name
        if data["class"] == "":
            data["class"] = default_class_name
        plugin_data[plugin] = data

    package_data["plugins"] = plugin_data
    package_data["built_in"] = built_in

    return package_data


# TODO : this would need to be revised
# pylint: disable=too-many-branches
def _get_init_method(interface_class: Type) -> str:

    # pylint: disable=line-too-long
    init_method = """

"""
    if interface_class is ReviewTypeInterface:
        init_method += """    def __init__(
        self, *, operation: colrev.process.operation.Operation, settings: dict
    ) -> None:
        self.settings = colrev.package_manager.package_settings.DefaultSettings(**settings)"""
    elif interface_class is SearchSourceInterface:
        init_method += """
    def __init__(
        self,
        *,
        source_operation: colrev.process.operation.Operation,
        settings: typing.Optional[dict] = None,
    ) -> None:
      pass # TODO"""
    elif interface_class is PrepInterface:
        init_method += """    def __init__(
        self,
        *,
        prep_operation: colrev.ops.prep.Prep,  # pylint: disable=unused-argument
        settings: dict,
    ) -> None:
        self.settings = colrev.package_manager.package_settings.DefaultSettings(**settings)"""
    elif interface_class is PrepManInterface:
        init_method += """    def __init__(
        self, *, prep_man_operation: colrev.ops.prep_man.PrepMan, settings: dict
    ) -> None:
        self.settings = colrev.package_manager.package_settings.DefaultSettings(**settings)"""
    elif interface_class is DedupeInterface:
        init_method += """    def __init__(
        self,
        *,
        dedupe_operation: colrev.ops.dedupe.Dedupe,
        settings: dict,
    ) -> None:
      pass # TODO"""
    elif interface_class is PrescreenInterface:
        init_method += """    def __init__(
        self,
        *,
        prescreen_operation: colrev.ops.prescreen.Prescreen,
        settings: dict,
    ) -> None:
      pass # TODO"""
    elif interface_class is PDFGetInterface:
        init_method += """    def __init__(
        self,
        *,
        pdf_get_operation: colrev.ops.pdf_get.PDFGet,
        settings: dict,
    ) -> None:
      pass # TODO"""
    elif interface_class is PDFGetManInterface:
        init_method += """    def __init__(
        self,
        *,
        pdf_get_man_operation: colrev.ops.pdf_get_man.PDFGetMan,
        settings: dict,
    ) -> None:
      pass # TODO"""
    elif interface_class is PDFPrepInterface:
        init_method += """    def __init__(
        self,
        *,
        pdf_prep_operation: colrev.ops.pdf_prep.PDFPrep,
        settings: dict,
    ) -> None:
      pass # TODO"""
    elif interface_class is PDFPrepManInterface:
        init_method += """    def __init__(
        self,
        *,
        pdf_prep_man_operation: colrev.ops.pdf_prep_man.PDFPrepMan,
        settings: dict,
    ) ->: None:
      pass # TODO"""
    elif interface_class is ScreenInterface:
        init_method += """    def __init__(
        self,
        *,
        screen_operation: colrev.ops.screen.Screen,
        settings: dict,
    ) -> None:
      pass # TODO"""
    elif interface_class is DataInterface:
        init_method += """    def __init__(
        self,
        *,
        data_operation: colrev.ops.data.Data,
        settings: dict,
    ) -> None:
      pass # TODO"""
    else:
        init_method += "#TODO"

    return init_method


def _generate_method_signatures(module_path: str, class_name: str) -> list:
    module = import_module(module_path)
    interface_class = getattr(module, class_name)
    members = inspect.getmembers(interface_class)

    interface_class_attrs = next(
        (member for member in members if member[0] == "_InterfaceClass__attrs"), None
    )
    if interface_class_attrs:
        attrs_dict = interface_class_attrs[1]

        method_signatures = []

        for name, attr in attrs_dict.items():
            # TODO
            # if isinstance(attr, zope.interface.interface.Attribute) and not isinstance(
            #     attr, zope.interface.interface.Method
            # ):
            method_signatures.append(f"    {name} = '' #TODO\n")
        method_signatures.append("\n")
        method_signatures.append(_get_init_method(interface_class))
        method_signatures.append("\n")
        method_signatures.append("\n")

        for name, attr in attrs_dict.items():
            # TODO
            # if isinstance(attr, zope.interface.interface.Method):
            sig_string = attr.getSignatureString().replace("(", "(self, ")
            method_signatures.append(
                f"    def {name}{sig_string}:\n"
                f'      """{attr.getDoc()}"""\n      # TODO\n\n'
            )

        return method_signatures

    return ["Attribute '_InterfaceClass__attrs' not found."]


# pylint: disable=too-many-return-statements
# pylint: disable=too-many-branches
def _get_package_imports(plugin: str) -> str:
    if plugin == "review_type":
        return "import colrev.ops.data"
    if plugin == "search_source":
        return "import colrev.process.operation"
    if plugin == "prep":
        return "import colrev.ops.prep"
    if plugin == "prep_man":
        return "import colrev.ops.prep_man"
    if plugin == "dedupe":
        return "import colrev.ops.dedupe"
    if plugin == "prescreen":
        return "import colrev.ops.prescreen"
    if plugin == "pdf_get":
        return "import colrev.ops.pdf_get"
    if plugin == "pdf_get_man":
        return "import colrev.ops.pdf_get_man"
    if plugin == "pdf_prep":
        return "import colrev.ops.pdf_prep"
    if plugin == "pdf_prep_man":
        return "import colrev.ops.pdf_prep_man"
    if plugin == "screen":
        return "import colrev.ops.screen"
    if plugin == "data":
        return "import colrev.ops.data"
    return "#TODO"


def _create_module_files(package_data: dict) -> None:

    os.makedirs("src", exist_ok=True)

    for plugin, data in package_data["plugins"].items():
        file_path = os.path.join("src", f"{data['module']}.py")
        baseclass = BASECLASS_MAP[plugin]

        module_path = "colrev.package_manager.interfaces"
        method_signatures = _generate_method_signatures(module_path, baseclass)

        with open(file_path, "w", encoding="utf-8") as file:
            file.write(
                f'''#! /usr/bin/env python
"""{baseclass}: {data['class']}"""

import typing
from colrev.package_manager.interfaces import {baseclass}
import colrev.package_manager.package_settings
{_get_package_imports(plugin)}

class {data['class']}({baseclass}):
'''
            )
            for signature in method_signatures:
                file.write(signature)


def _create_src_init(package_data: dict) -> None:

    with open("src/__init__.py", "w", encoding="utf-8") as file:
        file.write(
            f'''"""Package for {package_data['name']}."""

__author__ = "{package_data['author']['name']}"
__email__ = "{package_data['author']['email']}"'''
        )


def _create_docs_readme() -> None:

    Path("docs").mkdir()

    with open("docs/README.md", "w", encoding="utf-8") as file:
        file.write("""# TODO : Docs""")


def _create_readme(package_data: dict) -> None:

    with open("README.md", "w", encoding="utf-8") as file:
        file.write(f"""# {package_data['name']}""")
        if package_data["description"]:
            file.write(f"\n\n{package_data['description']}")
        file.write("\n\n## Installation")
        file.write("\n\n```bash")
        file.write(f"\ncolrev install {package_data['name']}")
        file.write("\n```")
        file.write("\n\n## Usage")
        file.write("\n\nTODO")
        file.write("\n\n## License")
        file.write(
            f"\n\nThis project is licensed under the {package_data['license']} "
            "License - see the [LICENSE](LICENSE) file for details."
        )


def _create_license_file(package_data: dict) -> None:

    license_file_path = "LICENSE"
    license_text = _get_license_text(package_data)
    with open(license_file_path, "w", encoding="utf-8") as file:
        file.write(license_text)


def _get_license_text(package_data: dict) -> str:
    license_name = package_data["license"]

    current_year = datetime.now().year
    license_texts = {
        "MIT": f"""MIT License

        Copyright (c) [{current_year}] [{package_data['author']['name']}]

        Permission is hereby granted, free of charge, to any person obtaining a copy
        of this software and associated documentation files (the "Software"), to deal
        in the Software without restriction, including without limitation the rights
        to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
        copies of the Software, and to permit persons to whom the Software is
        furnished to do so, subject to the following conditions:

        The above copyright notice and this permission notice shall be included in all
        copies or substantial portions of the Software.

        THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
        IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
        FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
        AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
        LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
        OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
        SOFTWARE.""",
        # Add more license texts for other licenses if needed
    }

    license_text = license_texts.get(license_name, "")

    return license_text


def _create_pre_commit_hooks() -> None:

    pre_commit_hooks = """
repos:
-   repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.6.0
    hooks:
    -   id: trailing-whitespace
    -   id: end-of-file-fixer
        exclude: bib$|txt$|ris$|enl$|xml$
    -   id: check-docstring-first
    -   id: check-json
    -   id: check-yaml
    -   id: check-toml
    -   id: debug-statements
    -   id: name-tests-test
-   repo: https://github.com/psf/black-pre-commit-mirror
    rev: 24.4.2
    hooks:
      - id: black
        language_version: python3
-   repo: https://github.com/PyCQA/autoflake
    rev: v2.3.1
    hooks:
    -   id: autoflake
-   repo: https://github.com/PyCQA/flake8
    rev: 7.1.0
    hooks:
    -   id: flake8
        additional_dependencies: [flake8-typing-imports==1.12.0]
        args: ['--max-line-length=110', '--extend-ignore=E203,TYP006']
-   repo: https://github.com/asottile/reorder-python-imports
    rev: v3.13.0
    hooks:
    -   id: reorder-python-imports
        args: [--py3-plus]
-   repo: https://github.com/asottile/pyupgrade
    rev: v3.16.0
    hooks:
    -   id: pyupgrade
        args: [--py36-plus, --keep-runtime-typing]
-   repo: https://github.com/pre-commit/mirrors-mypy
    rev: 'v1.11.0'
    hooks:
    -   id: mypy
        args: [--disallow-untyped-defs, --disallow-incomplete-defs, --disallow-untyped-calls]
        additional_dependencies: [types-toml]
- repo: https://github.com/astral-sh/ruff-pre-commit
  rev: v0.5.4
  hooks:
    - id: ruff # runs faster than pylint
      args: [--fix, --exit-non-zero-on-fix]
- repo: local
  hooks:
    - id: pylint
      name: pylint
      entry: pylint
      language: system
      types: [python]
      files: colrev
      args:
        [
          "-rn", # Only display messages
          "-sn", # Don't display the score
        ]
"""
    with open(".pre-commit-config.yaml", "w", encoding="utf-8") as file:
        file.write(pre_commit_hooks)


def _add_to_packages_json(package_data: dict) -> None:
    packages_json_path = (
        Path(__file__).resolve().parent.parent.parent
        / "colrev/package_manager/packages.json"
    )
    with open(packages_json_path, encoding="utf-8") as file:

        data = json.load(file)

        # Add the package with "experimental" status
        data[package_data["name"]] = {"dev_status": "experimental"}

        with open(packages_json_path, "w", encoding="utf-8") as file_out:
            json.dump(data, file_out, indent=4)


def main() -> None:
    """Main function to create a CoLRev package."""

    built_in = _create_built_in_package()
    current_dir = Path.cwd()
    if any(Path(current_dir).iterdir()):
        print("The current directory is not empty. Please select an empty directory.")
        return
    colrev_packages_dir = Path(__file__).resolve().parent.parent / "packages"
    if built_in:
        if not colrev_packages_dir.is_dir() or not str(current_dir).startswith(
            str(colrev_packages_dir)
        ):
            print(
                "To create a built-in package, "
                "please navigate to a subdirectory of the 'packages' directory:"
                f"\n{colrev_packages_dir}/{Colors.ORANGE}<your-package_name>{Colors.END}"
            )
            return
        if current_dir.name.startswith("colrev."):
            print("The built-in package dir should not start with 'colrev.'")
            return
        default_package_name = f"colrev.{current_dir.name}"

    else:
        if str(current_dir).startswith(str(colrev_packages_dir)):
            print(
                "To create a standalone package, "
                "please navigate to a directory outside of the CoLRev package."
            )
            return

        default_package_name = current_dir.name

    package_data = _get_package_data(default_package_name, built_in)

    _create_pyproject_toml(package_data)
    _create_module_files(package_data)
    _create_src_init(package_data)
    _create_readme(package_data)
    _create_license_file(package_data)
    _create_pre_commit_hooks()
    _create_docs_readme()
    if not built_in:
        _create_git_repo()

    if built_in:
        _add_to_packages_json(package_data)

    # tests
    # gh-actions: pypi-publishing setup
