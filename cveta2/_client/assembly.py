"""Pure assembly helpers: DTOs -> domain records and frame/job lookups.

Moved out of ``client.py`` so the client holds only orchestration; these
functions are deterministic transformations over DTOs and models.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import pandas as pd

from cveta2._client.context import _TaskContext
from cveta2._client.dtos import NewIssue, NewShape
from cveta2._client.extractors import _collect_shapes
from cveta2.models import DeletedImage, ImageWithoutAnnotations
from cveta2.s3_utils import names_with_basename_fallback

if TYPE_CHECKING:
    from cveta2._client.dtos import RawAnnotations, RawDataMeta, RawIssue, RawJob
    from cveta2.models import AnnotationRecord, TaskInfo

BBOX_COLUMNS = ("bbox_x_tl", "bbox_y_tl", "bbox_x_br", "bbox_y_br")


def build_name_to_frame(data_meta: RawDataMeta) -> dict[str, int]:
    """Build frame-name -> frame-index mapping (with basename fallback)."""
    return names_with_basename_fallback(
        (frame.name, idx) for idx, frame in enumerate(data_meta.frames)
    )


def find_job_for_frame(jobs: list[RawJob], frame: int) -> int | None:
    """Return the job ID whose [start_frame, stop_frame] range contains *frame*."""
    for job in jobs:
        if job.start_frame <= frame <= job.stop_frame:
            return job.id
    return None


def issue_position_from_row(row: pd.Series[Any]) -> list[float] | None:
    """Return the row's bbox as an issue rectangle, or None without full bbox."""
    values = [row.get(col) for col in BBOX_COLUMNS]
    coords = [value for value in values if value is not None and pd.notna(value)]
    if len(coords) == len(BBOX_COLUMNS):
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


@dataclass
class ShapeBuildResult:
    """Shapes to upload plus per-reason skip diagnostics."""

    shapes: list[NewShape] = field(default_factory=list)
    unknown_images: int = 0
    unknown_labels: list[str] = field(default_factory=list)


def build_upload_shapes(
    annotations_df: pd.DataFrame,
    name_to_frame: dict[str, int],
    label_name_to_id: dict[str, int],
) -> ShapeBuildResult:
    """Translate annotated rows into ``NewShape`` DTOs (pure).

    Rows whose image is absent from *name_to_frame* or whose label is
    unknown are counted/collected in the returned result instead of being
    uploaded.
    """
    has_annotation = annotations_df["instance_label"].notna() & annotations_df[
        list(BBOX_COLUMNS)
    ].notna().all(axis=1)
    result = ShapeBuildResult()
    for _, row in annotations_df[has_annotation].iterrows():
        img_name = str(row["image_name"])
        label_name = str(row["instance_label"])
        if img_name not in name_to_frame:
            result.unknown_images += 1
            continue
        if label_name not in label_name_to_id:
            result.unknown_labels.append(label_name)
            continue
        result.shapes.append(
            NewShape(
                frame=name_to_frame[img_name],
                label_id=label_name_to_id[label_name],
                points=[float(row[col]) for col in BBOX_COLUMNS],
            ),
        )
    return result


@dataclass
class IssueBuildResult:
    """Issues to open plus per-reason skip diagnostics (image names)."""

    issues: list[NewIssue] = field(default_factory=list)
    unknown_images: list[str] = field(default_factory=list)
    unmapped_frames: list[str] = field(default_factory=list)
    missing_bbox: list[str] = field(default_factory=list)


def build_task_issues(
    new_rows: pd.DataFrame,
    name_to_frame: dict[str, int],
    jobs: list[RawJob],
) -> IssueBuildResult:
    """Translate ``issue_state == "new"`` rows into ``NewIssue`` DTOs (pure).

    Rows with an unknown image, no job for the frame, or an incomplete
    bbox are recorded in the returned result rather than opened.
    """
    result = IssueBuildResult()
    for _, row in new_rows.iterrows():
        image_name = str(row["image_name"])
        frame = name_to_frame.get(image_name)
        if frame is None:
            result.unknown_images.append(image_name)
            continue
        position = issue_position_from_row(row)
        if position is None:
            result.missing_bbox.append(image_name)
            continue
        job_id = find_job_for_frame(jobs, frame)
        if job_id is None:
            result.unmapped_frames.append(image_name)
            continue
        result.issues.append(
            NewIssue(
                job_id=job_id,
                frame=frame,
                position=position,
                message=str(row["issue_text"]),
            ),
        )
    return result
