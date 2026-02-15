"""Implementation of the ``cveta2 ignore`` command."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import questionary
from loguru import logger

from cveta2.config import (
    IgnoreConfig,
    load_ignore_config,
    require_interactive,
    save_ignore_config,
)
from cveta2.projects_cache import ProjectInfo, load_projects_cache

if TYPE_CHECKING:
    import argparse

_ACTION_ADD = "add"
_ACTION_REMOVE = "remove"
_ACTION_EXIT = "exit"


def run_ignore(args: argparse.Namespace) -> None:
    """Run the ``ignore`` command: add, remove, or interactive menu."""
    ignore_cfg = load_ignore_config()

    if args.project is not None:
        project_name = args.project.strip()
    else:
        project_name = _select_project(ignore_cfg)

    # Non-interactive path: --add / --remove flags
    if args.add:
        for task_id in args.add:
            ignore_cfg.add_task(project_name, task_id)
            logger.info(
                f"Задача {task_id} добавлена в ignore-список проекта {project_name!r}"
            )
        save_ignore_config(ignore_cfg)
        return

    if args.remove:
        for task_id in args.remove:
            removed = ignore_cfg.remove_task(project_name, task_id)
            if removed:
                logger.info(
                    f"Задача {task_id} удалена из ignore-списка "
                    f"проекта {project_name!r}"
                )
            else:
                logger.warning(
                    f"Задача {task_id} не найдена в ignore-списке "
                    f"проекта {project_name!r}"
                )
        save_ignore_config(ignore_cfg)
        return

    # Interactive mode
    _interactive_loop(ignore_cfg, project_name)


def _select_project(ignore_cfg: IgnoreConfig) -> str:
    """Interactive project selection from cache and existing ignore entries."""
    require_interactive("Pass --project / -p to specify the project name.")

    # Collect known project names from the projects cache and the ignore config
    cached_projects = load_projects_cache()
    known_names = _build_project_names(cached_projects, ignore_cfg)

    if not known_names:
        sys.exit(
            "Нет известных проектов. "
            "Укажите --project или запустите cveta2 fetch для заполнения кэша."
        )

    choices = [questionary.Choice(title=name, value=name) for name in known_names]
    answer: str | None = questionary.select(
        "Выберите проект:",
        choices=choices,
        use_shortcuts=False,
        use_indicator=True,
        use_search_filter=True,
        use_jk_keys=False,
    ).ask()

    if answer is None:
        sys.exit("Выбор отменён.")
    return answer


def _build_project_names(
    cached_projects: list[ProjectInfo],
    ignore_cfg: IgnoreConfig,
) -> list[str]:
    """Build a deduplicated sorted list of project names."""
    names: set[str] = set()
    for p in cached_projects:
        names.add(p.name)
    for name in ignore_cfg.projects:
        names.add(name)
    return sorted(names)


def _print_ignored_list(ignore_cfg: IgnoreConfig, project_name: str) -> None:
    """Display the current ignore list for *project_name*."""
    ignored = ignore_cfg.get_ignored_tasks(project_name)
    if not ignored:
        logger.info(f"Проект {project_name!r}: ignore-список пуст")
    else:
        logger.info(f"Проект {project_name!r}: игнорируемые задачи ({len(ignored)}):")
        for task_id in ignored:
            logger.info(f"  - task {task_id}")


def _interactive_loop(ignore_cfg: IgnoreConfig, project_name: str) -> None:
    """Run the interactive TUI loop for managing the ignore list."""
    changed = False

    while True:
        _print_ignored_list(ignore_cfg, project_name)

        ignored = ignore_cfg.get_ignored_tasks(project_name)
        choices = [
            questionary.Choice(
                title="Добавить задачи в ignore-список",
                value=_ACTION_ADD,
            ),
        ]
        if ignored:
            choices.append(
                questionary.Choice(
                    title="Убрать задачи из ignore-списка",
                    value=_ACTION_REMOVE,
                ),
            )
        choices.append(
            questionary.Choice(title="Готово", value=_ACTION_EXIT),
        )

        action = questionary.select(
            "Что сделать?",
            choices=choices,
            use_shortcuts=False,
            use_indicator=True,
        ).ask()

        if action is None or action == _ACTION_EXIT:
            break

        if action == _ACTION_ADD:
            _interactive_add(ignore_cfg, project_name)
            changed = True

        elif action == _ACTION_REMOVE:
            removed_any = _interactive_remove(ignore_cfg, project_name)
            if removed_any:
                changed = True

    if changed:
        save_ignore_config(ignore_cfg)


def _interactive_add(ignore_cfg: IgnoreConfig, project_name: str) -> None:
    """Prompt the user to enter task IDs to add."""
    raw = questionary.text(
        "Введите ID задач через пробел:",
    ).ask()
    if not raw:
        return

    for token in raw.split():
        cleaned = token.strip().rstrip(",")
        if not cleaned:
            continue
        try:
            task_id = int(cleaned)
        except ValueError:
            logger.warning(f"Пропущено: {cleaned!r} — не число")
            continue
        ignore_cfg.add_task(project_name, task_id)
        logger.info(f"Задача {task_id} добавлена")


def _interactive_remove(
    ignore_cfg: IgnoreConfig,
    project_name: str,
) -> bool:
    """Show a checkbox list of ignored tasks to remove. Returns True if any removed."""
    ignored = ignore_cfg.get_ignored_tasks(project_name)
    if not ignored:
        logger.info("Ignore-список пуст — нечего удалять.")
        return False

    choices = [questionary.Choice(title=f"task {tid}", value=tid) for tid in ignored]
    selected: list[int] | None = questionary.checkbox(
        "Выберите задачи для удаления из ignore-списка:",
        choices=choices,
    ).ask()

    if not selected:
        return False

    for task_id in selected:
        ignore_cfg.remove_task(project_name, task_id)
        logger.info(f"Задача {task_id} удалена")

    return True
