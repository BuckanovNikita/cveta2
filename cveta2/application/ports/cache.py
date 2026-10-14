"""Task cache and invalidation contracts owned by the application."""

from typing import Protocol

from cveta2.application.settings import CacheProjectSettings
from cveta2.domain.models import TaskAnnotations, TaskInfo
from cveta2.domain.storage import CloudStorageInfo


class TaskCache(Protocol):
    """Cache completed annotations and invalidate stale task entries."""

    def get(self, task: TaskInfo) -> TaskAnnotations | None:
        """Return a valid cached task payload or a miss."""
        ...

    def put(self, task: TaskInfo, result: TaskAnnotations) -> None:
        """Cache the completed annotation payload for this task."""
        ...

    def invalidate(self, task_id: int, *, strict: bool = False) -> None:
        """Remove every applicable cache copy of a task."""
        ...

    def prune(self, live_task_ids: set[int]) -> int:
        """Remove local entries for tasks absent from the current project."""
        ...


class CacheFactory(Protocol):
    """Create caches from explicit project storage and settings."""

    def create(
        self,
        project_id: int,
        cs_info: CloudStorageInfo | None,
        settings: CacheProjectSettings,
        *,
        local_only: bool = False,
    ) -> TaskCache:
        """Build a project cache, optionally restricting it to local files."""
        ...


class CacheInvalidator(Protocol):
    """Invalidate the task identity across the applicable cache layers."""

    def __call__(
        self,
        project_id: int,
        task_id: int,
        project_name: str,
        cs_info: CloudStorageInfo | None = None,
    ) -> None:
        """Perform the explicitly supplied outgoing operation."""
        ...
