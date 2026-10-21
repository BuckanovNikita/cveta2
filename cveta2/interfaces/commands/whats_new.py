"""Implementation of the ``cveta2 whats-new`` command."""

from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from cveta2.composition.conversion import compute_baseline
from cveta2.composition.files import read_dataset_csv
from cveta2.domain.baseline import REQUIRED_COLUMNS
from cveta2.interfaces.commands._bootstrap import open_client
from cveta2.interfaces.commands._helpers import (
    echo_if_prompted,
    project_cli_spec,
    resolve_project,
)

if TYPE_CHECKING:
    import argparse


from cveta2.interfaces.commands._parsers import add_project_arg


def configure_whats_new(parser: "argparse.ArgumentParser") -> None:
    """Declare the ``whats-new`` command arguments."""
    add_project_arg(parser)
    parser.add_argument(
        "--dataset",
        "-d",
        required=True,
        help="Path to dataset.csv produced by the fetch command.",
    )


def run_whats_new(args: "argparse.Namespace") -> None:
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
