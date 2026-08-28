"""Implementation of the ``cveta2 whats-new`` command."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from cveta2.commands._bootstrap import open_client
from cveta2.commands._helpers import (
    echo_if_prompted,
    project_cli_spec,
    resolve_project,
)
from cveta2.services.output import read_dataset_csv
from cveta2.services.whats_new import REQUIRED_COLUMNS, compute_baseline

if TYPE_CHECKING:
    import argparse


def run_whats_new(args: argparse.Namespace) -> None:
    """Run the ``whats-new`` command: list tasks completed after a fetched CSV."""
    dataset_path = Path(args.dataset)
    df = read_dataset_csv(dataset_path, REQUIRED_COLUMNS)
    baseline = compute_baseline(df, dataset_path)

    prompted = not args.project
    with open_client() as client:
        project_id, project_name = resolve_project(client, args.project)
        echo_if_prompted(
            "whats-new",
            {"-p": project_cli_spec(client, project_name), "-d": args.dataset},
            prompted=prompted,
        )
        tasks = client.list_new_completed_tasks(
            project_id, baseline.cutoff, baseline.known_task_ids
        )

    logger.info(f"Задача отсечки (из {dataset_path}): task_id={baseline.cutoff}")
    if not tasks:
        logger.info(
            f"Новых завершённых задач в проекте {project_name!r} "
            f"после task_id={baseline.cutoff} не найдено"
        )
        return

    logger.info(
        f"Проект {project_name!r}: {len(tasks)} задач(а) завершено "
        f"после task_id={baseline.cutoff}:"
    )
    for task in tasks:
        logger.info(f"id={task.id} {task.name} (updated {task.updated_date})")
