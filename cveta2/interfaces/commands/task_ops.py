"""Implementation of the ``cveta2 task`` write operations.

Actions: ``mark-deleted``, ``drop-label``, ``delete``, ``status``.
"""

from contextlib import contextmanager
from typing import TYPE_CHECKING

from loguru import logger

from cveta2.composition.workflows import resolved_task
from cveta2.domain.errors import Cveta2Error
from cveta2.domain.models import JOB_STAGES
from cveta2.interfaces.commands import interactive
from cveta2.interfaces.commands._bootstrap import open_client
from cveta2.interfaces.commands._helpers import (
    echo_if_prompted,
    project_cli_spec,
    resolve_project,
)
from cveta2.interfaces.commands._parsers import add_project_arg

if TYPE_CHECKING:
    import argparse
    from collections.abc import Iterator

    from cveta2.composition.client import CvatClient
    from cveta2.domain.models import JobState, TaskInfo

STATE_CLI_TO_CVAT: "dict[str, JobState]" = {
    "new": "new",
    "in-progress": "in progress",
    "completed": "completed",
    "rejected": "rejected",
}
"""Mapping from CLI ``--state`` values to CVAT job state values."""


_CONFIRM_HINT = "Запустите команду с флагом --yes."


def _add_task_common_args(parser: "argparse.ArgumentParser") -> None:
    """Add ``--project`` / ``--task`` arguments shared by task actions."""
    add_project_arg(parser)
    parser.add_argument(
        "--task",
        "-t",
        type=str,
        required=True,
        help="Task ID or name.",
    )


def configure_task_mark_deleted(parser: "argparse.ArgumentParser") -> None:
    """Declare the ``task-mark-deleted`` command arguments."""
    _add_task_common_args(parser)
    parser.add_argument(
        "--frame",
        nargs="+",
        type=int,
        default=None,
        metavar="N",
        help="Frame ID(s) to mark as deleted: --frame 1 2.",
    )
    parser.add_argument(
        "--image",
        nargs="+",
        type=str,
        default=None,
        metavar="NAME",
        help="Image name(s) to mark as deleted: --image a.jpg b.jpg.",
    )


def configure_task_drop_label(parser: "argparse.ArgumentParser") -> None:
    """Declare the ``task-drop-label`` command arguments."""
    _add_task_common_args(parser)
    parser.add_argument(
        "--label",
        required=True,
        help="Label name whose annotations will be deleted.",
    )
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Skip the confirmation prompt.",
    )


def configure_task_delete(parser: "argparse.ArgumentParser") -> None:
    """Declare the ``task-delete`` command arguments."""
    _add_task_common_args(parser)
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Skip the confirmation prompt.",
    )


def configure_task_status(parser: "argparse.ArgumentParser") -> None:
    """Declare the ``task-status`` command arguments."""
    _add_task_common_args(parser)
    parser.add_argument(
        "--stage",
        choices=JOB_STAGES,
        default=None,
        help="Job stage to set on every job of the task.",
    )
    parser.add_argument(
        "--state",
        choices=sorted(STATE_CLI_TO_CVAT),
        default=None,
        help="Job state to set on every job of the task.",
    )


@contextmanager
def _task_session(
    args: "argparse.Namespace",
) -> "Iterator[tuple[CvatClient, TaskInfo, str]]":
    """Open a client, resolve ``--project``/``--task``, invalidate cache on exit.

    Yields ``(client, task, project_name)``.  Only the prompting project
    resolution is local; the resolve-and-invalidate scaffold is the one
    ``api`` uses, so the two cannot drift on it.
    """
    with open_client() as client:
        project_id, project_name = resolve_project(client, args.project)
        with resolved_task(client, project_id, project_name, args.task) as task:
            yield client, task, project_name


def run_task_mark_deleted(args: "argparse.Namespace") -> None:
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


def run_task_drop_label(args: "argparse.Namespace") -> None:
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


def run_task_delete(args: "argparse.Namespace") -> None:
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


def run_task_status(args: "argparse.Namespace") -> None:
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
