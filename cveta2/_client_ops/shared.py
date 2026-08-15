"""Shared value objects and helpers for the client-op mixins.

These have no dependency on :class:`cveta2.client.CvatClient`, so both the
fetch mixin and the public ``client`` module can import them without a cycle.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from cveta2.exceptions import CvatApiError
    from cveta2.models import TaskInfo

_HTTP_5XX_MIN = 500
_HTTP_5XX_MAX = 600
_HTTP_TOO_MANY_REQUESTS = 429


@dataclass(frozen=True)
class _FetchAnnotationsOptions:
    """Options for prepare_fetch (filters + display/hint)."""

    completed_only: bool = False
    ignore_task_ids: set[int] | None = None
    silent_task_ids: set[int] | None = None
    task_selector: list[int | str] | None = None
    host: str = ""
    project_name: str = ""


@dataclass(frozen=True)
class FetchContext:
    """Prepared context for per-task annotation fetching.

    Returned by :meth:`CvatClient.prepare_fetch`; passed to
    :meth:`CvatClient.fetch_one_task` for each task in the loop.
    """

    tasks: list[TaskInfo]
    label_names: dict[int, str]
    attr_names: dict[int, str]
    host: str = ""
    project_name: str = ""
    raise_on_failure: bool = False


def _is_rate_limited(e: CvatApiError) -> bool:
    """Report whether *e* is CVAT refusing the call for rate-limiting.

    Rate limiting must never be handled by skipping the task: the retry
    budget is already spent by the time this is asked, and dropping the
    task would silently shrink the dataset for a reason that has nothing to
    do with the task's contents.
    """
    return e.status_code == _HTTP_TOO_MANY_REQUESTS


def _log_task_5xx_skip(
    task: TaskInfo,
    ctx: FetchContext,
    e: CvatApiError,
) -> None:
    """Log 5xx error and ignore-command hint for a skipped task."""
    task_link = (
        f"{ctx.host.rstrip('/')}/tasks/{task.id}"
        if ctx.host
        else f"task_id={task.id} {task.name!r}"
    )
    logger.error(f"CVAT server error (HTTP {e.status_code}) for task {task_link}: {e}")
    if ctx.project_name:
        logger.info(
            f"Чтобы пропустить задачу при следующем запуске: "
            f"cveta2 ignore --project {ctx.project_name!r} --add {task.id}"
        )
    else:
        logger.info(
            f"Чтобы пропустить задачу при следующем запуске: "
            f"cveta2 ignore --project <имя_проекта> --add {task.id}"
        )
