"""Partition annotation DataFrame into dataset / obsolete / in_progress parts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pandas as pd
from loguru import logger

if TYPE_CHECKING:
    from cveta2.models import DeletedImage


@dataclass
class PartitionResult:
    """Three-way partition of the annotation DataFrame."""

    dataset: pd.DataFrame
    obsolete: pd.DataFrame
    in_progress: pd.DataFrame
    deleted_images: list[DeletedImage] = field(default_factory=list)


def _parse_task_dates(dates: pd.Series[str]) -> pd.Series[pd.Timestamp]:
    """Parse ``task_updated_date`` strings to UTC timestamps (NaT on failure)."""
    return pd.to_datetime(dates, errors="coerce", utc=True)


def _deleted_registry_frame(
    deleted_images: list[DeletedImage],
) -> pd.DataFrame:
    """Build a frame of deletion records (one row per deleted task/image)."""
    columns = ["image_name", "task_id", "task_updated_date", "_is_deleted"]
    rows = [
        {
            "image_name": d.image_name,
            "task_id": d.task_id,
            "task_updated_date": d.task_updated_date,
            "_is_deleted": 1,
        }
        for d in deleted_images
    ]
    return pd.DataFrame(rows, columns=columns)


def _latest_row_per_image(df: pd.DataFrame) -> pd.DataFrame:
    """Return one row per ``image_name``: the one with the max ``_parsed_date``.

    The stable sort keeps the original row order among equal dates, so
    callers break ties by ordering *df* (deletion records first).
    """
    latest: pd.DataFrame = df.sort_values(
        "_parsed_date", ascending=False, kind="stable"
    ).drop_duplicates(subset=["image_name"], keep="first")
    return latest


def _latest_task_per_image(
    df: pd.DataFrame,
    deleted_images: list[DeletedImage],
    parsed_dates: pd.Series[pd.Timestamp],
) -> pd.DataFrame:
    """Return the latest task per ``image_name`` across df rows and deletions.

    Deletion records are concatenated **first** so they win ties on an
    identical ``task_updated_date`` (annotations may exist for a frame the
    same task also deleted).  Indexed by ``image_name``.
    """
    latest_from_df = (
        df[["image_name", "task_id"]]
        .assign(_parsed_date=parsed_dates, _is_deleted=0)
        .drop_duplicates(subset=["image_name", "task_id"])
    )

    registry = _deleted_registry_frame(deleted_images)
    registry["_parsed_date"] = _parse_task_dates(registry["task_updated_date"])

    combined = pd.concat(
        [registry[latest_from_df.columns], latest_from_df],
        ignore_index=True,
    )
    latest_per_image: pd.DataFrame = _latest_row_per_image(combined).set_index(
        "image_name"
    )
    return latest_per_image


def _split_completed(
    completed_non_deleted: pd.DataFrame,
    parsed_dates: pd.Series[pd.Timestamp],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split completed rows into (latest-task dataset, stale obsolete)."""
    if completed_non_deleted.empty:
        return completed_non_deleted.copy(), completed_non_deleted.copy()

    cnd = completed_non_deleted.assign(_parsed_date=parsed_dates)
    latest_completed = _latest_row_per_image(cnd)[["image_name", "task_id"]].rename(
        columns={"task_id": "_latest_task_id"}
    )
    merged = completed_non_deleted.merge(latest_completed, on="image_name", how="left")
    is_latest = (merged["task_id"] == merged["_latest_task_id"]).to_numpy()
    return completed_non_deleted[is_latest], completed_non_deleted[~is_latest]


def _filter_deleted_images(
    deleted_images: list[DeletedImage],
    deleted_image_names: set[str],
    latest_per_image: pd.DataFrame,
) -> list[DeletedImage]:
    """Return deduplicated ``DeletedImage`` list for truly-deleted images.

    Only keeps entries whose ``task_id`` matches the latest deletion task
    for that ``image_name``.
    """
    latest_deleted_task: dict[str, int] = {}
    for name in deleted_image_names:
        row = latest_per_image.loc[name]
        latest_deleted_task[name] = int(row["task_id"])

    filtered = [
        img
        for img in deleted_images
        if img.image_name in latest_deleted_task
        and img.task_id == latest_deleted_task[img.image_name]
    ]
    seen: set[str] = set()
    unique: list[DeletedImage] = []
    for img in sorted(filtered, key=lambda x: x.image_name):
        if img.image_name not in seen:
            seen.add(img.image_name)
            unique.append(img)
    return unique


def partition_annotations_df(
    df: pd.DataFrame,
    deleted_images: list[DeletedImage],
) -> PartitionResult:
    """Partition an annotation DataFrame into dataset, obsolete and in-progress parts.

    Required columns in *df*: ``image_name``, ``task_id``, ``task_updated_date``,
    ``task_status``.

    Algorithm
    ---------
    1. :func:`_latest_task_per_image` finds the latest task per ``image_name``
       across *df* rows and ``deleted_images`` (deletions win ties).
    2. If that latest task is a deletion → the image is "deleted": all its rows
       go to **obsolete** and it is collected via :func:`_filter_deleted_images`.
    3. For non-deleted images:
       - rows where ``task_status != "completed"`` → **in_progress**
       - :func:`_split_completed` sends the *latest completed task* per image to
         **dataset** and the rest to **obsolete**.
    """
    if df.empty:
        empty = df.copy()
        return PartitionResult(
            dataset=empty, obsolete=empty.copy(), in_progress=empty.copy()
        )

    parsed_dates = _parse_task_dates(df["task_updated_date"])
    latest_per_image = _latest_task_per_image(df, deleted_images, parsed_dates)

    deleted_image_names: set[str] = set(
        latest_per_image.index[latest_per_image["_is_deleted"] == 1]
    )

    unique_deleted = _filter_deleted_images(
        deleted_images,
        deleted_image_names,
        latest_per_image,
    )
    if unique_deleted:
        logger.debug(f"Images deleted in their latest task: {len(unique_deleted)}")

    is_deleted = df["image_name"].isin(deleted_image_names)
    is_completed = df["task_status"] == "completed"

    obsolete_deleted = df[is_deleted]
    in_progress = df[~is_deleted & ~is_completed]
    completed_non_deleted = df[~is_deleted & is_completed]

    dataset, obsolete_stale = _split_completed(
        completed_non_deleted, parsed_dates[completed_non_deleted.index]
    )
    obsolete = pd.concat([obsolete_deleted, obsolete_stale], ignore_index=True)

    logger.debug(
        f"Partition result: "
        f"dataset={len(dataset)} rows/{dataset['image_name'].nunique()} images, "
        f"obsolete={len(obsolete)} rows/{obsolete['image_name'].nunique()} images, "
        f"in_progress={len(in_progress)} rows/"
        f"{in_progress['image_name'].nunique()} images, "
        f"deleted_images={len(unique_deleted)}",
    )

    return PartitionResult(
        dataset=dataset.reset_index(drop=True),
        obsolete=obsolete.reset_index(drop=True),
        in_progress=in_progress.reset_index(drop=True),
        deleted_images=unique_deleted,
    )
