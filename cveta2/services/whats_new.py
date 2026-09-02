"""Cutoff computation for the whats-new workflow."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pandas as pd
from loguru import logger

from cveta2.dataset_partition import completed_task_ids
from cveta2.exceptions import Cveta2Error
from cveta2.services.output import CSV_READ_OPTIONS

if TYPE_CHECKING:
    from pathlib import Path

REQUIRED_COLUMNS = {"job_stage", "job_state", "task_id"}

SIBLING_CSV_NAMES = ("obsolete.csv", "deleted.csv")
"""The CSVs ``fetch`` writes beside ``dataset.csv`` whose tasks are done for good.

A task superseded by a newer one keeps no row in ``dataset.csv``; without
reading these too, every such task would look unknown and be reported as
new on every run.  ``in_progress.csv`` is deliberately left out: a task
listed there that has since completed is exactly what whats-new reports.
"""


@dataclass(frozen=True)
class WhatsNewBaseline:
    """What a fetched dataset CSV already contains: cutoff id + task ids."""

    cutoff: int
    known_task_ids: set[int]


def compute_baseline(df: pd.DataFrame, path: Path) -> WhatsNewBaseline:
    """Build the comparison baseline from a fetched dataset CSV.

    ``known_task_ids`` spans *df* plus the finished-for-good CSVs ``fetch``
    wrote next to *path* (:data:`SIBLING_CSV_NAMES`), so a task that was
    still in progress at fetch time can be told apart from one the dataset
    already accounts for.
    """
    return WhatsNewBaseline(
        cutoff=compute_cutoff(df, path),
        known_task_ids=_known_task_ids(df, path),
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
        raise Cveta2Error(
            f"Ошибка: столбец task_id в {path} пуст — "
            f"невозможно определить задачу отсечки."
        )
    completed_ids = _task_ids(df[df["task_id"].isin(completed_task_ids(df))])
    return max(completed_ids or all_ids)


def _task_ids(df: pd.DataFrame) -> set[int]:
    """Return the usable integer ``task_id`` values of *df*."""
    return {int(v) for v in pd.to_numeric(df["task_id"], errors="coerce").dropna()}


def _known_task_ids(df: pd.DataFrame, path: Path) -> set[int]:
    """Collect task ids from *df* and from the CSVs fetch wrote beside it.

    A sibling that is missing or unreadable simply contributes nothing:
    the baseline then knows fewer tasks and reports a few of them again,
    which is the harmless direction to be wrong in.
    """
    known = _task_ids(df)
    for name in SIBLING_CSV_NAMES:
        sibling = path.parent / name
        if not sibling.is_file():
            continue
        try:
            sibling_df = pd.read_csv(sibling, **CSV_READ_OPTIONS)
        except (pd.errors.ParserError, pd.errors.EmptyDataError, OSError) as e:
            logger.info(f"{sibling} не прочитан ({e}) — его задачи считаются новыми")
            continue
        if "task_id" in sibling_df.columns:
            known |= _task_ids(sibling_df)
    return known
