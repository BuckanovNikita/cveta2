"""Interactive prompting for CLI commands — the one place that prompts.

This package is the single owner of every interactive prompt.  Command
modules import handlers from here and never touch ``questionary``, ``input``
or ``getpass`` directly.  The handlers re-exported below form the stable seam
that tests patch (e.g. ``patch("cveta2.commands.interactive.text", ...)``).
"""

from __future__ import annotations

from cveta2.commands.interactive._questionary import Choice
from cveta2.commands.interactive.credentials import prompt_credentials
from cveta2.commands.interactive.entities import (
    build_task_choices,
    pick_tasks,
    select_label,
    select_labels,
    select_project,
    select_project_name,
    select_tasks,
)
from cveta2.commands.interactive.primitives import (
    confirm,
    confirm_or_exit,
    path,
    prompt_password,
    select_many,
    select_one,
    text,
)

__all__ = [
    "Choice",
    "build_task_choices",
    "confirm",
    "confirm_or_exit",
    "path",
    "pick_tasks",
    "prompt_credentials",
    "prompt_password",
    "select_label",
    "select_labels",
    "select_many",
    "select_one",
    "select_project",
    "select_project_name",
    "select_tasks",
    "text",
]
