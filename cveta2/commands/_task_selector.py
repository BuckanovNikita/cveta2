"""Shared task-selection helpers (TUI checkbox, choice builders)."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import questionary

from cveta2.config import require_interactive

if TYPE_CHECKING:
    from cveta2.client import CvatClient
    from cveta2.models import TaskInfo


def build_task_choices(
    tasks: list[TaskInfo],
) -> list[questionary.Choice]:
    """Build questionary choices from a task list."""
    return [
        questionary.Choice(
            title=t.format_display(),
            value=t.id,
        )
        for t in tasks
    ]


def select_tasks_tui(
    client: CvatClient,
    project_id: int,
    exclude_ids: set[int] | None = None,
) -> list[TaskInfo]:
    """Interactive multi-task selection via TUI checkbox.

    Returns full ``TaskInfo`` objects so callers can access ``.id`` and ``.name``.
    Tasks whose IDs are in *exclude_ids* are hidden from the list.
    """
    require_interactive(
        "Pass task ID(s) or name(s) with --task / -t to specify task(s)."
    )
    tasks = client.list_project_tasks(project_id)
    if exclude_ids:
        tasks = [t for t in tasks if t.id not in exclude_ids]
    if not tasks:
        sys.exit("Нет доступных задач в этом проекте.")

    choices = build_task_choices(tasks)
    answer = questionary.checkbox(
        "Выберите задачу (задачи):",
        choices=choices,
        use_jk_keys=False,
        use_search_filter=True,
    ).ask()
    if answer is None:
        sys.exit("Выбор отменён.")

    selected_ids: set[int] = {int(v) for v in answer}
    if not selected_ids:
        sys.exit("Задачи не выбраны.")

    tasks_by_id = {t.id: t for t in tasks}
    return [tasks_by_id[tid] for tid in selected_ids if tid in tasks_by_id]
