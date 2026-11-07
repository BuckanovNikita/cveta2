"""Shared value objects and helpers for the client-op mixins.

These have no dependency on :class:`cveta2.composition.client.CvatClient`, so both the
fetch mixin and the public ``client`` module can import them without a cycle.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from cveta2.domain.errors import CvatApiError
    from cveta2.domain.models import TaskInfo

_HTTP_5XX_MIN = 500
_HTTP_5XX_MAX = 600
_HTTP_TOO_MANY_REQUESTS = 429
_HTTP_NOT_FOUND = 404


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
    ``all_task_ids`` is the unfiltered inventory snapshot, or ``None`` when
    only individually selected tasks were retrieved. An empty snapshot is
    complete and can safely prune every orphaned cache entry.
    """

    tasks: "list[TaskInfo]"
    label_names: dict[int, str]
    attr_names: dict[int, str]
    host: str = ""
    project_name: str = ""
    raise_on_failure: bool = False
    all_task_ids: frozenset[int] | None = None


def _is_rate_limited(e: "CvatApiError") -> bool:
    """Report whether *e* is CVAT refusing the call for rate-limiting.

    Rate limiting must never be handled by skipping the task: the retry
    budget is already spent by the time this is asked, and dropping the
    task would silently shrink the dataset for a reason that has nothing to
    do with the task's contents.
    """
    return e.status_code == _HTTP_TOO_MANY_REQUESTS


def _log_task_5xx_skip(
    task: "TaskInfo",
    ctx: FetchContext,
    e: "CvatApiError",
) -> None:
    """Log 5xx error and ignore-command hint for a skipped task."""
    # Transport diagnostics already contain the sanitized endpoint. Rebuilding
    # a link from the configured host could expose URL credentials or queries.
    logger.error(f"Ошибка CVAT (HTTP {e.status_code}), задача #{task.id} {task.name!r} пропущена: {e}")
    if ctx.project_name:
        logger.info(
            f"Чтобы пропустить задачу при следующем запуске: "
            f"cveta2 ignore --project {ctx.project_name!r} --add {task.id}"
        )
    else:
        logger.info(
            f"Чтобы пропустить задачу при следующем запуске: cveta2 ignore --project <имя_проекта> --add {task.id}"
        )
