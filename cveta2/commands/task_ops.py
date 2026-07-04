"""Implementation of the ``cveta2 task`` write operations.

Actions: ``mark-deleted``, ``drop-label``, ``delete``, ``status``.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from loguru import logger

from cveta2.commands import interactive
from cveta2.commands._bootstrap import open_client
from cveta2.commands._helpers import resolve_project
from cveta2.config import is_interactive_disabled
from cveta2.exceptions import TaskNotFoundError
from cveta2.task_cache import invalidate_local_entry

if TYPE_CHECKING:
    import argparse

    from cveta2.client import CvatClient
    from cveta2.models import TaskInfo

STATE_CLI_TO_CVAT: dict[str, str] = {
    "new": "new",
    "in-progress": "in progress",
    "completed": "completed",
    "rejected": "rejected",
}
"""Mapping from CLI ``--state`` values to CVAT job state values."""

JOB_STAGES: list[str] = ["annotation", "validation", "acceptance"]
"""Valid CVAT job stages for the CLI ``--stage`` choices."""


def _confirm_or_exit(prompt: str, *, yes: bool) -> None:
    """Ask for confirmation before a destructive operation.

    Proceeds silently when *yes* is set.  In noninteractive mode
    (``CVETA2_NO_INTERACTIVE=true``) exits with a hint to pass ``--yes``.
    Otherwise asks a y/N question and exits unless the answer is yes.
    """
    if yes:
        return
    if is_interactive_disabled():
        sys.exit(
            "Ошибка: требуется подтверждение, но интерактивный режим отключён. "
            "Запустите команду с флагом --yes."
        )
    if not interactive.confirm(
        f"{prompt} [y/N]",
        hint="Run the command with --yes to skip confirmation.",
    ):
        sys.exit("Отменено.")


def _resolve_single_task(
    client: CvatClient,
    project_id: int,
    selector: str,
) -> TaskInfo:
    """Resolve a single ``--task`` selector (ID or name) to a task."""
    tasks = client.list_project_tasks(project_id)
    try:
        matched = client.resolve_task_selectors(tasks, [selector])
    except TaskNotFoundError as e:
        sys.exit(str(e))
    return matched[0]


def run_task_mark_deleted(args: argparse.Namespace) -> None:
    """Run ``cveta2 task mark-deleted``."""
    frames: list[int] = args.frame or []
    images: list[str] = args.image or []
    if not frames and not images:
        sys.exit("Ошибка: укажите хотя бы один --frame или --image.")

    with open_client() as client:
        project_id, _ = resolve_project(args.project, client)
        task = _resolve_single_task(client, project_id, args.task)
        marked = 0
        if images:
            marked += client.mark_frames_deleted(task.id, set(images))
        if frames:
            marked += client.mark_frames_deleted_by_ids(task.id, frames)
        invalidate_local_entry(project_id, task.id)
        logger.info(
            f"Задача {task.name!r} (id={task.id}): помечено удалёнными кадров: {marked}"
        )


def run_task_drop_label(args: argparse.Namespace) -> None:
    """Run ``cveta2 task drop-label``."""
    with open_client() as client:
        project_id, _ = resolve_project(args.project, client)
        task = _resolve_single_task(client, project_id, args.task)
        try:
            count = client.count_task_label_shapes(task.id, args.label)
        except ValueError as e:
            sys.exit(str(e))
        if count == 0:
            logger.info(
                f"В задаче {task.name!r} (id={task.id}) "
                f"нет аннотаций с меткой {args.label!r}."
            )
            return
        _confirm_or_exit(
            f"Удалить {count} аннотаций с меткой {args.label!r} "
            f"из задачи {task.name!r} (id={task.id})?",
            yes=args.yes,
        )
        deleted = client.drop_label_annotations(task.id, args.label)
        invalidate_local_entry(project_id, task.id)
        logger.info(
            f"Задача {task.name!r} (id={task.id}): удалено аннотаций: {deleted}"
        )


def run_task_delete(args: argparse.Namespace) -> None:
    """Run ``cveta2 task delete``."""
    with open_client() as client:
        project_id, _ = resolve_project(args.project, client)
        task = _resolve_single_task(client, project_id, args.task)
        _confirm_or_exit(
            f"Удалить задачу {task.name!r} (id={task.id}) безвозвратно?",
            yes=args.yes,
        )
        client.delete_task(task.id)
        invalidate_local_entry(project_id, task.id)
        logger.info(f"Задача {task.name!r} (id={task.id}) удалена.")


def run_task_status(args: argparse.Namespace) -> None:
    """Run ``cveta2 task status``."""
    if args.stage is None and args.state is None:
        sys.exit("Ошибка: укажите хотя бы один --stage или --state.")
    state = STATE_CLI_TO_CVAT[args.state] if args.state else None

    with open_client() as client:
        project_id, _ = resolve_project(args.project, client)
        task = _resolve_single_task(client, project_id, args.task)
        num_jobs = client.set_task_jobs_status(task.id, stage=args.stage, state=state)
        invalidate_local_entry(project_id, task.id)
        logger.info(
            f"Задача {task.name!r} (id={task.id}): обновлено jobs: {num_jobs} "
            f"(stage={args.stage or '-'}, state={state or '-'})"
        )
