"""Assemble fetched CVAT facts into annotation and deleted-frame records."""

from typing import TYPE_CHECKING

from cveta2.application.client.context import _TaskContext
from cveta2.application.client.extractors import _collect_shapes
from cveta2.domain.models import DeletedImage, ImageWithoutAnnotations

if TYPE_CHECKING:
    from cveta2.application.ports.dtos import (
        RawAnnotations,
        RawDataMeta,
        RawIssue,
        RawJob,
    )
    from cveta2.domain.models import AnnotationRecord, TaskInfo


def task_to_records(  # noqa: PLR0913, PLR0917
    task: "TaskInfo",
    data_meta: "RawDataMeta",
    annotations: "RawAnnotations",
    label_names: dict[int, str],
    attr_names: dict[int, str],
    issues: "list[RawIssue] | None" = None,
    jobs: "list[RawJob] | None" = None,
) -> "tuple[list[AnnotationRecord], list[DeletedImage]]":
    """Build annotation records and deleted list for one task."""
    ctx = _TaskContext.from_raw(task, data_meta, label_names, attr_names, issues, jobs)
    task_annotations = _collect_shapes(annotations.shapes, ctx)
    deleted_ids = set(data_meta.deleted_frames)
    frames = ctx.frames
    task_deleted = [
        DeletedImage(
            task_id=task.id,
            task_name=task.name,
            job_stage=ctx.job_position(fid)[0],
            job_state=ctx.job_position(fid)[1],
            task_completed=ctx.task_completed,
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
            job_stage=ctx.job_position(fid)[0],
            job_state=ctx.job_position(fid)[1],
            task_completed=ctx.task_completed,
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
