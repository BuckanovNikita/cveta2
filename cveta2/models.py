"""Pydantic models for CVAT annotation data."""

from __future__ import annotations

import json
from typing import Annotated, Literal

from pydantic import BaseModel, Discriminator

Split = Literal["train", "val", "test"]
"""Allowed values for the ``split`` field (our convention for dataset splits)."""


class BBoxAnnotation(BaseModel):
    """Single bounding-box annotation record."""

    image_name: str
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
    attributes: dict[str, str]

    def to_csv_row(self) -> dict[str, str | int | float | bool | None]:
        """Convert BBoxAnnotation to a flat dict for CSV (attributes as JSON)."""
        row = self.model_dump()
        attrs = row.pop("attributes")
        row["attributes"] = json.dumps(attrs, ensure_ascii=False)
        return row


# Canonical CSV column order shared by all AnnotationRecord variants.
# Inferred from BBoxAnnotation (full schema); every to_csv_row() must use these keys.
CSV_COLUMNS: tuple[str, ...] = tuple(BBoxAnnotation.model_fields.keys())


class ImageWithoutAnnotations(BaseModel):
    """Image without bbox annotations.

    The row is still included in CSV with empty bbox-related fields.
    Discriminated from ``BBoxAnnotation`` via ``instance_shape="none"``.
    """

    image_name: str
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

    def to_csv_row(self) -> dict[str, str | int | float | bool | None]:
        """Return a row matching ``CSV_COLUMNS`` with bbox fields set to None."""
        row: dict[str, str | int | float | bool | None] = dict.fromkeys(
            CSV_COLUMNS,
            None,
        )
        for key, value in self.model_dump().items():
            if key in row:
                row[key] = value
        row["attributes"] = json.dumps({}, ensure_ascii=False)
        return row


class DeletedImage(BaseModel):
    """Record of a deleted image."""

    task_id: int
    task_name: str
    task_status: str = ""
    task_updated_date: str = ""
    frame_id: int
    image_name: str


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
        """Build flat CSV rows from all annotation records.

        Each row has the keys from ``CSV_COLUMNS``.
        """
        return [record.to_csv_row() for record in self.annotations]
