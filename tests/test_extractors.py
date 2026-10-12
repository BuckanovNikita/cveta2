"""Unit tests for _collect_shapes (shape extraction from DTOs)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

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
        task_updated_date="2026-01-01T00:00:00+00:00",
        subset="train",
        frame_jobs=dict.fromkeys(_FRAMES, ("acceptance", "completed")),
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
    assert (first.job_stage, first.job_state) == ctx.job_position(first_shape.frame)
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


def test_unsupported_shape_skipped() -> None:
    """Other unsupported shapes are still skipped."""
    ctx = _make_ctx()
    polygon = make_raw_shape(type="polyline")
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


def test_unsupported_shape_logs_warning(capture_logs: list[str]) -> None:
    """Unsupported shapes retain their warning."""
    ctx = _make_ctx()
    polygon = make_raw_shape(type="polyline")

    result = _collect_shapes([polygon], ctx)

    assert result == []
    assert any("polyline" in m.lower() for m in capture_logs)


@pytest.mark.parametrize(
    ("points", "expected"),
    [
        ([12, 30.5, 90.75, 10.25, 40.5, 80], (12, 10.25, 90.75, 80)),
        ([6, 6, 8, 2, 5, 4, 2, 8, 1, 1], (1, 1, 8, 8)),
        ([10, 20, 30, 40, 20, 50, 10, 20], (10, 20, 30, 50)),
        (
            [-0.125, 700.75, 950.875, -3.25, 20.5, 80.125],
            (-0.125, -3.25, 950.875, 700.75),
        ),
        ([0, 0, 1, 1, 2, 2], (0, 0, 2, 2)),
    ],
    ids=[
        "triangle",
        "concave-unordered-extrema",
        "closed",
        "outside-fractional",
        "collinear",
    ],
)
def test_polygon_bounds_use_every_vertex_without_clipping(
    points: list[float],
    expected: tuple[float, float, float, float],
    capture_logs: list[str],
) -> None:
    result = _collect_shapes(
        [make_raw_shape(id=73, type="polygon", points=points)], _make_ctx()
    )

    assert len(result) == 1
    box = result[0]
    assert (box.bbox_x_tl, box.bbox_y_tl, box.bbox_x_br, box.bbox_y_br) == expected
    assert box.instance_shape == "box"
    assert box.rotation == 0
    assert len(capture_logs) == 1
    assert "100" in capture_logs[0]
    assert "73" in capture_logs[0]
    assert "приближение" in capture_logs[0].lower()
    assert "прямоугольник" in capture_logs[0].lower()


def test_polygon_preserves_annotation_and_frame_context() -> None:
    ctx = _make_ctx(
        frames={1: RawFrame(name="nested/img_1.jpg", width=800, height=600)},
        attr_names={10: "color"},
    )
    ctx.task_completed = True
    ctx.frame_issues = {1: ("incorrect label; fix bounds", "open")}
    shape = make_raw_shape(
        id=73,
        type="polygon",
        frame=1,
        label_id=2,
        points=[12, 30.5, 90.75, 10.25, 40.5, 80],
        rotation=45.5,
        created_by="annotator",
        source="auto",
        occluded=True,
        z_order=4,
        attributes=[RawAttribute(10, "red"), RawAttribute(77, "matte")],
    )

    box = _collect_shapes([shape], ctx)[0]

    assert box.image_name == "img_1.jpg"
    assert box.frame_path == "nested/img_1.jpg"
    assert (box.image_width, box.image_height) == (800, 600)
    assert (box.bbox_x_tl, box.bbox_y_tl, box.bbox_x_br, box.bbox_y_br) == (
        12,
        10.25,
        90.75,
        80,
    )
    assert box.rotation == 0
    assert box.annotation_id == 73
    assert box.instance_label == "person"
    assert box.attributes == {"color": "red", "77": "matte"}
    assert box.created_by_username == "annotator"
    assert box.source == "auto"
    assert box.occluded is True
    assert box.z_order == 4
    assert (box.task_id, box.task_name) == (100, "test-task")
    assert box.task_updated_date == "2026-01-01T00:00:00+00:00"
    assert box.frame_id == 1
    assert box.subset == "train"
    assert box.task_completed is True
    assert (box.job_stage, box.job_state) == ("acceptance", "completed")
    assert (box.issue_text, box.issue_state) == ("incorrect label; fix bounds", "open")


@pytest.mark.parametrize(
    ("points", "reason"),
    [
        ([], "менее трёх"),
        ([0, 0, 10, 10], "менее трёх"),
        ([0, 0, 10, 10, 2, 2, 4], "нечётное"),
        ([0, 0, float("nan"), 10, 2, 2], "нечисловые или бесконечные"),
        ([0, 0, 10, float("inf"), 2, 2], "нечисловые или бесконечные"),
        ([0, 0, 10, 10, float("-inf"), 2], "нечисловые или бесконечные"),
        ([3, 0, 3, 10, 3, 2], "нулевая ширина"),
        ([0, 3, 10, 3, 2, 3], "нулевая высота"),
    ],
)
def test_malformed_polygon_is_diagnosed_and_counted(
    points: list[float],
    reason: str,
    capture_logs: list[str],
) -> None:
    result = _collect_shapes(
        [make_raw_shape(id=73, type="polygon", points=points)], _make_ctx()
    )

    assert result == []
    assert len(capture_logs) == 2
    assert "100" in capture_logs[0]
    assert "73" in capture_logs[0]
    assert reason in capture_logs[0].lower()
    assert "100" in capture_logs[1]
    assert "пропущено полигонов: 1" in capture_logs[1].lower()


def test_mixed_task_keeps_valid_shapes_and_counts_only_malformed_polygons(
    capture_logs: list[str],
) -> None:
    shapes = [
        make_raw_shape(id=1, rotation=27.5, points=[5, 6, 7, 8]),
        make_raw_shape(id=2, type="polygon", points=[12, 30.5, 90.75, 10.25, 40.5, 80]),
        make_raw_shape(id=3, type="polygon", points=[0, 0, 1, 1]),
        make_raw_shape(id=4, type="polygon", points=[1, 1, 1, 2, 1, 3]),
        make_raw_shape(id=5, type="polyline"),
        make_raw_shape(id=6, type="points"),
        make_raw_shape(id=7, type="polygon", frame=999, points=[0, 0, 1, 1, 2, 2]),
    ]

    result = _collect_shapes(shapes, _make_ctx())

    assert [box.annotation_id for box in result] == [1, 2]
    assert result[0].rotation == 27.5
    assert (
        result[0].bbox_x_tl,
        result[0].bbox_y_tl,
        result[0].bbox_x_br,
        result[0].bbox_y_br,
    ) == (5, 6, 7, 8)
    summaries = [
        message for message in capture_logs if "пропущено полигонов" in message.lower()
    ]
    assert len(summaries) == 1
    assert "100" in summaries[0]
    assert "пропущено полигонов: 2" in summaries[0].lower()
    assert len(capture_logs) == 6
