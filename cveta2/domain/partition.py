"""Partition annotation DataFrame into dataset / obsolete / in_progress parts."""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pandas as pd
from loguru import logger

from cveta2.domain.models import COMPLETED_JOB_STAGE, COMPLETED_JOB_STATE

if TYPE_CHECKING:
    from cveta2.domain.models import DeletedImage


@dataclass
class PartitionResult:
    """Three-way partition of the annotation DataFrame.

    *pending_deletions* are deletions made by tasks that are not finished
    yet. They decide nothing until their task completes; the writers append
    them to ``in_progress.csv`` (see :func:`in_progress_table`).
    """

    dataset: "pd.DataFrame"
    obsolete: "pd.DataFrame"
    in_progress: "pd.DataFrame"
    deleted_images: "list[DeletedImage]" = field(default_factory=list)
    pending_deletions: "list[DeletedImage]" = field(default_factory=list)


def _rows_are_finished(frame: "pd.DataFrame") -> "pd.Series[bool]":
    """Use explicit task completion, falling back to legacy per-job columns."""
    finished = (frame["job_stage"] == COMPLETED_JOB_STAGE) & (frame["job_state"] == COMPLETED_JOB_STATE)
    if "task_completed" in frame:
        finished = finished.where(frame["task_completed"].isna(), frame["task_completed"].eq(other=True))
    # Nullable pandas columns propagate unknown comparisons as pd.NA. An
    # unknown legacy position is unfinished evidence, not an ignorable row.
    return finished.fillna(value=False)


def usable_task_ids(values: "pd.Series") -> "pd.Series":
    """Return *values* as numeric task IDs, with unusable cells as NaN.

    Text, fractional and infinite cells name no task: they are dropped
    rather than truncated, and one of them cannot turn the whole column
    into text that no longer matches numeric IDs.
    """
    numeric = pd.to_numeric(values, errors="coerce")
    return numeric.where(numeric % 1 == 0)


def completed_task_ids(
    df: "pd.DataFrame",
    deleted_images: "list[DeletedImage] | None" = None,
) -> set[int]:
    """Return the ids of tasks whose every job has finished review.

    ``task_completed`` captures every live job, even jobs with no exported
    frames. When absent/null (legacy CSV), fall back to per-row
    ``job_stage``/``job_state``. Any unfinished row excludes the task.

    *deleted_images* are folded in because their rows live in a separate
    file: a job whose every frame was deleted contributes nothing to *df*
    and would otherwise let an unfinished task pass as complete.

    The two frames are scanned separately rather than concatenated: a task
    qualifies when it owns at least one row and no unfinished one, which
    the set difference expresses without either frame's row labels having
    to mean anything.  A row without a ``task_id`` belongs to no task and
    neither qualifies nor disqualifies one; neither does an unusable one.
    """
    columns = ["task_id", "job_stage", "job_state"]
    if "task_completed" in df:
        columns.append("task_completed")
    frames = [df.loc[:, columns]]
    if deleted_images:
        frames.append(
            pd.DataFrame(
                [
                    {
                        "task_id": d.task_id,
                        "job_stage": d.job_stage,
                        "job_state": d.job_state,
                        "task_completed": d.task_completed,
                    }
                    for d in deleted_images
                ]
            )
        )
    finished: set[int] = set()
    unfinished: set[int] = set()
    for frame in frames:
        is_finished = _rows_are_finished(frame)
        task_ids = usable_task_ids(frame["task_id"])
        finished |= {int(t) for t in task_ids[is_finished].dropna()}
        unfinished |= {int(t) for t in task_ids[~is_finished].dropna()}
    return finished - unfinished


def _deleted_registry_frame(
    deleted_images: "list[DeletedImage]",
) -> "pd.DataFrame":
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


def _latest_row_per_image(df: "pd.DataFrame") -> "pd.DataFrame":
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
    ordered = df.assign(_row_order=list(range(len(df)))).sort_values(["task_id", "_row_order"], ascending=[False, True])
    latest: pd.DataFrame = ordered.drop_duplicates(subset=["image_name"], keep="first").drop(columns="_row_order")
    return latest


def _latest_task_per_image(
    df: "pd.DataFrame",
    deleted_images: "list[DeletedImage]",
) -> "pd.DataFrame":
    """Return the latest task per ``image_name`` across *df* rows and deletions.

    Two different tasks can no longer tie, so the only tie left is within a
    single task: a frame that task annotated and also marked deleted.
    Deletion records are concatenated **first** to win it.  Indexed by
    ``image_name``.
    """
    latest_from_df = (
        df[["image_name", "task_id"]].assign(_is_deleted=0).drop_duplicates(subset=["image_name", "task_id"])
    )

    registry = _deleted_registry_frame(deleted_images)

    combined = pd.concat(
        [registry[latest_from_df.columns], latest_from_df],
        ignore_index=True,
    )
    latest_per_image: pd.DataFrame = _latest_row_per_image(combined).set_index("image_name")
    return latest_per_image


def _split_completed(
    completed_non_deleted: "pd.DataFrame",
) -> "tuple[pd.DataFrame, pd.DataFrame]":
    """Split completed rows into (latest-task dataset, stale obsolete)."""
    if completed_non_deleted.empty:
        return completed_non_deleted.copy(), completed_non_deleted.copy()

    latest_completed = _latest_row_per_image(completed_non_deleted)[["image_name", "task_id"]].rename(
        columns={"task_id": "_latest_task_id"}
    )
    # is_latest is applied positionally below, so the merge must preserve row
    # order. image_name is the only column the two frames share and every key
    # matches, which is also why on=/how= cannot change the outcome here.
    merged = completed_non_deleted.merge(latest_completed, on="image_name", how="left")
    is_latest = (merged["task_id"] == merged["_latest_task_id"]).to_numpy()
    return completed_non_deleted[is_latest], completed_non_deleted[~is_latest]


def _filter_deleted_images(
    deleted_images: "list[DeletedImage]",
    deleted_image_names: set[str],
    latest_per_image: "pd.DataFrame",
) -> "list[DeletedImage]":
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
        if img.image_name in latest_deleted_task and img.task_id == latest_deleted_task[img.image_name]
    ]
    seen: set[str] = set()
    unique: list[DeletedImage] = []
    for img in sorted(filtered, key=lambda x: x.image_name):
        if img.image_name not in seen:
            seen.add(img.image_name)
            unique.append(img)
    return unique


def _carried_rows(
    df: "pd.DataFrame",
    candidates: "pd.Series[bool]",
    deletion_pairs: set[tuple[str, int]],
) -> "pd.Series[bool]":
    """Mark the rows of the newest task that holds each image as a live frame.

    Among *candidates*, a row whose own task also deleted the image is the
    retained shape of a deleted frame, not a live annotation, so it never
    counts.
    """
    task_ids = usable_task_ids(df["task_id"])
    live = candidates & pd.Series(
        [
            pd.notna(task) and (image, int(task)) not in deletion_pairs
            for image, task in zip(df["image_name"], task_ids, strict=True)
        ],
        index=df.index,
        dtype=bool,
    )
    newest = task_ids[live].groupby(df["image_name"][live]).max()
    carried: pd.Series[bool] = live & task_ids.eq(df["image_name"].map(newest))
    return carried


def _newest_live_task(
    df: "pd.DataFrame",
    rows: "pd.Series[bool]",
    deletion_pairs: set[tuple[str, int]],
) -> dict[str, int]:
    """Return per image the highest task that holds it as a live frame among *rows*."""
    newest: dict[str, int] = {}
    selected = df[rows]
    for image, task in zip(selected["image_name"], usable_task_ids(selected["task_id"]), strict=True):
        if pd.isna(task) or (image, int(task)) in deletion_pairs:
            continue
        newest[image] = max(newest.get(image, int(task)), int(task))
    return newest


def _pending_deletions(
    deleted_images: "list[DeletedImage]",
    completed: set[int],
    deleted_image_names: set[str],
    decided_task: dict[str, int],
) -> "list[DeletedImage]":
    """Return unfinished deletions newer than the image's completed result.

    One record per image and task, ordered by image then task. An image
    already in ``deleted.csv`` has nothing left to delete, and a deletion
    older than the completed result is superseded by it.
    """
    pending: dict[tuple[str, int], DeletedImage] = {}
    for record in deleted_images:
        key = (record.image_name, record.task_id)
        if record.task_id in completed or record.image_name in deleted_image_names or key in pending:
            continue
        if record.task_id < decided_task.get(record.image_name, -1):
            continue
        pending[key] = record
    return [pending[key] for key in sorted(pending)]


def in_progress_table(result: "PartitionResult") -> "pd.DataFrame":
    """Return the ``in_progress.csv`` table: unfinished rows, then pending deletions.

    Pending deletions are written as ``instance_shape="deleted"`` rows, as in
    ``raw.csv``. Both parts are combined as objects so the annotation rows keep
    their own cell text: a sparse deletion row would otherwise turn an integer
    column such as ``z_order`` into floats.
    """
    if not result.pending_deletions:
        return result.in_progress
    pending = pd.DataFrame([record.to_csv_row() for record in result.pending_deletions])
    columns = list(result.in_progress.columns)
    columns += [name for name in pending.columns if name not in columns]
    return pd.concat(
        [
            result.in_progress.reindex(columns=columns).astype(object),
            pending.reindex(columns=columns).astype(object),
        ],
        ignore_index=True,
    )


def partition_annotations_df(
    df: "pd.DataFrame",
    deleted_images: "list[DeletedImage]",
) -> "PartitionResult":
    """Partition an annotation DataFrame into dataset, obsolete and in-progress parts.

    Required columns in *df*: ``image_name``, ``task_id``, ``job_stage``,
    ``job_state``.

    Only completed tasks (see :func:`completed_task_ids`) decide an image:

    1. :func:`_latest_task_per_image` over completed rows and completed
       deletions finds each image's completed result (highest task id;
       a deletion wins a tie inside its own task).
    2. A result that is a deletion makes the image **deleted**: all its rows
       go to **obsolete** and its record to ``deleted_images``. The exception:
       a newer unfinished task that holds the image as a live frame reopens
       it. A reopened image is in nobody's deleted list; the rows of its
       newest completed task that holds it live move to **in_progress**, its
       other completed rows go to **obsolete**.
    3. Otherwise the latest completed task goes to **dataset** and older
       completed tasks to **obsolete**.
    4. Rows of unfinished tasks of an image that is not deleted go to
       **in_progress**; unfinished deletions newer than the completed result
       become ``pending_deletions``.
    """
    if df.empty:
        df = df.reindex(columns=df.columns.union(["image_name", "task_id", "job_stage", "job_state"], sort=False))

    completed = completed_task_ids(df, deleted_images)
    is_completed = df["task_id"].isin(completed)
    deletion_pairs = {(record.image_name, record.task_id) for record in deleted_images}

    decision = _latest_task_per_image(
        df[is_completed],
        [record for record in deleted_images if record.task_id in completed],
    )
    # Completed tasks are usable integer ids by construction of ``completed``.
    decided_task = {str(name): int(task) for name, task in decision["task_id"].items()}
    deleted_by_completed = decision.index[decision["_is_deleted"] == 1]
    newest_unfinished = _newest_live_task(df, ~is_completed, deletion_pairs)
    reopened = {name for name in deleted_by_completed if newest_unfinished.get(name, -1) > decided_task[name]}
    deleted_image_names = set(deleted_by_completed) - reopened

    unique_deleted = _filter_deleted_images(deleted_images, deleted_image_names, decision)
    if unique_deleted:
        logger.debug(f"Images deleted in their latest completed task: {len(unique_deleted)}")
    pending = _pending_deletions(deleted_images, completed, deleted_image_names, decided_task)

    is_deleted = df["image_name"].isin(deleted_image_names)
    is_reopened = df["image_name"].isin(reopened)
    is_carried = _carried_rows(df, is_reopened & is_completed, deletion_pairs)

    dataset, obsolete_stale = _split_completed(df[~is_deleted & ~is_reopened & is_completed])
    in_progress = df[(~is_deleted & ~is_completed) | is_carried]
    obsolete = pd.concat(
        [df[is_deleted], obsolete_stale, df[is_reopened & is_completed & ~is_carried]],
        ignore_index=True,
    )

    logger.debug(
        f"Partition result: "
        f"dataset={len(dataset)} rows/{dataset['image_name'].nunique()} images, "
        f"obsolete={len(obsolete)} rows/{obsolete['image_name'].nunique()} images, "
        f"in_progress={len(in_progress)} rows/"
        f"{in_progress['image_name'].nunique()} images, "
        f"deleted_images={len(unique_deleted)}, pending_deletions={len(pending)}",
    )

    return PartitionResult(
        dataset=dataset.reset_index(drop=True),
        obsolete=obsolete.reset_index(drop=True),
        in_progress=in_progress.reset_index(drop=True),
        deleted_images=unique_deleted,
        pending_deletions=pending,
    )
