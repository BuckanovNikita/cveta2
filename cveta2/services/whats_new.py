"""Cutoff computation for the whats-new workflow."""

from __future__ import annotations

from typing import TYPE_CHECKING

from cveta2.exceptions import Cveta2Error

if TYPE_CHECKING:
    from pathlib import Path

    import pandas as pd

REQUIRED_COLUMNS = {"task_updated_date", "task_status", "task_id"}


def compute_cutoff(df: pd.DataFrame, path: Path) -> str:
    """Compute the cutoff date from the CSV's ``task_updated_date`` column.

    Uses the max date among rows with ``task_status == "completed"``;
    falls back to the max over all rows when no completed rows exist.
    Raises :class:`Cveta2Error` when the column has no usable values.
    """
    all_dates = df["task_updated_date"].dropna().astype(str)
    all_dates = all_dates[all_dates != ""]
    if all_dates.empty:
        raise Cveta2Error(
            f"Ошибка: столбец task_updated_date в {path} пуст — "
            f"невозможно определить дату отсечки."
        )
    completed_mask = df["task_status"] == "completed"
    completed_dates = df.loc[completed_mask, "task_updated_date"].dropna().astype(str)
    completed_dates = completed_dates[completed_dates != ""]
    pool = completed_dates if not completed_dates.empty else all_dates
    return str(pool.max())
