"""Behavioral coverage for keep-first, positional duplicate handling."""

from dataclasses import dataclass
from typing import Any, cast

import numpy as np
import pandas as pd
import pytest

from cveta2.domain.verification import geometry
from cveta2.domain.verification.geometry import BOX_COLUMNS, find_duplicates


def boxes(
    *rows: tuple[object, ...], positions: list[int] | None = None
) -> pd.DataFrame:
    return pd.DataFrame(
        rows,
        columns=[
            "image_name",
            "instance_label",
            "bbox_x_tl",
            "bbox_y_tl",
            "bbox_x_br",
            "bbox_y_br",
        ],
        index=positions,
    )


def test_exact_duplicates_reference_original_positions_and_keep_first() -> None:
    frame = boxes(
        ("a", "cat", "0", "0", "10", "10"),
        ("a", "cat", "0", "0", "10", "10"),
        positions=[2, 8],
    )
    issues = find_duplicates(frame, [(2, 8)], iou_threshold=0.99)
    assert [
        (issue.code, issue.row_position, issue.related_rows, issue.iou)
        for issue in issues
    ] == [("duplicate_row", 8, (2,), None)]


def test_class_agnostic_iou_ignores_rotation_and_lexical_numeric_differences() -> None:
    frame = boxes(
        ("a", "cat", "0", "0", "10", "10"), ("a", "dog", "0.0", "0", "10", "10")
    )
    frame["rotation"] = [0, 90]
    (issue,) = find_duplicates(frame, [(0, 1)], iou_threshold=1)
    assert (issue.code, issue.row_position, issue.related_rows, issue.iou) == (
        "high_iou",
        1,
        (0,),
        1,
    )


def test_iou_uses_absolute_coordinates_and_inclusive_threshold() -> None:
    frame = boxes(("a", "cat", 0, 0, 3, 1), ("a", "cat", 1, 0, 4, 1))
    (issue,) = find_duplicates(frame, [(0, 1)], iou_threshold=0.5)
    assert issue.iou == pytest.approx(0.5)
    assert find_duplicates(frame, [(0, 1)], iou_threshold=0.50001) == []


def test_removed_boxes_cannot_suppress_later_chain_members() -> None:
    frame = boxes(
        ("a", "cat", 0, 0, 3, 1), ("a", "dog", 1, 0, 4, 1), ("a", "bird", 2, 0, 5, 1)
    )
    issues = find_duplicates(frame, [(0, 1, 2)], iou_threshold=0.5)
    assert [(issue.row_position, issue.related_rows) for issue in issues] == [(1, (0,))]


def test_group_histories_and_singletons_remain_independent() -> None:
    frame = boxes(*[("a", "cat", 0, 0, 3, 1)] * 3, positions=[3, 9, 12])
    assert find_duplicates(frame, [(3,), (9,), (12,)], iou_threshold=1) == []


def test_extra_columns_and_null_aware_containers_define_duplicates() -> None:
    frame = boxes(*[("a", "", None, None, None, None)] * 5)
    frame["extra"] = pd.Series(
        [[1, None], [1, np.nan], {"a": [2, None]}, {"a": [2, pd.NA]}, (1, None)],
        dtype=object,
    )
    original = frame.copy(deep=True)
    issues = find_duplicates(frame, [(0, 1, 2, 3, 4)], iou_threshold=1)
    assert [
        (issue.code, issue.row_position, issue.related_rows) for issue in issues
    ] == [
        ("duplicate_row", 1, (0,)),
        ("duplicate_row", 3, (2,)),
    ]
    pd.testing.assert_frame_equal(frame, original)


def test_numpy_array_extras_are_compared_without_mutation() -> None:
    frame = boxes(*[("a", "", None, None, None, None)] * 3)
    first = np.array([1.0, np.nan])
    frame["extra"] = pd.Series(
        [first, np.array([1.0, np.nan]), np.array([2.0, np.nan])], dtype=object
    )
    issues = find_duplicates(frame, [(0, 1, 2)], iou_threshold=1)
    assert [(issue.code, issue.row_position) for issue in issues] == [
        ("duplicate_row", 1)
    ]
    assert cast("object", frame.loc[0, "extra"]) is first
    np.testing.assert_equal(first, np.array([1.0, np.nan]))


def test_negative_and_deleted_rows_skip_iou_but_still_deduplicate_exact_rows() -> None:
    frame = boxes(
        ("a", "cat", 0, 0, 10, 10),
        ("a", "", None, None, None, None),
        ("a", "", None, None, None, None),
        ("a", "", None, None, None, None),
    )
    frame["instance_shape"] = ["box", "none", "deleted", "deleted"]
    issues = find_duplicates(frame, [(0, 1, 2, 3)], iou_threshold=1)
    assert [(issue.code, issue.row_position) for issue in issues] == [
        ("duplicate_row", 3)
    ]


def test_exact_copies_of_rejected_rows_reference_a_retained_box() -> None:
    frame = boxes(
        ("a", "cat", 0, 0, 10, 10),
        ("a", "dog", 0, 0, 10, 10),
        ("a", "dog", 0, 0, 10, 10),
    )
    issues = find_duplicates(frame, [(0, 1, 2)], iou_threshold=1)
    assert [
        (issue.code, issue.row_position, issue.related_rows) for issue in issues
    ] == [
        ("high_iou", 1, (0,)),
        ("high_iou", 2, (0,)),
    ]


def test_exact_duplicate_comparison_preserves_lexical_strings() -> None:
    frame = boxes(("a", "", None, None, None, None), ("a", "", None, None, None, None))
    frame["extra"] = ["01", "1"]
    assert find_duplicates(frame, [(0, 1)], iou_threshold=1) == []


def test_missing_optional_shape_does_not_prevent_box_duplicates() -> None:
    frame = boxes(("a", "cat", 0, 0, 10, 10), ("a", "dog", 0, 0, 10, 10))
    frame["instance_shape"] = [pd.NA, pd.NA]
    issues = find_duplicates(frame, [(0, 1)], iou_threshold=1)
    assert [(issue.code, issue.row_position) for issue in issues] == [("high_iou", 1)]


@pytest.mark.parametrize("extent", [1e200, 1e-200])
def test_finite_extreme_coordinates_do_not_overflow_or_underflow_iou(
    extent: float,
) -> None:
    frame = boxes(
        ("a", "cat", 0, 0, extent, extent), ("a", "dog", 0, 0, extent, extent)
    )
    issues = find_duplicates(frame, [(0, 1)], iou_threshold=1)
    assert [(issue.code, issue.row_position, issue.iou) for issue in issues] == [
        ("high_iou", 1, 1)
    ]


@pytest.mark.parametrize(
    "factory",
    [
        lambda value: bytearray([value]),
        lambda value: memoryview(bytearray([value])),
        lambda value: pd.Series([value, 2], index=["x", "y"], name="extra"),
        lambda value: pd.DataFrame({"x": [value, 2]}),
    ],
)
def test_binary_and_tabular_extras_preserve_structural_equality(factory: Any) -> None:
    frame = boxes(*[("a", "", None, None, None, None)] * 3)
    originals = [factory(1), factory(1), factory(3)]
    frame["extra"] = pd.Series(originals, dtype=object)
    issues = find_duplicates(frame, [(0, 1, 2)], iou_threshold=0.99)
    assert [
        (issue.code, issue.row_position, issue.related_rows) for issue in issues
    ] == [("duplicate_row", 1, (0,))]
    assert all(
        frame.iloc[position]["extra"] is original
        for position, original in enumerate(originals)
    )


@dataclass
class OpaqueExtra:
    """An opaque unhashable metadata value outside the supported equality contract."""


def test_opaque_extras_warn_without_guessing_equality_and_still_check_iou() -> None:
    frame = boxes(("a", "cat", 0, 0, 10, 10), ("a", "dog", 0, 0, 10, 10))
    frame["extra"] = pd.Series([OpaqueExtra(), OpaqueExtra()], dtype=object)
    issues = find_duplicates(frame, [(0, 1)], iou_threshold=0.99)
    assert [
        (issue.row_position, issue.related_rows)
        for issue in issues
        if issue.code == "high_iou"
    ] == [(1, (0,))]
    assert [
        issue.row_position
        for issue in issues
        if issue.code == "exact_comparison_unavailable"
    ] == [0, 1]
    assert all(
        issue.severity == "warning"
        for issue in issues
        if issue.code == "exact_comparison_unavailable"
    )


def test_class_conflicts_include_both_endpoints_of_every_cross_class_pair() -> None:
    frame = boxes(
        ("a", "cat", 0, 0, 10, 10),
        ("a", "dog", 0, 0, 10, 10),
        ("a", "bird", 0, 0, 10, 10),
        positions=[2, 8, 13],
    )
    original = frame.copy(deep=True)
    issues = geometry.find_class_conflicts(frame, [(13, 2, 8)], iou_threshold=1)
    assert [(issue.row_position, issue.related_rows) for issue in issues] == [
        (2, (8,)),
        (8, (2,)),
        (2, (13,)),
        (13, (2,)),
        (8, (13,)),
        (13, (8,)),
    ]
    assert all(
        issue.code == "class_conflict" and issue.severity == "error" for issue in issues
    )
    assert all(issue.columns == ("instance_label", *BOX_COLUMNS) for issue in issues)
    assert all(issue.iou == 1 and "class" in issue.message.lower() for issue in issues)
    pd.testing.assert_frame_equal(frame, original)


def test_class_conflicts_consider_rows_that_same_class_deduplication_would_remove() -> (
    None
):
    frame = boxes(
        ("a", "cat", 0, 0, 10, 10),
        ("a", "cat", 2, 0, 12, 10),
        ("a", "dog", 4, 0, 14, 10),
    )
    assert [
        (issue.row_position, issue.related_rows)
        for issue in find_duplicates(frame, [(0, 1)], iou_threshold=0.6)
    ] == [(1, (0,))]
    issues = geometry.find_class_conflicts(frame, [(0, 1, 2)], iou_threshold=0.6)
    assert [(issue.row_position, issue.related_rows) for issue in issues] == [
        (1, (2,)),
        (2, (1,)),
    ]
    assert all(issue.iou == pytest.approx(2 / 3) for issue in issues)


def test_class_conflict_threshold_is_inclusive() -> None:
    frame = boxes(("a", "cat", 0, 0, 3, 3), ("a", "dog", 1, 0, 4, 3))
    issues = geometry.find_class_conflicts(frame, [(0, 1)], iou_threshold=0.5)
    assert len(issues) == 2
    assert all(issue.iou == pytest.approx(0.5) for issue in issues)
    assert geometry.find_class_conflicts(frame, [(0, 1)], iou_threshold=0.50001) == []


def test_class_conflicts_keep_group_histories_independent_and_skip_same_class() -> None:
    frame = boxes(
        ("a", "cat", 0, 0, 10, 10),
        ("a", "cat", 0, 0, 10, 10),
        ("b", "dog", 0, 0, 10, 10),
        ("b", "bird", 0, 0, 10, 10),
        positions=[3, 9, 12, 18],
    )
    issues = geometry.find_class_conflicts(
        frame, [(3, 9), (12,), (18,)], iou_threshold=1
    )
    assert issues == []


@pytest.mark.parametrize("empty", [None, "", pd.NA, np.nan])
def test_class_conflicts_skip_empty_negative_boxes(empty: object) -> None:
    frame = boxes(
        ("a", "cat", 0, 0, 10, 10),
        ("a", "", empty, empty, empty, empty),
        ("a", "dog", 0, 0, 10, 10),
    )
    issues = geometry.find_class_conflicts(frame, [(0, 1, 2)], iou_threshold=1)
    assert [(issue.row_position, issue.related_rows) for issue in issues] == [
        (0, (2,)),
        (2, (0,)),
    ]


@pytest.mark.parametrize("extent", [1e200, 1e-200])
def test_class_conflict_iou_is_stable_for_extreme_finite_coordinates(
    extent: float,
) -> None:
    frame = boxes(
        ("a", "cat", 0, 0, extent, extent), ("a", "dog", 0, 0, extent, extent)
    )
    with np.errstate(over="raise", invalid="raise", divide="raise"):
        issues = geometry.find_class_conflicts(frame, [(0, 1)], iou_threshold=1)
    assert [(issue.row_position, issue.iou) for issue in issues] == [(0, 1), (1, 1)]


def test_class_conflicts_use_original_labels_and_ignore_opaque_metadata() -> None:
    frame = boxes(("a", "01", "0", "0", "10", "10"), ("a", "1", "0.0", "0", "10", "10"))
    frame["extra"] = pd.Series([OpaqueExtra(), OpaqueExtra()], dtype=object)
    issues = geometry.find_class_conflicts(frame, [(0, 1)], iou_threshold=1)
    assert len(issues) == 2
    assert all(issue.code == "class_conflict" for issue in issues)
