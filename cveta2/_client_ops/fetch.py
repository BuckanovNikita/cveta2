"""Annotation fetching: task-selector resolution and per-task pipelines."""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from cveta2._client.assembly import task_to_records
from cveta2._client.mapping import _build_label_maps
from cveta2._client_ops.base import _ClientBase
from cveta2._client_ops.shared import (
    _HTTP_5XX_MAX,
    _HTTP_5XX_MIN,
    _HTTP_NOT_FOUND,
    FetchContext,
    _FetchAnnotationsOptions,
    _is_rate_limited,
    _log_task_5xx_skip,
)
from cveta2._concurrency import Workers, run_concurrent
from cveta2.config import should_raise_on_fetch_failure
from cveta2.exceptions import CvatApiError, Cveta2Error, TaskNotFoundError
from cveta2.models import TaskAnnotations, TaskInfo

if TYPE_CHECKING:
    from collections.abc import Sequence

    from cveta2._client.ports import CvatApiPort


def _format_task_choices(tasks: Sequence[TaskInfo]) -> str:
    """Render ``'name' (id=N)`` per task, comma-separated, for humans."""
    return ", ".join(f"{t.name!r} (id={t.id})" for t in tasks)


def _filter_tasks_for_fetch(
    tasks: list[TaskInfo],
    options: _FetchAnnotationsOptions,
) -> list[TaskInfo]:
    """Apply ignore list, task selector, completed_only; return filtered list."""
    if options.ignore_task_ids:
        skipped = [t for t in tasks if t.id in options.ignore_task_ids]
        silent_ids = options.silent_task_ids or set()
        logged = [t for t in skipped if t.id not in silent_ids]
        if logged:
            logger.warning(f"Пропускаем {len(logged)} задач(а) из ignore-списка:")
            for t in logged:
                logger.warning(f"  - #{t.id} {t.name!r} (обновлена: {t.updated_date})")
        tasks = [t for t in tasks if t.id not in options.ignore_task_ids]
    if options.task_selector is not None:
        tasks = _FetchMixin.resolve_task_selectors(tasks, options.task_selector)
        logger.info(
            f"Selected {len(tasks)} task(s): {_format_task_choices(tasks)}",
        )
    if options.completed_only:
        tasks = [t for t in tasks if t.status == "completed"]
        logger.trace(f"Filtered to {len(tasks)} completed task(s)")
    return tasks


def _numeric_selector_ids(
    selectors: Sequence[int | str] | None,
) -> list[int] | None:
    """Return *selectors* as unique task ids, or None if any names a task."""
    if not selectors:
        return None
    ids: list[int] = []
    for selector in selectors:
        text = str(selector).strip()
        if not (isinstance(selector, int) or text.isdigit()):
            return None
        ids.append(int(text))
    return list(dict.fromkeys(ids))


def _get_task_if_present(api: CvatApiPort, task_id: int) -> TaskInfo | None:
    """Return the task, or None when CVAT has no task with that id."""
    try:
        return api.get_task(task_id)
    except CvatApiError as e:
        if e.status_code == _HTTP_NOT_FOUND:
            return None
        raise


def _resolve_selected_tasks_by_id(
    api: CvatApiPort,
    project_id: int,
    options: _FetchAnnotationsOptions,
) -> list[TaskInfo] | None:
    """Retrieve the selected tasks one by one, or None to list the project.

    Listing every task of a project to pick one out of it is the largest
    fixed cost of a task fetch, and it grows with the project rather than
    with the request: the CVAT SDK pages that listing serially.  When the
    caller named tasks by id there is nothing to search — ``get_task``
    answers each selector in a single request.

    ``None`` means the full list is needed after all, which restores the
    listing path together with its error messages.  Each such case is an
    error or a skip — an unknown id may still match a task *name*, a task
    from another project or an ignored one must raise rather than fetch —
    so no run that goes on to download anything pays for the listing.
    """
    task_ids = _numeric_selector_ids(options.task_selector)
    if task_ids is None:
        return None
    if options.ignore_task_ids and not options.ignore_task_ids.isdisjoint(task_ids):
        return None
    outcomes = run_concurrent(
        task_ids,
        lambda task_id: _get_task_if_present(api, task_id),
        max_workers=Workers.cvat,
        catch=(),
        desc="Resolving tasks",
        unit="task",
    )
    tasks = [outcome for outcome in outcomes if isinstance(outcome, TaskInfo)]
    if len(tasks) != len(task_ids):
        return None
    if any(task.project_id != project_id for task in tasks):
        return None
    return tasks


def _select_tasks_for_fetch(
    api: CvatApiPort,
    project_id: int,
    options: _FetchAnnotationsOptions,
) -> list[TaskInfo]:
    """Return the tasks to fetch, listing the project only when needed.

    The filters run over the shortlist exactly as they run over the full
    list: resolving the selectors against tasks that *are* the selection
    is a no-op, and an ignored id never reaches here (it is one of the
    cases that falls back).
    """
    selected = _resolve_selected_tasks_by_id(api, project_id, options)
    if selected is None:
        selected = api.get_project_tasks(project_id)
    return _filter_tasks_for_fetch(selected, options)


class _FetchMixin(_ClientBase):
    """Fetch bbox annotations for a project, task by task."""

    def prepare_fetch(  # noqa: PLR0913
        self,
        project_id: int,
        *,
        completed_only: bool = False,
        ignore_task_ids: set[int] | None = None,
        silent_task_ids: set[int] | None = None,
        task_selector: list[int | str] | None = None,
        project_name: str = "",
    ) -> FetchContext:
        """Prepare fetch context: get task list, labels, apply filters.

        The returned :class:`FetchContext` holds the filtered task list
        and label maps.  Pass it to :meth:`fetch_one_task` for each task.
        """
        options = _FetchAnnotationsOptions(
            completed_only=completed_only,
            ignore_task_ids=ignore_task_ids,
            silent_task_ids=silent_task_ids,
            task_selector=task_selector,
            host=self._cfg.host,
            project_name=project_name,
        )
        api = self._require_api("prepare_fetch")
        tasks = _select_tasks_for_fetch(api, project_id, options)
        label_names, attr_names = _build_label_maps(api.get_project_labels(project_id))
        return FetchContext(
            tasks=tasks,
            label_names=label_names,
            attr_names=attr_names,
            host=options.host,
            project_name=options.project_name,
            raise_on_failure=should_raise_on_fetch_failure(),
        )

    @staticmethod
    def _resolve_one_task_selector(
        tasks: list[TaskInfo],
        selector: int | str,
    ) -> TaskInfo:
        """Resolve a single task selector (ID or name) to a task.

        Numeric strings and ints match by task ID first, then by name.
        Non-numeric strings match by name (case-insensitive).
        Raises ``TaskNotFoundError`` when no task matches.
        """
        s = str(selector).strip()
        if s.isdigit():
            task_id = int(s)
            for t in tasks:
                if t.id == task_id:
                    return t
        search = s.casefold()
        for t in tasks:
            if t.name.casefold() == search:
                return t
        raise TaskNotFoundError(
            f"Task not found: {s!r}. Available tasks: {_format_task_choices(tasks)}"
        )

    @staticmethod
    def resolve_task_selectors(
        tasks: list[TaskInfo],
        selectors: Sequence[int | str],
    ) -> list[TaskInfo]:
        """Resolve a list of task selectors to matching tasks.

        Each selector is resolved independently via
        ``_resolve_one_task_selector``.  Duplicates (same task matched
        by different selectors) are removed, preserving order.
        """
        seen_ids: set[int] = set()
        matched: list[TaskInfo] = []
        for sel in selectors:
            task = _FetchMixin._resolve_one_task_selector(tasks, sel)
            if task.id not in seen_ids:
                seen_ids.add(task.id)
                matched.append(task)
        return matched

    @staticmethod
    def fetch_one_task(
        api: CvatApiPort,
        task: TaskInfo,
        ctx: FetchContext,
    ) -> TaskAnnotations | None:
        """Fetch annotations for a single task via the API port.

        The jobs request is not optional the way issues are: ``job_stage``
        and ``job_state`` are what the partition reads to tell a finished
        task from one still being annotated, so a task whose jobs cannot be
        read is skipped rather than emitted as unreviewed.

        Returns ``None`` when the task was skipped (5xx with
        ``ctx.raise_on_failure`` not set).
        """
        try:
            data_meta = api.get_task_data_meta(task.id)
            annotations = api.get_task_annotations(task.id)
            jobs = api.get_task_jobs(task.id)
        except CvatApiError as e:
            if _is_rate_limited(e):
                msg = (
                    f"CVAT ограничивает частоту запросов (HTTP {e.status_code}) "
                    f"на задаче {task.id}, повторы исчерпаны. Задача НЕ пропущена, "
                    f"чтобы датасет не потерял её молча — уменьшите "
                    f"network.cvat_workers и повторите запуск."
                )
                raise Cveta2Error(msg) from e
            if _HTTP_5XX_MIN <= e.status_code < _HTTP_5XX_MAX:
                if ctx.raise_on_failure:
                    raise
                _log_task_5xx_skip(task, ctx, e)
                return None
            raise

        issues_complete = True
        try:
            issues = api.get_task_issues(task.id)
        except CvatApiError as e:
            logger.warning(
                f"Не удалось получить issues задачи {task.id}: {e} — "
                f"колонки issue_text/issue_state останутся пустыми"
            )
            issues = []
            issues_complete = False

        records, deleted = task_to_records(
            task, data_meta, annotations, ctx.label_names, ctx.attr_names, issues, jobs
        )
        return TaskAnnotations(
            task_id=task.id,
            task_name=task.name,
            annotations=records,
            deleted_images=deleted,
            issues_complete=issues_complete,
        )
