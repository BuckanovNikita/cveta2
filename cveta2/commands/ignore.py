"""Implementation of the ``cveta2 ignore`` command."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import questionary
from loguru import logger

from cveta2.client import CvatClient
from cveta2.commands._helpers import (
    load_config,
    require_host,
    resolve_project_from_args,
)
from cveta2.commands._task_selector import build_task_choices
from cveta2.config import (
    IgnoreConfig,
    IgnoredTask,
    load_ignore_config,
    require_interactive,
    save_ignore_config,
)
from cveta2.exceptions import Cveta2Error
from cveta2.projects_cache import load_projects_cache

if TYPE_CHECKING:
    import argparse

    from cveta2.models import ProjectInfo, TaskInfo

_ACTION_ADD = "add"
_ACTION_REMOVE = "remove"
_ACTION_EXIT = "exit"


def run_ignore_list() -> None:
    """Print ignored tasks for every project in the config."""
    ignore_cfg = load_ignore_config()

    if not ignore_cfg.projects:
        logger.info("Ignore-списки пусты — нет игнорируемых задач ни в одном проекте")
        return

    total = 0
    for project_name in sorted(ignore_cfg.projects):
        entries = ignore_cfg.get_ignored_entries(project_name)
        if not entries:
            continue
        total += len(entries)
        logger.info(f"Проект {project_name!r} ({len(entries)} задач):")
        for entry in entries:
            logger.info(f"  - {_format_ignored_entry(entry)}")

    if total == 0:
        logger.info("Ignore-списки пусты — нет игнорируемых задач ни в одном проекте")
    else:
        logger.info(f"Всего игнорируемых задач: {total}")


def run_ignore(args: argparse.Namespace) -> None:
    """Run the ``ignore`` command: add, remove, list-all, or interactive menu."""
    if args.list_all:
        run_ignore_list()
        return

    cfg = load_config()
    require_host(cfg)
    ignore_cfg = load_ignore_config()

    with CvatClient(cfg) as client:
        project_id, project_name = _resolve_project(args, client, ignore_cfg)

        if args.add:
            description = (args.description or "").strip()
            silent = args.silent
            resolved = _resolve_selectors(client, project_id, args.add)
            for task in resolved:
                ignore_cfg.add_task(
                    project_name, task.id, task.name, description, silent=silent
                )
                logger.info(
                    f"Задача {task.name!r} (id={task.id}) добавлена "
                    f"в ignore-список проекта {project_name!r}"
                )
            save_ignore_config(ignore_cfg)
            return

        if args.remove:
            resolved = _resolve_selectors(client, project_id, args.remove)
            for task in resolved:
                removed = ignore_cfg.remove_task(project_name, task.id)
                if removed:
                    logger.info(
                        f"Задача {task.name!r} (id={task.id}) удалена "
                        f"из ignore-списка проекта {project_name!r}"
                    )
                else:
                    logger.warning(
                        f"Задача {task.name!r} (id={task.id}) не найдена "
                        f"в ignore-списке проекта {project_name!r}"
                    )
            save_ignore_config(ignore_cfg)
            return

        _interactive_loop(client, project_id, project_name, ignore_cfg)


# ------------------------------------------------------------------
# Project resolution
# ------------------------------------------------------------------


def _resolve_project(
    args: argparse.Namespace,
    client: CvatClient,
    ignore_cfg: IgnoreConfig,
) -> tuple[int, str]:
    """Resolve project ID and name from CLI args or interactive TUI."""
    try:
        resolved = resolve_project_from_args(args.project, client)
    except Cveta2Error as e:
        sys.exit(str(e))

    if resolved is not None:
        return resolved
    return _select_project_tui(client, ignore_cfg)


def _select_project_tui(
    client: CvatClient,
    ignore_cfg: IgnoreConfig,
) -> tuple[int, str]:
    """Interactive project selection, returning ``(project_id, project_name)``."""
    require_interactive("Pass --project / -p to specify the project name.")

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

    project_name = answer
    cached = load_projects_cache()
    try:
        project_id = client.resolve_project_id(project_name, cached=cached)
    except Cveta2Error as e:
        sys.exit(str(e))
    return project_id, project_name


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


# ------------------------------------------------------------------
# Selector resolution
# ------------------------------------------------------------------


def _resolve_selectors(
    client: CvatClient,
    project_id: int,
    selectors: list[str],
) -> list[TaskInfo]:
    """Fetch project tasks and resolve selectors to ``TaskInfo`` objects."""
    tasks = client.list_project_tasks(project_id)
    return CvatClient.resolve_task_selectors(tasks, selectors)


# ------------------------------------------------------------------
# Interactive loop
# ------------------------------------------------------------------


def _format_ignored_entry(e: IgnoredTask) -> str:
    """Build a human-readable label for an ignored task entry."""
    label = f"{e.name!r} (id={e.id})" if e.name else f"id={e.id}"
    if e.description:
        label += f" — {e.description}"
    if e.silent:
        label += " [silent]"
    return label


def _print_ignored_list(ignore_cfg: IgnoreConfig, project_name: str) -> None:
    """Display the current ignore list for *project_name*."""
    entries = ignore_cfg.get_ignored_entries(project_name)
    if not entries:
        logger.info(f"Проект {project_name!r}: ignore-список пуст")
    else:
        logger.info(f"Проект {project_name!r}: игнорируемые задачи ({len(entries)}):")
        for e in entries:
            logger.info(f"  - {_format_ignored_entry(e)}")


def _interactive_loop(
    client: CvatClient,
    project_id: int,
    project_name: str,
    ignore_cfg: IgnoreConfig,
) -> None:
    """Run the interactive TUI loop for managing the ignore list."""
    changed = False

    while True:
        _print_ignored_list(ignore_cfg, project_name)

        ignored_ids = ignore_cfg.get_ignored_tasks(project_name)
        choices = [
            questionary.Choice(
                title="Добавить задачи в ignore-список",
                value=_ACTION_ADD,
            ),
        ]
        if ignored_ids:
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
            added = _interactive_add(client, project_id, project_name, ignore_cfg)
            if added:
                changed = True

        elif action == _ACTION_REMOVE:
            removed = _interactive_remove(ignore_cfg, project_name)
            if removed:
                changed = True

    if changed:
        save_ignore_config(ignore_cfg)


def _interactive_add(
    client: CvatClient,
    project_id: int,
    project_name: str,
    ignore_cfg: IgnoreConfig,
) -> bool:
    """Show TUI checkbox of project tasks to add to the ignore list.

    Unlike ``select_tasks_tui``, a cancel or empty selection here returns
    False instead of terminating the program, so the interactive loop can
    continue.
    """
    ignored_ids = set(ignore_cfg.get_ignored_tasks(project_name))
    tasks = client.list_project_tasks(project_id)
    if ignored_ids:
        tasks = [t for t in tasks if t.id not in ignored_ids]
    if not tasks:
        logger.info("Нет доступных задач для добавления.")
        return False

    choices = build_task_choices(tasks)
    answer = questionary.checkbox(
        "Выберите задачи для добавления в ignore-список:",
        choices=choices,
        use_jk_keys=False,
        use_search_filter=True,
    ).ask()
    if not answer:
        return False

    description = (
        questionary.text("Описание / причина (Enter — пропустить):").ask() or ""
    ).strip()
    silent = questionary.confirm(
        "Не показывать предупреждение при fetch (silent)?", default=False
    ).ask()

    tasks_by_id = {t.id: t for t in tasks}
    for val in answer:
        task = tasks_by_id.get(int(val))
        if task is not None:
            ignore_cfg.add_task(
                project_name, task.id, task.name, description, silent=bool(silent)
            )
            logger.info(f"Задача {task.name!r} (id={task.id}) добавлена")
    return True


def _interactive_remove(
    ignore_cfg: IgnoreConfig,
    project_name: str,
) -> bool:
    """Show a checkbox list of ignored tasks to remove. Returns True if any removed."""
    entries = ignore_cfg.get_ignored_entries(project_name)
    if not entries:
        logger.info("Ignore-список пуст — нечего удалять.")
        return False

    choices = [
        questionary.Choice(
            title=_format_ignored_entry(e),
            value=e.id,
        )
        for e in entries
    ]
    selected: list[int] | None = questionary.checkbox(
        "Выберите задачи для удаления из ignore-списка:",
        choices=choices,
        use_jk_keys=False,
        use_search_filter=True,
    ).ask()

    if not selected:
        return False

    for task_id in selected:
        ignore_cfg.remove_task(project_name, task_id)
        logger.info(f"Задача id={task_id} удалена")

    return True
