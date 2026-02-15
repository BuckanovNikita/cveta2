"""Pydantic models for CVAT annotation data."""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel

# Canonical CSV column order shared by BBoxAnnotation and ImageWithoutAnnotations.
# Both ``to_csv_row()`` implementations must produce dicts with exactly these keys.
CSV_COLUMNS: tuple[str, ...] = (
    "image_name",
    "image_width",
    "image_height",
    "instance_shape",
    "instance_label",
    "bbox_x_tl",
    "bbox_y_tl",
    "bbox_x_br",
    "bbox_y_br",
    "task_id",
    "task_name",
    "task_status",
    "task_updated_date",
    "created_by_username",
    "frame_id",
    "subset",
    "occluded",
    "z_order",
    "rotation",
    "source",
    "annotation_id",
    "attributes",
)


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


class ImageWithoutAnnotations(BaseModel):
    """Image without bbox annotations.

    The row is still included in CSV with empty bbox-related fields.
    """

    image_name: str
    image_width: int
    image_height: int
    task_id: int
    task_name: str
    task_status: str = ""
    task_updated_date: str = ""
    frame_id: int
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


class ProjectAnnotations(BaseModel):
    """Result of fetching annotations from a CVAT project."""

    annotations: list[BBoxAnnotation]
    deleted_images: list[DeletedImage]
    images_without_annotations: list[ImageWithoutAnnotations] = []

    def to_csv_rows(self) -> list[dict[str, str | int | float | bool | None]]:
        """Build flat CSV rows (annotations + images-without-annotations).

        Each row has the keys from ``CSV_COLUMNS``.
        """
        rows = [ann.to_csv_row() for ann in self.annotations]
        rows.extend(img.to_csv_row() for img in self.images_without_annotations)
        return rows
