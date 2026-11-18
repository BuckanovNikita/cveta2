"""Pure task baseline and completion policies."""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from cveta2.domain.errors import Cveta2Error
from cveta2.domain.partition import completed_task_ids, usable_task_ids

REQUIRED_COLUMNS = {"job_stage", "job_state", "task_id"}
SIBLING_CSV_NAMES = ("obsolete.csv", "deleted.csv")
IN_PROGRESS_CSV_NAME = "in_progress.csv"


@dataclass(frozen=True)
class WhatsNewBaseline:
    """What a fetched dataset CSV already contains: cutoff id + task ids."""

    cutoff: int
    known_task_ids: set[int]


def compute_baseline(
    df: pd.DataFrame,
    path: Path,
    siblings: Sequence[pd.DataFrame] = (),
    in_progress: pd.DataFrame | None = None,
) -> WhatsNewBaseline:
    """Build the comparison baseline from a fetched dataset CSV.

    ``known_task_ids`` spans completed tasks in *df* and the sibling CSVs
    written next to *path*. Any observed unfinished rows keep that task
    eligible for reporting when it subsequently completes.

    From *in_progress* only rows that explicitly say their task completed
    count: those are the boxes of a completed task that wait for a newer
    unfinished task to re-annotate an image the completed one deleted.
    Every other task there was unfinished at fetch time, which is exactly
    what whats-new reports once it completes.
    """
    return WhatsNewBaseline(
        cutoff=compute_cutoff(df, path),
        known_task_ids=_known_task_ids(df, siblings, in_progress),
    )


def compute_cutoff(df: pd.DataFrame, path: Path) -> int:
    """Compute the cutoff ``task_id`` from a fetched dataset CSV.

    Uses the max id among rows of tasks whose every job has finished
    review; falls back to the max over all rows when no task has.  CVAT
    hands out ids in creation order, and unlike ``task_updated_date`` they
    survive a project-wide label edit untouched.
    Raises :class:`Cveta2Error` when the column has no usable values.
    """
    all_ids = _task_ids(df)
    if not all_ids:
        raise Cveta2Error(f"Ошибка: столбец task_id в {path} пуст — невозможно определить задачу отсечки.")
    completed_ids = _task_ids(df[usable_task_ids(df["task_id"]).isin(completed_task_ids(df))])
    return max(completed_ids or all_ids)


def _task_ids(df: pd.DataFrame) -> set[int]:
    """Return the usable integer ``task_id`` values of *df*."""
    return {int(v) for v in usable_task_ids(df["task_id"]).dropna()}


def _explicitly_completed_task_ids(frame: pd.DataFrame | None) -> set[int]:
    """Return tasks whose rows in *frame* all explicitly say the task completed.

    Rows without an explicit ``task_completed`` prove nothing here: legacy
    stage/state columns describe one job, not the task.
    """
    if frame is None or not {"task_id", "task_completed"}.issubset(frame.columns):
        return set()
    task_ids = usable_task_ids(frame["task_id"])
    explicit = frame["task_completed"].eq(other=True)
    return {int(t) for t in task_ids[explicit].dropna()} - {int(t) for t in task_ids[~explicit].dropna()}


def _known_task_ids(
    df: pd.DataFrame,
    siblings: Sequence[pd.DataFrame],
    in_progress: pd.DataFrame | None,
) -> set[int]:
    """Collect completed task ids from the baseline and supplied sibling frames.

    Any unfinished row in either source keeps that task eligible for reporting.
    Missing or unreadable siblings are handled by the persistence boundary.
    """
    known = _task_ids(df) | _explicitly_completed_task_ids(in_progress)
    unfinished = _task_ids(df) - completed_task_ids(df)
    for sibling_df in siblings:
        if "task_id" in sibling_df.columns:
            sibling_ids = _task_ids(sibling_df)
            known |= sibling_ids
            if REQUIRED_COLUMNS.issubset(sibling_df.columns):
                unfinished |= sibling_ids - completed_task_ids(sibling_df)
    return known - unfinished
