"""Task cache and invalidation contracts owned by the application."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from cveta2.application.ports.dtos import RawAnnotations, RawJob
from cveta2.application.settings import CacheProjectSettings
from cveta2.domain.models import TaskInfo
from cveta2.domain.storage import CloudStorageInfo


@dataclass(frozen=True)
class AnnotationScope:
    """The jobs whose annotations one cache entry holds.

    A job scope holds the shapes of one annotation job. The task scope holds
    the shapes CVAT returns for the whole task and is used when the jobs
    cannot be separated (Ground Truth, consensus or overlapping ranges).
    Either entry is valid only while every job it covers is unchanged.
    """

    jobs: tuple[RawJob, ...]
    whole_task: bool = False

    @property
    def name(self) -> str:
        """Return the entry name inside the task's cache directory."""
        return "task" if self.whole_task else f"job_{self.jobs[0].id}"


class TaskCache(Protocol):
    """Cache raw annotations per job and invalidate stale task entries."""

    def get(self, task: TaskInfo, scope: AnnotationScope) -> RawAnnotations | None:
        """Return the cached shapes of *scope* while task and jobs are unchanged, or a miss."""
        ...

    def put(self, task: TaskInfo, scope: AnnotationScope, annotations: RawAnnotations) -> None:
        """Cache the shapes of *scope* against the current task and jobs."""
        ...

    def keep_only(self, task_id: int, scopes: Sequence[AnnotationScope]) -> None:
        """Drop the task's local entries for jobs or layouts it no longer has."""
        ...

    def invalidate(self, task_id: int, *, strict: bool = False) -> None:
        """Remove every applicable cache copy of a task."""
        ...

    def prune(self, live_task_ids: set[int]) -> int:
        """Remove local entries for tasks absent from the current project."""
        ...

    def remove_legacy_entries(self) -> int:
        """Delete local entries of the old per-task format; return how many."""
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
    """Invalidate the task identity across the applicable cache layers.

    It runs after the remote write has succeeded, so expected cache failures
    are reported as warnings and never raised.
    """

    def __call__(
        self,
        project_id: int,
        task_id: int,
        project_name: str,
        cs_info: CloudStorageInfo | None = None,
    ) -> None:
        """Perform the explicitly supplied outgoing operation."""
        ...
