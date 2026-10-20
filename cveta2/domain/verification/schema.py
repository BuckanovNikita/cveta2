"""Complete, non-coercing Pandera field schemas and positional diagnostics."""

import json
from collections.abc import Callable
from functools import partial
from math import isfinite
from typing import cast

import numpy as np
import pandas as pd
import pandera.pandas as pa

from cveta2.domain.verification.cells import integer, is_missing, number
from cveta2.domain.verification.models import DatasetInputError, Issue, Profile

BOX_COLUMNS = ("bbox_x_tl", "bbox_y_tl", "bbox_x_br", "bbox_y_br")
CVETA_COLUMNS = (
    "image_name",
    "image_width",
    "image_height",
    "instance_shape",
    "instance_label",
    *BOX_COLUMNS,
    "task_id",
    "task_name",
    "job_stage",
    "job_state",
    "task_completed",
    "task_updated_date",
    "created_by_username",
    "frame_id",
    "split",
    "subset",
    "occluded",
    "z_order",
    "rotation",
    "source",
    "annotation_id",
    "confidence",
    "issue_text",
    "issue_state",
    "s3_image_path",
    "image_path",
    "attributes",
)
REQUIRED_COLUMNS: dict[Profile, tuple[str, ...]] = {
    "cveta2": (
        "image_name",
        "image_width",
        "image_height",
        "instance_shape",
        "instance_label",
        *BOX_COLUMNS,
    ),
    "clearml-yolo": (
        "image_name",
        "image_path",
        "instance_label",
        *BOX_COLUMNS,
        "split",
    ),
}
KNOWN_COLUMNS = frozenset((*CVETA_COLUMNS, "width", "height", "source_row_id"))
CLEARML_COLUMNS = (
    *REQUIRED_COLUMNS["clearml-yolo"],
    "image_width",
    "image_height",
    "width",
    "height",
)

_ROW_COLUMNS: dict[str, tuple[str, ...]] = {
    "invalid_label": ("instance_label",),
    "missing_bbox": BOX_COLUMNS,
    "invalid_negative": ("instance_label", *BOX_COLUMNS),
    "invalid_box_area": BOX_COLUMNS,
    "invalid_dimension": ("image_width", "image_height", "width", "height"),
}

_REASONS = {
    "missing_column": "Required column is absent",
    "duplicate_column": "Column names must be unique",
    "invalid_image_name": (
        "Expected a nonempty bare filename without directory separators"
    ),
    "invalid_image_path": "Expected a nonempty local image path",
    "invalid_text": "Expected text or an empty optional cell",
    "invalid_shape": "Expected a supported shape: box or none (also deleted in cveta2)",
    "invalid_label": "A box needs a nonempty label; cveta2 labels must be strings",
    "missing_bbox": "A box requires all four coordinates",
    "invalid_coordinate": "Expected a finite number for the coordinate",
    "negative_coordinate": "Coordinates must be nonnegative",
    "invalid_box_area": (
        "Box width, height and derived area must be positive and finite"
    ),
    "invalid_negative": (
        "Empty/deleted records require an empty label and all four coordinates empty"
    ),
    "invalid_dimension": (
        "Expected positive "
        "integral image dimensions (zero allowed "
        "for cveta2 deleted rows)"
    ),
    "invalid_integer": (
        "Expected an integral value; task, frame and annotation IDs must be nonnegative"
    ),
    "invalid_boolean": "Expected true/false or 0/1",
    "invalid_rotation": "Expected a finite rotation in [0, 360] degrees",
    "invalid_confidence": "Expected a finite confidence in [0, 1]",
    "invalid_attributes": "Expected a JSON object mapping string keys to string values",
    "invalid_split": (
        "Expected train, val or test (an empty split is allowed only in cveta2)"
    ),
    "invalid_job_stage": "Expected annotation, validation or acceptance",
    "invalid_job_state": "Expected new, in progress, completed or rejected",
    "invalid_issue_state": (
        "Expected open, resolved, their pipe-separated combination, or upload value new"
    ),
}


def required_columns(profile: Profile) -> tuple[str, ...]:
    """Return required headers, independent of whether a dataset contains any rows."""
    try:
        return REQUIRED_COLUMNS[profile]
    except KeyError as error:
        raise DatasetInputError(f"Unknown validation profile: {profile!r}") from error


def _text(value: object) -> bool:
    return isinstance(value, str)


def _nonempty_text(value: object) -> bool:
    return isinstance(value, str) and value != ""


def _image_name(value: object) -> bool:
    return (
        _nonempty_text(value)
        and isinstance(value, str)
        and value not in (".", "..")
        and not any(separator in value for separator in ("/", "\\"))
    )


def _label(profile: Profile, value: object) -> bool:
    return _nonempty_text(value) or (
        profile == "clearml-yolo" and number(value) is not None
    )


def _optional(predicate: Callable[[object], bool], value: object) -> bool:
    return is_missing(value) or predicate(value)


def _enum(allowed: tuple[str, ...], value: object) -> bool:
    return isinstance(value, str) and value in allowed


def _nonnegative_integer(value: object) -> bool:
    parsed = number(value)
    return integer(value) and parsed is not None and parsed >= 0


def _boolean(value: object) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return True
    if isinstance(value, str) and value.lower() in ("true", "false"):
        return True
    return number(value) in (0, 1)


def _range(lower: float, upper: float, value: object) -> bool:
    parsed = number(value)
    return parsed is not None and lower <= parsed <= upper


def _attributes(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed: object = json.loads(value)
    except (ValueError, RecursionError):
        return False
    return isinstance(parsed, dict) and all(
        isinstance(key, str) and isinstance(item, str) for key, item in parsed.items()
    )


def _check(
    predicate: Callable[[object], bool], code: str, *, optional: bool = True
) -> pa.Check:
    check = partial(_optional, predicate) if optional else predicate
    return pa.Check(check, element_wise=True, ignore_na=False, name=code)


def valid_box_geometry(
    coordinates: tuple[float, float, float, float], profile: Profile
) -> bool:
    """Check derived geometry, sharing the profile's minimum with bounded repairs."""
    x1, y1, x2, y2 = coordinates
    width, height = x2 - x1, y2 - y1
    minimum = 2 if profile == "clearml-yolo" else 0
    area = width * height
    return (
        width > minimum
        and height > minimum
        and (profile == "cveta2" or area > minimum)
        and all(map(isfinite, (width, height, area)))
    )


# Keep the complete schema-code dispatch explicit and non-coercing.
def _row_masks(frame: pd.DataFrame, profile: Profile, code: str) -> "pd.Series[bool]":  # noqa: C901, PLR0912
    """Produce boolean masks; leave missing-header checks to the schema."""
    valid: pd.Series[bool] = pd.Series(data=True, index=frame.index, dtype=bool)
    if code == "invalid_dimension":
        for column in ("image_width", "image_height", "width", "height"):
            if column not in frame:
                continue
            shapes = (
                frame["instance_shape"]
                if profile == "cveta2" and "instance_shape" in frame
                else [None] * len(frame)
            )
            required = profile == "cveta2" and column in ("image_width", "image_height")
            values = []
            for value, shape in zip(frame[column], shapes, strict=True):
                parsed = number(value)
                deleted = (
                    isinstance(shape, str)
                    and shape == "deleted"
                    and profile == "cveta2"
                )
                values.append(
                    (not required and is_missing(value))
                    or (
                        integer(value)
                        and parsed is not None
                        and (parsed >= 0 if deleted else parsed > 0)
                    )
                )
            valid &= pd.Series(values, index=frame.index, dtype=bool)
        return valid
    if "instance_label" not in frame or not set(BOX_COLUMNS).issubset(frame.columns):
        return valid
    shapes = (
        frame["instance_shape"]
        if profile == "cveta2" and "instance_shape" in frame
        else [None] * len(frame)
    )
    annotations = frame[["instance_label", *BOX_COLUMNS]].itertuples(
        index=False, name=None
    )
    values = []
    for shape, annotation in zip(shapes, annotations, strict=True):
        label, *coordinates = annotation
        blank = is_missing(label) and all(is_missing(cell) for cell in coordinates)
        negative = isinstance(shape, str) and shape in ("none", "deleted")
        if profile == "clearml-yolo":
            negative = blank
        if code == "invalid_negative":
            values.append(
                (not is_missing(label) or blank)
                if profile == "clearml-yolo"
                else (not negative or blank)
            )
        elif code == "invalid_label":
            label_ok = _nonempty_text(label) or (
                profile == "clearml-yolo" and number(label) is not None
            )
            values.append(negative or label_ok)
        elif code == "missing_bbox":
            values.append(negative or all(not is_missing(cell) for cell in coordinates))
        elif code == "invalid_box_area":
            numeric = [number(cell) for cell in coordinates]
            if negative or any(value is None for value in numeric):
                values.append(True)
            else:
                values.append(
                    valid_box_geometry(
                        cast("tuple[float, float, float, float]", tuple(numeric)),
                        profile,
                    )
                )
    result: pd.Series[bool] = pd.Series(values, index=frame.index, dtype=bool)
    return result


def schema_for(profile: Profile) -> pa.DataFrameSchema:
    """Return a non-coercing profile schema preserving values and extras."""
    required = required_columns(profile)
    columns = {
        name: pa.Column(required=name in required, nullable=True, coerce=False)
        for name in (*CVETA_COLUMNS, "width", "height", "source_row_id")
    }
    for name in (
        "task_name",
        "task_updated_date",
        "created_by_username",
        "subset",
        "source",
        "issue_text",
        "s3_image_path",
        "image_path",
    ):
        columns[name].checks.append(_check(_text, "invalid_text"))
    columns["image_name"].checks.append(
        _check(_image_name, "invalid_image_name", optional=False)
    )
    columns["instance_label"].checks.append(
        _check(partial(_label, profile), "invalid_label")
    )
    if profile == "clearml-yolo":
        columns["image_path"].checks.append(
            _check(_nonempty_text, "invalid_image_path", optional=False)
        )
    shapes = ("box", "none", "deleted") if profile == "cveta2" else ("box", "none")
    columns["instance_shape"].checks.append(
        _check(
            partial(_enum, shapes), "invalid_shape", optional=profile == "clearml-yolo"
        )
    )
    for name in BOX_COLUMNS:
        columns[name].checks.extend(
            [
                _check(lambda value: number(value) is not None, "invalid_coordinate"),
                _check(
                    lambda value: (
                        number(value) is None or cast("float", number(value)) >= 0
                    ),
                    "negative_coordinate",
                ),
            ]
        )
    for name in ("task_id", "frame_id", "annotation_id"):
        columns[name].checks.append(_check(_nonnegative_integer, "invalid_integer"))
    columns["z_order"].checks.append(_check(integer, "invalid_integer"))
    for name in ("occluded", "task_completed"):
        columns[name].checks.append(_check(_boolean, "invalid_boolean"))
    columns["rotation"].checks.append(
        _check(partial(_range, 0, 360), "invalid_rotation")
    )
    columns["confidence"].checks.append(
        _check(partial(_range, 0, 1), "invalid_confidence")
    )
    columns["attributes"].checks.append(_check(_attributes, "invalid_attributes"))
    for name, allowed in (
        ("job_stage", ("annotation", "validation", "acceptance")),
        ("job_state", ("new", "in progress", "completed", "rejected")),
        (
            "issue_state",
            ("open", "resolved", "open | resolved", "resolved | open", "new"),
        ),
        ("split", ("train", "val", "test")),
    ):
        columns[name].checks.append(
            _check(
                partial(_enum, allowed),
                f"invalid_{name}",
                optional=name != "split" or profile == "cveta2",
            )
        )
    checks = [
        pa.Check(
            partial(_row_masks, profile=profile, code=code), name=code, ignore_na=False
        )
        for code in _ROW_COLUMNS
    ]
    if profile == "clearml-yolo":
        columns = {name: columns[name] for name in CLEARML_COLUMNS}
    return pa.DataFrameSchema(
        columns, checks=checks, strict=False, coerce=False, unique_column_names=True
    )


def schema_issues(frame: pd.DataFrame, profile: Profile) -> list[Issue]:
    """Collect lazy failures with original positional lineage."""
    try:
        schema_for(profile).validate(frame, lazy=True)
    except pa.errors.SchemaErrors as error:
        issues: list[Issue] = []
        seen: set[tuple[str, int | None, tuple[str, ...]]] = set()
        for failure in error.failure_cases.itertuples(index=False):
            check = str(failure.check)
            column = failure.column
            fields: tuple[str, ...]
            if check == "column_in_dataframe":
                code = "missing_column"
                fields = (str(failure.failure_case),)
            elif check == "dataframe_column_labels_unique":
                code = "duplicate_column"
                fields = tuple(
                    str(name)
                    for name in frame.columns[frame.columns.duplicated()].unique()
                )
            else:
                code = check
                fields = _ROW_COLUMNS.get(
                    code, (str(column),) if isinstance(column, str) else ()
                )
                fields = tuple(field for field in fields if field in frame.columns)
            index = failure.index
            position = None if is_missing(index) else int(index)
            key = (code, position, fields)
            if key not in seen:
                seen.add(key)
                reason = _REASONS.get(code, code)
                if code == "invalid_box_area" and profile == "clearml-yolo":
                    reason = (
                        "Box width and height must each exceed 2 px; "
                        "area must exceed 2 square pixels; all must be finite"
                    )
                issues.append(
                    Issue(
                        code=code,
                        message=f"{reason}: {', '.join(fields)}.",
                        row_position=position,
                        columns=fields,
                    )
                )
        return sorted(
            issues,
            key=lambda issue: (
                -1 if issue.row_position is None else issue.row_position,
                issue.code,
                issue.columns,
            ),
        )
    return []
