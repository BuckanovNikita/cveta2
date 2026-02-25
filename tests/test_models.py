"""Unit tests for pydantic models: to_csv_row, merge, format_display."""

from __future__ import annotations

import json

from cveta2.models import (
    CSV_COLUMNS,
    BBoxAnnotation,
    DeletedImage,
    ImageWithoutAnnotations,
    LabelAttributeInfo,
    LabelInfo,
    ProjectAnnotations,
    TaskAnnotations,
    TaskInfo,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bbox(**overrides: object) -> BBoxAnnotation:
    defaults: dict[str, object] = {
        "image_name": "img.jpg",
        "image_width": 640,
        "image_height": 480,
        "instance_label": "car",
        "bbox_x_tl": 10.0,
        "bbox_y_tl": 20.0,
        "bbox_x_br": 100.0,
        "bbox_y_br": 200.0,
        "task_id": 1,
        "task_name": "task-1",
        "task_status": "completed",
        "task_updated_date": "2026-01-01T00:00:00",
        "created_by_username": "tester",
        "frame_id": 0,
        "subset": "train",
        "occluded": False,
        "z_order": 0,
        "rotation": 0.0,
        "source": "manual",
        "annotation_id": 42,
        "attributes": {"color": "red"},
    }
    defaults.update(overrides)
    return BBoxAnnotation(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# BBoxAnnotation.to_csv_row
# ---------------------------------------------------------------------------


def test_bbox_to_csv_row_keys_match_csv_columns() -> None:
    """to_csv_row() returns all keys from CSV_COLUMNS."""
    row = _bbox().to_csv_row()
    assert set(row.keys()) == set(CSV_COLUMNS)


def test_bbox_to_csv_row_attributes_serialized_as_json() -> None:
    """Attributes dict is serialized as a JSON string."""
    row = _bbox(attributes={"color": "red", "make": "BMW"}).to_csv_row()
    parsed = json.loads(row["attributes"])  # type: ignore[arg-type]
    assert parsed == {"color": "red", "make": "BMW"}


def test_bbox_to_csv_row_all_keys_present() -> None:
    """All expected fields are present and non-None for a full BBoxAnnotation."""
    row = _bbox().to_csv_row()
    for key in ("image_name", "bbox_x_tl", "bbox_y_tl", "bbox_x_br", "bbox_y_br"):
        assert row[key] is not None


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
    row = _bbox().to_csv_row()
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
    bbox = _bbox()
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
        annotations=[_bbox(task_id=1)],
        deleted_images=[],
    )
    t2 = TaskAnnotations(
        task_id=2,
        task_name="t2",
        annotations=[_bbox(task_id=2, image_name="b.jpg")],
        deleted_images=[
            DeletedImage(image_name="c.jpg", task_id=2, task_name="t2", frame_id=0)
        ],
    )
    result = TaskAnnotations.merge([t1, t2])

    assert len(result.annotations) == 2
    assert len(result.deleted_images) == 1
    assert isinstance(result, ProjectAnnotations)


# ---------------------------------------------------------------------------
# LabelInfo.format_display
# ---------------------------------------------------------------------------


def test_label_format_display_minimal() -> None:
    """Label with no color and no attributes."""
    label = LabelInfo(id=1, name="car")
    display = label.format_display()
    assert "'car'" in display
    assert "id=1" in display
    assert "цвет=" not in display
    assert "атрибуты:" not in display


def test_label_format_display_with_color() -> None:
    """Label with color shows it."""
    label = LabelInfo(id=1, name="car", color="#ff0000")
    display = label.format_display()
    assert "цвет=#ff0000" in display


def test_label_format_display_with_attributes() -> None:
    """Label with attributes shows their names."""
    label = LabelInfo(
        id=1,
        name="car",
        attributes=[
            LabelAttributeInfo(id=10, name="color"),
            LabelAttributeInfo(id=11, name="make"),
        ],
    )
    display = label.format_display()
    assert "атрибуты: color, make" in display


# ---------------------------------------------------------------------------
# TaskInfo.format_display
# ---------------------------------------------------------------------------


def test_task_format_display() -> None:
    """Basic format check for TaskInfo.format_display."""
    task = TaskInfo(
        id=42,
        name="my-task",
        status="completed",
        subset="train",
        updated_date="2026-01-01",
    )
    display = task.format_display()
    assert "my-task" in display
    assert "id=42" in display
    assert "completed" in display
