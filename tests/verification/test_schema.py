"""Semantic field and row contracts, independent of pandas inferred dtypes."""

import numpy as np
import pandas as pd
import pandera.pandas as pa
import pytest

from cveta2.domain.verification.cells import integer, is_missing, number
from cveta2.domain.verification.schema import schema_for, schema_issues


def box(**updates: object) -> dict[str, object]:
    row: dict[str, object] = {
        "image_name": "NA.jpg",
        "image_width": "100",
        "image_height": 50.0,
        "instance_shape": "box",
        "instance_label": "001",
        "bbox_x_tl": "0",
        "bbox_y_tl": 1.0,
        "bbox_x_br": "10",
        "bbox_y_br": 20,
    }
    return row | updates


@pytest.mark.parametrize("value", [None, pd.NA, np.nan, ""])
def test_only_empty_cells_are_missing(value: object) -> None:
    assert is_missing(value)


@pytest.mark.parametrize("value", ["NA", "null", " ", [], {}, False])
def test_literal_text_and_containers_are_not_missing(value: object) -> None:
    assert not is_missing(value)


@pytest.mark.parametrize(
    "value", [True, np.bool_(0), "nan", "inf", float("inf"), {}, "x"]
)
def test_non_finite_and_boolean_values_are_not_numbers(value: object) -> None:
    assert number(value) is None
    assert not integer(value)


def test_numeric_semantics_accept_csv_and_float_integrals() -> None:
    assert number("1.25") == 1.25
    assert integer("12.0")
    assert integer(np.int64(3))
    assert not integer(1.5)


def test_valid_full_cveta_record_retains_raw_cells_and_extra_columns() -> None:
    frame = pd.DataFrame(
        [
            box(
                task_id="1.0",
                task_name="task",
                job_stage="annotation",
                job_state="in progress",
                task_completed="TRUE",
                task_updated_date="producer supplied date",
                created_by_username="user",
                frame_id=0,
                split="train",
                subset="NA",
                occluded=np.bool_(1),
                z_order="1.0",
                rotation="360",
                source="custom source",
                annotation_id=4,
                confidence="0.5",
                issue_text="text",
                issue_state="open | resolved",
                s3_image_path="s3://bucket/key",
                image_path="relative/image.jpg",
                attributes='{"NA": "001"}',
                extra="raw",
            )
        ]
    )
    before = frame.copy(deep=True)
    assert schema_issues(frame, "cveta2") == []
    pd.testing.assert_frame_equal(
        schema_for("cveta2").validate(frame, lazy=True), before
    )
    pd.testing.assert_frame_equal(frame, before)


@pytest.mark.parametrize(("shape", "width"), [("none", 100), ("deleted", 0)])
def test_sparse_cveta_images_accept_null_annotation_metadata(
    shape: str, width: int
) -> None:
    frame = pd.DataFrame(
        [
            box(
                instance_shape=shape,
                image_width=width,
                image_height=width,
                instance_label=None,
                bbox_x_tl=None,
                bbox_y_tl=None,
                bbox_x_br=None,
                bbox_y_br=None,
                occluded=None,
                z_order=None,
                rotation=None,
                attributes="{}",
            )
        ]
    )
    assert schema_issues(frame, "cveta2") == []


@pytest.mark.parametrize("label", ["cat", 0, 1.5, "001", "NA"])
def test_clearml_accepts_text_and_numeric_labels(label: object) -> None:
    frame = pd.DataFrame(
        [box(instance_label=label, image_path="image.jpg", split="val")]
    )
    assert schema_issues(frame, "clearml-yolo") == []


def test_clearml_explicit_negative_needs_all_annotation_cells_blank() -> None:
    row = box(
        image_path="x.jpg",
        split="test",
        instance_shape="none",
        instance_label="",
        bbox_x_tl="",
        bbox_y_tl="",
        bbox_x_br="",
        bbox_y_br="",
    )
    assert schema_issues(pd.DataFrame([row]), "clearml-yolo") == []
    row["bbox_x_tl"] = 0
    assert "invalid_negative" in {
        i.code for i in schema_issues(pd.DataFrame([row]), "clearml-yolo")
    }


def test_collects_all_reasons_for_one_row_by_position() -> None:
    frame = pd.DataFrame(
        [
            box(
                image_name="",
                image_width=1.5,
                bbox_x_tl=-1,
                bbox_x_br=-2,
                confidence=2,
                attributes='{"a": 1}',
                split="bad",
            )
        ]
    )
    issues = schema_issues(frame, "cveta2")
    assert {i.code for i in issues} >= {
        "invalid_image_name",
        "invalid_dimension",
        "negative_coordinate",
        "invalid_box_area",
        "invalid_confidence",
        "invalid_attributes",
        "invalid_split",
    }
    assert all(i.row_position == 0 for i in issues)
    with pytest.raises(pa.errors.SchemaErrors):
        schema_for("cveta2").validate(frame, lazy=True)


def test_row_checks_report_one_reason_with_relevant_columns() -> None:
    issues = schema_issues(pd.DataFrame([box(image_width=0, bbox_x_br=-1)]), "cveta2")
    areas = [issue for issue in issues if issue.code == "invalid_box_area"]
    assert len(areas) == 1
    assert areas[0].columns == ("bbox_x_tl", "bbox_y_tl", "bbox_x_br", "bbox_y_br")
    assert "image_name" not in next(
        i.columns for i in issues if i.code == "invalid_dimension"
    )


@pytest.mark.parametrize(
    ("column", "value", "code"),
    [
        ("instance_label", 1, "invalid_label"),
        ("instance_shape", "polygon", "invalid_shape"),
        ("bbox_x_tl", True, "invalid_coordinate"),
        ("bbox_y_tl", "nan", "invalid_coordinate"),
        ("image_height", 0, "invalid_dimension"),
        ("task_id", -1, "invalid_integer"),
        ("annotation_id", "1.5", "invalid_integer"),
        ("frame_id", "foo", "invalid_integer"),
        ("z_order", 0.5, "invalid_integer"),
        ("rotation", 361, "invalid_rotation"),
        ("occluded", "perhaps", "invalid_boolean"),
        ("task_completed", 2, "invalid_boolean"),
        ("attributes", "[]", "invalid_attributes"),
        ("attributes", "null", "invalid_attributes"),
        ("job_stage", "wrong", "invalid_job_stage"),
        ("job_state", "wrong", "invalid_job_state"),
        ("issue_state", "closed", "invalid_issue_state"),
        ("task_name", 17, "invalid_text"),
    ],
)
def test_invalid_field_semantics_are_reported(
    column: str, value: object, code: str
) -> None:
    issues = schema_issues(pd.DataFrame([box(**{column: value})]), "cveta2")
    assert any(i.code == code and column in i.columns for i in issues)


@pytest.mark.parametrize(
    "value", [True, False, "TRUE", "false", 0, 1, "0", "1", None, ""]
)
def test_boolean_metadata_supports_native_and_csv_values(value: object) -> None:
    assert schema_issues(pd.DataFrame([box(occluded=value)]), "cveta2") == []


def test_optional_empty_metadata_and_upload_issue_state_are_valid() -> None:
    assert (
        schema_issues(
            pd.DataFrame(
                [
                    box(
                        job_stage="",
                        job_state="",
                        issue_state="new",
                        task_id=None,
                        confidence="",
                        attributes="",
                    )
                ]
            ),
            "cveta2",
        )
        == []
    )


def test_missing_columns_are_dataset_issues_even_in_empty_frame() -> None:
    issues = schema_issues(pd.DataFrame(columns=["image_name"]), "cveta2")
    assert {i.columns[0] for i in issues} == {
        "image_width",
        "image_height",
        "instance_shape",
        "instance_label",
        "bbox_x_tl",
        "bbox_y_tl",
        "bbox_x_br",
        "bbox_y_br",
    }
    assert all(i.code == "missing_column" and i.row_position is None for i in issues)


def test_empty_valid_header_has_no_row_failures() -> None:
    assert schema_issues(pd.DataFrame(columns=list(box())), "cveta2") == []


def test_missing_columns_do_not_prevent_other_applicable_checks() -> None:
    issues = schema_issues(
        pd.DataFrame([{"image_name": "", "confidence": 2}]), "cveta2"
    )
    assert {i.code for i in issues} >= {
        "missing_column",
        "invalid_image_name",
        "invalid_confidence",
    }


def test_invalid_labels_are_checked_even_when_coordinate_headers_are_missing() -> None:
    issues = schema_issues(
        pd.DataFrame([{"image_name": "x", "instance_label": True}]), "cveta2"
    )
    assert any(
        issue.code == "invalid_label" and issue.row_position == 0 for issue in issues
    )


def test_clearml_source_row_id_can_be_an_opaque_lexical_identifier() -> None:
    row = box(image_path="x", split="train", source_row_id="capture:0001")
    assert schema_issues(pd.DataFrame([row]), "clearml-yolo") == []


def test_integrality_is_not_rounded_through_binary_float_parsing() -> None:
    assert not integer("9007199254740993.5")
    assert integer("9007199254740993")


@pytest.mark.parametrize("name", [".", "..", "folder/img.jpg", "folder\\img.jpg"])
def test_image_name_is_a_bare_filename(name: str) -> None:
    issues = schema_issues(pd.DataFrame([box(image_name=name)]), "cveta2")
    assert any(issue.code == "invalid_image_name" for issue in issues)


def test_derived_box_area_must_remain_finite() -> None:
    issues = schema_issues(
        pd.DataFrame([box(bbox_x_br=1e300, bbox_y_br=1e300)]), "cveta2"
    )
    assert any(issue.code == "invalid_box_area" for issue in issues)


def test_duplicate_headers_are_reported_as_actual_column_names() -> None:
    frame = pd.DataFrame([["a.jpg", "b.jpg"]], columns=["image_name", "image_name"])
    duplicates = [
        issue
        for issue in schema_issues(frame, "cveta2")
        if issue.code == "duplicate_column"
    ]
    assert len(duplicates) == 1
    assert duplicates[0].columns == ("image_name",)
    assert duplicates[0].row_position is None


def test_clearml_ignores_shape_but_rejects_empty_split() -> None:
    issues = schema_issues(
        pd.DataFrame([box(instance_shape="deleted", image_path="x", split="")]),
        "clearml-yolo",
    )
    assert {i.code for i in issues} == {"invalid_split"}
