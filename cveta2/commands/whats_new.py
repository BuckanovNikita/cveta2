"""Implementation of the ``cveta2 whats-new`` command."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from cveta2.commands._bootstrap import open_client
from cveta2.commands._helpers import (
    read_dataset_csv,
    resolve_project_or_exit,
)

if TYPE_CHECKING:
    import argparse

    import pandas as pd

_REQUIRED_COLUMNS = {"task_updated_date", "task_status", "task_id"}


def run_whats_new(args: argparse.Namespace) -> None:
    """Run the ``whats-new`` command: list tasks completed after a fetched CSV."""
    dataset_path = Path(args.dataset)
    df = read_dataset_csv(dataset_path, _REQUIRED_COLUMNS)
    cutoff = _compute_cutoff(df, dataset_path)
    known_task_ids = {int(v) for v in df["task_id"].dropna()}

    with open_client() as client:
        project_id, project_name = resolve_project_or_exit(args.project, client)
        tasks = client.list_tasks_completed_after(project_id, cutoff)

    logger.info(f"Дата отсечки (из {dataset_path}): {cutoff}")
    if not tasks:
        logger.info(
            f"Новых завершённых задач в проекте {project_name!r} "
            f"после {cutoff} не найдено"
        )
        return

    logger.info(
        f"Проект {project_name!r}: {len(tasks)} задач(а) завершено после {cutoff}:"
    )
    for task in tasks:
        marker = " (обновлена)" if task.id in known_task_ids else ""
        logger.info(f"id={task.id} {task.name} (updated {task.updated_date}){marker}")


def _compute_cutoff(df: pd.DataFrame, path: Path) -> str:
    """Compute the cutoff date from the CSV's ``task_updated_date`` column.

    Uses the max date among rows with ``task_status == "completed"``;
    falls back to the max over all rows when no completed rows exist.
    Exits with an error when the column has no usable values.
    """
    all_dates = df["task_updated_date"].dropna().astype(str)
    all_dates = all_dates[all_dates != ""]
    if all_dates.empty:
        sys.exit(
            f"Ошибка: столбец task_updated_date в {path} пуст — "
            f"невозможно определить дату отсечки."
        )
    completed_mask = df["task_status"] == "completed"
    completed_dates = df.loc[completed_mask, "task_updated_date"].dropna().astype(str)
    completed_dates = completed_dates[completed_dates != ""]
    pool = completed_dates if not completed_dates.empty else all_dates
    return str(pool.max())
