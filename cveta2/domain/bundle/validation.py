"""Training-bundle policy around the offline validator, preserving original evidence."""

from collections import defaultdict
from pathlib import PurePath
from typing import Literal

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

type TrainabilityGap = Literal["train_images", "val_images", "train_box"]
# Default-mode blocker texts, in reporting order.
_TRAINABILITY_BLOCKERS: dict[TrainabilityGap, str] = {
    "train_images": "Required train split has no valid images.",
    "val_images": "Required val split has no valid images.",
    "train_box": "At least one valid training box is required.",
}
# Portable consumer contract, inspected in clearml-yolo dataset_records.py, without
# the extensions Pillow cannot decode (heic, heif, dng): listing those would promise
# support while every such image is quarantined as unreadable.
_MIN_SIDE = 10
_NATIVE_EXTENSIONS = frozenset(
    {
        "avif",
        "bmp",
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
        elif fact.image_format is not None and fact.image_format.lower() not in _NATIVE_EXTENSIONS | {"jpeg2000"}:
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


def _canonicalize_classes(frame: pd.DataFrame, metadata: DatasetMetadata) -> tuple[pd.DataFrame, list[Issue]]:
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
                            message=(f"Canonicalized class {label!r} to {canonical!r}."),
                            severity="warning",
                            row_position=position,
                            columns=("instance_label",),
                        )
                    )
    return working, issues


def _column(frame: pd.DataFrame, name: str) -> list[object]:
    """Read one column positionally; an absent column reads as missing cells."""
    return frame[name].tolist() if name in frame else [None] * len(frame)


def _resolved_labels(frame: pd.DataFrame, metadata: DatasetMetadata) -> list[str | None]:
    """Canonical class per row: ``None`` for a missing, non-text or unknown label."""
    lookup = class_lookup(metadata.classes)
    return [lookup.get(label) if isinstance(label, str) else None for label in _column(frame, "instance_label")]


def missing_active_classes(frame: pd.DataFrame, metadata: DatasetMetadata) -> tuple[str, ...]:
    """Sorted canonical names of non-excluded classes without a bbox row in any split.

    A bbox row has a nonempty text label whose class resolves through
    ``class_lookup`` (aliases count for their class) and a ``box`` or empty
    ``instance_shape``; only an explicit other shape (``none``, ``deleted``)
    does not count, matching ``_kind`` in verification.
    """
    covered = {
        canonical
        for canonical, shape in zip(_resolved_labels(frame, metadata), _column(frame, "instance_shape"), strict=True)
        if canonical is not None and (is_missing(shape) or shape == "box")
    }
    return tuple(sorted(name for name, info in metadata.classes.items() if not info.empty and name not in covered))


def excluded_class_rows(frame: pd.DataFrame, metadata: DatasetMetadata) -> int:
    """Count rows whose label resolves to a class marked ``empty``."""
    return sum(
        canonical is not None and metadata.classes[canonical].empty for canonical in _resolved_labels(frame, metadata)
    )


def images_without_split(frame: pd.DataFrame) -> int:
    """Count distinct named images with a row whose ``split`` is missing (or no ``split`` column)."""
    return len(
        {
            name
            for name, split in zip(_column(frame, "image_name"), _column(frame, "split"), strict=True)
            if not is_missing(name) and is_missing(split)
        }
    )


def trainability_gaps(clean: pd.DataFrame) -> tuple[TrainabilityGap, ...]:
    """Training requirements the rows with a split do not meet, in reporting order."""
    rows = [
        (split, label)
        for split, label in zip(_column(clean, "split"), _column(clean, "instance_label"), strict=True)
        if not is_missing(split)
    ]
    gaps: list[TrainabilityGap] = []
    if not any(split == "train" for split, _label in rows):
        gaps.append("train_images")
    if not any(split == "val" for split, _label in rows):
        gaps.append("val_images")
    if not any(split == "train" and not is_missing(label) for split, label in rows):
        gaps.append("train_box")
    return tuple(gaps)


def _prepare_policy(
    frame: pd.DataFrame, metadata: DatasetMetadata, *, allow_empty_split: bool
) -> tuple[pd.DataFrame, list[Issue], list[str], dict[str, list[int]]]:
    working = frame.copy(deep=True)
    issues: list[Issue] = []
    blockers: list[str] = []
    groups: dict[str, list[int]] = defaultdict(list)
    if frame.columns.is_unique:
        if "image_path" in frame:
            for value in frame["image_path"]:
                if not isinstance(value, str) or not value or "\x00" in value or not PurePath(value).is_absolute():
                    raise UploadError(f"Upload image_path must be an absolute local path: {value!r}")
        if not allow_empty_split and (
            "split" not in frame
            or any(
                not isinstance(value, str) or value not in {"train", "val", "test"} for value in frame.get("split", [])
            )
        ):
            blockers.append("Every input row must have a valid train, val or test split assignment.")
        if "image_name" in frame:
            for position, name in enumerate(frame["image_name"]):
                key = name if isinstance(name, str) and name else f"\x00unidentified:{position}"
                groups[key].append(position)
        working, issues = _canonicalize_classes(frame, metadata)
    return working, issues, blockers, groups


def validate_bundle(
    frame: pd.DataFrame,
    metadata: DatasetMetadata,
    *,
    inspection: MediaInspection | None = None,
    allow_empty_split: bool = False,
) -> BundleValidation:
    """Canonicalize classes and quarantine untrainable image records.

    ``allow_empty_split`` is bundle preparation mode: an empty ``split`` cell
    is accepted (a present value must still be train, val or test), and the
    split and trainability blockers are left to the caller, which reports
    them with ``images_without_split`` and ``trainability_gaps``. Structural
    and "no valid images" blockers apply in both modes. Class coverage is
    never checked here; callers use ``missing_active_classes``.
    """
    inspection = inspection or MediaInspection(rows=())
    working, issues, blockers, groups = _prepare_policy(frame, metadata, allow_empty_split=allow_empty_split)
    core = validate_dataframe(
        working,
        profile="clearml-yolo",
        options=ValidationOptions(check_images=True, emit_warnings=False),
        inspection=inspection,
        allow_empty_split=allow_empty_split,
    )
    issues.extend(_training_media_issues(inspection) if not core.structural_errors else [])
    direct = {issue.row_position for issue in issues if issue.severity == "error" and issue.row_position is not None}
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
    kept_offsets = [offset for offset, position in enumerate(core.clean_row_positions) if position not in rejected]
    clean = core.clean.iloc[kept_offsets].copy(deep=True)
    clean_positions = tuple(position for position in core.clean_row_positions if position not in rejected)
    broken_positions = tuple(sorted(rejected))
    broken_image_positions = sorted(
        {position for positions in groups.values() if rejected.intersection(positions) for position in positions}
        | rejected
    )
    if core.structural_errors:
        blockers.append("Input CSV has structural validation errors.")
    if clean.empty:
        blockers.append("No valid images remain for upload.")
    elif not allow_empty_split:
        blockers.extend(_TRAINABILITY_BLOCKERS[gap] for gap in trainability_gaps(clean))
    result = ValidationResult(
        profile=core.profile,
        clean=clean,
        broken=frame.iloc[list(broken_positions)].copy(deep=True),
        clean_row_positions=clean_positions,
        broken_row_positions=broken_positions,
        issues=tuple(
            sorted(
                (*core.issues, *issues),
                key=lambda issue: -1 if issue.row_position is None else issue.row_position,
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
