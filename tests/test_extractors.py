"""Unit tests for _collect_shapes (shape extraction from DTOs)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from cveta2._client.context import _TaskContext
from cveta2._client.dtos import RawAttribute, RawFrame
from cveta2._client.extractors import _collect_shapes
from tests.helpers import make_raw_shape

if TYPE_CHECKING:
    from cveta2._client.dtos import RawAnnotations, RawDataMeta
    from cveta2.models import TaskInfo

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FRAMES: dict[int, RawFrame] = {
    0: RawFrame(name="img_0.jpg", width=640, height=480),
    1: RawFrame(name="img_1.jpg", width=800, height=600),
}


def _make_ctx(
    frames: dict[int, RawFrame] | None = None,
    label_names: dict[int, str] | None = None,
    attr_names: dict[int, str] | None = None,
) -> _TaskContext:
    return _TaskContext(
        frames=frames if frames is not None else dict(_FRAMES),
        label_names=label_names if label_names is not None else {1: "car", 2: "person"},
        attr_names=attr_names if attr_names is not None else {},
        task_id=100,
        task_name="test-task",
        task_status="completed",
        task_updated_date="2026-01-01T00:00:00+00:00",
        subset="train",
    )


def _ctx_for(
    name: str,
    tasks_by_name: dict[str, tuple[TaskInfo, RawDataMeta, RawAnnotations]],
    label_maps: tuple[dict[int, str], dict[int, str]],
) -> tuple[_TaskContext, RawAnnotations]:
    """Build _TaskContext + return annotations for a named fixture task."""
    task, data_meta, annotations = tasks_by_name[name]
    label_names, attr_names = label_maps
    ctx = _TaskContext.from_raw(task, data_meta, label_names, attr_names)
    return ctx, annotations


# ---------------------------------------------------------------------------
# Tests using fixture data
# ---------------------------------------------------------------------------


def test_normal_task_produces_annotations(
    coco8_tasks_by_name: dict[str, tuple[TaskInfo, RawDataMeta, RawAnnotations]],
    coco8_label_maps: tuple[dict[int, str], dict[int, str]],
) -> None:
    """Normal task produces the expected number of BBoxAnnotation objects."""
    ctx, annotations = _ctx_for("normal", coco8_tasks_by_name, coco8_label_maps)
    result = _collect_shapes(annotations.shapes, ctx)

    assert len(result) == len(annotations.shapes)
    assert len(result) == 30  # known from fixture


def test_empty_task_no_annotations(
    coco8_tasks_by_name: dict[str, tuple[TaskInfo, RawDataMeta, RawAnnotations]],
    coco8_label_maps: tuple[dict[int, str], dict[int, str]],
) -> None:
    """all-empty task has no shapes, so _collect_shapes returns []."""
    ctx, annotations = _ctx_for("all-empty", coco8_tasks_by_name, coco8_label_maps)
    result = _collect_shapes(annotations.shapes, ctx)
    assert result == []


def test_field_mapping_correct(
    coco8_tasks_by_name: dict[str, tuple[TaskInfo, RawDataMeta, RawAnnotations]],
    coco8_label_maps: tuple[dict[int, str], dict[int, str]],
) -> None:
    """First shape from normal task has correct field mapping."""
    ctx, annotations = _ctx_for("normal", coco8_tasks_by_name, coco8_label_maps)
    result = _collect_shapes(annotations.shapes, ctx)
    first = result[0]
    first_shape = annotations.shapes[0]

    assert first.image_name == ctx.frames[first_shape.frame].name
    assert first.bbox_x_tl == first_shape.points[0]
    assert first.bbox_y_tl == first_shape.points[1]
    assert first.bbox_x_br == first_shape.points[2]
    assert first.bbox_y_br == first_shape.points[3]
    assert first.instance_label == ctx.label_names[first_shape.label_id]
    assert first.task_id == ctx.task_id
    assert first.task_name == ctx.task_name
    assert first.frame_id == first_shape.frame
    assert first.occluded == first_shape.occluded
    assert first.rotation == first_shape.rotation
    assert first.source == first_shape.source
    assert first.created_by_username == first_shape.created_by
    assert first.image_width == ctx.frames[first_shape.frame].width
    assert first.image_height == ctx.frames[first_shape.frame].height
    assert first.z_order == first_shape.z_order
    assert first.subset == ctx.subset
    assert first.task_status == ctx.task_status
    assert first.task_updated_date == ctx.task_updated_date


def test_all_except_first_empty(
    coco8_tasks_by_name: dict[str, tuple[TaskInfo, RawDataMeta, RawAnnotations]],
    coco8_label_maps: tuple[dict[int, str], dict[int, str]],
) -> None:
    """all-except-first-empty: only frame 0 produces annotations."""
    ctx, annotations = _ctx_for(
        "all-except-first-empty", coco8_tasks_by_name, coco8_label_maps
    )
    result = _collect_shapes(annotations.shapes, ctx)

    assert len(result) == 8  # known from fixture: 8 shapes all on frame 0
    frame_ids = {a.frame_id for a in result}
    assert frame_ids == {0}


# ---------------------------------------------------------------------------
# Tests using synthetic data
# ---------------------------------------------------------------------------


def test_non_rectangle_shape_skipped() -> None:
    """Non-rectangle shapes are skipped."""
    ctx = _make_ctx()
    polygon = make_raw_shape(type="polygon")
    rect = make_raw_shape(id=2)
    result = _collect_shapes([polygon, rect], ctx)

    assert len(result) == 1
    assert result[0].annotation_id == 2


def test_missing_frame_skipped() -> None:
    """Shape referencing a non-existent frame is skipped."""
    ctx = _make_ctx()
    bad_frame = make_raw_shape(frame=999)
    good = make_raw_shape(id=2, frame=0)
    result = _collect_shapes([bad_frame, good], ctx)

    assert len(result) == 1
    assert result[0].frame_id == 0


def test_unknown_label_fallback() -> None:
    """Shape with unknown label_id gets instance_label '<unknown>'."""
    ctx = _make_ctx(label_names={})
    shape = make_raw_shape(label_id=9999)
    result = _collect_shapes([shape], ctx)

    assert len(result) == 1
    assert result[0].instance_label == "<unknown>"


def test_attributes_resolved() -> None:
    """Shape attributes with known spec_ids are resolved to names."""
    ctx = _make_ctx(attr_names={10: "color", 11: "make"})
    attrs = [
        RawAttribute(spec_id=10, value="red"),
        RawAttribute(spec_id=11, value="BMW"),
    ]
    shape = make_raw_shape(attributes=attrs)
    result = _collect_shapes([shape], ctx)

    assert len(result) == 1
    assert result[0].attributes == {"color": "red", "make": "BMW"}


def test_unknown_attribute_spec_falls_back_to_its_id() -> None:
    """An attribute whose spec is missing keeps a usable key.

    Real CVAT projects carry attributes whose spec is not in the label map
    (added to one label, read from a task that predates it). The fallback keys
    them by id; without it the key becomes None and every such attribute
    collapses into a single ``"null"`` entry once the dict is JSON-encoded into
    the CSV cell — silently losing all but the last value.
    """
    ctx = _make_ctx(attr_names={10: "color"})
    attrs = [
        RawAttribute(spec_id=10, value="red"),
        RawAttribute(spec_id=77, value="matte"),
        RawAttribute(spec_id=88, value="rusty"),
    ]
    shape = make_raw_shape(attributes=attrs)

    result = _collect_shapes([shape], ctx)

    assert result[0].attributes == {"color": "red", "77": "matte", "88": "rusty"}


def test_author_is_carried_over_from_the_shape() -> None:
    """``created_by_username=shape.created_by`` must survive the transfer.

    The coco8 fixtures have ``created_by=None``, which equals the model
    default, so asserting against them cannot tell a dropped keyword from a
    forwarded one. This uses a synthetic shape with a real author.
    """
    ctx = _make_ctx()
    shape = make_raw_shape(created_by="tester")

    result = _collect_shapes([shape], ctx)

    assert result[0].created_by_username == "tester"


def test_multiple_shapes_on_same_frame() -> None:
    """Two shapes on the same frame are both collected."""
    ctx = _make_ctx()
    s1 = make_raw_shape(id=1, frame=0, label_id=1)
    s2 = make_raw_shape(id=2, frame=0, label_id=2)
    result = _collect_shapes([s1, s2], ctx)

    assert len(result) == 2
    assert {r.annotation_id for r in result} == {1, 2}
    assert all(r.frame_id == 0 for r in result)


def test_non_rectangle_shape_logs_warning(capture_logs: list[str]) -> None:
    """Non-rectangle shape is skipped and a warning is logged."""
    ctx = _make_ctx()
    polygon = make_raw_shape(type="polygon")

    result = _collect_shapes([polygon], ctx)

    assert result == []
    assert any("polygon" in m.lower() for m in capture_logs)
