"""Internal data structures used while processing a CVAT task."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cveta2._client.dtos import RawDataMeta, RawFrame, RawIssue, RawJob
    from cveta2.models import TaskInfo

_RECTANGLE = "rectangle"

_COMMENTS_SEPARATOR = "; "
_ISSUES_SEPARATOR = " | "


def _build_frame_issues(issues: list[RawIssue]) -> dict[int, tuple[str, str]]:
    """Group issues by frame into pre-joined ``(issue_text, issue_state)`` pairs.

    Each issue's text is its comments joined with ``"; "``.  Multiple issues
    on one frame are joined with ``" | "`` in both columns, in the same order,
    so texts and states stay positionally aligned.
    """
    by_frame: dict[int, list[RawIssue]] = {}
    for issue in issues:
        by_frame.setdefault(issue.frame, []).append(issue)
    result: dict[int, tuple[str, str]] = {}
    for frame, frame_issues in by_frame.items():
        texts = [_COMMENTS_SEPARATOR.join(issue.comments) for issue in frame_issues]
        states = ["resolved" if issue.resolved else "open" for issue in frame_issues]
        result[frame] = (
            _ISSUES_SEPARATOR.join(texts),
            _ISSUES_SEPARATOR.join(states),
        )
    return result


def _build_frame_jobs(jobs: list[RawJob]) -> dict[int, tuple[str, str]]:
    """Map every frame covered by a job to that job's ``(stage, state)``.

    A frame belongs to exactly one job, so the review position CVAT
    records per job is the one every record of that frame carries.
    Frames no job covers are absent and read as empty.
    """
    return {
        frame: (job.stage, job.state)
        for job in jobs
        for frame in range(job.start_frame, job.stop_frame + 1)
    }


@dataclass
class _TaskContext:
    """Shared context for extracting annotations from a single task."""

    frames: dict[int, RawFrame]
    label_names: dict[int, str]
    attr_names: dict[int, str]
    task_id: int
    task_name: str
    task_updated_date: str
    subset: str
    frame_issues: dict[int, tuple[str, str]] = field(default_factory=dict)
    frame_jobs: dict[int, tuple[str, str]] = field(default_factory=dict)

    def job_position(self, frame: int) -> tuple[str, str]:
        """Return ``(job_stage, job_state)`` for *frame*, empty when unknown."""
        return self.frame_jobs.get(frame, ("", ""))

    @classmethod
    def from_raw(  # noqa: PLR0913, PLR0917
        cls,
        task: TaskInfo,
        data_meta: RawDataMeta,
        label_names: dict[int, str],
        attr_names: dict[int, str],
        issues: list[RawIssue] | None = None,
        jobs: list[RawJob] | None = None,
    ) -> _TaskContext:
        """Build context from DTO objects."""
        return cls(
            frames=dict(enumerate(data_meta.frames)),
            label_names=label_names,
            attr_names=attr_names,
            task_id=task.id,
            task_name=task.name,
            task_updated_date=task.updated_date,
            subset=task.subset,
            frame_issues=_build_frame_issues(issues or []),
            frame_jobs=_build_frame_jobs(jobs or []),
        )
