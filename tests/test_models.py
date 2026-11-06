"""Unit tests for pydantic models: to_csv_row, merge, validators."""

import json
from collections.abc import Callable

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from cveta2.domain.models import (
    CSV_COLUMNS,
    BBoxAnnotation,
    DeletedImage,
    ImageWithoutAnnotations,
    TaskAnnotations,
)
from tests.helpers import make_bbox

ImageRecord = BBoxAnnotation | ImageWithoutAnnotations | DeletedImage

# ---------------------------------------------------------------------------
# BBoxAnnotation.to_csv_row
# ---------------------------------------------------------------------------


def test_bbox_to_csv_row_writes_attributes_as_literal_json() -> None:
    """Attributes become a JSON string; Cyrillic stays text, not u-escapes."""
    row = make_bbox(attributes={"color": "red", "цвет": "красный"}).to_csv_row()
    assert row["attributes"] == '{"color": "red", "цвет": "красный"}'


# ---------------------------------------------------------------------------
# Sparse rows: ImageWithoutAnnotations / DeletedImage .to_csv_row
# ---------------------------------------------------------------------------


def _without_annotations(*, image_name: str) -> ImageWithoutAnnotations:
    return ImageWithoutAnnotations(
        image_width=640,
        image_height=480,
        task_id=1,
        task_name="t",
        frame_id=0,
        image_name=image_name,
    )


def _deleted(*, image_name: str) -> DeletedImage:
    return DeletedImage(task_id=1, task_name="t", frame_id=0, image_name=image_name)


@pytest.mark.parametrize(
    ("factory", "shape"), [(_without_annotations, "none"), (_deleted, "deleted")]
)
def test_sparse_csv_row(factory: Callable[..., ImageRecord], shape: str) -> None:
    """Bbox fields are empty and the attributes cell is still parseable JSON."""
    row = factory(image_name="img.jpg").to_csv_row()

    assert row["instance_shape"] == shape
    for key in ("bbox_x_tl", "bbox_y_tl", "bbox_x_br", "bbox_y_br", "instance_label"):
        assert row[key] is None
    assert set(row.keys()) == set(CSV_COLUMNS)
    assert isinstance(row["attributes"], str)
    assert json.loads(row["attributes"]) == {}


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


# ---------------------------------------------------------------------------
# image_name / frame_path normalisation
# ---------------------------------------------------------------------------


_RECORD_FACTORIES = [make_bbox, _without_annotations, _deleted]
_segment = st.text(alphabet="ab1_-", min_size=1, max_size=4)


@pytest.mark.parametrize(
    "factory", _RECORD_FACTORIES, ids=["bbox", "without_annotations", "deleted"]
)
@given(folders=st.lists(_segment, max_size=3), stem=_segment)
def test_image_name_keeps_basename_and_nested_frame_path(
    factory: Callable[..., ImageRecord], folders: list[str], stem: str
) -> None:
    """A nested CVAT frame name collapses to its basename, keeping the full key."""
    raw = "/".join([*folders, f"{stem}.jpg"])
    record = factory(image_name=raw)
    assert record.image_name == f"{stem}.jpg"
    assert record.frame_path == (raw if folders else None)


def test_explicit_frame_path_is_not_overwritten() -> None:
    """A frame_path given explicitly wins over the captured image_name."""
    bbox = make_bbox(image_name="sub/img.jpg", frame_path="other/img.jpg")
    assert bbox.frame_path == "other/img.jpg"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"image_name": ""}, "image_name must be a non-empty filename"),
        (
            {"image_path": "relative/path/img.jpg"},
            "image_path must be an absolute path",
        ),
    ],
)
def test_invalid_names_and_paths_are_rejected(
    kwargs: dict[str, str], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        make_bbox(**kwargs)


@pytest.mark.parametrize("image_path", ["/home/user/images/img.jpg", None])
def test_image_path_accepts_absolute_or_none(image_path: str | None) -> None:
    assert make_bbox(image_path=image_path).image_path == image_path


def test_frame_path_excluded_from_csv() -> None:
    """frame_path is internal: absent from CSV_COLUMNS and to_csv_row()."""
    assert "frame_path" not in CSV_COLUMNS
    bbox = make_bbox(image_name="sub/img.jpg")
    assert "frame_path" not in bbox.to_csv_row()
    deleted = DeletedImage(
        image_name="sub/del.jpg", task_id=1, task_name="t", frame_id=0
    )
    assert "frame_path" not in deleted.to_csv_row()


def test_frame_path_survives_json_round_trip() -> None:
    """frame_path is kept in model JSON (task-cache serialization)."""
    bbox = make_bbox(image_name="sub/img.jpg")
    restored = type(bbox).model_validate_json(bbox.model_dump_json())
    assert restored.frame_path == "sub/img.jpg"


@pytest.mark.parametrize("confidence", [0.95, None])
def test_bbox_confidence_reaches_the_csv_row(confidence: float | None) -> None:
    ann = make_bbox() if confidence is None else make_bbox(confidence=confidence)
    assert ann.confidence == confidence
    assert ann.to_csv_row()["confidence"] == confidence
