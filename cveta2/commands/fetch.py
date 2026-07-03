"""Implementation of the ``cveta2 fetch`` and ``cveta2 fetch-task`` commands."""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd
import questionary
from loguru import logger
from tqdm import tqdm

from cveta2.client import CvatClient, FetchContext
from cveta2.commands._helpers import (
    require_host,
    resolve_project_and_cloud_storage,
    write_dataset_and_deleted,
)
from cveta2.commands._task_selector import select_tasks_tui
from cveta2.config import (
    CvatConfig,
    is_interactive_disabled,
    load_ignore_config,
    load_image_cache_config,
    save_image_cache_config,
)
from cveta2.dataset_partition import PartitionResult, partition_annotations_df
from cveta2.exceptions import Cveta2Error
from cveta2.models import CSV_COLUMNS, TaskAnnotations
from cveta2.s3_utils import build_s3_key

if TYPE_CHECKING:
    import argparse

    from cveta2.image_downloader import CloudStorageInfo
    from cveta2.models import ProjectAnnotations

# ------------------------------------------------------------------
# Public command entry points
# ------------------------------------------------------------------


def run_fetch(args: argparse.Namespace) -> None:
    """Run the ``fetch`` command (all project tasks)."""
    output_dir = _resolve_output_dir(Path(args.output_dir))
    result, project_name = _fetch_common(args, output_dir)

    _write_output(args, result, output_dir)

    from cveta2._clearml import maybe_publish_clearml  # noqa: PLC0415

    maybe_publish_clearml(project_name, output_dir)


def run_fetch_task(args: argparse.Namespace) -> None:
    """Run the ``fetch-task`` command (selected task(s) only)."""
    output_dir = Path(args.output_dir)
    result, _ = _fetch_common(args, output_dir)
    write_dataset_and_deleted(result, output_dir)


def _fetch_common(
    args: argparse.Namespace,
    output_dir: Path,
) -> tuple[ProjectAnnotations, str]:
    """Shared fetch logic for ``run_fetch`` and ``run_fetch_task``.

    Returns ``(result, project_name)``.
    """
    cfg = CvatConfig.load()
    require_host(cfg)

    with CvatClient(cfg) as client:
        try:
            project_id, project_name, cs_info = resolve_project_and_cloud_storage(
                client, getattr(args, "project", None)
            )
        except Cveta2Error as e:
            sys.exit(str(e))

        ignore_set, silent_set = _warn_ignored_tasks(project_name)

        task_selector: list[int | str] | None = None
        if hasattr(args, "task"):
            task_selector = _resolve_task_selector(args, client, project_id, ignore_set)

        try:
            ctx = client.prepare_fetch(
                project_id,
                completed_only=args.completed_only,
                ignore_task_ids=ignore_set,
                silent_task_ids=silent_set,
                task_selector=task_selector,
                project_name=project_name,
            )
        except Cveta2Error as e:
            sys.exit(str(e))

        result = _fetch_and_save_tasks(
            client,
            ctx,
            output_dir,
            save_tasks=args.save_tasks,
        )

        images_dir = _download_images(
            _DownloadImagesParams(
                args, project_id, project_name, client, result, cs_info
            )
        )
        _populate_paths(result, cs_info, images_dir)

    return result, project_name


# ------------------------------------------------------------------
# Shared helpers (project resolution, output, images)
# ------------------------------------------------------------------


@dataclass(frozen=True)
class _DownloadImagesParams:
    """Arguments for _download_images (avoids PLR0913)."""

    args: argparse.Namespace
    project_id: int
    project_name: str
    client: CvatClient
    result: ProjectAnnotations
    project_cloud_storage: CloudStorageInfo | None = None


def _populate_paths(
    result: ProjectAnnotations,
    cs_info: CloudStorageInfo | None,
    images_dir: Path | None,
) -> None:
    """Set ``s3_image_path`` and ``image_path`` on all annotation/deleted records."""
    for record in (*result.annotations, *result.deleted_images):
        if cs_info is not None:
            record.s3_image_path = build_s3_key(cs_info.prefix, record.image_name)
        if images_dir is not None:
            local = images_dir / record.image_name
            if local.exists():
                record.image_path = str(local.resolve())


def _fetch_and_save_tasks(
    client: CvatClient,
    ctx: FetchContext,
    output_dir: Path,
    *,
    save_tasks: bool = False,
) -> ProjectAnnotations:
    """Fetch tasks one by one, saving per-task CSVs into ``output_dir/.tasks/``.

    When *save_tasks* is False (default), the ``.tasks/`` directory is
    removed after merging.

    Returns the merged :class:`ProjectAnnotations` from all fetched tasks.
    """
    if not ctx.tasks:
        logger.warning("No tasks in this project.")
        return TaskAnnotations.merge([])

    tasks_dir = output_dir / ".tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)

    task_results: list[TaskAnnotations] = []
    with client.open_api() as api:
        for task in tqdm(ctx.tasks, desc="Processing tasks", unit="task", leave=False):
            task_result = client.fetch_one_task(api, task, ctx)
            if task_result is None:
                continue

            rows = task_result.to_csv_rows()
            if rows:
                df = pd.DataFrame(rows)
                task_csv = tasks_dir / f"task_{task.id}.csv"
                df.to_csv(task_csv, index=False, encoding="utf-8")
                logger.trace(
                    f"Task {task.name!r} (id={task.id}): {len(rows)} rows → {task_csv}"
                )

            task_results.append(task_result)

    if not save_tasks:
        shutil.rmtree(tasks_dir, ignore_errors=True)

    return TaskAnnotations.merge(task_results)


def _download_images(params: _DownloadImagesParams) -> Path | None:
    """Download images if requested (within the CvatClient context).

    Returns the resolved images directory, or ``None`` if download was skipped.
    """
    images_dir = _resolve_images_dir(params.args, params.project_name)
    if images_dir is not None:
        stats = params.client.download_images(
            params.result,
            images_dir,
            project_id=params.project_id,
            project_cloud_storage=params.project_cloud_storage,
        )
        logger.info(
            f"Изображения: {stats.downloaded} загружено, "
            f"{stats.cached} из кэша, {stats.failed} ошибок"
        )
    return images_dir


def _write_output(
    args: argparse.Namespace,
    result: ProjectAnnotations,
    output_dir: Path,
) -> None:
    """Partition annotations and write output files."""
    rows = result.to_csv_rows()
    df = pd.DataFrame(rows)

    if args.raw:
        deleted_rows = [d.to_csv_row() for d in result.deleted_images]
        raw_df = pd.DataFrame(rows + deleted_rows)
        output_dir.mkdir(parents=True, exist_ok=True)
        raw_path = output_dir / "raw.csv"
        raw_df.to_csv(raw_path, index=False, encoding="utf-8")
        logger.info(f"Raw CSV saved to {raw_path} ({len(raw_df)} rows)")

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
    """Write all partition DataFrames and deleted.csv into *output_dir*."""
    output_dir.mkdir(parents=True, exist_ok=True)

    for df, name, label in [
        (partition.dataset, "dataset.csv", "Dataset CSV"),
        (partition.obsolete, "obsolete.csv", "Obsolete CSV"),
        (partition.in_progress, "in_progress.csv", "In-progress CSV"),
    ]:
        path = output_dir / name
        df.to_csv(path, index=False, encoding="utf-8")
        logger.info(f"{label} saved to {path} ({len(df)} rows)")

    deleted_rows = [img.to_csv_row() for img in partition.deleted_images]
    deleted_df = (
        pd.DataFrame(deleted_rows, columns=list(CSV_COLUMNS))
        if deleted_rows
        else pd.DataFrame(columns=list(CSV_COLUMNS))
    )
    deleted_path = output_dir / "deleted.csv"
    deleted_df.to_csv(deleted_path, index=False, encoding="utf-8")
    logger.info(f"Deleted CSV saved to {deleted_path} ({len(deleted_df)} rows)")


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


def _warn_ignored_tasks(
    project_name: str,
) -> tuple[set[int] | None, set[int] | None]:
    """Load ignore config, return ``(ignore_set, silent_set)``.

    *ignore_set* contains all ignored task IDs (or None if empty).
    *silent_set* contains IDs of tasks marked ``silent=True``.
    """
    ignore_cfg = load_ignore_config()
    ignored_ids = ignore_cfg.get_ignored_tasks(project_name)
    if not ignored_ids:
        return None, None
    silent_ids = ignore_cfg.get_silent_task_ids(project_name)
    return set(ignored_ids), (silent_ids or None)


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
