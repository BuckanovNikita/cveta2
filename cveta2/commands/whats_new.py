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
from cveta2.exceptions import Cveta2Error
from cveta2.services.whats_new import REQUIRED_COLUMNS, compute_cutoff

if TYPE_CHECKING:
    import argparse


def run_whats_new(args: argparse.Namespace) -> None:
    """Run the ``whats-new`` command: list tasks completed after a fetched CSV."""
    dataset_path = Path(args.dataset)
    df = read_dataset_csv(dataset_path, REQUIRED_COLUMNS)
    try:
        cutoff = compute_cutoff(df, dataset_path)
    except Cveta2Error as e:
        sys.exit(str(e))
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
