"""Pure published-split propagation, reviewed source overlap and dataset comparison."""

import math
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from numbers import Integral, Real
from typing import Literal, TypedDict, cast

import pandas as pd

from cveta2.domain.managed.models import ManagedError, OverlapDecision

type SplitName = Literal["train", "val", "test"]
type RowKey = tuple[tuple[str, str], ...]


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


def _published_split(digest: str, split: str) -> SplitName:
    """Accept only a published train, val or test assignment of a content identity."""
    if _text(digest) is None or split not in {"train", "val", "test"}:
        raise ManagedError(f"Invalid published image split assignment: {digest!r}")
    return cast("SplitName", split)


def propagate_splits(
    frame: pd.DataFrame,
    image_hashes: Mapping[str, str],
    published: Mapping[str, str],
) -> tuple[pd.DataFrame, int]:
    """Write each published split over the rows of the same image content.

    Rows of unpublished content keep their own split, even an empty one, and
    rows without a content hash are left unchanged. Returns the copy and the
    number of rows whose split changed.
    """
    _validate_frame(frame, ("image_path",))
    splits = {digest: _published_split(digest, split) for digest, split in published.items()}
    result = frame.copy(deep=True)
    if "split" not in result:
        result["split"] = ""
    values = result["split"].tolist()
    replaced = 0
    for position, path in enumerate(result["image_path"]):
        digest = image_hashes.get(key) if (key := _text(path)) is not None else None
        if digest is not None and (split := splits.get(digest)) is not None and values[position] != split:
            values[position] = split
            replaced += 1
    result["split"] = values
    return result, replaced


def rebuild_assignments(
    frame: pd.DataFrame,
    image_hashes: Mapping[str, str],
    base: Mapping[str, str],
) -> dict[str, SplitName]:
    """Overlay the splits of hashed rows on earlier assignments, keeping removed images."""
    assignments = cast("dict[str, SplitName]", dict(base))
    for row in frame.to_dict(orient="records"):
        split = row.get("split")
        if not isinstance(split, str) or not split:
            continue
        if split not in {"train", "val", "test"}:
            name = _text(row.get("image_name")) or row.get("image_path")
            raise ManagedError(f"Invalid split for image: {name}")
        path = _text(row.get("image_path"))
        if path is not None and (digest := image_hashes.get(path)) is not None:
            assignments[digest] = cast("SplitName", split)
    return dict(sorted(assignments.items()))


@dataclass(frozen=True)
class ParentSplits:
    """Published splits of a parent without managed evidence, by content identity."""

    assignments: dict[str, SplitName] = field(default_factory=dict)
    conflicts: int = 0
    unresolved: int = 0


def parent_splits(frame: pd.DataFrame, image_hashes: Mapping[str, str]) -> ParentSplits:
    """Carry a legacy parent's split only for content published under one split.

    Identity is the SHA-256 of an image readable now. Paths without a hash are
    unresolved; content published under several or invalid splits is a conflict.
    """
    _validate_frame(frame, ("image_path", "split"))
    published: dict[str, set[object]] = defaultdict(set)
    unresolved: set[object] = set()
    for path, split in zip(frame["image_path"], frame["split"], strict=True):
        key = _text(path)
        digest = image_hashes.get(key) if key is not None else None
        if _text(digest) is None:
            unresolved.add(str(path))
            continue
        published[cast("str", digest)].add(split)
    assignments: dict[str, SplitName] = {}
    for digest, splits in sorted(published.items()):
        if len(splits) == 1 and (split := next(iter(splits))) in {"train", "val", "test"}:
            assignments[digest] = split
    return ParentSplits(assignments, len(published) - len(assignments), len(unresolved))


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
