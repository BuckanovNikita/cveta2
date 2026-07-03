"""Builders converting cveta2 DTOs into ``cvat_sdk`` request models.

Kept separate from the adapter so ``sdk_adapter.py`` stays readable:
the adapter owns API calls and error translation, this module owns the
request-object construction.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cvat_sdk.api_client import models as cvat_models

if TYPE_CHECKING:
    from cveta2._client.dtos import (
        LabelPatch,
        NewIssue,
        NewShape,
        RawShape,
        UploadTaskSpec,
    )


def build_task_write_request(spec: UploadTaskSpec) -> cvat_models.TaskWriteRequest:
    """Build the task-creation request from an upload spec."""
    return cvat_models.TaskWriteRequest(
        name=spec.name,
        project_id=spec.project_id,
        segment_size=spec.segment_size,
    )


def build_data_request(spec: UploadTaskSpec) -> cvat_models.DataRequest:
    """Build the cloud-storage data-attachment request from an upload spec."""
    return cvat_models.DataRequest(
        image_quality=spec.image_quality,
        server_files=spec.server_files,
        cloud_storage_id=spec.cloud_storage_id,
        use_cache=True,
        sorting_method=cvat_models.SortingMethod("natural"),
    )


def build_new_shapes_payload(
    shapes: list[NewShape],
) -> cvat_models.PatchedLabeledDataRequest:
    """Build the annotation payload creating new shapes."""
    return cvat_models.PatchedLabeledDataRequest(
        shapes=[
            cvat_models.LabeledShapeRequest(
                type=cvat_models.ShapeType(shape.type),
                frame=shape.frame,
                label_id=shape.label_id,
                points=list(shape.points),
            )
            for shape in shapes
        ],
    )


def build_delete_shapes_payload(
    shapes: list[RawShape],
) -> cvat_models.PatchedLabeledDataRequest:
    """Build the annotation payload referencing existing shapes for deletion."""
    return cvat_models.PatchedLabeledDataRequest(
        shapes=[
            cvat_models.LabeledShapeRequest(
                type=cvat_models.ShapeType(shape.type),
                frame=shape.frame,
                label_id=shape.label_id,
                points=list(shape.points),
                id=shape.id,
            )
            for shape in shapes
        ],
    )


def build_issue_request(issue: NewIssue) -> cvat_models.IssueWriteRequest:
    """Build the issue-creation request."""
    return cvat_models.IssueWriteRequest(
        frame=issue.frame,
        position=list(issue.position),
        job=issue.job_id,
        message=issue.message,
    )


def build_deleted_frames_request(
    frame_ids: list[int],
) -> cvat_models.PatchedDataMetaWriteRequest:
    """Build the data_meta PATCH replacing the deleted-frames list."""
    return cvat_models.PatchedDataMetaWriteRequest(deleted_frames=frame_ids)


def _build_label_patch_request(patch: LabelPatch) -> cvat_models.PatchedLabelRequest:
    if patch.id is None:
        return cvat_models.PatchedLabelRequest(name=patch.name)
    if patch.deleted:
        return cvat_models.PatchedLabelRequest(id=patch.id, deleted=True)
    if patch.name is not None:
        return cvat_models.PatchedLabelRequest(id=patch.id, name=patch.name)
    return cvat_models.PatchedLabelRequest(id=patch.id, color=patch.color)


def build_labels_patch_request(
    patches: list[LabelPatch],
) -> cvat_models.PatchedProjectWriteRequest:
    """Build the project PATCH applying the given label changes."""
    return cvat_models.PatchedProjectWriteRequest(
        labels=[_build_label_patch_request(p) for p in patches],
    )


def build_job_patch_request(
    *,
    stage: str | None,
    state: str | None,
) -> cvat_models.PatchedJobWriteRequest:
    """Build a job PATCH request with only the provided fields."""
    patch_kwargs: dict[str, object] = {}
    if stage is not None:
        patch_kwargs["stage"] = cvat_models.JobStage(stage)
    if state is not None:
        patch_kwargs["state"] = cvat_models.OperationStatus(state)
    return cvat_models.PatchedJobWriteRequest(**patch_kwargs)
