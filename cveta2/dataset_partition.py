"""Partition annotation DataFrame into dataset / obsolete / in_progress parts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pandas as pd
from loguru import logger

from cveta2.models import COMPLETED_JOB_STAGE, COMPLETED_JOB_STATE

if TYPE_CHECKING:
    from cveta2.models import DeletedImage


@dataclass
class PartitionResult:
    """Three-way partition of the annotation DataFrame."""

    dataset: pd.DataFrame
    obsolete: pd.DataFrame
    in_progress: pd.DataFrame
    deleted_images: list[DeletedImage] = field(default_factory=list)


def _rows_are_finished(frame: pd.DataFrame) -> pd.Series[bool]:
    """Per-row mask: this row's job sits on the finished ``(stage, state)``."""
    return (frame["job_stage"] == COMPLETED_JOB_STAGE) & (
        frame["job_state"] == COMPLETED_JOB_STATE
    )


def completed_task_ids(
    df: pd.DataFrame,
    deleted_images: list[DeletedImage] | None = None,
) -> set[int]:
    """Return the ids of tasks whose every job has finished review.

    ``job_stage``/``job_state`` are per-job, so a task counts as finished
    only when all of its rows do — the same "no job left at annotation or
    validation" rule CVAT applies to derive a task's status.

    *deleted_images* are folded in because their rows live in a separate
    file: a job whose every frame was deleted contributes nothing to *df*
    and would otherwise let an unfinished task pass as complete.

    The two frames are scanned separately rather than concatenated: a task
    qualifies when it owns at least one row and no unfinished one, which
    the set difference expresses without either frame's row labels having
    to mean anything.  A row without a ``task_id`` belongs to no task and
    neither qualifies nor disqualifies one.
    """
    frames = [df.loc[:, ["task_id", "job_stage", "job_state"]]]
    if deleted_images:
        frames.append(
            pd.DataFrame(
                [
                    {
                        "task_id": d.task_id,
                        "job_stage": d.job_stage,
                        "job_state": d.job_state,
                    }
                    for d in deleted_images
                ]
            )
        )
    finished: set[int] = set()
    unfinished: set[int] = set()
    for frame in frames:
        is_finished = _rows_are_finished(frame)
        task_ids = frame["task_id"]
        finished |= {int(t) for t in task_ids[is_finished].dropna()}
        unfinished |= {int(t) for t in task_ids[~is_finished].dropna()}
    return finished - unfinished


def _deleted_registry_frame(
    deleted_images: list[DeletedImage],
) -> pd.DataFrame:
    """Build a frame of deletion records (one row per deleted task/image)."""
    columns = ["image_name", "task_id", "_is_deleted"]
    rows = [
        {
            "image_name": d.image_name,
            "task_id": d.task_id,
            "_is_deleted": 1,
        }
        for d in deleted_images
    ]
    return pd.DataFrame(rows, columns=columns)


def _latest_row_per_image(df: pd.DataFrame) -> pd.DataFrame:
    """Return one row per ``image_name``: the one with the max ``task_id``.

    CVAT hands out task ids in creation order, and unlike ``updated_date``
    an id never moves: editing a project's labels rewrites every task's
    date at once, which would otherwise scramble this ordering.  A row
    without a ``task_id`` sorts last and so loses to any row that has one.

    Equal ids are broken by row position, so callers express precedence by
    ordering *df* (deletion records first). That position is sorted on
    explicitly instead of leaning on sort stability, which the single-key
    ``sort_values`` path only delivers for frames small enough to stay in
    insertion sort.
    """
    ordered = df.assign(_row_order=list(range(len(df)))).sort_values(
        ["task_id", "_row_order"], ascending=[False, True]
    )
    latest: pd.DataFrame = ordered.drop_duplicates(
        subset=["image_name"], keep="first"
    ).drop(columns="_row_order")
    return latest


def _latest_task_per_image(
    df: pd.DataFrame,
    deleted_images: list[DeletedImage],
) -> pd.DataFrame:
    """Return the latest task per ``image_name`` across df rows and deletions.

    Two different tasks can no longer tie, so the only tie left is within a
    single task: a frame that task annotated and also marked deleted.
    Deletion records are concatenated **first** to win it.  Indexed by
    ``image_name``.
    """
    latest_from_df = (
        df[["image_name", "task_id"]]
        .assign(_is_deleted=0)
        .drop_duplicates(subset=["image_name", "task_id"])
    )

    registry = _deleted_registry_frame(deleted_images)

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
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split completed rows into (latest-task dataset, stale obsolete)."""
    if completed_non_deleted.empty:
        return completed_non_deleted.copy(), completed_non_deleted.copy()

    latest_completed = _latest_row_per_image(completed_non_deleted)[
        ["image_name", "task_id"]
    ].rename(columns={"task_id": "_latest_task_id"})
    # is_latest is applied positionally below, so the merge must preserve row
    # order. image_name is the only column the two frames share and every key
    # matches, which is also why on=/how= cannot change the outcome here.
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

    Required columns in *df*: ``image_name``, ``task_id``, ``job_stage``,
    ``job_state``.

    Algorithm
    ---------
    1. :func:`_latest_task_per_image` finds the latest task per ``image_name``
       across *df* rows and ``deleted_images`` (deletions win ties).
    2. If that latest task is a deletion → the image is "deleted": all its rows
       go to **obsolete** and it is collected via :func:`_filter_deleted_images`.
    3. For non-deleted images:
       - rows of tasks with an unfinished job (see
         :func:`completed_task_ids`) → **in_progress**
       - :func:`_split_completed` sends the *latest completed task* per image to
         **dataset** and the rest to **obsolete**.
    """
    if df.empty:
        empty = df.copy()
        return PartitionResult(
            dataset=empty, obsolete=empty.copy(), in_progress=empty.copy()
        )

    latest_per_image = _latest_task_per_image(df, deleted_images)

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
    is_completed = df["task_id"].isin(completed_task_ids(df, deleted_images))

    obsolete_deleted = df[is_deleted]
    in_progress = df[~is_deleted & ~is_completed]
    completed_non_deleted = df[~is_deleted & is_completed]

    dataset, obsolete_stale = _split_completed(completed_non_deleted)
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
