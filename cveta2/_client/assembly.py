"""Pure assembly helpers: DTOs -> domain records and frame/job lookups.

Moved out of ``client.py`` so the client holds only orchestration; these
functions are deterministic transformations over DTOs and models.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

import pandas as pd

from cveta2._client.context import _TaskContext
from cveta2._client.extractors import _collect_shapes
from cveta2.models import DeletedImage, ImageWithoutAnnotations

if TYPE_CHECKING:
    from cveta2._client.dtos import RawAnnotations, RawDataMeta, RawIssue, RawJob
    from cveta2.models import AnnotationRecord, TaskInfo

ISSUE_BBOX_COLUMNS = ("bbox_x_tl", "bbox_y_tl", "bbox_x_br", "bbox_y_br")


def build_name_to_frame(data_meta: RawDataMeta) -> dict[str, int]:
    """Build frame-name -> frame-index mapping from task data_meta.

    Basename fallback handles month-subfolder frame names
    (e.g. ``"2026-02/img.jpg"`` -> also accessible via ``"img.jpg"``).
    """
    name_to_frame: dict[str, int] = {}
    for idx, frame in enumerate(data_meta.frames):
        name_to_frame[frame.name] = idx
        base = PurePosixPath(frame.name).name
        if base not in name_to_frame:
            name_to_frame[base] = idx
    return name_to_frame


def find_job_for_frame(jobs: list[RawJob], frame: int) -> int | None:
    """Return the job ID whose [start_frame, stop_frame] range contains *frame*."""
    for job in jobs:
        if job.start_frame <= frame <= job.stop_frame:
            return job.id
    return None


def issue_position_from_row(row: pd.Series[Any]) -> list[float] | None:
    """Return the row's bbox as an issue rectangle, or None without full bbox."""
    values = [row.get(col) for col in ISSUE_BBOX_COLUMNS]
    coords = [value for value in values if value is not None and pd.notna(value)]
    if len(coords) == len(ISSUE_BBOX_COLUMNS):
        return [float(value) for value in coords]
    return None


def task_to_records(  # noqa: PLR0913
    task: TaskInfo,
    data_meta: RawDataMeta,
    annotations: RawAnnotations,
    label_names: dict[int, str],
    attr_names: dict[int, str],
    issues: list[RawIssue] | None = None,
) -> tuple[list[AnnotationRecord], list[DeletedImage]]:
    """Build annotation records and deleted list for one task."""
    ctx = _TaskContext.from_raw(task, data_meta, label_names, attr_names, issues)
    task_annotations = _collect_shapes(annotations.shapes, ctx)
    deleted_ids = set(data_meta.deleted_frames)
    frames = ctx.frames
    task_deleted = [
        DeletedImage(
            task_id=task.id,
            task_name=task.name,
            task_status=task.status,
            task_updated_date=task.updated_date,
            frame_id=fid,
            image_name=(frames[fid].name if fid in frames else "<unknown>"),
            image_width=(frames[fid].width if fid in frames else 0),
            image_height=(frames[fid].height if fid in frames else 0),
            subset=task.subset,
        )
        for fid in data_meta.deleted_frames
    ]
    annotated_ids = {a.frame_id for a in task_annotations}
    task_without = [
        ImageWithoutAnnotations(
            image_name=frame.name,
            image_width=frame.width,
            image_height=frame.height,
            task_id=task.id,
            task_name=task.name,
            task_status=task.status,
            task_updated_date=task.updated_date,
            frame_id=fid,
            subset=task.subset,
            issue_text=ctx.frame_issues.get(fid, ("", ""))[0],
            issue_state=ctx.frame_issues.get(fid, ("", ""))[1],
        )
        for fid, frame in frames.items()
        if fid not in deleted_ids and fid not in annotated_ids
    ]
    return (
        list(task_annotations) + task_without,
        task_deleted,
    )
