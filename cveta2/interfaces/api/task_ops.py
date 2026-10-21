"""Public task write APIs and resolve/invalidate context ownership."""

from contextlib import contextmanager
from typing import TYPE_CHECKING

from cveta2.application.client.task_ops import STAGE_OR_STATE_REQUIRED
from cveta2.application.use_cases.resolve import resolve_project_spec
from cveta2.composition.workflows import resolved_task
from cveta2.domain.errors import Cveta2Error
from cveta2.domain.models import JOB_STAGES, JOB_STATES
from cveta2.interfaces.api.connection import _open
from cveta2.interfaces.api.types import (
    Connection,  # noqa: TC001 - Public runtime annotations.
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from cveta2.composition.client import CvatClient
    from cveta2.domain.models import JobStage, JobState, TaskInfo

_ERR_NO_FRAME_OR_IMAGE = "Укажите хотя бы один frame или image."
_JOB_STAGES_HINT = ", ".join(JOB_STAGES)
_JOB_STATES_HINT = ", ".join(JOB_STATES)


@contextmanager
def _resolved_task(
    connection: "Connection | None",
    project: int | str,
    task: int | str,
) -> "Iterator[tuple[CvatClient, TaskInfo]]":
    """Open a client, resolve *project*/*task*, and invalidate the cache on exit.

    Resolves the project without prompting, then hands off to the shared
    scaffold in ``services.task_ops`` that the CLI uses too.
    """
    with _open(connection) as c:
        project_id, project_name = resolve_project_spec(c, project)
        with resolved_task(c, project_id, project_name, task) as task_info:
            yield c, task_info


def task_mark_deleted(
    project: int | str,
    task: int | str,
    *,
    frames: "Iterable[int] | None" = None,
    images: "Iterable[str] | None" = None,
    connection: "Connection | None" = None,
) -> int:
    """Mark frames of a task as deleted (by frame ids and/or image names)."""
    if not frames and not images:
        raise Cveta2Error(_ERR_NO_FRAME_OR_IMAGE)
    with _resolved_task(connection, project, task) as (c, task_info):
        by_name = c.mark_frames_deleted(task_info.id, set(images)) if images else 0
        by_id = c.mark_frames_deleted_by_ids(task_info.id, frames) if frames else 0
        return by_name + by_id


def task_drop_label(
    project: int | str,
    task: int | str,
    label: str,
    *,
    connection: "Connection | None" = None,
) -> int:
    """Delete all annotation shapes with *label* from a task."""
    with _resolved_task(connection, project, task) as (c, task_info):
        return c.drop_label_annotations(task_info.id, label)


def task_delete(
    project: int | str,
    task: int | str,
    *,
    connection: "Connection | None" = None,
) -> None:
    """Delete a CVAT task permanently."""
    with _resolved_task(connection, project, task) as (c, task_info):
        c.delete_task(task_info.id)


def task_set_status(
    project: int | str,
    task: int | str,
    *,
    stage: "JobStage | None" = None,
    state: "JobState | None" = None,
    connection: "Connection | None" = None,
) -> int:
    """Set stage and/or state on every job of a task (CVAT-native values).

    Valid values: :data:`cveta2.JOB_STAGES` / :data:`cveta2.JOB_STATES`.
    """
    if stage is None and state is None:
        raise Cveta2Error(STAGE_OR_STATE_REQUIRED)
    if stage is not None and stage not in JOB_STAGES:
        raise Cveta2Error(
            f"Недопустимый stage {stage!r}; допустимые: {_JOB_STAGES_HINT}."
        )
    if state is not None and state not in JOB_STATES:
        raise Cveta2Error(
            f"Недопустимый state {state!r}; допустимые: {_JOB_STATES_HINT}."
        )
    with _resolved_task(connection, project, task) as (c, task_info):
        return c.set_task_jobs_status(task_info.id, stage=stage, state=state)
