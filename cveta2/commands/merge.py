"""Implementation of the ``cveta2 merge`` command."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd
from loguru import logger

from cveta2.commands._helpers import read_dataset_csv, write_df_csv

if TYPE_CHECKING:
    import argparse

# Minimal columns that every dataset CSV must contain.
_REQUIRED_COLUMNS: set[str] = {
    "image_name",
    "instance_shape",
    "instance_label",
    "bbox_x_tl",
    "bbox_y_tl",
    "bbox_x_br",
    "bbox_y_br",
}

# Column required when --by-time is used.
_TIME_COLUMN = "task_updated_date"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_dataset_csv(path: Path, *, by_time: bool = False) -> pd.DataFrame:
    """Read a dataset CSV and validate required columns.

    When *by_time* is ``True`` the ``task_updated_date`` column is also
    required.
    """
    return read_dataset_csv(
        path,
        _REQUIRED_COLUMNS,
        require_time_column=by_time,
    )


def _read_deleted_names(path: Path | None) -> set[str]:
    """Read *deleted.txt* and return image names as a set."""
    if path is None:
        return set()
    if not path.is_file():
        sys.exit(f"Ошибка: файл не найден: {path}")
    names = {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    logger.info(f"Загружен {path}: {len(names)} удалённых изображений")
    return names


def _propagate_splits(
    merged: pd.DataFrame,
    old: pd.DataFrame,
    new: pd.DataFrame,
    common_images: set[str],
) -> pd.DataFrame:
    """Propagate ``split`` values from *old* into *merged* rows that lack them.

    For images present in both datasets where **new** won the merge, the
    ``split`` from *old* is copied over when the merged row has no split.

    Warnings are emitted when:
    - *old* has no ``split`` data at all (column missing or all NaN).
    - Both *old* and *new* have non-null ``split`` for the same common images.
    """
    if "split" not in old.columns or old["split"].isna().all():
        logger.warning("В old-датасете нет данных split — пропагация split невозможна")
        return merged

    old_splits: dict[str, str] = (
        old[old["split"].notna()]
        .drop_duplicates("image_name")
        .set_index("image_name")["split"]
        .to_dict()
    )

    if "split" in new.columns:
        new_split_images = set(
            new.loc[
                new["split"].notna() & new["image_name"].isin(common_images),
                "image_name",
            ]
        )
        conflict_images = new_split_images & set(old_splits.keys())
        if conflict_images:
            logger.warning(
                f"split задан в обоих датасетах для {len(conflict_images)} "
                f"изображений — используется значение из победившей стороны"
            )

    if "split" not in merged.columns:
        return merged

    mask = merged["split"].isna() & merged["image_name"].isin(old_splits.keys())
    merged.loc[mask, "split"] = merged.loc[mask, "image_name"].map(old_splits)

    propagated_count = int(mask.sum())
    if propagated_count > 0:
        logger.info(
            f"Пропагация split: заполнено {propagated_count} строк из old-датасета"
        )

    return merged


def _merge_datasets(
    old: pd.DataFrame,
    new: pd.DataFrame,
    deleted: set[str],
    *,
    by_time: bool = False,
) -> pd.DataFrame:
    """Merge *old* and *new* datasets, removing images from *deleted*.

    Default behaviour (``by_time=False``):
        For images present in both datasets keep only **new** annotations.

    ``--by-time`` mode (``by_time=True``):
        For images present in both datasets keep annotations from whichever
        dataset has the more recent ``task_updated_date`` for that image.
    """
    old_images: set[str] = set(old["image_name"].dropna().unique())
    new_images: set[str] = set(new["image_name"].dropna().unique())
    common_images = old_images & new_images

    # --- determine which side wins for each conflicting image ---------------
    keep_from_old: set[str]
    if by_time and common_images:
        keep_from_new = _resolve_by_time(old, new, common_images)
        keep_from_old = common_images - keep_from_new
    else:
        # Default: new always wins
        keep_from_new = common_images
        keep_from_old = set()

    # Build masks
    old_keep_mask = old["image_name"].isin(
        (old_images - common_images - deleted) | keep_from_old
    )
    new_keep_mask = new["image_name"].isin((new_images - deleted) - keep_from_old)

    old_filtered = old[old_keep_mask]
    new_filtered = new[new_keep_mask]

    merged: pd.DataFrame = pd.concat([old_filtered, new_filtered], ignore_index=True)

    # --- propagate split from old to new ------------------------------------
    merged = _propagate_splits(merged, old, new, common_images)

    # --- log summary --------------------------------------------------------
    only_old = old_images - new_images - deleted
    only_new = new_images - old_images - deleted
    deleted_hit = (old_images | new_images) & deleted
    overridden_by_new = keep_from_new - deleted
    overridden_by_old = keep_from_old - deleted

    logger.info(
        f"Результат слияния: "
        f"только в old={len(only_old)}, "
        f"только в new={len(only_new)}, "
        f"конфликт→new={len(overridden_by_new)}, "
        f"конфликт→old={len(overridden_by_old)}, "
        f"удалено={len(deleted_hit)}, "
        f"итого строк={len(merged)}"
    )
    return merged


def _resolve_by_time(
    old: pd.DataFrame,
    new: pd.DataFrame,
    common_images: set[str],
) -> set[str]:
    """Return the subset of *common_images* where **new** should win.

    For each image present in both datasets, compare the maximum
    ``task_updated_date``.  If new >= old the image goes to the
    "keep from new" set, otherwise it stays with old.
    """
    common_list = sorted(common_images)

    old_common = old[old["image_name"].isin(common_images)]
    new_common = new[new["image_name"].isin(common_images)]

    old_max = (
        old_common.assign(
            _parsed=pd.to_datetime(old_common[_TIME_COLUMN], errors="coerce", utc=True)
        )
        .groupby("image_name")["_parsed"]
        .max()
    )
    new_max = (
        new_common.assign(
            _parsed=pd.to_datetime(new_common[_TIME_COLUMN], errors="coerce", utc=True)
        )
        .groupby("image_name")["_parsed"]
        .max()
    )

    keep_from_new: set[str] = set()
    for img in common_list:
        old_ts = old_max.get(img)
        new_ts = new_max.get(img)
        # If either side has no parseable date, fall back to new-wins.
        if pd.isna(old_ts) or pd.isna(new_ts) or new_ts >= old_ts:
            keep_from_new.add(img)
    return keep_from_new


# ---------------------------------------------------------------------------
# Main handler
# ---------------------------------------------------------------------------


def run_merge(args: argparse.Namespace) -> None:
    """Run the ``merge`` command."""
    by_time: bool = args.by_time

    old_df = _read_dataset_csv(Path(args.old), by_time=by_time)
    new_df = _read_dataset_csv(Path(args.new), by_time=by_time)
    deleted = _read_deleted_names(
        Path(args.deleted) if args.deleted else None,
    )

    merged = _merge_datasets(old_df, new_df, deleted, by_time=by_time)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_df_csv(merged, output_path, "Merged CSV")
