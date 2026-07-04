"""Annotation fetching: task-selector resolution and per-task pipelines."""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger
from tqdm import tqdm

from cveta2._client.assembly import task_to_records
from cveta2._client.mapping import _build_label_maps
from cveta2._client_ops.base import _ClientBase
from cveta2._client_ops.shared import (
    _HTTP_5XX_MAX,
    _HTTP_5XX_MIN,
    FetchContext,
    _FetchAnnotationsOptions,
    _log_task_5xx_skip,
)
from cveta2.config import should_raise_on_fetch_failure
from cveta2.exceptions import CvatApiError, TaskNotFoundError
from cveta2.models import BBoxAnnotation, ProjectAnnotations, TaskAnnotations

if TYPE_CHECKING:
    from collections.abc import Sequence

    from cveta2._client.ports import CvatApiPort
    from cveta2.models import TaskInfo


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
        names = ", ".join(f"{t.name!r} (id={t.id})" for t in tasks)
        logger.info(f"Selected {len(tasks)} task(s): {names}")
    if options.completed_only:
        tasks = [t for t in tasks if t.status == "completed"]
        logger.trace(f"Filtered to {len(tasks)} completed task(s)")
    return tasks


class _FetchMixin(_ClientBase):
    """Fetch bbox annotations for a project, task by task."""

    def fetch_annotations(  # noqa: PLR0913
        self,
        project_id: int,
        *,
        completed_only: bool = False,
        ignore_task_ids: set[int] | None = None,
        silent_task_ids: set[int] | None = None,
        task_selector: list[int | str] | None = None,
        project_name: str = "",
    ) -> ProjectAnnotations:
        """Fetch all bbox annotations and deleted images from a project.

        If ``completed_only`` is True, only completed tasks are processed.
        Tasks whose IDs are in ``ignore_task_ids`` are silently skipped.
        ``silent_task_ids`` suppresses the skip-warning for those IDs.
        If ``task_selector`` is given (list of task IDs or names), only
        matching tasks are processed.
        """
        options = _FetchAnnotationsOptions(
            completed_only=completed_only,
            ignore_task_ids=ignore_task_ids,
            silent_task_ids=silent_task_ids,
            task_selector=task_selector,
            host=(self._cfg.host or ""),
            project_name=project_name,
        )
        source = self._require_api("fetch_annotations")
        return self._fetch_annotations(source, project_id, options)

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
            host=(self._cfg.host or ""),
            project_name=project_name,
        )
        source = self._require_api("prepare_fetch")
        return self._prepare_fetch(source, project_id, options)

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
        available = ", ".join(f"{t.name!r} (id={t.id})" for t in tasks)
        raise TaskNotFoundError(f"Task not found: {s!r}. Available tasks: {available}")

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
    def _prepare_fetch(
        api: CvatApiPort,
        project_id: int,
        options: _FetchAnnotationsOptions,
    ) -> FetchContext:
        """Get task list and labels, apply filters, return context."""
        tasks = api.get_project_tasks(project_id)
        labels = api.get_project_labels(project_id)
        label_names, attr_names = _build_label_maps(labels)
        tasks = _filter_tasks_for_fetch(tasks, options)
        return FetchContext(
            tasks=tasks,
            label_names=label_names,
            attr_names=attr_names,
            host=options.host,
            project_name=options.project_name,
            raise_on_failure=should_raise_on_fetch_failure(),
        )

    @staticmethod
    def fetch_one_task(
        api: CvatApiPort,
        task: TaskInfo,
        ctx: FetchContext,
    ) -> TaskAnnotations | None:
        """Fetch annotations for a single task via the API port.

        Returns ``None`` when the task was skipped (5xx with
        ``ctx.raise_on_failure`` not set).
        """
        try:
            data_meta = api.get_task_data_meta(task.id)
            annotations = api.get_task_annotations(task.id)
        except CvatApiError as e:
            if _HTTP_5XX_MIN <= e.status_code < _HTTP_5XX_MAX:
                if ctx.raise_on_failure:
                    raise
                _log_task_5xx_skip(task, ctx.host, ctx.project_name, e)
                return None
            raise

        try:
            issues = api.get_task_issues(task.id)
        except CvatApiError as e:
            logger.warning(
                f"Не удалось получить issues задачи {task.id}: {e} — "
                f"колонки issue_text/issue_state останутся пустыми"
            )
            issues = []

        records, deleted = task_to_records(
            task, data_meta, annotations, ctx.label_names, ctx.attr_names, issues
        )
        return TaskAnnotations(
            task_id=task.id,
            task_name=task.name,
            annotations=records,
            deleted_images=deleted,
        )

    @staticmethod
    def _fetch_annotations(
        api: CvatApiPort,
        project_id: int,
        options: _FetchAnnotationsOptions,
    ) -> ProjectAnnotations:
        """Fetch annotations through a ``CvatApiPort`` implementation."""
        ctx = _FetchMixin._prepare_fetch(api, project_id, options)
        if not ctx.tasks:
            logger.warning("No tasks in this project.")
            return ProjectAnnotations(
                annotations=[],
                deleted_images=[],
            )

        task_results: list[TaskAnnotations] = []
        for task in tqdm(ctx.tasks, desc="Processing tasks", unit="task", leave=False):
            result = _FetchMixin.fetch_one_task(api, task, ctx)
            if result is not None:
                task_results.append(result)

        merged = TaskAnnotations.merge(task_results)
        bbox_count = sum(1 for r in merged.annotations if isinstance(r, BBoxAnnotation))
        without_count = len(merged.annotations) - bbox_count
        logger.trace(
            f"Fetched {bbox_count} bbox annotation(s), "
            f"{len(merged.deleted_images)} deleted image(s), "
            f"{without_count} image(s) without annotations",
        )
        return merged
