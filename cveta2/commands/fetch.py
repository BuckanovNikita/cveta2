"""CLI adapters for ``cveta2 fetch`` and ``cveta2 fetch-task``.

Only argument mapping, interactive prompts and ``sys.exit`` UX live here;
the pipeline itself is :mod:`cveta2.services.fetch`.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from cveta2.commands import interactive
from cveta2.commands._bootstrap import open_client
from cveta2.commands._helpers import resolve_project_and_cloud_storage
from cveta2.commands.interactive import select_tasks
from cveta2.config import (
    is_interactive_disabled,
    load_image_cache_config,
    save_image_cache_config,
)
from cveta2.exceptions import Cveta2Error
from cveta2.services.fetch import (
    FetchOptions,
    fetch_project,
    fetch_selected_tasks,
    load_ignore_sets,
)

if TYPE_CHECKING:
    import argparse

    from cveta2.client import CvatClient
    from cveta2.image_downloader import CloudStorageInfo


def run_fetch(args: argparse.Namespace) -> None:
    """Run the ``fetch`` command (all project tasks)."""
    output_dir = _resolve_output_dir(Path(args.output_dir))
    with open_client() as client:
        project_id, project_name, cs_info = _resolve_project_or_exit(client, args)
        options = _build_fetch_options(args, client, project_id, project_name)
        try:
            fetch_project(
                client, project_id, project_name, output_dir, cs_info, options
            )
        except Cveta2Error as e:
            sys.exit(str(e))


def run_fetch_task(args: argparse.Namespace) -> None:
    """Run the ``fetch-task`` command (selected task(s) only)."""
    output_dir = Path(args.output_dir)
    with open_client() as client:
        project_id, project_name, cs_info = _resolve_project_or_exit(client, args)
        options = _build_fetch_options(args, client, project_id, project_name)
        try:
            fetch_selected_tasks(
                client, project_id, project_name, output_dir, cs_info, options
            )
        except Cveta2Error as e:
            sys.exit(str(e))


def _resolve_project_or_exit(
    client: CvatClient,
    args: argparse.Namespace,
) -> tuple[int, str, CloudStorageInfo | None]:
    """Resolve project id/name and cloud storage; exit with message on failure."""
    try:
        return resolve_project_and_cloud_storage(client, getattr(args, "project", None))
    except Cveta2Error as e:
        sys.exit(str(e))


def _build_fetch_options(
    args: argparse.Namespace,
    client: CvatClient,
    project_id: int,
    project_name: str,
) -> FetchOptions:
    """Resolve interactive inputs and map CLI args onto FetchOptions."""
    ignore_set, silent_set = load_ignore_sets(project_name)

    task_selector: list[int | str] | None = None
    if hasattr(args, "task"):
        task_selector = _resolve_task_selector(args, client, project_id, ignore_set)

    return FetchOptions(
        completed_only=args.completed_only,
        task_selector=task_selector,
        ignore_task_ids=ignore_set,
        silent_task_ids=silent_set,
        use_cache=not args.no_cache,
        force=args.force,
        save_tasks=args.save_tasks,
        images_dir=_resolve_images_dir(args, project_name),
        raw=getattr(args, "raw", False),
    )


def _resolve_output_dir(output_dir: Path) -> Path:
    """Resolve output directory, prompting on overwrite if interactive."""
    if not output_dir.exists():
        return output_dir
    if is_interactive_disabled():
        logger.info(
            f"Папка {output_dir} уже существует — перезапись (неинтерактивный режим)."
        )
        return output_dir
    answer = interactive.select_one(
        f"Папка {output_dir} уже существует. Что делать?",
        [
            interactive.Choice(title="Перезаписать", value="overwrite"),
            interactive.Choice(title="Указать другой путь", value="change"),
            interactive.Choice(title="Отмена", value="cancel"),
        ],
        hint="Pass --output / -o to specify the output directory.",
    )
    if answer == "cancel":
        sys.exit("Отменено.")
    if answer == "change":
        new_path = interactive.text(
            "Новый путь: ",
            hint="Pass --output / -o to specify the output directory.",
            allow_empty=False,
            empty_message="Путь не указан.",
        )
        return Path(new_path)  # type: ignore[arg-type]
    return output_dir


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
    selected = select_tasks(client, project_id, exclude_ids=ignore_task_ids)
    return [t.id for t in selected]


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

    new_path = interactive.path(
        f"Укажите путь для кэширования изображений проекта {project_name!r}: ",
        hint=(
            f"Укажите --images-dir, --no-images или добавьте "
            f"image_cache.{project_name} в конфигурацию."
        ),
    )
    if new_path is None:
        logger.warning("Путь не указан — загрузка изображений пропущена.")
        return None

    ic_cfg.set_cache_dir(project_name, new_path)
    save_image_cache_config(ic_cfg)
    return new_path
