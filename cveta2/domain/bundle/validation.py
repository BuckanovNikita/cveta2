"""Training-bundle policy around the offline validator, preserving original evidence."""

from collections import defaultdict
from pathlib import PurePath

import pandas as pd

from cveta2.domain.bundle.classes import class_lookup
from cveta2.domain.bundle.models import BundleValidation, DatasetMetadata, UploadError
from cveta2.domain.verification.cells import is_missing
from cveta2.domain.verification.models import (
    Issue,
    MediaInspection,
    ValidationOptions,
    ValidationResult,
)
from cveta2.domain.verification.validation import validate_dataframe

# Portable consumer contract, inspected in clearml-yolo dataset_records.py.
_MIN_SIDE = 10
_NATIVE_EXTENSIONS = frozenset(
    {
        "avif",
        "bmp",
        "dng",
        "heic",
        "heif",
        "jp2",
        "jpeg",
        "jpg",
        "mpo",
        "png",
        "tif",
        "tiff",
        "webp",
    }
)


def _training_media_issues(inspection: MediaInspection) -> list[Issue]:
    """Apply consumer format and minimum-size policy to decoded media facts."""
    issues: list[Issue] = []
    for fact in inspection.rows:
        if fact.canonical_path is None:
            continue
        path = PurePath(fact.canonical_path)
        failure: tuple[str, str] | None = None
        if path.suffix.removeprefix(".").lower() not in _NATIVE_EXTENSIONS:
            failure = (
                "training_image_format",
                f"Unsupported native training image extension: {path.suffix}",
            )
        elif (
            fact.image_format is not None
            and fact.image_format.lower() not in _NATIVE_EXTENSIONS | {"jpeg2000"}
        ):
            failure = (
                "training_image_format",
                f"Unsupported decoded image format: {fact.image_format}",
            )
        elif fact.size is not None and min(fact.size) < _MIN_SIDE:
            failure = (
                "training_image_size",
                f"Training image sides must be at least 10 pixels: {fact.size}",
            )
        if failure is not None:
            issues.append(
                Issue(
                    code=failure[0],
                    message=failure[1],
                    row_position=fact.row_position,
                    columns=("image_path",),
                )
            )
    return issues


def _canonicalize_classes(
    frame: pd.DataFrame, metadata: DatasetMetadata
) -> tuple[pd.DataFrame, list[Issue]]:
    lookup = class_lookup(metadata.classes)
    working = frame.copy(deep=True)
    issues: list[Issue] = []
    if "instance_label" in frame:
        working["instance_label"] = working["instance_label"].astype(object)
        label_column = list(working.columns).index("instance_label")
        for position, label in enumerate(frame["instance_label"]):
            if is_missing(label):
                # Core checks all coordinates are empty for negatives.
                continue
            canonical = lookup.get(label) if isinstance(label, str) else None
            if canonical is None:
                issues.append(
                    Issue(
                        code="unknown_class",
                        message=f"Unknown class: {label!r}",
                        row_position=position,
                        columns=("instance_label",),
                    )
                )
            elif metadata.classes[canonical].empty:
                issues.append(
                    Issue(
                        code="empty_class",
                        message=f"Class is marked empty: {canonical!r}",
                        row_position=position,
                        columns=("instance_label",),
                    )
                )
            else:
                working.iloc[position, label_column] = canonical
                if label != canonical:
                    issues.append(
                        Issue(
                            code="class_canonicalized",
                            message=(
                                f"Canonicalized class {label!r} to {canonical!r}."
                            ),
                            severity="warning",
                            row_position=position,
                            columns=("instance_label",),
                        )
                    )
    return working, issues


def _prepare_policy(
    frame: pd.DataFrame, metadata: DatasetMetadata
) -> tuple[pd.DataFrame, list[Issue], list[str], dict[str, list[int]]]:
    working = frame.copy(deep=True)
    issues: list[Issue] = []
    blockers: list[str] = []
    groups: dict[str, list[int]] = defaultdict(list)
    if frame.columns.is_unique:
        if "image_path" in frame:
            for value in frame["image_path"]:
                if (
                    not isinstance(value, str)
                    or not value
                    or "\x00" in value
                    or not PurePath(value).is_absolute()
                ):
                    raise UploadError(
                        f"Upload image_path must be an absolute local path: {value!r}"
                    )
        if "split" not in frame or any(
            not isinstance(value, str) or value not in {"train", "val", "test"}
            for value in frame.get("split", [])
        ):
            blockers.append(
                "Every input row must have a valid train, val or test split assignment."
            )
        if "image_name" in frame:
            for position, name in enumerate(frame["image_name"]):
                key = (
                    name
                    if isinstance(name, str) and name
                    else f"\x00unidentified:{position}"
                )
                groups[key].append(position)
        working, issues = _canonicalize_classes(frame, metadata)
    return working, issues, blockers, groups


def validate_bundle(
    frame: pd.DataFrame,
    metadata: DatasetMetadata,
    *,
    inspection: MediaInspection | None = None,
) -> BundleValidation:
    """Canonicalize classes and quarantine untrainable image records."""
    inspection = inspection or MediaInspection(rows=())
    working, issues, blockers, groups = _prepare_policy(frame, metadata)
    core = validate_dataframe(
        working,
        profile="clearml-yolo",
        options=ValidationOptions(check_images=True, emit_warnings=False),
        inspection=inspection,
    )
    issues.extend(
        _training_media_issues(inspection) if not core.structural_errors else []
    )
    direct = {
        issue.row_position
        for issue in issues
        if issue.severity == "error" and issue.row_position is not None
    }
    quarantined: set[int] = set()
    for positions in groups.values():
        triggers = tuple(position for position in positions if position in direct)
        if triggers:
            quarantined.update(positions)
            issues.extend(
                Issue(
                    code="image_quarantined",
                    message="Another rejected record quarantined this image.",
                    row_position=position,
                    related_rows=triggers,
                )
                for position in positions
                if position not in direct
            )
    rejected = set(core.broken_row_positions) | quarantined
    kept_offsets = [
        offset
        for offset, position in enumerate(core.clean_row_positions)
        if position not in rejected
    ]
    clean = core.clean.iloc[kept_offsets].copy(deep=True)
    clean_positions = tuple(
        position for position in core.clean_row_positions if position not in rejected
    )
    broken_positions = tuple(sorted(rejected))
    broken_image_positions = sorted(
        {
            position
            for positions in groups.values()
            if rejected.intersection(positions)
            for position in positions
        }
        | rejected
    )
    if core.structural_errors:
        blockers.append("Input CSV has structural validation errors.")
    if clean.empty:
        blockers.append("No valid images remain for upload.")
    else:
        blockers.extend(
            f"Required {split} split has no valid images."
            for split in ("train", "val")
            if not clean["split"].eq(split).any()
        )
        if not any(
            not is_missing(label)
            for label in clean.loc[clean["split"].eq("train"), "instance_label"]
        ):
            blockers.append("At least one valid training box is required.")
    result = ValidationResult(
        profile=core.profile,
        clean=clean,
        broken=frame.iloc[list(broken_positions)].copy(deep=True),
        clean_row_positions=clean_positions,
        broken_row_positions=broken_positions,
        issues=tuple(
            sorted(
                (*core.issues, *issues),
                key=lambda issue: (
                    -1 if issue.row_position is None else issue.row_position
                ),
            )
        ),
        input_row_count=len(frame),
        checked_checks=(
            *core.checked_checks,
            "class_policy",
            "training_images",
            "trainability",
        ),
        skipped_checks=core.skipped_checks,
        structural_errors=core.structural_errors,
        input_image_count=core.input_image_count,
        clean_image_count=len(set(clean["image_name"])) if "image_name" in clean else 0,
    )
    return BundleValidation(
        result=result,
        broken_images=frame.iloc[broken_image_positions].copy(deep=True),
        blockers=tuple(blockers),
    )
