"""Cutoff computation for the whats-new workflow."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from cveta2.dataset_partition import completed_task_ids
from cveta2.exceptions import Cveta2Error

if TYPE_CHECKING:
    from pathlib import Path

    import pandas as pd

REQUIRED_COLUMNS = {"task_updated_date", "job_stage", "job_state", "task_id"}


@dataclass(frozen=True)
class WhatsNewBaseline:
    """What a fetched dataset CSV already contains: cutoff date + task ids."""

    cutoff: str
    known_task_ids: set[int]


def compute_baseline(df: pd.DataFrame, path: Path) -> WhatsNewBaseline:
    """Build the comparison baseline from a fetched dataset CSV.

    ``known_task_ids`` lets callers mark returned tasks that are already
    present in the CSV as *updated* rather than new.
    """
    return WhatsNewBaseline(
        cutoff=compute_cutoff(df, path),
        known_task_ids={int(v) for v in df["task_id"].dropna()},
    )


def compute_cutoff(df: pd.DataFrame, path: Path) -> str:
    """Compute the cutoff date from the CSV's ``task_updated_date`` column.

    Uses the max date among rows of tasks whose every job has finished
    review; falls back to the max over all rows when no task has.
    Raises :class:`Cveta2Error` when the column has no usable values.
    """
    all_dates = df["task_updated_date"].dropna().astype(str)
    all_dates = all_dates[all_dates != ""]
    if all_dates.empty:
        raise Cveta2Error(
            f"Ошибка: столбец task_updated_date в {path} пуст — "
            f"невозможно определить дату отсечки."
        )
    completed_mask = df["task_id"].isin(completed_task_ids(df))
    completed_dates = df.loc[completed_mask, "task_updated_date"].dropna().astype(str)
    completed_dates = completed_dates[completed_dates != ""]
    pool = completed_dates if not completed_dates.empty else all_dates
    return str(pool.max())
