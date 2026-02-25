"""Unit tests for pydantic models: to_csv_row, merge, validators."""

from __future__ import annotations

import json

import pytest

from cveta2.models import (
    CSV_COLUMNS,
    DeletedImage,
    ImageWithoutAnnotations,
    ProjectAnnotations,
    TaskAnnotations,
)
from tests.conftest import make_bbox

# ---------------------------------------------------------------------------
# BBoxAnnotation.to_csv_row
# ---------------------------------------------------------------------------


def test_bbox_to_csv_row_attributes_serialized_as_json() -> None:
    """Attributes dict is serialized as a JSON string."""
    row = make_bbox(attributes={"color": "red", "make": "BMW"}).to_csv_row()
    parsed = json.loads(row["attributes"])  # type: ignore[arg-type]
    assert parsed == {"color": "red", "make": "BMW"}


# ---------------------------------------------------------------------------
# ImageWithoutAnnotations.to_csv_row
# ---------------------------------------------------------------------------


def test_without_annotations_to_csv_row() -> None:
    """Bbox fields are None, instance_shape is 'none'."""
    record = ImageWithoutAnnotations(
        image_name="img.jpg",
        image_width=640,
        image_height=480,
        task_id=1,
        task_name="task-1",
        frame_id=0,
    )
    row = record.to_csv_row()

    assert row["instance_shape"] == "none"
    for key in ("bbox_x_tl", "bbox_y_tl", "bbox_x_br", "bbox_y_br", "instance_label"):
        assert row[key] is None
    assert set(row.keys()) == set(CSV_COLUMNS)


# ---------------------------------------------------------------------------
# DeletedImage.to_csv_row
# ---------------------------------------------------------------------------


def test_deleted_image_to_csv_row() -> None:
    """Bbox fields are None, instance_shape is 'deleted'."""
    record = DeletedImage(
        image_name="img.jpg",
        task_id=1,
        task_name="task-1",
        frame_id=0,
    )
    row = record.to_csv_row()

    assert row["instance_shape"] == "deleted"
    for key in ("bbox_x_tl", "bbox_y_tl", "bbox_x_br", "bbox_y_br", "instance_label"):
        assert row[key] is None
    assert set(row.keys()) == set(CSV_COLUMNS)


# ---------------------------------------------------------------------------
# CSV_COLUMNS
# ---------------------------------------------------------------------------


def test_csv_columns_matches_bbox_fields() -> None:
    """CSV_COLUMNS matches keys from BBoxAnnotation.to_csv_row()."""
    row = make_bbox().to_csv_row()
    assert tuple(row.keys()) == CSV_COLUMNS


# ---------------------------------------------------------------------------
# TaskAnnotations.merge
# ---------------------------------------------------------------------------


def test_merge_empty_list() -> None:
    """Merging empty list produces empty ProjectAnnotations."""
    result = TaskAnnotations.merge([])
    assert result.annotations == []
    assert result.deleted_images == []


def test_merge_single_task_passthrough() -> None:
    """Merging a single task passes through its data."""
    bbox = make_bbox()
    deleted = DeletedImage(image_name="del.jpg", task_id=1, task_name="t", frame_id=1)
    task = TaskAnnotations(
        task_id=1,
        task_name="t",
        annotations=[bbox],
        deleted_images=[deleted],
    )
    result = TaskAnnotations.merge([task])

    assert len(result.annotations) == 1
    assert len(result.deleted_images) == 1


def test_merge_multiple_tasks() -> None:
    """Merging multiple tasks combines annotations and deleted images."""
    t1 = TaskAnnotations(
        task_id=1,
        task_name="t1",
        annotations=[make_bbox(task_id=1)],
        deleted_images=[],
    )
    t2 = TaskAnnotations(
        task_id=2,
        task_name="t2",
        annotations=[make_bbox(task_id=2, image_name="b.jpg")],
        deleted_images=[
            DeletedImage(image_name="c.jpg", task_id=2, task_name="t2", frame_id=0)
        ],
    )
    result = TaskAnnotations.merge([t1, t2])

    assert len(result.annotations) == 2
    assert len(result.deleted_images) == 1
    assert isinstance(result, ProjectAnnotations)


# ---------------------------------------------------------------------------
# image_name validator
# ---------------------------------------------------------------------------


def test_image_name_strips_directory_prefix() -> None:
    """Path-like image_name is stripped to bare filename."""
    bbox = make_bbox(image_name="subdir/img.jpg")
    assert bbox.image_name == "img.jpg"


def test_image_name_strips_deep_path() -> None:
    """Deeply nested path is stripped to bare filename."""
    bbox = make_bbox(image_name="a/b/c/photo.png")
    assert bbox.image_name == "photo.png"


def test_image_name_passes_plain_filename() -> None:
    """Plain filename is passed through unchanged."""
    bbox = make_bbox(image_name="photo.jpg")
    assert bbox.image_name == "photo.jpg"


def test_image_name_rejects_empty_string() -> None:
    """Empty string raises ValidationError."""
    with pytest.raises(Exception, match="image_name must be a non-empty filename"):
        make_bbox(image_name="")


def test_image_name_validator_on_deleted_image() -> None:
    """DeletedImage also strips directory prefix."""
    record = DeletedImage(
        image_name="prefix/del.jpg", task_id=1, task_name="t", frame_id=0
    )
    assert record.image_name == "del.jpg"


def test_image_name_validator_on_image_without_annotations() -> None:
    """ImageWithoutAnnotations also strips directory prefix."""
    record = ImageWithoutAnnotations(
        image_name="dir/img.jpg",
        image_width=640,
        image_height=480,
        task_id=1,
        task_name="t",
        frame_id=0,
    )
    assert record.image_name == "img.jpg"


# ---------------------------------------------------------------------------
# s3_path and image_path defaults
# ---------------------------------------------------------------------------


def test_s3_path_defaults_to_none() -> None:
    """s3_path defaults to None."""
    bbox = make_bbox()
    assert bbox.s3_path is None


def test_image_path_defaults_to_none() -> None:
    """image_path defaults to None."""
    bbox = make_bbox()
    assert bbox.image_path is None


# ---------------------------------------------------------------------------
# image_path validator
# ---------------------------------------------------------------------------


def test_image_path_rejects_relative_path() -> None:
    """Relative image_path raises ValidationError."""
    with pytest.raises(Exception, match="image_path must be an absolute path"):
        make_bbox(image_path="relative/path/img.jpg")


def test_image_path_accepts_absolute_path() -> None:
    """Absolute image_path is accepted."""
    bbox = make_bbox(image_path="/home/user/images/img.jpg")
    assert bbox.image_path == "/home/user/images/img.jpg"


def test_image_path_accepts_none() -> None:
    """None image_path is accepted."""
    bbox = make_bbox(image_path=None)
    assert bbox.image_path is None
