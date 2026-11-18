"""Read task annotations through the per-job annotation cache.

Only raw shapes are cached; records, completion and job positions are
rebuilt from the fresh jobs list on every fetch. A job's shapes are cached
once the job sits at ``acceptance``/``completed``: an unfinished job is
being edited and would be rewritten on nearly every run.

Per-job entries are used only when the jobs can be separated: every job is
an ordinary annotation job and no two frame ranges overlap. CVAT then
returns task annotations as the jobs' shapes one after another, so the
task response splits exactly by range. Ground Truth and consensus jobs,
honeypots and overlapping ranges make CVAT merge or exclude shapes in ways
that per-job reads cannot reproduce; such a task keeps one entry of the
task endpoint's shapes, valid only while all of its jobs are unchanged.
"""

from dataclasses import dataclass
from itertools import pairwise
from typing import TYPE_CHECKING

from cveta2.application.ports.cache import AnnotationScope, TaskCache
from cveta2.application.ports.dtos import RawAnnotations, RawJob, RawShape
from cveta2.domain.models import COMPLETED_JOB_STAGE, COMPLETED_JOB_STATE

if TYPE_CHECKING:
    from cveta2.application.ports.cvat import CvatApiPort
    from cveta2.domain.models import TaskInfo

_ANNOTATION_JOB = "annotation"


def _finished(job: RawJob) -> bool:
    return (job.stage, job.state) == (COMPLETED_JOB_STAGE, COMPLETED_JOB_STATE)


def _cacheable(scope: AnnotationScope) -> bool:
    """Cache an entry only once every job it covers has finished review."""
    return bool(scope.jobs) and all(_finished(job) for job in scope.jobs)


def separable_jobs(jobs: list[RawJob]) -> list[RawJob] | None:
    """Return *jobs* ordered by first frame when they can be cached one by one, else None."""
    ordered = sorted(jobs, key=lambda job: (job.start_frame, job.id))
    if not ordered or any(job.type != _ANNOTATION_JOB for job in ordered):
        return None
    if any(earlier.stop_frame >= later.start_frame for earlier, later in pairwise(ordered)):
        return None
    return ordered


def _split(annotations: RawAnnotations, jobs: list[RawJob]) -> list[RawAnnotations] | None:
    """Split task shapes by job range; None when a shape lies outside every range."""
    parts: list[list[RawShape]] = [[] for _ in jobs]
    for shape in annotations.shapes:
        owner = next((i for i, job in enumerate(jobs) if job.start_frame <= shape.frame <= job.stop_frame), None)
        if owner is None:
            return None
        parts[owner].append(shape)
    return [RawAnnotations(shapes=shapes) for shapes in parts]


def _join(parts: list[RawAnnotations]) -> RawAnnotations:
    return RawAnnotations(shapes=[shape for part in parts for shape in part.shapes])


@dataclass(frozen=True)
class CachedAnnotations:
    """Annotation reads through *cache*; ``read=False`` (``--force``) only writes."""

    cache: TaskCache
    read: bool = True

    def load(self, api: "CvatApiPort", task: "TaskInfo", jobs: list[RawJob]) -> tuple[RawAnnotations, bool]:
        """Return the task's shapes and whether all of them came from the cache.

        When no entry of a separable task can be reused, one task request
        is split into the job entries; otherwise only the jobs without a
        reusable entry are read from the job endpoint.
        """
        ordered = separable_jobs(jobs)
        if ordered is None:
            return self._load_whole_task(api, task, jobs)
        scopes = [AnnotationScope(jobs=(job,)) for job in ordered]
        self.cache.keep_only(task.id, [scope for scope in scopes if _cacheable(scope)])
        cached = [self._read(task, scope) for scope in scopes]
        if all(hit is None for hit in cached):
            fetched = api.get_task_annotations(task.id)
            parts = _split(fetched, ordered)
            if parts is None:
                return fetched, False
            for scope, part in zip(scopes, parts, strict=True):
                self._write(task, scope, part)
            return _join(parts), False
        loaded: list[RawAnnotations] = []
        for scope, hit in zip(scopes, cached, strict=True):
            if hit is None:
                hit = api.get_job_annotations(scope.jobs[0].id)  # noqa: PLW2901 - fill the miss in place
                self._write(task, scope, hit)
            loaded.append(hit)
        return _join(loaded), all(hit is not None for hit in cached)

    def _load_whole_task(self, api: "CvatApiPort", task: "TaskInfo", jobs: list[RawJob]) -> tuple[RawAnnotations, bool]:
        scope = AnnotationScope(jobs=tuple(jobs), whole_task=True)
        self.cache.keep_only(task.id, [scope] if _cacheable(scope) else [])
        cached = self._read(task, scope)
        if cached is not None:
            return cached, True
        fetched = api.get_task_annotations(task.id)
        self._write(task, scope, fetched)
        return fetched, False

    def _read(self, task: "TaskInfo", scope: AnnotationScope) -> RawAnnotations | None:
        if not self.read or not _cacheable(scope):
            return None
        return self.cache.get(task, scope)

    def _write(self, task: "TaskInfo", scope: AnnotationScope, annotations: RawAnnotations) -> None:
        if _cacheable(scope):
            self.cache.put(task, scope, annotations)
