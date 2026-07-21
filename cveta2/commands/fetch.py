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
from cveta2.commands._helpers import echo_cli_command, resolve_project_and_cloud_storage
from cveta2.commands.interactive import select_tasks
from cveta2.config import (
    CacheConfig,
    ImageCacheConfig,
    cache_dir_for_project,
    is_interactive_disabled,
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


def run_fetch(args: argparse.Namespace) -> None:
    """Run the ``fetch`` command (all project tasks)."""
    output_dir = _resolve_output_dir(Path(args.output_dir))
    prompted = not args.project or output_dir != Path(args.output_dir)
    with open_client() as client:
        project_id, project_name, cs_info = resolve_project_and_cloud_storage(
            client, args.project
        )
        options = _build_project_fetch_options(args, project_name)
        if prompted:
            echo_cli_command(
                "fetch",
                {
                    "-p": project_name,
                    "-o": str(output_dir),
                    "--raw": options.raw,
                    "--no-clearml": args.no_clearml,
                }
                | _common_fetch_echo_args(args),
            )
        fetch_project(client, project_id, project_name, output_dir, cs_info, options)


def run_fetch_task(args: argparse.Namespace) -> None:
    """Run the ``fetch-task`` command (selected task(s) only)."""
    output_dir = Path(args.output_dir)
    tasks_prompted = not args.task or not any(v.strip() for v in args.task)
    prompted = not args.project or tasks_prompted
    with open_client() as client:
        project_id, project_name, cs_info = resolve_project_and_cloud_storage(
            client, args.project
        )
        options = _build_task_fetch_options(args, client, project_id, project_name)
        if prompted:
            echo_cli_command(
                "fetch-task",
                {
                    "-p": project_name,
                    "-t": options.task_selector,
                    "-o": str(output_dir),
                }
                | _common_fetch_echo_args(args),
            )
        fetch_selected_tasks(
            client, project_id, project_name, output_dir, cs_info, options
        )


def _common_fetch_echo_args(args: argparse.Namespace) -> dict[str, object]:
    """Map the shared fetch/fetch-task flags onto echo_cli_command pairs."""
    return {
        "--completed-only": args.completed_only,
        "--no-images": args.no_images,
        "--images-dir": args.images_dir,
        "--save-tasks": args.save_tasks,
        "--no-cache": args.no_cache,
        "--force": args.force,
    }


def _build_project_fetch_options(
    args: argparse.Namespace,
    project_name: str,
) -> FetchOptions:
    """Map ``fetch`` CLI args onto FetchOptions (whole-project run)."""
    ignore_set, silent_set = load_ignore_sets(project_name)
    return FetchOptions(
        completed_only=args.completed_only,
        ignore_task_ids=ignore_set,
        silent_task_ids=silent_set,
        use_cache=not args.no_cache,
        force=args.force,
        save_tasks=args.save_tasks,
        images_dir=_resolve_images_dir(args, project_name),
        raw=args.raw,
        publish_clearml=not args.no_clearml,
    )


def _build_task_fetch_options(
    args: argparse.Namespace,
    client: CvatClient,
    project_id: int,
    project_name: str,
) -> FetchOptions:
    """Resolve the task selector and map ``fetch-task`` CLI args onto FetchOptions."""
    ignore_set, silent_set = load_ignore_sets(project_name)
    return FetchOptions(
        completed_only=args.completed_only,
        task_selector=_resolve_task_selector(args, client, project_id, ignore_set),
        ignore_task_ids=ignore_set,
        silent_task_ids=silent_set,
        use_cache=not args.no_cache,
        force=args.force,
        save_tasks=args.save_tasks,
        images_dir=_resolve_images_dir(args, project_name),
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
            history_key="output-dir",
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
    ic_cfg = ImageCacheConfig.load()
    cached_dir = ic_cfg.get_cache_dir(project_name)
    if cached_dir is not None:
        return cached_dir

    images_root = CacheConfig.load().for_project(project_name).images_root
    if images_root is not None:
        return cache_dir_for_project(images_root, project_name)

    # Not configured — interactive prompt or error
    if is_interactive_disabled():
        raise Cveta2Error(
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
        history_key="image-cache-dir",
    )
    if new_path is None:
        logger.warning("Путь не указан — загрузка изображений пропущена.")
        return None

    ic_cfg.set_cache_dir(project_name, new_path)
    ic_cfg.save()
    return new_path
