"""Pydantic models for CVAT annotation data."""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel


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
        """Return a row matching `BBoxAnnotation.to_csv_row` keys."""
        return {
            "image_name": self.image_name,
            "image_width": self.image_width,
            "image_height": self.image_height,
            "instance_shape": None,
            "instance_label": None,
            "bbox_x_tl": None,
            "bbox_y_tl": None,
            "bbox_x_br": None,
            "bbox_y_br": None,
            "task_id": self.task_id,
            "task_name": self.task_name,
            "task_status": self.task_status,
            "task_updated_date": self.task_updated_date,
            "created_by_username": None,
            "frame_id": self.frame_id,
            "subset": self.subset,
            "occluded": None,
            "z_order": None,
            "rotation": None,
            "source": None,
            "annotation_id": None,
            "attributes": json.dumps({}, ensure_ascii=False),
        }


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
