"""End-to-end cleanup, identity and original-row lineage."""

import warnings
from dataclasses import dataclass
from typing import Any

import pandas as pd
import pytest


def row(name: Any = "a.jpg", **overrides: Any) -> Any:
    return {
        "image_name": name,
        "image_path": name,
        "instance_label": "cat",
        "split": "train",
        "bbox_x_tl": 0,
        "bbox_y_tl": 0,
        "bbox_x_br": 10,
        "bbox_y_br": 10,
        "image_width": 100,
        "image_height": 100,
        **overrides,
    }


def validate(rows: Any, *, profile: Any = "clearml-yolo", **kwargs: Any) -> Any:
    from cveta2.composition.verification import ValidationOptions, validate_dataframe

    if profile == "cveta2":
        rows = [{"instance_shape": "box", **record} for record in rows]
    return validate_dataframe(
        pd.DataFrame(rows),
        profile=profile,
        options=ValidationOptions(emit_warnings=False),
        **kwargs,
    )


def test_malformed_box_quarantines_whole_image_without_synthetic_background() -> None:
    result = validate(
        [row(bbox_x_br="bad"), row(bbox_x_tl=20, bbox_x_br=30), row("b.jpg")]
    )
    assert result.clean_row_positions == (2,)
    assert result.broken_row_positions == (0, 1)
    reason = next(i for i in result.reasons_for(1) if i.code == "image_quarantined")
    assert reason.related_rows == (0,)
    assert result.input_image_count == 2
    assert result.clean_image_count == 1


def test_cveta_duplicates_keep_first_across_labels_without_quarantining_image() -> None:
    result = validate([row(), row(), row(instance_label="dog")], profile="cveta2")
    assert result.clean_row_positions == (0,)
    assert result.reasons_for(1)[0].code == "duplicate_row"
    assert result.reasons_for(2)[0].code == "high_iou"


def test_quarantine_precedes_duplicate_removal() -> None:
    result = validate([row(bbox_x_br=2), row(bbox_x_br=2)])
    assert result.clean.empty
    assert not any(i.code in {"duplicate_row", "high_iou"} for i in result.issues)


def test_outside_bounds_is_recoverable_whole_image_rejection() -> None:
    from cveta2.composition.verification import DatasetWarning, validate_dataframe

    with pytest.warns(DatasetWarning, match="reject"):
        result = validate_dataframe(
            pd.DataFrame([row(bbox_x_br=110), row()]), profile="clearml-yolo"
        )
    assert result.clean.empty
    assert any(i.code == "out_of_bounds" for i in result.reasons_for(0))


def test_cveta_history_and_missing_task_ids_are_separate_per_image() -> None:
    result = validate(
        [row(task_id=1), row(task_id=2), row(task_id=None), row(task_id=None)],
        profile="cveta2",
    )
    assert result.clean_row_positions == (0, 1, 2)
    assert any(i.code == "unscoped_task" for i in result.warnings)


def test_cveta_malformed_annotation_quarantines_only_its_task() -> None:
    result = validate(
        [row(task_id=1, bbox_x_br=0), row(task_id=1), row(task_id=2)], profile="cveta2"
    )
    assert result.clean_row_positions == (2,)


def test_original_indices_values_and_unknown_container_columns_survive() -> None:
    from cveta2.composition.verification import validate_dataframe

    frame = pd.DataFrame(
        [row(instance_label="001", extra={"a": [1]}), row("b.jpg", extra={"a": [2]})],
        index=[7, 7],
    )
    original = frame.copy(deep=True)
    with warnings.catch_warnings(record=True) as seen:
        result = validate_dataframe(frame, profile="clearml-yolo")
    assert not seen
    pd.testing.assert_frame_equal(result.clean, original)
    pd.testing.assert_frame_equal(frame, original)


def test_missing_dimensions_reports_unavailable_bounds() -> None:
    record = row()
    del record["image_width"], record["image_height"]
    result = validate([record])
    assert result.is_valid
    assert "upper_image_bounds" in result.skipped_checks
    assert any(i.code == "bounds_unchecked" for i in result.warnings)


def test_mixed_negative_and_annotations_quarantines_image() -> None:
    empty = row(
        instance_label="", bbox_x_tl="", bbox_y_tl="", bbox_x_br="", bbox_y_br=""
    )
    result = validate([empty, row()])
    assert result.clean.empty
    assert any(i.code == "mixed_image_kinds" for i in result.issues)


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"split": "test"}, "split_conflict"),
        ({"image_path": "other/a.jpg"}, "path_conflict"),
        ({"image_width": 200}, "dimension_conflict"),
    ],
)
def test_image_identity_conflicts_quarantine_every_owner(
    overrides: Any, code: Any
) -> None:
    result = validate([row(), row(**overrides)])
    assert result.clean.empty
    assert any(i.code == code for i in result.issues)


def test_path_basename_must_match_image_name() -> None:
    result = validate([row(image_path="b.jpg")])
    assert result.clean.empty
    assert any(i.code == "path_name_mismatch" for i in result.issues)


def test_missing_columns_return_structural_report_without_throwing() -> None:
    from cveta2.composition.verification import ValidationOptions, validate_dataframe

    result = validate_dataframe(
        pd.DataFrame({"image_name": ["a.jpg"]}),
        profile="clearml-yolo",
        options=ValidationOptions(emit_warnings=False),
    )
    assert result.structural_errors
    assert not result.is_valid
    assert result.clean.empty
    assert result.broken_row_positions == (0,)
    assert any(i.row_position is None for i in result.issues)
    assert result.reasons_for(0)


def test_cveta_optional_identity_uses_first_nonmissing_owner() -> None:
    from cveta2.composition.verification import ValidationOptions, validate_dataframe

    records = [
        row(instance_shape="box", task_id=1, image_path=None, split=None),
        row(instance_shape="box", task_id=1, image_path="a.jpg", split="train"),
        row(instance_shape="box", task_id=1, image_path="other/a.jpg", split="test"),
    ]
    result = validate_dataframe(
        pd.DataFrame(records),
        profile="cveta2",
        options=ValidationOptions(emit_warnings=False),
    )
    assert result.clean.empty
    assert {"path_conflict", "split_conflict"}.issubset({i.code for i in result.issues})


def test_cveta_large_distinct_integer_task_ids_are_not_rounded_into_one_task() -> None:
    result = validate(
        [row(task_id="9007199254740992"), row(task_id="9007199254740993")],
        profile="cveta2",
    )
    assert result.clean_row_positions == (0, 1)


def test_valid_empty_table_is_successful_and_warns() -> None:
    from cveta2.composition.verification import DatasetWarning, validate_dataframe

    with pytest.warns(DatasetWarning, match="empty"):
        result = validate_dataframe(pd.DataFrame(columns=row()), profile="clearml-yolo")
    assert result.is_valid
    assert result.clean.empty


def test_cveta_rotation_warns_and_still_uses_axis_aligned_iou() -> None:
    result = validate([row(rotation=90), row(rotation=0)], profile="cveta2")
    assert result.clean_row_positions == (0,)
    assert any(i.code == "rotation_ignored" for i in result.warnings)


def test_cleanup_is_idempotent_and_never_mutates_input() -> None:
    from cveta2.composition.verification import ValidationOptions, validate_dataframe

    frame = pd.DataFrame(
        [row(), row(), row("b.jpg", bbox_x_br=-1), row("b.jpg"), row("c.jpg")]
    )
    original = frame.copy(deep=True)
    options = ValidationOptions(emit_warnings=False)
    first = validate_dataframe(frame, profile="clearml-yolo", options=options)
    second = validate_dataframe(first.clean, profile="clearml-yolo", options=options)
    pd.testing.assert_frame_equal(first.clean, second.clean)
    pd.testing.assert_frame_equal(frame, original)
    assert second.is_valid


def test_media_dimensions_are_used_and_mismatch_quarantines(tmp_path: Any) -> None:
    from PIL import Image

    from cveta2.composition.verification import ValidationOptions, validate_dataframe

    Image.new("RGB", (20, 30)).save(tmp_path / "a.jpg")
    options = ValidationOptions(
        check_images=True, base_dir=tmp_path, emit_warnings=False
    )
    frame = pd.DataFrame([row(image_width=20, image_height=30, bbox_x_br=21)])
    result = validate_dataframe(frame, profile="clearml-yolo", options=options)
    assert result.is_valid
    assert any(i.code == "bbox_clipped" for i in result.issues)
    frame.loc[0, "image_width"] = 21
    result = validate_dataframe(frame, profile="clearml-yolo", options=options)
    assert any(i.code == "image_dimension_mismatch" for i in result.issues)


def test_warning_emission_can_be_disabled() -> None:
    with warnings.catch_warnings(record=True) as seen:
        result = validate([row(extra="x", bbox_x_br=0)])
    assert result.broken_row_positions == (0,)
    assert not seen


@pytest.mark.parametrize(
    ("right", "expected"), [(98.999, (0, 1)), (99, (0,)), (99.001, (0,))]
)
def test_default_iou_boundary_is_inclusive_at_point_99(
    right: Any, expected: Any
) -> None:
    result = validate([row(bbox_x_br=100), row(bbox_x_br=right)])
    assert result.clean_row_positions == expected


def test_lexical_path_aliases_do_not_create_identity_conflicts() -> None:
    result = validate([row(image_path="images/../a.jpg"), row(image_path="./a.jpg")])
    assert result.clean_row_positions == (0,)
    assert not any(i.code == "path_conflict" for i in result.issues)


def test_nonlocal_image_path_is_invalid_without_attempting_network() -> None:
    result = validate([row(image_path="https://example.org/a.jpg")])
    assert result.clean.empty
    assert any(i.code == "invalid_local_path" for i in result.issues)


def test_cveta_uncomparable_extra_cells_warn_without_rejecting_negative_rows() -> None:
    @dataclass
    class Opaque:
        """An unsupported unhashable metadata cell."""

    empty = {
        "instance_shape": "none",
        "instance_label": "",
        "bbox_x_tl": "",
        "bbox_y_tl": "",
        "bbox_x_br": "",
        "bbox_y_br": "",
    }
    result = validate(
        [row(**empty, extra=Opaque()), row(**empty, extra=Opaque())], profile="cveta2"
    )
    assert result.is_valid
    assert result.clean_row_positions == (0, 1)
    assert any(
        issue.code == "exact_comparison_unavailable" for issue in result.warnings
    )
    assert "full_row_duplicates" in result.skipped_checks
