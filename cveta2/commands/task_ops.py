"""Implementation of the ``cveta2 task`` write operations.

Actions: ``mark-deleted``, ``drop-label``, ``delete``, ``status``.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from loguru import logger

from cveta2.commands import interactive
from cveta2.commands._bootstrap import open_client
from cveta2.commands._helpers import (
    echo_if_prompted,
    project_cli_spec,
    resolve_project,
)
from cveta2.exceptions import Cveta2Error
from cveta2.services.task_ops import resolved_task

if TYPE_CHECKING:
    import argparse
    from collections.abc import Iterator

    from cveta2.client import CvatClient
    from cveta2.models import JobState, TaskInfo

STATE_CLI_TO_CVAT: dict[str, JobState] = {
    "new": "new",
    "in-progress": "in progress",
    "completed": "completed",
    "rejected": "rejected",
}
"""Mapping from CLI ``--state`` values to CVAT job state values."""


_CONFIRM_HINT = "Запустите команду с флагом --yes."


@contextmanager
def _task_session(
    args: argparse.Namespace,
) -> Iterator[tuple[CvatClient, TaskInfo, str]]:
    """Open a client, resolve ``--project``/``--task``, invalidate cache on exit.

    Yields ``(client, task, project_name)``.  Only the prompting project
    resolution is local; the resolve-and-invalidate scaffold is the one
    ``api`` uses, so the two cannot drift on it.
    """
    with open_client() as client:
        project_id, project_name = resolve_project(client, args.project)
        with resolved_task(client, project_id, project_name, args.task) as task:
            yield client, task, project_name


def run_task_mark_deleted(args: argparse.Namespace) -> None:
    """Run ``cveta2 task mark-deleted``."""
    frames: list[int] = args.frame or []
    images: list[str] = args.image or []
    if not frames and not images:
        raise Cveta2Error("Ошибка: укажите хотя бы один --frame или --image.")

    with _task_session(args) as (client, task, project_name):
        prompted = not args.project
        echo_if_prompted(
            "task mark-deleted",
            {
                "-p": project_cli_spec(client, project_name),
                "-t": args.task,
                "--frame": frames,
                "--image": images,
            },
            prompted=prompted,
        )
        marked = 0
        if images:
            marked += client.mark_frames_deleted(task.id, set(images))
        if frames:
            marked += client.mark_frames_deleted_by_ids(task.id, frames)
        logger.info(
            f"Задача {task.name!r} (id={task.id}): помечено удалёнными кадров: {marked}"
        )


def run_task_drop_label(args: argparse.Namespace) -> None:
    """Run ``cveta2 task drop-label``."""
    with _task_session(args) as (client, task, project_name):
        count = client.count_task_label_shapes(task.id, args.label)
        if count == 0:
            logger.info(
                f"В задаче {task.name!r} (id={task.id}) "
                f"нет аннотаций с меткой {args.label!r}."
            )
            return
        interactive.confirm_or_exit(
            f"Удалить {count} аннотаций с меткой {args.label!r} "
            f"из задачи {task.name!r} (id={task.id})?",
            yes=args.yes,
            hint=_CONFIRM_HINT,
        )
        prompted = not args.project or not args.yes
        echo_if_prompted(
            "task drop-label",
            {
                "-p": project_cli_spec(client, project_name),
                "-t": args.task,
                "--label": args.label,
                "--yes": True,
            },
            prompted=prompted,
        )
        deleted = client.drop_label_annotations(task.id, args.label)
        logger.info(
            f"Задача {task.name!r} (id={task.id}): удалено аннотаций: {deleted}"
        )


def run_task_delete(args: argparse.Namespace) -> None:
    """Run ``cveta2 task delete``."""
    with _task_session(args) as (client, task, project_name):
        interactive.confirm_or_exit(
            f"Удалить задачу {task.name!r} (id={task.id}) безвозвратно?",
            yes=args.yes,
            hint=_CONFIRM_HINT,
        )
        prompted = not args.project or not args.yes
        echo_if_prompted(
            "task delete",
            {
                "-p": project_cli_spec(client, project_name),
                "-t": args.task,
                "--yes": True,
            },
            prompted=prompted,
        )
        client.delete_task(task.id)
        logger.info(f"Задача {task.name!r} (id={task.id}) удалена.")


def run_task_status(args: argparse.Namespace) -> None:
    """Run ``cveta2 task status``."""
    if args.stage is None and args.state is None:
        raise Cveta2Error("Ошибка: укажите хотя бы один --stage или --state.")
    state = STATE_CLI_TO_CVAT[args.state] if args.state else None

    with _task_session(args) as (client, task, project_name):
        prompted = not args.project
        echo_if_prompted(
            "task status",
            {
                "-p": project_cli_spec(client, project_name),
                "-t": args.task,
                "--stage": args.stage,
                "--state": args.state,
            },
            prompted=prompted,
        )
        num_jobs = client.set_task_jobs_status(task.id, stage=args.stage, state=state)
        logger.info(
            f"Задача {task.name!r} (id={task.id}): обновлено jobs: {num_jobs} "
            f"(stage={args.stage or '-'}, state={state or '-'})"
        )
