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
    write_deleted_txt,
    write_df_csv,
)
from cveta2.config import (
    is_interactive_disabled,
    load_ignore_config,
    load_image_cache_config,
    require_interactive,
    save_image_cache_config,
)
from cveta2.dataset_partition import PartitionResult, partition_annotations_df
from cveta2.exceptions import Cveta2Error
from cveta2.projects_cache import ProjectInfo, load_projects_cache, save_projects_cache

if TYPE_CHECKING:
    import argparse

    from cveta2._client.dtos import RawTask
    from cveta2.models import ProjectAnnotations

_RESCAN_VALUE = "__rescan__"


# ------------------------------------------------------------------
# Public command entry points
# ------------------------------------------------------------------


def run_fetch(args: argparse.Namespace) -> None:
    """Run the ``fetch`` command (all project tasks)."""
    cfg = load_config()
    require_host(cfg)

    with CvatClient(cfg) as client:
        project_id, project_name = _resolve_project(args, client)
        ignore_set = _warn_ignored_tasks(project_name)

        try:
            result = client.fetch_annotations(
                project_id=project_id,
                completed_only=args.completed_only,
                ignore_task_ids=ignore_set,
            )
        except Cveta2Error as e:
            sys.exit(str(e))

        _download_images(args, project_name, client, result)

    _write_output(args, result)


def run_fetch_task(args: argparse.Namespace) -> None:
    """Run the ``fetch-task`` command (selected task(s) only)."""
    cfg = load_config()
    require_host(cfg)

    with CvatClient(cfg) as client:
        project_id, project_name = _resolve_project(args, client)
        ignore_set = _warn_ignored_tasks(project_name)

        task_sel = _resolve_task_selector(args, client, project_id, ignore_set)

        try:
            result = client.fetch_annotations(
                project_id=project_id,
                completed_only=args.completed_only,
                ignore_task_ids=ignore_set,
                task_selector=task_sel,
            )
        except Cveta2Error as e:
            sys.exit(str(e))

        _download_images(args, project_name, client, result)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = result.to_csv_rows()
    df = pd.DataFrame(rows)
    write_df_csv(df, output_dir / "dataset.csv", "Dataset CSV")
    deleted_names = [img.image_name for img in result.deleted_images]
    write_deleted_txt(deleted_names, output_dir / "deleted.txt")


# ------------------------------------------------------------------
# Shared helpers (project resolution, output, images)
# ------------------------------------------------------------------


def _resolve_project(
    args: argparse.Namespace,
    client: CvatClient,
) -> tuple[int, str]:
    """Resolve project ID and human-readable name from CLI args.

    Returns ``(project_id, project_name)``.
    """
    project_name: str | None = None

    if args.project is not None:
        cached = load_projects_cache()
        try:
            project_id = client.resolve_project_id(args.project.strip(), cached=cached)
        except Cveta2Error as e:
            sys.exit(str(e))
        project_name = args.project.strip()
    else:
        project_id = _select_project_tui(client)

    if project_name is None or project_name.isdigit():
        for p in load_projects_cache():
            if p.id == project_id:
                project_name = p.name
                break

    if project_name is None:
        project_name = str(project_id)

    return project_id, project_name


def _download_images(
    args: argparse.Namespace,
    project_name: str,
    client: CvatClient,
    result: ProjectAnnotations,
) -> None:
    """Download images if requested (within the CvatClient context)."""
    images_dir = _resolve_images_dir(args, project_name)
    if images_dir is not None:
        stats = client.download_images(result, images_dir)
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


def _build_project_choices(
    projects: list[ProjectInfo],
) -> list[questionary.Choice]:
    """Build questionary choices: project list + rescan option last."""
    choices: list[questionary.Choice] = [
        questionary.Choice(title=f"{p.name} (id={p.id})", value=p.id) for p in projects
    ]
    choices.append(
        questionary.Choice(
            title="↻ Обновить список проектов с CVAT",
            value=_RESCAN_VALUE,
        ),
    )
    return choices


def _select_project_tui(client: CvatClient) -> int:
    """Interactive project selection via TUI list.

    Arrow keys to pick, with an option to rescan CVAT.
    """
    require_interactive("Pass --project / -p to specify the project ID or name.")
    projects = load_projects_cache()
    while True:
        if not projects:
            logger.info("Кэш проектов пуст. Загружаю список с CVAT...")
            projects = client.list_projects()
            save_projects_cache(projects)
            if not projects:
                sys.exit("Нет доступных проектов.")
        choices = _build_project_choices(projects)
        answer = questionary.select(
            "Выберите проект:",
            choices=choices,
            use_shortcuts=False,
            use_indicator=True,
            use_search_filter=True,
            use_jk_keys=False,
        ).ask()
        if answer is None:
            sys.exit("Выбор отменён.")
        if answer == _RESCAN_VALUE:
            projects = client.list_projects()
            save_projects_cache(projects)
            logger.info(f"Загружено проектов: {len(projects)}")
            continue
        return int(answer)


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
    return _select_tasks_tui(client, project_id, ignore_task_ids)


def _select_tasks_tui(
    client: CvatClient,
    project_id: int,
    ignore_task_ids: set[int] | None,
) -> list[int | str]:
    """Interactive multi-task selection via TUI checkbox."""
    require_interactive(
        "Pass task ID(s) or name(s) with --task / -t to specify task(s)."
    )
    tasks = client.list_project_tasks(project_id)
    if ignore_task_ids:
        tasks = [t for t in tasks if t.id not in ignore_task_ids]
    if not tasks:
        sys.exit("Нет доступных задач в этом проекте.")
    choices = _build_task_choices(tasks)
    answer = questionary.checkbox(
        "Выберите задачу (задачи):",
        choices=choices,
        use_jk_keys=False,
        use_search_filter=True,
    ).ask()
    if answer is None:
        sys.exit("Выбор отменён.")
    selected: list[int | str] = [int(v) for v in answer]
    if not selected:
        sys.exit("Задачи не выбраны.")
    return selected


def _build_task_choices(
    tasks: list[RawTask],
) -> list[questionary.Choice]:
    """Build questionary choices from a task list."""
    return [
        questionary.Choice(
            title=f"{t.name} (id={t.id}, {t.status})",
            value=t.id,
        )
        for t in tasks
    ]


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
