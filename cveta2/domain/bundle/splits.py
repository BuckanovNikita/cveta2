"""Split carry-over from a published parent's ``dataset.csv``, keyed by ``image_name``."""

from collections.abc import Mapping
from typing import cast

import pandas as pd

from cveta2.domain.models import Split
from cveta2.domain.verification.cells import is_missing

_SPLITS = frozenset({"train", "val", "test"})


def _pairs(frame: pd.DataFrame) -> list[tuple[object, object]]:
    """Positional ``(image_name, split)`` pairs; an absent ``split`` column reads as missing."""
    if "image_name" not in frame:
        return []
    splits = frame["split"].tolist() if "split" in frame else [None] * len(frame)
    return list(zip(frame["image_name"].tolist(), splits, strict=True))


def published_splits(frame: pd.DataFrame) -> dict[str, Split]:
    """Map each named image to its valid split; a name held with two splits is left out."""
    seen: dict[str, set[str]] = {}
    for name, split in _pairs(frame):
        if isinstance(name, str) and name and isinstance(split, str) and split in _SPLITS:
            seen.setdefault(name, set()).add(split)
    return {name: cast("Split", next(iter(splits))) for name, splits in seen.items() if len(splits) == 1}


def prefill_splits(frame: pd.DataFrame, published: Mapping[str, Split]) -> tuple[pd.DataFrame, int]:
    """Fill empty ``split`` cells of published images; count the images that got a value.

    Non-empty cells, including invalid ones, are kept. A frame without a
    ``split`` column gets one with empty cells first.
    """
    working = frame.copy(deep=True)
    if "split" not in working:
        # An empty string is what the bundle CSV reader yields for an empty cell.
        working["split"] = [""] * len(working)
    if "image_name" not in working:
        return working, 0
    values: list[object] = []
    filled: set[str] = set()
    for name, split in _pairs(working):
        if isinstance(name, str) and name in published and is_missing(split):
            values.append(published[name])
            filled.add(name)
        else:
            values.append(split)
    # Whole-column replacement keeps duplicate indices and avoids dtype upcast warnings.
    working["split"] = pd.Series(values, dtype=object).to_numpy()
    return working, len(filled)


def changed_splits(frame: pd.DataFrame, published: Mapping[str, Split]) -> tuple[tuple[str, Split, str], ...]:
    """Sorted ``(image_name, published, current)`` for published images now in another split."""
    changes = {
        (name, published[name], split if isinstance(split, str) else str(split))
        for name, split in _pairs(frame)
        if isinstance(name, str) and name in published and not is_missing(split) and split != published[name]
    }
    return tuple(sorted(changes))
