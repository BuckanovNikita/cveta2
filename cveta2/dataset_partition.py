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
    deleted_names: list[str] = field(default_factory=list)


def partition_annotations_df(
    df: pd.DataFrame,
    deleted_images: list[DeletedImage],
) -> PartitionResult:
    """Partition an annotation DataFrame into dataset, obsolete and in-progress parts.

    Algorithm
    ---------
    1. Build a *deleted registry* — ``{image_name: [(task_id, task_updated_date)]}``
       from ``deleted_images``.
    2. For every unique ``image_name`` that appears in *df* **or** the deleted
       registry, determine the **latest task** (max ``task_updated_date`` across
       both sources).
    3. If the latest task for an image is a deletion record → the image is
       "deleted": all its rows in *df* go to **obsolete** and the filename is
       collected into ``deleted_names``.
    4. For non-deleted images:
       - rows where ``task_status != "completed"`` → **in_progress**
       - among completed rows, those from the *latest completed task* per image
         → **dataset**, the rest → **obsolete**
    """
    if df.empty:
        empty = df.copy()
        return PartitionResult(
            dataset=empty, obsolete=empty.copy(), in_progress=empty.copy()
        )

    # ------------------------------------------------------------------
    # 1. Build deleted registry: image_name → [(task_id, task_updated_date)]
    # ------------------------------------------------------------------
    deleted_registry: dict[str, list[tuple[int, str]]] = {}
    for d in deleted_images:
        deleted_registry.setdefault(d.image_name, []).append(
            (d.task_id, d.task_updated_date),
        )

    # ------------------------------------------------------------------
    # 2. Per-image latest task (across df rows + deleted records)
    # ------------------------------------------------------------------
    # Latest task_updated_date per (image_name, task_id) from df rows
    latest_from_df = df[["image_name", "task_id", "task_updated_date"]].drop_duplicates(
        subset=["image_name", "task_id"]
    )

    # Build a parallel frame from deleted records
    deleted_rows: list[dict[str, str | int]] = []
    for image_name, entries in deleted_registry.items():
        for task_id, task_updated_date in entries:
            deleted_rows.append(
                {
                    "image_name": image_name,
                    "task_id": task_id,
                    "task_updated_date": task_updated_date,
                    "_is_deleted": 1,
                },
            )

    if deleted_rows:
        deleted_df = pd.DataFrame(deleted_rows)
    else:
        deleted_df = pd.DataFrame(
            columns=["image_name", "task_id", "task_updated_date", "_is_deleted"],
        )

    latest_from_df = latest_from_df.copy()
    latest_from_df["_is_deleted"] = 0

    combined = pd.concat([latest_from_df, deleted_df], ignore_index=True)
    # Parse dates properly so comparisons work regardless of format/timezone.
    combined["_parsed_date"] = pd.to_datetime(
        combined["task_updated_date"],
        errors="coerce",
        utc=True,
    )
    # For each image, find the row with the maximum task_updated_date
    idx_latest = combined.groupby("image_name")["_parsed_date"].idxmax()
    latest_per_image = combined.loc[idx_latest].set_index("image_name")

    # ------------------------------------------------------------------
    # 3. Identify deleted images (latest task is a deletion)
    # ------------------------------------------------------------------
    deleted_mask_map = latest_per_image["_is_deleted"] == 1
    deleted_image_names: set[str] = set(deleted_mask_map[deleted_mask_map].index)
    deleted_names_sorted = sorted(deleted_image_names)

    if deleted_names_sorted:
        logger.debug(
            f"Images deleted in their latest task: {len(deleted_names_sorted)}"
        )

    # ------------------------------------------------------------------
    # 4. Partition the DataFrame
    # ------------------------------------------------------------------
    is_deleted = df["image_name"].isin(deleted_image_names)
    is_completed = df["task_status"] == "completed"

    # 4a. All rows for deleted images → obsolete
    obsolete_deleted = df[is_deleted]

    # 4b. Non-deleted, non-completed → in_progress
    in_progress = df[~is_deleted & ~is_completed]

    # 4c. Non-deleted, completed → partition into dataset vs obsolete
    completed_non_deleted = df[~is_deleted & is_completed]

    if completed_non_deleted.empty:
        dataset = completed_non_deleted.copy()
        obsolete_stale = completed_non_deleted.copy()
    else:
        # For each image_name, find the latest completed task_id
        cnd = completed_non_deleted.copy()
        cnd["_parsed_date"] = pd.to_datetime(
            cnd["task_updated_date"],
            errors="coerce",
            utc=True,
        )
        latest_completed = (
            cnd.sort_values("_parsed_date", ascending=False)
            .drop_duplicates(subset=["image_name"], keep="first")[
                ["image_name", "task_id"]
            ]
            .rename(columns={"task_id": "_latest_task_id"})
        )
        merged = completed_non_deleted.merge(
            latest_completed, on="image_name", how="left"
        )
        is_latest = merged["task_id"] == merged["_latest_task_id"]

        dataset = completed_non_deleted[is_latest.to_numpy()]
        obsolete_stale = completed_non_deleted[~is_latest.to_numpy()]

    obsolete = pd.concat([obsolete_deleted, obsolete_stale], ignore_index=True)

    logger.debug(
        f"Partition result: dataset={len(dataset)}, obsolete={len(obsolete)}, "
        f"in_progress={len(in_progress)}, deleted_names={len(deleted_names_sorted)}",
    )

    return PartitionResult(
        dataset=dataset.reset_index(drop=True),
        obsolete=obsolete.reset_index(drop=True),
        in_progress=in_progress.reset_index(drop=True),
        deleted_names=deleted_names_sorted,
    )
