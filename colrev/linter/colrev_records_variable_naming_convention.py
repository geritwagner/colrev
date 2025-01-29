#!/usr/bin/env python3
"""Linter for CoLRev - records variable naming convention"""
from __future__ import annotations

import typing

from astroid import nodes
from pylint import checkers
from pylint.checkers.utils import only_required_for_messages


if typing.TYPE_CHECKING:  # pragma: no cover
    from pylint.lint import PyLinter


class RecordsVariableNamingConventionChecker(checkers.BaseChecker):
    """RecordsVariableNamingConvention"""

    name = "colrev-records-variable-naming-convention"

    msgs = {
        "W0934": (
            "Records variable not named according to convention",
            "colrev-records-variable-naming-convention",
            "Emitted when the records variable is not named according to convention",
        ),
    }

    @only_required_for_messages("colrev-records-variable-naming-convention")
    def visit_assign(self, node: nodes.Assign) -> None:
        """
        Detect colrev-records-variable-naming-convention.
        """

        if len(node.targets) != 1:  # pragma: no cover
            return

        assigned = node.value

        if (
            not hasattr(assigned, "func")
            or not isinstance(assigned.func, nodes.Attribute)
            or assigned.func.attrname != "load_records_dict"
            or len(node.targets) != 1
            or not hasattr(node.targets[0], "name")
        ):
            return

        if hasattr(assigned, "keywords"):
            for keyword in assigned.keywords:
                if keyword.arg == "header_only":
                    if keyword.value.value is True:
                        if node.targets[0].name != "records_headers":
                            self.add_message(self.name, node=node)
                    else:
                        if not node.targets[0].name.endswith("records"):
                            self.add_message(self.name, node=node)
                    return

        if not node.targets[0].name.endswith("records"):
            self.add_message(self.name, node=node)


def register(linter: PyLinter) -> None:  # pragma: no cover
    """required method to auto register this checker"""

    linter.register_checker(RecordsVariableNamingConventionChecker(linter))
