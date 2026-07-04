"""Read-only CVAT queries: projects, tasks, labels and cloud storage."""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger
from tqdm import tqdm

from cveta2._client_ops.base import _ClientBase
from cveta2.exceptions import CvatApiError, ProjectNotFoundError

if TYPE_CHECKING:
    from cveta2.image_downloader import CloudStorageInfo
    from cveta2.models import LabelInfo, ProjectInfo, TaskInfo


class _ReadMixin(_ClientBase):
    """List projects/tasks/labels and detect a project's cloud storage."""

    def list_projects(self) -> list[ProjectInfo]:
        """Fetch list of projects from CVAT (id and name)."""
        return self._require_api("list_projects").list_projects()

    def list_project_tasks(self, project_id: int) -> list[TaskInfo]:
        """Fetch the list of tasks for a project from CVAT."""
        return self._require_api("list_project_tasks").get_project_tasks(project_id)

    def list_tasks_completed_after(
        self,
        project_id: int,
        cutoff: str,
    ) -> list[TaskInfo]:
        """List completed project tasks updated strictly after *cutoff*.

        *cutoff* and task ``updated_date`` values are normalized ISO
        strings (see ``_extract_updated_date`` in the SDK adapter), so
        lexicographic comparison matches chronological order.  Tasks
        without an ``updated_date`` are treated as not-newer.  The result
        is sorted by ``updated_date`` ascending.
        """
        tasks = self.list_project_tasks(project_id)
        newer = [
            t
            for t in tasks
            if t.status == "completed" and t.updated_date and t.updated_date > cutoff
        ]
        return sorted(newer, key=lambda t: t.updated_date)

    def get_project_labels(self, project_id: int) -> list[LabelInfo]:
        """Fetch label definitions for a project from CVAT."""
        return self._require_api("get_project_labels").get_project_labels(project_id)

    def count_label_usage(self, project_id: int) -> dict[int, int]:
        """Count annotations per label across all project tasks.

        Returns a mapping ``{label_id: annotation_count}``.
        Used to warn before label deletion.
        """
        source = self._require_api("count_label_usage")
        tasks = source.get_project_tasks(project_id)
        counts: dict[int, int] = {}
        skipped: list[int] = []
        for task in tqdm(tasks, desc="Checking annotations", unit="task", leave=False):
            try:
                annotations = source.get_task_annotations(task.id)
            except CvatApiError:
                logger.warning(
                    f"Не удалось получить аннотации задачи {task.id},"
                    " подсчёт меток может быть неполным",
                )
                skipped.append(task.id)
                continue
            for shape in annotations.shapes:
                counts[shape.label_id] = counts.get(shape.label_id, 0) + 1
        if skipped:
            logger.warning(f"Пропущено задач при подсчёте меток: {skipped}")
        return counts

    def resolve_project_id(
        self,
        project_spec: int | str,
        *,
        cached: list[ProjectInfo] | None = None,
    ) -> int:
        """Resolve project id from numeric id or project name.

        If project_spec is int or digit string, returns it as int.
        If it is a name, looks in cached list first, then via API.
        """
        if isinstance(project_spec, int):
            return project_spec
        s = str(project_spec).strip()
        if s.isdigit():
            return int(s)
        search = s.casefold()
        if cached:
            for p in cached:
                if (p.name or "").casefold() == search:
                    return p.id
        projects = self.list_projects()
        for p in projects:
            if (p.name or "").casefold() == search:
                return p.id
        raise ProjectNotFoundError(f"Project not found: {s!r}")

    def detect_project_cloud_storage(
        self,
        project_id: int,
    ) -> CloudStorageInfo | None:
        """Detect cloud storage for a project from the project's source_storage.

        Returns the :class:`CloudStorageInfo` from the project's own
        ``source_storage.cloud_storage_id`` (ProjectRead API), or ``None``
        if the project has no source_storage.

        Requires an active context manager (``with CvatClient(...) as c:``).
        """
        api = self._require_api("detect_project_cloud_storage")
        return api.get_project_cloud_storage(project_id)
