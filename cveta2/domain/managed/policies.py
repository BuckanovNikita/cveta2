"""Pure stable splitting, reviewed source overlap and dataset comparison."""

import hashlib
import math
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from numbers import Integral, Real
from typing import Literal, TypedDict, cast

import pandas as pd

from cveta2.domain.managed.models import ManagedError, OverlapDecision, SplitPolicy

SplitName = Literal["train", "val", "test"]
RowKey = tuple[tuple[str, str], ...]


class RowComparison(TypedDict):
    """Multiset comparison preserves repeated annotation rows."""

    old: int
    new: int
    added: int
    removed: int
    unchanged: int


class ImageComparison(TypedDict):
    """Image identities added, removed or carrying different records."""

    added: list[str]
    removed: list[str]
    changed: list[str]


class ClassComparison(TypedDict):
    """Changes to represented nonempty class labels."""

    added: list[str]
    removed: list[str]


class SplitComparison(TypedDict):
    """Per-split image counts before and after a change."""

    old: dict[str, int]
    new: dict[str, int]


class FrameComparison(TypedDict):
    """JSON-compatible comparison without serializing source row values."""

    rows: RowComparison
    images: ImageComparison
    classes: ClassComparison
    splits: SplitComparison


def _validate_frame(frame: pd.DataFrame, required: Sequence[str] = ()) -> None:
    """Do not let duplicate headers or missing identity pick an arbitrary owner."""
    if not frame.columns.is_unique or any(not isinstance(column, str) or not column for column in frame.columns):
        raise ManagedError("Managed CSV must have unique, nonempty string columns")
    if missing := set(required) - set(frame.columns):
        raise ManagedError(f"Managed CSV lacks required columns: {sorted(missing)}")


def _text(value: object) -> str | None:
    """Lineage and file identifiers are explicit strings, never inferred values."""
    return value if isinstance(value, str) and value and "\x00" not in value else None


def _content_hashes(frame: pd.DataFrame, image_hashes: Mapping[str, str]) -> list[str]:
    """Resolve supplied image hashes without inspecting the filesystem."""
    _validate_frame(frame, ("image_path",))
    digests = []
    for position, path in enumerate(frame["image_path"]):
        if (key := _text(path)) is None:
            raise ManagedError(f"Invalid image_path at row {position}")
        digest = image_hashes.get(key)
        if _text(digest) is None:
            raise ManagedError(f"Missing image content hash at row {position}: {key}")
        digests.append(cast("str", digest))
    return digests


def _new_split(digest: str, policy: SplitPolicy) -> SplitName:
    """Assign a content identity independently of input row order."""
    value = int.from_bytes(hashlib.sha256(f"{policy.seed}\x00{digest}".encode()).digest()) / (1 << 256)
    if value < policy.train:
        return "train"
    return "val" if value < policy.train + policy.val else "test"


def assign_splits(
    frame: pd.DataFrame,
    policy: SplitPolicy,
    image_hashes: Mapping[str, str],
    previous: Mapping[str, str] | None = None,
) -> tuple[pd.DataFrame, dict[str, SplitName]]:
    """Replace input splits while retaining every published content assignment.

    Removed content keeps its assignment so reintroduction cannot leak it into a
    different split. This policy targets proportions and never silently moves
    existing images to satisfy minimum training/validation requirements.
    """
    assignments: dict[str, SplitName] = {}
    for digest, split in (previous or {}).items():
        if _text(digest) is None or split not in {"train", "val", "test"}:
            raise ManagedError(f"Invalid published image split assignment: {digest!r}")
        assignments[digest] = cast("SplitName", split)
    digests = _content_hashes(frame, image_hashes)
    for digest in sorted(set(digests)):
        assignments.setdefault(digest, _new_split(digest, policy))
    result = frame.copy(deep=True)
    result["split"] = [assignments[digest] for digest in digests]
    return result, dict(sorted(assignments.items()))


def resolve_overlaps(
    frame: pd.DataFrame,
    image_hashes: Mapping[str, str],
    decisions: Mapping[str, OverlapDecision],
) -> pd.DataFrame:
    """Require reviewed content ownership without guessing missing provenance."""
    _validate_frame(frame, ("image_name", "image_path"))
    digests = _content_hashes(frame, image_hashes)
    name_content: dict[str, str] = {}
    grouped: dict[str, list[int]] = defaultdict(list)
    for position, (name, digest) in enumerate(zip(frame["image_name"], digests, strict=True)):
        if (filename := _text(name)) is None:
            raise ManagedError(f"Invalid image filename at row {position}")
        if name_content.setdefault(filename, digest) != digest:
            raise ManagedError(f"Conflicting image filename for different content: {filename}")
        grouped[digest].append(position)
    sources: list[str | None] = (
        [_text(value) for value in frame["source_id"]] if "source_id" in frame else [None] * len(frame)
    )
    retained = [True] * len(frame)
    for digest, positions in grouped.items():
        members = {source for position in positions if (source := sources[position]) is not None}
        decision = decisions.get(digest)
        if decision is None:
            if len(members) > 1:
                raise ManagedError(
                    f"Image overlap requires source selection or exclusion: {digest}; sources={sorted(members)}"
                )
            continue
        _validate_overlap_decision(digest, positions, sources, members, decision)
        for position in positions:
            retained[position] = decision.source is not None and sources[position] == decision.source
    return frame.iloc[[position for position, keep in enumerate(retained) if keep]].copy(deep=True)


def _validate_overlap_decision(
    digest: str,
    positions: list[int],
    sources: list[str | None],
    members: set[str],
    decision: OverlapDecision,
) -> None:
    """Reject stale ownership reviews and unmapped contributors."""
    if set(decision.members) != members or len(set(decision.members)) != len(decision.members):
        raise ManagedError(f"Image overlap membership changed; review decision: {digest}")
    if any(sources[position] is None for position in positions):
        raise ManagedError(f"Image overlap contains unmapped rows: {digest}")
    if decision.source is not None and decision.source not in members:
        raise ManagedError(f"Image overlap selects an unknown source: {digest}")


def _cell_key(value: object) -> tuple[str, str]:
    """Compare lexical/scalar cells without invoking arbitrary object serializers."""
    if value is None or value is pd.NA or value is pd.NaT:
        return ("missing", "")
    if isinstance(value, str):
        return ("str", value)
    if isinstance(value, (bool, Integral)):
        return ("bool", str(value)) if isinstance(value, bool) else ("int", str(int(value)))
    if isinstance(value, Real):
        return ("missing", "") if math.isnan(float(value)) else ("float", str(float(value)))
    if isinstance(value, Decimal):
        return ("missing", "") if value.is_nan() else ("decimal", str(value))
    if isinstance(value, (datetime, date)):
        return (type(value).__name__, value.isoformat())
    raise ManagedError(f"Unsupported comparison cell type: {type(value).__name__}")


def _rows(frame: pd.DataFrame, columns: list[str]) -> list[RowKey]:
    """Canonical column order makes equality independent of CSV header order."""
    return [
        tuple(_cell_key(value) for value in row)
        for row in frame.reindex(columns=columns).itertuples(index=False, name=None)
    ]


def _image_rows(frame: pd.DataFrame, rows: list[RowKey]) -> dict[str, Counter[RowKey]]:
    """Group by explicit output image name, falling back only to output path."""
    column = "image_name" if "image_name" in frame else "image_path"
    grouped: dict[str, Counter[RowKey]] = defaultdict(Counter)
    if column in frame:
        for name, row in zip(frame[column], rows, strict=True):
            if (key := _text(name)) is not None:
                grouped[key][row] += 1
    return dict(grouped)


def _classes(frame: pd.DataFrame) -> set[str]:
    """Count represented class names without introducing a background class."""
    return {name for value in frame.get("instance_label", []) if (name := _text(value)) is not None}


def _split_counts(frame: pd.DataFrame) -> dict[str, int]:
    """Count unique images per split rather than annotation rows."""
    column = "image_name" if "image_name" in frame else "image_path"
    if "split" not in frame or column not in frame:
        return {}
    groups: dict[str, set[str]] = defaultdict(set)
    for raw_split, raw_name in zip(frame["split"], frame[column], strict=True):
        split, name = _text(raw_split), _text(raw_name)
        if split is not None and name is not None:
            groups[split].add(name)
    return {split: len(names) for split, names in sorted(groups.items())}


def compare_frames(old: pd.DataFrame, new: pd.DataFrame) -> FrameComparison:
    """Compare annotation multisets and output image/class/split identities."""
    _validate_frame(old)
    _validate_frame(new)
    columns = sorted(set(old.columns) | set(new.columns))
    old_rows, new_rows = _rows(old, columns), _rows(new, columns)
    before, after = Counter(old_rows), Counter(new_rows)
    old_images, new_images = _image_rows(old, old_rows), _image_rows(new, new_rows)
    return {
        "rows": {
            "old": len(old),
            "new": len(new),
            "added": sum((after - before).values()),
            "removed": sum((before - after).values()),
            "unchanged": sum((before & after).values()),
        },
        "images": {
            "added": sorted(new_images.keys() - old_images.keys()),
            "removed": sorted(old_images.keys() - new_images.keys()),
            "changed": sorted(
                name for name in old_images.keys() & new_images.keys() if old_images[name] != new_images[name]
            ),
        },
        "classes": {
            "added": sorted(_classes(new) - _classes(old)),
            "removed": sorted(_classes(old) - _classes(new)),
        },
        "splits": {"old": _split_counts(old), "new": _split_counts(new)},
    }
