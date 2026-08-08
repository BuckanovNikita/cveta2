"""Dataset merge service: split propagation, by-time resolution, and I/O."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import pandas as pd
from loguru import logger

from cveta2.exceptions import Cveta2Error
from cveta2.services.output import read_dataset_csv, read_text_utf8, save_csv

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


def _read_dataset_csv(path: Path, *, by_time: bool) -> pd.DataFrame:
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
    """Read *deleted.csv* and return image names as a set.

    Supports both the new CSV format (with ``image_name`` column) and the
    legacy plain-text format (one name per line) for backward compatibility.
    """
    if path is None:
        return set()
    if not path.is_file():
        raise Cveta2Error(f"Ошибка: файл не найден: {path}")

    text = read_text_utf8(path)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines or "image_name" not in lines[0]:
        legacy_names = set(lines)
        logger.info(f"Загружен {path}: {len(legacy_names)} удалённых изображений")
        return legacy_names

    try:
        df = pd.read_csv(StringIO(text))
    except (pd.errors.ParserError, pd.errors.EmptyDataError) as e:
        raise Cveta2Error(f"Ошибка: не удалось прочитать CSV {path}: {e}") from e
    names = set(df["image_name"].dropna().unique())
    logger.info(f"Загружен {path}: {len(names)} удалённых изображений")
    return names


def _propagate_splits(
    merged: pd.DataFrame,
    old: pd.DataFrame,
    new: pd.DataFrame,
    common_images: set[str],
) -> pd.DataFrame:
    """Return *merged* with ``split`` values filled in from *old* where absent.

    For images present in both datasets where **new** won the merge, the
    ``split`` from *old* is copied over when the merged row has no split.
    *merged* itself is not modified.

    Warnings are emitted when:
    - *old* has no ``split`` data at all (column missing or all NaN).
    - Both *old* and *new* have non-null ``split`` for the same common images.
    """
    if "split" not in old.columns or old["split"].isna().all():
        logger.warning("В old-датасете нет данных split — пропагация split невозможна")
        return merged

    old_splits: dict[str, str] = {
        str(image_name): str(split)
        for image_name, split in old[old["split"].notna()]
        .drop_duplicates("image_name")
        .set_index("image_name")["split"]
        .items()
    }

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

    merged = merged.copy()
    mask = merged["split"].isna() & merged["image_name"].isin(old_splits.keys())
    merged.loc[mask, "split"] = merged.loc[mask, "image_name"].map(old_splits)

    if mask.any():
        logger.info(
            f"Пропагация split: заполнено {int(mask.sum())} строк из old-датасета"
        )

    return merged


def _split_winners(
    old: pd.DataFrame,
    new: pd.DataFrame,
    common_images: set[str],
    *,
    by_time: bool,
) -> tuple[set[str], set[str]]:
    """Return ``(keep_from_new, keep_from_old)`` for the conflicting images.

    By default **new** wins every conflict; in *by_time* mode each image
    goes to the side with the more recent ``task_updated_date``.
    """
    if by_time and common_images:
        keep_from_new = _resolve_by_time(old, new, common_images)
        return keep_from_new, common_images - keep_from_new
    return common_images, set()


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

    keep_from_new, keep_from_old = _split_winners(
        old, new, common_images, by_time=by_time
    )

    old_keep_mask = old["image_name"].isin(
        (old_images - common_images - deleted) | keep_from_old
    )
    new_keep_mask = new["image_name"].isin((new_images - deleted) - keep_from_old)
    merged: pd.DataFrame = pd.concat(
        [old[old_keep_mask], new[new_keep_mask]], ignore_index=True
    )
    merged = _propagate_splits(merged, old, new, common_images)

    logger.info(
        f"Результат слияния: "
        f"только в old={len(old_images - new_images - deleted)}, "
        f"только в new={len(new_images - old_images - deleted)}, "
        f"конфликт→new={len(keep_from_new - deleted)}, "
        f"конфликт→old={len(keep_from_old - deleted)}, "
        f"удалено={len((old_images | new_images) & deleted)}, "
        f"итого строк={len(merged)}"
    )
    return merged


def _max_updated_per_image(
    df: pd.DataFrame, images: set[str]
) -> pd.Series[pd.Timestamp]:
    """Return the max parsed ``task_updated_date`` per image within *images*."""
    subset = df[df["image_name"].isin(images)]
    parsed = pd.to_datetime(subset[_TIME_COLUMN], errors="coerce", utc=True)
    latest: pd.Series[pd.Timestamp] = parsed.groupby(subset["image_name"]).max()
    return latest


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
    old_max = _max_updated_per_image(old, common_images)
    new_max = _max_updated_per_image(new, common_images)

    keep_from_new: set[str] = set()
    for img in sorted(common_images):
        old_ts = old_max.get(img)
        new_ts = new_max.get(img)
        # If either side has no parseable date, fall back to new-wins.
        if pd.isna(old_ts) or pd.isna(new_ts) or new_ts >= old_ts:
            keep_from_new.add(img)
    return keep_from_new


def merge_datasets(
    old: str | Path,
    new: str | Path,
    output: str | Path,
    *,
    deleted: str | Path | None = None,
    by_time: bool = False,
) -> pd.DataFrame:
    """Merge two dataset CSVs and write the result to *output*.

    Returns the merged DataFrame.
    """
    old_df = _read_dataset_csv(Path(old), by_time=by_time)
    new_df = _read_dataset_csv(Path(new), by_time=by_time)
    deleted_names = _read_deleted_names(Path(deleted) if deleted else None)

    merged = _merge_datasets(old_df, new_df, deleted_names, by_time=by_time)

    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    save_csv(merged, output_path)
    return merged
