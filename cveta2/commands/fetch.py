"""Implementation of the ``cveta2 fetch`` and ``cveta2 fetch-task`` commands."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd
import questionary
from loguru import logger

from cveta2.client import CvatClient
from cveta2.commands._helpers import (
    load_config,
    require_host,
    resolve_project_and_cloud_storage,
    write_dataset_and_deleted,
    write_deleted_txt,
    write_df_csv,
)
from cveta2.commands._task_selector import select_tasks_tui
from cveta2.config import (
    is_interactive_disabled,
    load_ignore_config,
    load_image_cache_config,
    save_image_cache_config,
)
from cveta2.dataset_partition import PartitionResult, partition_annotations_df
from cveta2.exceptions import Cveta2Error

if TYPE_CHECKING:
    import argparse

    from cveta2.image_downloader import CloudStorageInfo
    from cveta2.models import ProjectAnnotations

# ------------------------------------------------------------------
# Public command entry points
# ------------------------------------------------------------------


def run_fetch(args: argparse.Namespace) -> None:
    """Run the ``fetch`` command (all project tasks)."""
    cfg = load_config()
    require_host(cfg)

    with CvatClient(cfg) as client:
        try:
            project_id, project_name, cs_info = resolve_project_and_cloud_storage(
                client, getattr(args, "project", None)
            )
        except Cveta2Error as e:
            sys.exit(str(e))

        ignore_set = _warn_ignored_tasks(project_name)

        try:
            result = client.fetch_annotations(
                project_id=project_id,
                completed_only=args.completed_only,
                ignore_task_ids=ignore_set,
                project_name=project_name,
            )
        except Cveta2Error as e:
            sys.exit(str(e))

        _download_images(args, project_id, project_name, client, result, cs_info)

    _write_output(args, result)


def run_fetch_task(args: argparse.Namespace) -> None:
    """Run the ``fetch-task`` command (selected task(s) only)."""
    cfg = load_config()
    require_host(cfg)

    with CvatClient(cfg) as client:
        try:
            project_id, project_name, cs_info = resolve_project_and_cloud_storage(
                client, getattr(args, "project", None)
            )
        except Cveta2Error as e:
            sys.exit(str(e))

        ignore_set = _warn_ignored_tasks(project_name)

        task_sel = _resolve_task_selector(args, client, project_id, ignore_set)

        try:
            result = client.fetch_annotations(
                project_id=project_id,
                completed_only=args.completed_only,
                ignore_task_ids=ignore_set,
                task_selector=task_sel,
                project_name=project_name,
            )
        except Cveta2Error as e:
            sys.exit(str(e))

        _download_images(args, project_id, project_name, client, result, cs_info)

    write_dataset_and_deleted(result, Path(args.output_dir))


# ------------------------------------------------------------------
# Shared helpers (project resolution, output, images)
# ------------------------------------------------------------------


def _download_images(  # noqa: PLR0913
    args: argparse.Namespace,
    project_id: int,
    project_name: str,
    client: CvatClient,
    result: ProjectAnnotations,
    project_cloud_storage: CloudStorageInfo | None = None,
) -> None:
    """Download images if requested (within the CvatClient context)."""
    images_dir = _resolve_images_dir(args, project_name)
    if images_dir is not None:
        stats = client.download_images(
            result,
            images_dir,
            project_id=project_id,
            project_cloud_storage=project_cloud_storage,
        )
        logger.info(
            f"Изображения: {stats.downloaded} загружено, "
            f"{stats.cached} из кэша, {stats.failed} ошибок"
        )


def _write_output(
    args: argparse.Namespace,
    result: ProjectAnnotations,
) -> None:
    """Partition annotations and write output files."""
    output_dir = _resolve_output_dir(Path(args.output_dir))

    rows = result.to_csv_rows()
    df = pd.DataFrame(rows)

    if args.raw:
        output_dir.mkdir(parents=True, exist_ok=True)
        write_df_csv(df, output_dir / "raw.csv", "Raw CSV")

    partition = partition_annotations_df(df, result.deleted_images)
    _write_partition_result(partition, output_dir)


def _resolve_output_dir(output_dir: Path) -> Path:
    """Resolve output directory, prompting on overwrite if interactive."""
    if not output_dir.exists():
        return output_dir
    if is_interactive_disabled():
        logger.info(
            f"Папка {output_dir} уже существует — перезапись (неинтерактивный режим)."
        )
        return output_dir
    answer = questionary.select(
        f"Папка {output_dir} уже существует. Что делать?",
        choices=[
            questionary.Choice(title="Перезаписать", value="overwrite"),
            questionary.Choice(title="Указать другой путь", value="change"),
            questionary.Choice(title="Отмена", value="cancel"),
        ],
        use_shortcuts=False,
        use_indicator=True,
    ).ask()
    if answer is None or answer == "cancel":
        sys.exit("Отменено.")
    if answer == "change":
        new_path = input("Новый путь: ").strip()
        if not new_path:
            sys.exit("Путь не указан.")
        return Path(new_path)
    return output_dir


def _write_partition_result(
    partition: PartitionResult,
    output_dir: Path,
) -> None:
    """Write all partition DataFrames and deleted.txt into *output_dir*."""
    output_dir.mkdir(parents=True, exist_ok=True)
    write_df_csv(partition.dataset, output_dir / "dataset.csv", "Dataset CSV")
    write_df_csv(partition.obsolete, output_dir / "obsolete.csv", "Obsolete CSV")
    write_df_csv(
        partition.in_progress,
        output_dir / "in_progress.csv",
        "In-progress CSV",
    )
    write_deleted_txt(partition.deleted_names, output_dir / "deleted.txt")


def _resolve_task_selector(
    args: argparse.Namespace,
    client: CvatClient,
    project_id: int,
    ignore_task_ids: set[int] | None,
) -> list[int | str]:
    """Turn ``args.task`` into a task selector list.

    Returns a list of task IDs/names.
    When ``-t`` is omitted or passed without a value, launches
    interactive TUI.
    """
    raw: list[str] | None = args.task
    if raw is not None:
        explicit: list[int | str] = [v.strip() for v in raw if v.strip()]
        if explicit:
            return explicit
    selected = select_tasks_tui(client, project_id, exclude_ids=ignore_task_ids)
    return [t.id for t in selected]


def _warn_ignored_tasks(project_name: str) -> set[int] | None:
    """Load ignore config, warn about ignored tasks, return their IDs as a set."""
    ignore_cfg = load_ignore_config()
    ignored_ids = ignore_cfg.get_ignored_tasks(project_name)
    if not ignored_ids:
        return None
    return set(ignored_ids)


def _resolve_images_dir(
    args: argparse.Namespace,
    project_name: str,
) -> Path | None:
    """Resolve image cache directory for the given project.

    Returns None if ``--no-images`` or download should be skipped.
    """
    if args.no_images:
        return None

    # --images-dir takes top priority
    if args.images_dir:
        return Path(args.images_dir).resolve()

    # Look up per-project mapping in config
    ic_cfg = load_image_cache_config()
    cached_dir = ic_cfg.get_cache_dir(project_name)
    if cached_dir is not None:
        return cached_dir

    # Not configured — interactive prompt or error
    if is_interactive_disabled():
        sys.exit(
            f"Ошибка: путь кэширования изображений для проекта "
            f"{project_name!r} не настроен.\n"
            f"Укажите --images-dir, --no-images или добавьте "
            f"image_cache.{project_name} в конфигурацию."
        )

    path_str = input(
        f"Укажите путь для кэширования изображений проекта {project_name!r}: "
    ).strip()
    if not path_str:
        logger.warning("Путь не указан — загрузка изображений пропущена.")
        return None

    new_path = Path(path_str).resolve()
    ic_cfg.set_cache_dir(project_name, new_path)
    save_image_cache_config(ic_cfg)
    return new_path
