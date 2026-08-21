"""Read-only CVAT queries: projects, tasks, labels and cloud storage."""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger
from tqdm import tqdm

from cveta2._client_ops.base import _ClientBase
from cveta2.exceptions import CvatApiError, ProjectNotFoundError

if TYPE_CHECKING:
    from cveta2.image_downloader import CloudStorageInfo
    from cveta2.models import LabelInfo, OrganizationInfo, ProjectInfo, TaskInfo


class _ReadMixin(_ClientBase):
    """List projects/tasks/labels and detect a project's cloud storage."""

    def list_organizations(self) -> list[OrganizationInfo]:
        """Fetch the list of organizations the user is a member of."""
        return self._require_api("list_organizations").list_organizations()

    def list_projects(self) -> list[ProjectInfo]:
        """Fetch list of projects from CVAT (id and name)."""
        return self._require_api("list_projects").list_projects()

    def get_project(self, project_id: int) -> ProjectInfo:
        """Fetch one project by id (id and name)."""
        return self._require_api("get_project").get_project(project_id)

    def list_project_tasks(self, project_id: int) -> list[TaskInfo]:
        """Fetch the list of tasks for a project from CVAT."""
        return self._require_api("list_project_tasks").get_project_tasks(project_id)

    def get_task(self, task_id: int) -> TaskInfo:
        """Fetch one task by id (includes its ``project_id``)."""
        return self._require_api("get_task").get_task(task_id)

    def get_task_size(self, task_id: int) -> int:
        """Return how many frames a task holds.

        ``upload --resume`` compares this against the frame list it meant
        to upload: it is how a task whose data attach never finished is
        told apart from one where only the reply was lost.
        """
        return self._require_api("get_task_size").get_task_size(task_id)

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
                if p.name.casefold() == search:
                    return p.id
        projects = self.list_projects()
        for p in projects:
            if p.name.casefold() == search:
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

        The answer is remembered for the client's lifetime: it costs two
        requests, a fetch asks for it twice (the image download applies
        the sync-root override to it, the shared task cache deliberately
        does not), and a project's storage does not change mid-run.

        Requires an active context manager (``with CvatClient(...) as c:``).
        """
        if project_id in self._cloud_storage_memo:
            return self._cloud_storage_memo[project_id]
        api = self._require_api("detect_project_cloud_storage")
        cloud_storage = api.get_project_cloud_storage(project_id)
        self._cloud_storage_memo[project_id] = cloud_storage
        return cloud_storage
