"""Validation, image quarantine and deterministic cleanup orchestration."""

from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, cast

import pandas as pd

from cveta2.domain.verification.cells import is_missing, number
from cveta2.domain.verification.geometry import find_class_conflicts, find_duplicates
from cveta2.domain.verification.models import (
    DatasetInputError,
    Issue,
    MediaInspection,
    Profile,
    ValidationOptions,
    ValidationResult,
)
from cveta2.domain.verification.schema import (
    BOX_COLUMNS,
    CLEARML_COLUMNS,
    KNOWN_COLUMNS,
    required_columns,
    schema_issues,
    valid_box_geometry,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

_CLIP_LIMIT = 10


def _group_rows(frame: pd.DataFrame) -> tuple[list[tuple[int, ...]], list[Issue]]:
    groups: dict[tuple[str, int | None], list[int]] = defaultdict(list)
    scope_states: dict[str, set[bool]] = defaultdict(set)
    tasks: Sequence[object] = (
        frame["task_id"].tolist() if "task_id" in frame else [None] * len(frame)
    )
    for position, (name, task) in enumerate(
        zip(frame["image_name"], tasks, strict=True)
    ):
        # Unidentifiable rows cannot be joined to a known image by guesswork.
        key = name if isinstance(name, str) and name else f"\x00unidentified:{position}"
        task_id = None
        if not is_missing(task) and number(task) is not None:
            try:
                parsed = Decimal(str(task))
                if (
                    parsed.is_finite()
                    and parsed >= 0
                    and parsed == parsed.to_integral_value()
                ):
                    task_id = int(parsed)
            except InvalidOperation:
                # The schema reports malformed IDs; keep unscoped evidence separate.
                pass
        groups[key, task_id].append(position)
        scope_states[key].add(task_id is not None)
    mixed = sum(len(states) > 1 for states in scope_states.values())
    issues = []
    if mixed:
        issues.append(
            Issue(
                code="unscoped_task",
                severity="warning",
                columns=("task_id",),
                message=(
                    f"{mixed} image(s) mix task IDs and missing "
                    f"IDs; unscoped rows stay separate."
                ),
            )
        )
    return [tuple(rows) for rows in groups.values()], issues


def _kind(label: object, shape: object) -> str:
    if shape == "deleted":
        return "deleted"
    return "none" if is_missing(label) else "box"


# Keep the independent ownership checks together to report every conflicting endpoint.
def _identity_issues(  # noqa: C901
    frame: pd.DataFrame,
    groups: list[tuple[int, ...]],
    profile: Profile,
    inspection: MediaInspection,
) -> list[Issue]:
    issues: list[Issue] = []
    # Values used in consistency checks have already passed individual schema checks.
    positions_to_group = {
        position: index for index, rows in enumerate(groups) for position in rows
    }
    columns = ("image_name", "image_path", "split", "instance_label", "instance_shape")
    name_paths: dict[object, tuple[str, int]] = {}
    name_splits: dict[object, tuple[object, int]] = {}
    paths: dict[str, tuple[str, int]] = {}
    kinds: dict[int, tuple[str, int]] = {}

    def conflict(
        code: str, positions: tuple[int, int], column: str, message: str
    ) -> None:
        for position, other in (positions, positions[::-1]):
            issues.append(
                Issue(
                    code=code,
                    message=message,
                    row_position=position,
                    columns=(column,),
                    related_rows=(other,),
                )
            )

    facts = {fact.row_position: fact for fact in inspection.rows}
    for raw in frame.reindex(columns=columns).itertuples(index=True, name=None):
        position, name, _image_path, split, label, shape = raw
        pos = int(position)
        image_name = cast("str", name)
        group = positions_to_group[pos]
        kind = _kind(label, None if is_missing(shape) else shape)
        previous_kind = kinds.setdefault(group, (kind, pos))
        if previous_kind[0] != kind:
            conflict(
                "mixed_image_kinds",
                (previous_kind[1], pos),
                "instance_label",
                "The image/task mixes annotations, empty-image or deleted records.",
            )
        fact = facts.get(pos)
        resolved = fact.canonical_path if fact is not None else None
        if fact is not None:
            issues.extend(
                issue for issue in fact.issues if not issue.code.startswith("media_")
            )
        # cveta2 historical tasks may carry different assignments; training
        # ownership is global.
        owner_key: object = image_name if profile == "clearml-yolo" else group
        if resolved is not None:
            name_path = name_paths.setdefault(owner_key, (resolved, pos))
            if name_path[0] != resolved:
                conflict(
                    "path_conflict",
                    (name_path[1], pos),
                    "image_path",
                    "One image has conflicting local paths.",
                )
        if not is_missing(split):
            name_split = name_splits.setdefault(owner_key, (split, pos))
            if name_split[0] != split:
                conflict(
                    "split_conflict",
                    (name_split[1], pos),
                    "split",
                    "One image belongs to multiple splits.",
                )
        if resolved is not None:
            path_owner = paths.setdefault(resolved, (image_name, pos))
            if path_owner[0] != image_name:
                conflict(
                    "path_conflict",
                    (path_owner[1], pos),
                    "image_path",
                    "One canonical image path belongs to multiple image names.",
                )
    return issues


def _dimension_issues(
    frame: pd.DataFrame,
    groups: list[tuple[int, ...]],
    sizes: dict[int, tuple[int, int]],
) -> list[Issue]:
    """Constrain bounds with every supplied dimension, even unpaired axes."""
    issues: list[Issue] = []
    for group in groups:
        for axis, columns in enumerate(
            (("image_width", "width"), ("image_height", "height"))
        ):
            owner: tuple[float, int] | None = None
            for position in group:
                values = [
                    parsed
                    for column in columns
                    if column in frame
                    and (parsed := number(frame.loc[position, column])) is not None
                ]
                if not values:
                    continue
                if len(set(values)) > 1:
                    issues.append(
                        Issue(
                            code="dimension_conflict",
                            row_position=position,
                            columns=columns,
                            message=(
                                "Alternative declarations of the same "
                                "image dimension disagree."
                            ),
                        )
                    )
                if owner is None:
                    owner = (values[0], position)
                elif owner[0] != values[0]:
                    for current, other in ((position, owner[1]), (owner[1], position)):
                        issues.append(
                            Issue(
                                code="dimension_conflict",
                                row_position=current,
                                columns=columns,
                                related_rows=(other,),
                                message=(
                                    "Rows for the image declare different dimensions."
                                ),
                            )
                        )
                measured = sizes.get(position)
                if measured is not None and any(
                    value != measured[axis] for value in values
                ):
                    issues.append(
                        Issue(
                            code="image_dimension_mismatch",
                            row_position=position,
                            columns=columns,
                            message=(
                                f"Declared image dimension disagrees with "
                                f"measured size {measured}."
                            ),
                        )
                    )
    return issues


# One pass reconciles both declared axes and measured bounds without coercing cells.
def _bounds_issues(  # noqa: C901, PLR0912
    frame: pd.DataFrame,
    groups: list[tuple[int, ...]],
    sizes: dict[int, tuple[int, int]],
    profile: Profile,
) -> tuple[list[Issue], bool, bool, dict[int, tuple[float, float]]]:
    issues = (
        _dimension_issues(frame, groups, sizes) if profile == "clearml-yolo" else []
    )
    effective_sizes: dict[int, tuple[float, float]] = {}
    positions_to_group = {
        position: index for index, rows in enumerate(groups) for position in rows
    }
    owners: dict[int, tuple[tuple[float, float], int]] = {}
    columns = (
        *BOX_COLUMNS,
        "instance_label",
        "instance_shape",
        "image_width",
        "image_height",
        "width",
        "height",
        "rotation",
    )
    checked = False
    unchecked = 0
    rotated = 0
    for values in frame.reindex(columns=columns).itertuples(index=True, name=None):
        position, x1, y1, x2, y2, label, shape, iw, ih, width, height, rotation = values
        pos = int(position)
        if not is_missing(shape) and shape == "deleted":
            continue
        dimensions: list[tuple[float, float]] = []
        for w, h in ((iw, ih), (width, height)):
            parsed_w, parsed_h = number(w), number(h)
            if parsed_w is not None and parsed_h is not None:
                dimensions.append((parsed_w, parsed_h))
        if profile == "cveta2" and len(set(dimensions)) > 1:
            issues.append(
                Issue(
                    code="dimension_conflict",
                    row_position=pos,
                    message="The supplied dimension column pairs disagree.",
                )
            )
        declared = dimensions[0] if dimensions else None
        if profile == "cveta2" and declared is not None:
            owner = owners.setdefault(positions_to_group[pos], (declared, pos))
            if owner[0] != declared:
                for current, other in ((pos, owner[1]), (owner[1], pos)):
                    issues.append(
                        Issue(
                            code="dimension_conflict",
                            row_position=current,
                            related_rows=(other,),
                            message="Image/task dimensions disagree.",
                        )
                    )
        measured = sizes.get(pos)
        if (
            profile == "cveta2"
            and measured is not None
            and any(d != measured for d in dimensions)
        ):
            issues.append(
                Issue(
                    code="image_dimension_mismatch",
                    row_position=pos,
                    message=(
                        f"Declared image dimensions disagree with "
                        f"measured size {measured}."
                    ),
                )
            )
        effective = measured if measured is not None else declared
        if is_missing(label):
            continue
        if number(rotation) not in (None, 0):
            rotated += 1
        if effective is None:
            unchecked += 1
            continue
        effective_sizes[pos] = effective
        checked = True
        coords = (number(x1), number(y1), number(x2), number(y2))
        if all(value is not None for value in coords):
            left, top, right, bottom = cast("tuple[float, float, float, float]", coords)
            if left < 0 or top < 0 or right > effective[0] or bottom > effective[1]:
                issues.append(
                    Issue(
                        code="out_of_bounds",
                        row_position=pos,
                        columns=tuple(BOX_COLUMNS),
                        message=(
                            f"Box extends outside image bounds 0..{effective[0]:g} "
                            f"x "
                            f"0..{effective[1]:g}; image/task is rejected."
                        ),
                    )
                )
    if unchecked:
        issues.append(
            Issue(
                code="bounds_unchecked",
                severity="warning",
                message=f"Upper image bounds unavailable for {unchecked} box(es); "
                "supply dimensions or enable image inspection.",
            )
        )
    if rotated:
        issues.append(
            Issue(
                code="rotation_ignored",
                severity="warning",
                columns=("rotation",),
                message=(
                    f"IoU uses stored axis-aligned coordinates "
                    f"for {rotated} rotated box(es)."
                ),
            )
        )
    return issues, checked, bool(unchecked), effective_sizes


def _repair_bounds(
    frame: pd.DataFrame,
    groups: list[tuple[int, ...]],
    issues: list[Issue],
    sizes: dict[int, tuple[float, float]],
) -> dict[int, Issue]:
    """Apply eligible repairs to a private positional frame."""
    blocked, _ = _quarantine(
        groups,
        [
            issue
            for issue in issues
            if issue.code not in {"negative_coordinate", "out_of_bounds"}
        ],
    )
    candidates = {
        issue.row_position
        for issue in issues
        if issue.code == "out_of_bounds" and issue.row_position is not None
    }
    repairs: dict[int, Issue] = {}
    converted_columns: set[str] = set()
    for position in sorted(candidates - blocked):
        width, height = sizes[position]
        original = tuple(frame.loc[position, column] for column in BOX_COLUMNS)
        # Candidates have already passed finite-coordinate and positive-geometry checks.
        left, top, right, bottom = cast(
            "tuple[float, float, float, float]", tuple(map(number, original))
        )
        overflow = (
            max(0, -left),
            max(0, -top),
            max(0, right - width),
            max(0, bottom - height),
        )
        if max(overflow) >= _CLIP_LIMIT:
            continue
        clipped = (
            min(width, max(0, left)),
            min(height, max(0, top)),
            min(width, max(0, right)),
            min(height, max(0, bottom)),
        )
        if not valid_box_geometry(clipped, "clearml-yolo"):
            continue
        changed = []
        for column, old, numeric, new in zip(
            BOX_COLUMNS, original, (left, top, right, bottom), clipped, strict=True
        ):
            if numeric == new:
                continue
            # Object storage avoids coercing untouched cells when changing one
            # coordinate.
            if column not in converted_columns:
                if not isinstance(frame[column].dtype, pd.StringDtype):
                    frame[column] = frame[column].astype(object)
                converted_columns.add(column)
            boundary = int(new)
            frame.loc[position, column] = (
                str(boundary) if isinstance(old, str) else boundary
            )
            changed.append(column)
        final_coordinates = tuple(frame.loc[position, column] for column in BOX_COLUMNS)
        repairs[position] = Issue(
            code="bbox_clipped",
            severity="warning",
            row_position=position,
            columns=tuple(changed),
            message=(
                f"Clipped image-boundary overflow below "
                f"10 px per edge; before {original!r}; "
                f"after {final_coordinates!r}."
            ),
        )
    return repairs


def _class_groups(
    frame: pd.DataFrame, groups: list[tuple[int, ...]]
) -> list[tuple[int, ...]]:
    """Partition images by their accepted label values, without class remapping."""
    result: list[tuple[int, ...]] = []
    for group in groups:
        classes: dict[object, list[int]] = defaultdict(list)
        for position in group:
            label = frame.loc[position, "instance_label"]
            classes[None if is_missing(label) else label].append(position)
        result.extend(tuple(rows) for rows in classes.values())
    return result


def _quarantine(
    groups: list[tuple[int, ...]], issues: list[Issue]
) -> tuple[set[int], list[Issue]]:
    directly_broken = {
        i.row_position
        for i in issues
        if i.severity == "error" and i.row_position is not None
    }
    rejected: set[int] = set()
    additions: list[Issue] = []
    for group in groups:
        triggers = tuple(position for position in group if position in directly_broken)
        if not triggers:
            continue
        rejected.update(group)
        additions.extend(
            Issue(
                code="image_quarantined",
                row_position=position,
                related_rows=triggers,
                message="Another malformed record quarantined this entire image/task.",
            )
            for position in group
            if position not in directly_broken
        )
    return rejected, additions


# Finalize all provenance and policy outputs together without rereading the input.
def _finish(  # noqa: PLR0913, PLR0917
    frame: pd.DataFrame,
    profile: Profile,
    issues: list[Issue],
    rejected: set[int],
    checked: list[str],
    skipped: list[str],
    *,
    structural: bool = False,
    repaired_frame: pd.DataFrame | None = None,
    repairs: dict[int, Issue] | None = None,
) -> ValidationResult:
    clean_positions = tuple(
        position for position in range(len(frame)) if position not in rejected
    )
    broken_positions = tuple(sorted(rejected))
    clean = frame.iloc[list(clean_positions)].copy(deep=True)
    broken = frame.iloc[list(broken_positions)].copy(deep=True)
    if repaired_frame is not None and repairs:
        output_positions = {
            position: offset for offset, position in enumerate(clean_positions)
        }
        converted_columns: set[str] = set()
        for position, repair in repairs.items():
            if position not in output_positions:
                continue
            for column in repair.columns:
                if column not in converted_columns:
                    if not isinstance(clean[column].dtype, pd.StringDtype):
                        clean[column] = clean[column].astype(object)
                    converted_columns.add(column)
                clean.iloc[
                    output_positions[position],
                    cast("int", clean.columns.get_loc(column)),
                ] = repaired_frame.loc[position, column]
            issues.append(repair)
    issues.sort(key=lambda i: -1 if i.row_position is None else i.row_position)
    names = (
        frame["image_name"]
        if "image_name" in frame and frame.columns.is_unique
        else pd.Series(dtype=str)
    )
    clean_names = (
        clean["image_name"]
        if "image_name" in clean and clean.columns.is_unique
        else pd.Series(dtype=str)
    )
    return ValidationResult(
        profile=profile,
        clean=clean,
        broken=broken,
        clean_row_positions=clean_positions,
        broken_row_positions=broken_positions,
        issues=tuple(issues),
        input_row_count=len(frame),
        checked_checks=tuple(checked),
        skipped_checks=tuple(skipped),
        structural_errors=structural,
        input_image_count=len({v for v in names if isinstance(v, str) and v}),
        clean_image_count=len({v for v in clean_names if isinstance(v, str) and v}),
    )


# Ordering is policy: schema, identity, bounds, quarantine, then retained duplicates.
def validate_dataframe(  # noqa: C901, PLR0912, PLR0915
    frame: pd.DataFrame,
    *,
    profile: Profile = "cveta2",
    options: ValidationOptions | None = None,
    inspection: MediaInspection | None = None,
) -> ValidationResult:
    """Validate rows and propose repairs while preserving original broken records.

    Ordinary data errors never raise. Invalid configuration and missing optional
    dependencies remain explicit caller errors. Indices may be duplicated.
    """
    if profile not in ("cveta2", "clearml-yolo"):
        raise DatasetInputError(f"Unknown validation profile: {profile!r}")
    selected = options or ValidationOptions()
    working = frame.reset_index(drop=True).copy(deep=True)
    checked = ["schema"]
    skipped: list[str] = []
    if not frame.columns.is_unique or any(
        not isinstance(c, str) or not c for c in frame.columns
    ):
        issues = [
            Issue(
                code="invalid_header",
                message="Column names must be unique nonempty strings.",
            )
        ]
        return _finish(
            frame,
            profile,
            issues,
            set(range(len(frame))),
            checked,
            skipped,
            structural=True,
        )
    if profile == "clearml-yolo":
        working = working.loc[
            :, [column for column in CLEARML_COLUMNS if column in working]
        ]
    field_issues = schema_issues(working, profile)
    issues = field_issues.copy()
    extras = sorted(set(frame.columns) - set(KNOWN_COLUMNS))
    if extras and profile == "cveta2":
        issues.append(
            Issue(
                code="unknown_columns",
                severity="warning",
                columns=tuple(extras),
                message=(
                    f"Unknown columns are preserved without "
                    f"field validation: {', '.join(extras)}."
                ),
            )
        )
    if any(
        issue.severity == "error" and issue.row_position is None for issue in issues
    ):
        return _finish(
            frame,
            profile,
            issues,
            set(range(len(frame))),
            checked,
            skipped,
            structural=True,
        )
    if frame.empty:
        issues.append(
            Issue(
                code="empty_dataset",
                severity="warning",
                message="The dataset is empty.",
            )
        )
        return _finish(frame, profile, issues, set(), checked, skipped)
    groups, grouping_issues = _group_rows(working)
    issues.extend(grouping_issues)
    initially_rejected, _ = _quarantine(
        groups,
        [
            issue
            for issue in issues
            if profile != "clearml-yolo" or issue.code != "negative_coordinate"
        ],
    )
    eligible_groups = [group for group in groups if group[0] not in initially_rejected]
    eligible = working.drop(index=list(initially_rejected))
    issues.extend(
        _identity_issues(
            eligible, eligible_groups, profile, inspection or MediaInspection()
        )
    )
    checked.append("image_identity")
    sizes: dict[int, tuple[int, int]] = {}
    if selected.check_images:
        facts = {
            fact.row_position: fact for fact in (inspection or MediaInspection()).rows
        }
        for position in eligible.index:
            fact = facts.get(int(position))
            if fact is None:
                issues.append(
                    Issue(
                        code="media_uninspected",
                        message="Requested media inspection is unavailable.",
                        row_position=int(position),
                    )
                )
            else:
                if fact.size is not None:
                    sizes[int(position)] = fact.size
                issues.extend(
                    issue for issue in fact.issues if issue.code.startswith("media_")
                )
        checked.append("image_files")
    else:
        skipped.append("image_files")
    bounds, did_check, did_skip, effective_sizes = _bounds_issues(
        eligible, eligible_groups, sizes, profile
    )
    issues.extend(bounds)
    if did_check:
        checked.append("upper_image_bounds")
    if did_skip:
        skipped.append("upper_image_bounds")
    repairs: dict[int, Issue] = {}
    if profile == "clearml-yolo":
        repairs = _repair_bounds(working, groups, issues, effective_sizes)
        if repairs:
            # Revalidate the final coordinates, replacing deferred negative-
            # coordinate failures.
            issues = schema_issues(working, profile) + [
                issue
                for issue in issues[len(field_issues) :]
                if not (issue.code == "out_of_bounds" and issue.row_position in repairs)
            ]
        rejected, _ = _quarantine(groups, issues)
        conflict_groups = [group for group in groups if group[0] not in rejected]
        issues.extend(
            find_class_conflicts(
                working.drop(index=list(rejected)),
                conflict_groups,
                iou_threshold=selected.iou_threshold,
            )
        )
        checked.append("class_conflicts")
    rejected, quarantine_issues = _quarantine(groups, issues)
    issues.extend(quarantine_issues)
    retained_groups = [group for group in groups if group[0] not in rejected]
    duplicate_frame = working.drop(index=list(rejected))
    if profile == "clearml-yolo":
        retained_groups = _class_groups(duplicate_frame, retained_groups)
        duplicate_frame = duplicate_frame.loc[:, list(required_columns(profile))]
    duplicate_issues = find_duplicates(
        duplicate_frame, retained_groups, iou_threshold=selected.iou_threshold
    )
    issues.extend(duplicate_issues)
    rejected.update(
        issue.row_position
        for issue in duplicate_issues
        if issue.row_position is not None and issue.severity == "error"
    )
    if any(issue.code == "exact_comparison_unavailable" for issue in duplicate_issues):
        skipped.append("full_row_duplicates")
    checked.extend(("full_row_duplicates", "high_iou"))
    return _finish(
        frame,
        profile,
        issues,
        rejected,
        checked,
        skipped,
        repaired_frame=working,
        repairs=repairs,
    )
