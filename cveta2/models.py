"""Pydantic models for CVAT annotation data."""

from __future__ import annotations

import json
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    field_validator,
    model_validator,
)


class ProjectInfo(BaseModel):
    """CVAT project summary (id + name)."""

    model_config = ConfigDict(frozen=True)

    id: int
    name: str


class OrganizationInfo(BaseModel):
    """CVAT organization summary (slug + display name)."""

    model_config = ConfigDict(frozen=True)

    slug: str
    name: str


class TaskInfo(BaseModel):
    """CVAT task metadata."""

    model_config = ConfigDict(frozen=True)

    id: int
    name: str
    status: str
    subset: str
    updated_date: str
    project_id: int | None = None

    def format_display(self) -> str:
        """Human-readable one-line summary for TUI menus."""
        return f"{self.name} (id={self.id}, {self.status})"


class LabelAttributeInfo(BaseModel):
    """Attribute spec defined on a label."""

    model_config = ConfigDict(frozen=True)

    id: int
    name: str


class LabelInfo(BaseModel):
    """CVAT project label with attribute specs."""

    model_config = ConfigDict(frozen=True)

    id: int
    name: str
    color: str = ""
    attributes: list[LabelAttributeInfo] = Field(default_factory=list)

    def format_display(self) -> str:
        """Human-readable label description for TUI menus."""
        parts = [f"{self.name!r} (id={self.id})"]
        if self.color:
            parts.append(f"цвет={self.color}")
        if self.attributes:
            attr_names = ", ".join(a.name for a in self.attributes)
            parts.append(f"атрибуты: {attr_names}")
        return "  ".join(parts)


Split = Literal["train", "val", "test"]
"""Allowed values for the ``split`` field (our convention for dataset splits)."""


JobStage = Literal["annotation", "validation", "acceptance"]
"""CVAT-native job stage values."""

JOB_STAGES: tuple[JobStage, ...] = ("annotation", "validation", "acceptance")
"""All valid CVAT job stages (runtime counterpart of :data:`JobStage`)."""

JobState = Literal["new", "in progress", "completed", "rejected"]
"""CVAT-native job state values."""

JOB_STATES: tuple[JobState, ...] = ("new", "in progress", "completed", "rejected")
"""All valid CVAT job states (runtime counterpart of :data:`JobState`)."""


def _validate_image_name(v: str) -> str:
    """Ensure *image_name* is a bare filename (no directory components)."""
    name = PurePosixPath(v).name
    if not name:
        msg = f"image_name must be a non-empty filename, got {v!r}"
        raise ValueError(msg)
    return name


def _capture_frame_path(data: object) -> object:
    """Preserve a nested CVAT frame name before ``image_name`` is collapsed.

    CVAT frame names may contain subfolders (``2026-02/img.jpg``); the
    ``image_name`` validator keeps only the basename, so the original
    relative key is stored in ``frame_path`` for S3 path construction.
    """
    if isinstance(data, dict) and not data.get("frame_path"):
        raw = data.get("image_name")
        if isinstance(raw, str) and PurePosixPath(raw).name != raw:
            data["frame_path"] = raw
    return data


def _validate_image_path(v: str | None) -> str | None:
    """Ensure *image_path* is absolute when provided."""
    if v is not None and not PurePosixPath(v).is_absolute():
        msg = f"image_path must be an absolute path, got {v!r}"
        raise ValueError(msg)
    return v


class _ImageRecordBase(BaseModel):
    """Shared validators and sparse CSV row for per-image record models.

    Declares no fields so each subclass keeps its own field order
    (``CSV_COLUMNS`` is derived from ``BBoxAnnotation`` field order).
    """

    capture_frame_path = model_validator(mode="before")(_capture_frame_path)
    validate_image_name = field_validator(
        "image_name", mode="before", check_fields=False
    )(_validate_image_name)
    validate_image_path = field_validator(
        "image_path", mode="before", check_fields=False
    )(_validate_image_path)

    def to_csv_row(self) -> dict[str, str | int | float | bool | None]:
        """Return a row matching ``CSV_COLUMNS``; absent fields become None."""
        return _sparse_csv_row(self)


class BBoxAnnotation(_ImageRecordBase):
    """Single bounding-box annotation record."""

    image_name: str
    frame_path: str | None = None
    image_width: int
    image_height: int
    instance_shape: Literal["box"] = "box"
    instance_label: str
    bbox_x_tl: float
    bbox_y_tl: float
    bbox_x_br: float
    bbox_y_br: float
    # Extra fields
    task_id: int
    task_name: str
    task_status: str = ""
    task_updated_date: str = ""
    created_by_username: str = ""
    frame_id: int
    split: Split | None = None
    subset: str
    occluded: bool
    z_order: int
    rotation: float
    source: str
    annotation_id: int | None
    confidence: float | None = None
    issue_text: str = ""
    issue_state: str = ""
    s3_image_path: str | None = None
    image_path: str | None = None
    attributes: dict[str, str]

    def to_csv_row(self) -> dict[str, str | int | float | bool | None]:
        """Convert BBoxAnnotation to a flat dict for CSV (attributes as JSON)."""
        row = self.model_dump()
        del row["frame_path"]
        row["attributes"] = json.dumps(row["attributes"], ensure_ascii=False)
        return row


# Canonical CSV column order shared by all AnnotationRecord variants.
# Inferred from BBoxAnnotation (full schema); every to_csv_row() must use these
# keys.  ``frame_path`` is internal (kept in cache JSON, not written to CSV).
CSV_COLUMNS: tuple[str, ...] = tuple(
    name for name in BBoxAnnotation.model_fields if name != "frame_path"
)


_EMPTY_ATTRIBUTES_JSON = json.dumps({})
"""``attributes`` cell written for records that carry no attribute map."""


def _sparse_csv_row(model: BaseModel) -> dict[str, str | int | float | bool | None]:
    """Build a CSV row matching ``CSV_COLUMNS`` from a sparse model.

    Fields present on the model are written; all others default to None.
    An empty ``attributes`` JSON object is added.
    """
    row: dict[str, str | int | float | bool | None] = dict.fromkeys(CSV_COLUMNS)
    for key, value in model.model_dump().items():
        if key in row:
            row[key] = value
    row["attributes"] = _EMPTY_ATTRIBUTES_JSON
    return row


class ImageWithoutAnnotations(_ImageRecordBase):
    """Image without bbox annotations.

    The row is still included in CSV with empty bbox-related fields.
    Discriminated from ``BBoxAnnotation`` via ``instance_shape="none"``.
    """

    image_name: str
    frame_path: str | None = None
    image_width: int
    image_height: int
    instance_shape: Literal["none"] = "none"
    task_id: int
    task_name: str
    task_status: str = ""
    task_updated_date: str = ""
    frame_id: int
    split: Split | None = None
    subset: str = ""
    issue_text: str = ""
    issue_state: str = ""
    s3_image_path: str | None = None
    image_path: str | None = None


class DeletedImage(_ImageRecordBase):
    """Record of a deleted image.

    Written to ``deleted.csv`` with ``instance_shape="deleted"`` so the
    file shares the same column schema as ``dataset.csv``.
    """

    image_name: str
    frame_path: str | None = None
    image_width: int = 0
    image_height: int = 0
    instance_shape: Literal["deleted"] = "deleted"
    task_id: int
    task_name: str
    task_status: str = ""
    task_updated_date: str = ""
    frame_id: int
    subset: str = ""
    s3_image_path: str | None = None
    image_path: str | None = None


AnnotationRecord = Annotated[
    BBoxAnnotation | ImageWithoutAnnotations,
    Discriminator("instance_shape"),
]
"""Discriminated union: ``BBoxAnnotation`` (``instance_shape="box"``) or
``ImageWithoutAnnotations`` (``instance_shape="none"``)."""


class ProjectAnnotations(BaseModel):
    """Result of fetching annotations from a CVAT project."""

    annotations: list[AnnotationRecord]
    deleted_images: list[DeletedImage]

    def to_csv_rows(self) -> list[dict[str, str | int | float | bool | None]]:
        """Build flat CSV rows (keys = ``CSV_COLUMNS``) from all records."""
        return [record.to_csv_row() for record in self.annotations]


class TaskAnnotations(ProjectAnnotations):
    """Result of fetching annotations from a single CVAT task."""

    task_id: int
    task_name: str

    @staticmethod
    def merge(task_results: list[TaskAnnotations]) -> ProjectAnnotations:
        """Merge multiple per-task results into a single ProjectAnnotations."""
        all_annotations: list[AnnotationRecord] = []
        all_deleted: list[DeletedImage] = []
        for tr in task_results:
            all_annotations.extend(tr.annotations)
            all_deleted.extend(tr.deleted_images)
        return ProjectAnnotations(
            annotations=all_annotations,
            deleted_images=all_deleted,
        )
