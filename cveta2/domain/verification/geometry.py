"""Bounded duplicate and class-conflict detection for valid annotations."""

from collections.abc import Hashable
from datetime import date, time, timedelta
from decimal import Decimal
from numbers import Number
from typing import cast

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from .models import Issue

BOX_COLUMNS = ("bbox_x_tl", "bbox_y_tl", "bbox_x_br", "bbox_y_br")
_NULL = object()


# Preserve type-sensitive equality across the supported nested scientific values.
def _canonical(value: object) -> Hashable:  # noqa: C901, PLR0911, PLR0912
    """Hash nested extras without converting the caller's lexical cells."""
    if isinstance(value, (str, bytes)):
        return value
    if isinstance(value, bytearray):
        return (bytearray, bytes(value))
    if isinstance(value, memoryview):
        return (memoryview, value.format, value.shape, value.tobytes())
    if isinstance(value, pd.Series):
        return (
            pd.Series,
            _canonical(value.name),
            _canonical(value.index),
            tuple(_canonical(cell) for cell in value),
        )
    if isinstance(value, pd.DataFrame):
        return (
            pd.DataFrame,
            _canonical(value.index),
            _canonical(value.columns),
            tuple(
                tuple(_canonical(cell) for cell in row)
                for row in value.itertuples(index=False, name=None)
            ),
        )
    if isinstance(value, pd.Index):
        return (
            pd.Index,
            tuple(_canonical(name) for name in value.names),
            tuple(_canonical(cell) for cell in value),
        )
    if isinstance(value, np.ndarray):
        return (np.ndarray, value.shape, tuple(_canonical(cell) for cell in value.flat))
    if isinstance(value, (list, tuple)):
        return (type(value), tuple(_canonical(cell) for cell in value))
    if isinstance(value, dict):
        return (
            dict,
            frozenset(
                (_canonical(key), _canonical(cell)) for key, cell in value.items()
            ),
        )
    if isinstance(value, (set, frozenset)):
        return (type(value), frozenset(_canonical(cell) for cell in value))
    if value is None or value is pd.NA or value is pd.NaT:
        return _NULL
    if isinstance(value, (float, np.floating)) and np.isnan(value):
        return _NULL
    if isinstance(value, (np.datetime64, np.timedelta64)) and np.isnat(value):
        return _NULL
    if isinstance(value, (Number, Decimal, date, time, timedelta, np.generic)):
        # Scalar library types have value equality; arbitrary user-defined
        # objects need not have a usable hash or boolean equality operation.
        return cast("Hashable", value)
    raise TypeError(f"No structural equality contract for {type(value).__name__}")


def _ious(box: NDArray[np.float64], others: NDArray[np.float64]) -> NDArray[np.float64]:
    # Scale each pair's axes before multiplying lengths. IoU is invariant
    # under this scaling, even when valid finite pixel areas overflow floats.
    scales = np.maximum(box[2:], others[:, 2:])
    box_min, box_max = box[:2] / scales, box[2:] / scales
    other_min, other_max = others[:, :2] / scales, others[:, 2:] / scales
    intersections = np.maximum(
        0, np.minimum(box_max, other_max) - np.maximum(box_min, other_min)
    )
    intersection_areas = intersections[:, 0] * intersections[:, 1]
    box_lengths = box_max - box_min
    other_lengths = other_max - other_min
    box_areas = box_lengths[:, 0] * box_lengths[:, 1]
    areas = other_lengths[:, 0] * other_lengths[:, 1]
    unions = box_areas + areas - intersection_areas
    overlaps: NDArray[np.float64] = np.divide(
        intersection_areas, unions, out=np.zeros_like(unions), where=unions > 0
    )
    return overlaps


def _overlap(
    box: NDArray[np.float64],
    retained: NDArray[np.float64],
    positions: list[int],
    threshold: float,
) -> tuple[int, float] | None:
    if not positions:
        return None
    overlaps = _ious(box, retained[: len(positions)])
    matches = np.flatnonzero(overlaps >= threshold)
    if not len(matches):
        return None
    match = int(matches[0])
    return positions[match], float(overlaps[match])


def find_class_conflicts(
    frame: pd.DataFrame, groups: list[tuple[int, ...]], *, iou_threshold: float
) -> list[Issue]:
    """Report both endpoints of every overlapping cross-class pair per image.

    ``frame`` uses original row positions as its index and already-valid labels
    and geometry. Every boxed row participates, including later duplicates;
    empty negative rows do not. Working arrays are linear in one image group,
    although reporting every conflicting pair can itself require quadratic space.
    """
    issues: list[Issue] = []
    labels = frame["instance_label"].to_numpy(copy=False)
    columns = [frame[column].to_numpy(copy=False) for column in BOX_COLUMNS]
    for group in groups:
        if len(group) <= 1:
            continue
        positions = sorted(group)
        offsets = frame.index.get_indexer(pd.Index(positions))
        group_boxes = np.empty((len(group), 4), dtype=np.float64)
        boxed_positions: list[int] = []
        boxed_labels: list[object] = []
        for position, raw_offset in zip(positions, offsets, strict=True):
            offset = int(raw_offset)
            raw_box = [column[offset] for column in columns]
            if any(_canonical(value) is _NULL or value == "" for value in raw_box):
                continue
            group_boxes[len(boxed_positions)] = np.asarray(raw_box, dtype=np.float64)
            boxed_positions.append(position)
            boxed_labels.append(labels[offset])
        for first, position in enumerate(boxed_positions):
            overlaps = _ious(
                group_boxes[first], group_boxes[first + 1 : len(boxed_positions)]
            )
            for raw_match in np.flatnonzero(overlaps >= iou_threshold):
                match = int(raw_match)
                second = first + 1 + match
                if boxed_labels[first] == boxed_labels[second]:
                    continue
                other_position = boxed_positions[second]
                iou = float(overlaps[match])
                message = (
                    f"Overlapping boxes have conflicting classes "
                    f"{boxed_labels[first]!r} and {boxed_labels[second]!r}."
                )
                for endpoint, related in (
                    (position, other_position),
                    (other_position, position),
                ):
                    issues.append(
                        Issue(
                            code="class_conflict",
                            message=message,
                            row_position=endpoint,
                            columns=("instance_label", *BOX_COLUMNS),
                            related_rows=(related,),
                            iou=iou,
                        )
                    )
    return issues


# Representatives must pass full equality and then IoU in original input order.
def find_duplicates(  # noqa: C901, PLR0912
    frame: pd.DataFrame, groups: list[tuple[int, ...]], *, iou_threshold: float
) -> list[Issue]:
    """Check each row's full equality before its IoU against kept representatives.

    Only groups with several rows require column access. IoU intermediates are
    linear in one image/task group; no image-by-image or full NxN matrix is built.
    """
    issues: list[Issue] = []
    column_arrays = None
    columns = list(frame.columns)
    box_offsets = [columns.index(column) for column in BOX_COLUMNS]
    shape_offset = (
        columns.index("instance_shape") if "instance_shape" in frame else None
    )
    for group in groups:
        if len(group) <= 1:
            continue
        if column_arrays is None:
            column_arrays = [
                frame[column].to_numpy(copy=False) for column in frame.columns
            ]
        positions = sorted(group)
        offsets = frame.index.get_indexer(pd.Index(positions))
        seen: dict[tuple[Hashable, ...], int] = {}
        retained = np.empty((len(group), 4), dtype=np.float64)
        retained_positions: list[int] = []
        for position, raw_offset in zip(positions, offsets, strict=True):
            offset = int(raw_offset)
            try:
                key: tuple[Hashable, ...] | None = tuple(
                    _canonical(column[offset]) for column in column_arrays
                )
                hash(key)
            except (TypeError, ValueError, RecursionError) as error:
                key = None
                issues.append(
                    Issue(
                        code="exact_comparison_unavailable",
                        severity="warning",
                        row_position=position,
                        message=(
                            f"Exact-row comparison skipped for an opaque "
                            f"or cyclic cell: {error}. "
                            "Original values are preserved; box IoU is still checked."
                        ),
                    )
                )
            representative = seen.get(key) if key is not None else None
            if representative is not None:
                issues.append(
                    Issue(
                        code="duplicate_row",
                        message="Later full-row duplicate.",
                        row_position=position,
                        related_rows=(representative,),
                    )
                )
                continue
            shape = (
                column_arrays[shape_offset][offset]
                if shape_offset is not None
                else None
            )
            if isinstance(shape, str) and shape == "deleted":
                if key is not None:
                    seen[key] = position
                continue
            raw_box = [column_arrays[column][offset] for column in box_offsets]
            # Valid negative/deleted annotations have no box. Their exact-row
            # duplicates were handled above, without synthesizing detections.
            if any(_canonical(value) is _NULL or value == "" for value in raw_box):
                if key is not None:
                    seen[key] = position
                continue
            box = np.asarray(raw_box, dtype=np.float64)
            overlap = _overlap(box, retained, retained_positions, iou_threshold)
            if overlap is None:
                if key is not None:
                    seen[key] = position
                retained[len(retained_positions)] = box
                retained_positions.append(position)
            else:
                representative, iou = overlap
                issues.append(
                    Issue(
                        code="high_iou",
                        message="Later box overlaps a retained annotation.",
                        row_position=position,
                        columns=BOX_COLUMNS,
                        related_rows=(representative,),
                        iou=iou,
                    )
                )
    return issues
