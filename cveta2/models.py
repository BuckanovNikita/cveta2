"""Pydantic models for CVAT annotation data."""

from __future__ import annotations

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
    frame_id: int
    subset: str
    occluded: bool
    z_order: int
    rotation: float
    source: str
    annotation_id: int | None
    attributes: dict[str, str]


class DeletedImage(BaseModel):
    """Record of a deleted image."""

    task_id: int
    task_name: str
    frame_id: int
    image_name: str


class ProjectAnnotations(BaseModel):
    """Result of fetching annotations from a CVAT project."""

    annotations: list[BBoxAnnotation]
    deleted_images: list[DeletedImage]
