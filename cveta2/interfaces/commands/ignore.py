"""Implementation of the ``cveta2 ignore`` command."""

from typing import TYPE_CHECKING, cast

from loguru import logger

from cveta2.composition.client import CvatClient
from cveta2.composition.configuration import (
    IgnoreConfig,
    IgnoredTask,
    load_projects_cache,
)
from cveta2.interfaces.commands import interactive
from cveta2.interfaces.commands._bootstrap import open_client
from cveta2.interfaces.commands._helpers import (
    echo_cli_command,
    project_cli_spec,
    resolve_project_from_args,
)
from cveta2.interfaces.commands._parsers import add_project_arg

if TYPE_CHECKING:
    import argparse

    from cveta2.domain.models import TaskInfo

_ACTION_ADD = "add"
_ACTION_REMOVE = "remove"
_ACTION_EXIT = "exit"


def configure_ignore(parser: "argparse.ArgumentParser") -> None:
    """Declare the ``ignore`` command arguments."""
    add_project_arg(
        parser,
        help_text=(
            "Project name (as used in config). "
            "If omitted, interactive project selection is shown."
        ),
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--add",
        nargs="+",
        type=str,
        metavar="TASK",
        help="Add task(s) to the ignore list (ID or name).",
    )
    group.add_argument(
        "--remove",
        nargs="+",
        type=str,
        metavar="TASK",
        help="Remove task(s) from the ignore list (ID or name).",
    )
    group.add_argument(
        "--list",
        action="store_true",
        default=False,
        dest="list_only",
        help=(
            "List ignored tasks for all projects. Does not require a CVAT connection."
        ),
    )
    parser.add_argument(
        "--description",
        "-d",
        type=str,
        default=None,
        help="Description / reason for ignoring (used with --add).",
    )
    parser.add_argument(
        "--silent",
        action="store_true",
        default=False,
        help="Suppress per-task warning during fetch (used with --add).",
    )


def run_ignore_list() -> None:
    """Print ignored tasks for every project in the config."""
    ignore_cfg = IgnoreConfig.load()

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


def run_ignore(args: "argparse.Namespace") -> None:
    """Run the ``ignore`` command: add, remove, list-all, or interactive menu."""
    if args.list_only:
        run_ignore_list()
        return

    ignore_cfg = IgnoreConfig.load()

    with open_client() as client:
        project_id, project_name = _resolve_project(args, client, ignore_cfg)

        if args.add:
            description = (args.description or "").strip()
            silent = args.silent
            resolved = _resolve_selectors(client, project_id, args.add)
            for task in resolved:
                added = ignore_cfg.add_task(
                    project_name, task.id, task.name, description, silent=silent
                )
                if added:
                    logger.info(
                        f"Задача {task.name!r} (id={task.id}) добавлена "
                        f"в ignore-список проекта {project_name!r}"
                    )
                else:
                    logger.warning(
                        f"Задача {task.name!r} (id={task.id}) уже в ignore-списке "
                        f"проекта {project_name!r} — описание и silent не изменены "
                        f"(используйте --remove, затем --add)"
                    )
            ignore_cfg.save()
            return

        if args.remove:
            stored = {
                entry.id: entry
                for entry in ignore_cfg.get_ignored_entries(project_name)
            }
            stored_ids = {
                int(selector) for selector in args.remove if selector.isdigit()
            } & stored.keys()
            removal_entries: list[IgnoredTask | TaskInfo] = [
                stored[task_id] for task_id in sorted(stored_ids)
            ]
            remaining = [
                selector
                for selector in args.remove
                if not selector.isdigit() or int(selector) not in stored_ids
            ]
            if remaining:
                removal_entries.extend(
                    _resolve_selectors(client, project_id, remaining)
                )
            for entry in removal_entries:
                removed = ignore_cfg.remove_task(project_name, entry.id)
                if removed:
                    logger.info(
                        f"Задача {entry.name!r} (id={entry.id}) удалена "
                        f"из ignore-списка проекта {project_name!r}"
                    )
                else:
                    logger.warning(
                        f"Задача {entry.name!r} (id={entry.id}) не найдена "
                        f"в ignore-списке проекта {project_name!r}"
                    )
            ignore_cfg.save()
            return

        _interactive_loop(client, project_id, project_name, ignore_cfg)


def _resolve_project(
    args: "argparse.Namespace",
    client: CvatClient,
    ignore_cfg: IgnoreConfig,
) -> tuple[int, str]:
    """Resolve project ID and name from CLI args or interactive TUI."""
    resolved = resolve_project_from_args(client, args.project)
    if resolved is not None:
        return resolved
    cached = load_projects_cache()
    known_names = sorted({p.name for p in cached} | set(ignore_cfg.projects))
    project_name = interactive.select_project_name(known_names)
    project_id = client.resolve_project_id(project_name, cached=cached)
    return project_id, project_name


def _resolve_selectors(
    client: CvatClient,
    project_id: int,
    selectors: list[str],
) -> "list[TaskInfo]":
    """Fetch project tasks and resolve selectors to ``TaskInfo`` objects."""
    tasks = client.list_project_tasks(project_id)
    return CvatClient.resolve_task_selectors(tasks, selectors)


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
            interactive.Choice(
                title="Добавить задачи в ignore-список",
                value=_ACTION_ADD,
            ),
        ]
        if ignored_ids:
            choices.append(
                interactive.Choice(
                    title="Убрать задачи из ignore-списка",
                    value=_ACTION_REMOVE,
                ),
            )
        choices.append(
            interactive.Choice(title="Готово", value=_ACTION_EXIT),
        )

        action = interactive.select_one(
            "Что сделать?",
            choices,
            hint="Pass --project / -p to specify the project name.",
            on_cancel="none",
        )

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
        ignore_cfg.save()


def _interactive_add(
    client: CvatClient,
    project_id: int,
    project_name: str,
    ignore_cfg: IgnoreConfig,
) -> bool:
    """Show TUI checkbox of project tasks to add to the ignore list.

    Unlike ``select_tasks``, a cancel or empty selection here returns
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

    selected = interactive.pick_tasks(
        tasks, message="Выберите задачи для добавления в ignore-список:"
    )
    if not selected:
        return False

    description = (
        interactive.text(
            "Описание / причина (Enter — пропустить):",
            hint="Pass task ID(s) with --task to add non-interactively.",
            on_cancel="none",
            history_key="ignore-reason",
        )
        or ""
    )
    silent = interactive.confirm(
        "Не показывать предупреждение при fetch (silent)?",
        hint="Pass task ID(s) with --task to add non-interactively.",
    )

    for task in selected:
        ignore_cfg.add_task(
            project_name, task.id, task.name, description, silent=silent
        )
        logger.info(f"Задача {task.name!r} (id={task.id}) добавлена")
    echo_cli_command(
        "ignore",
        {
            "-p": project_cli_spec(client, project_name),
            "--add": [task.id for task in selected],
            "--description": description or None,
            "--silent": silent,
        },
    )
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
        interactive.Choice(
            title=_format_ignored_entry(e),
            value=e.id,
        )
        for e in entries
    ]
    answer = interactive.select_many(
        "Выберите задачи для удаления из ignore-списка:",
        choices,
        hint="Pass task ID(s) with --task to remove non-interactively.",
        on_cancel="none",
        allow_empty=True,
    )

    if not answer:
        return False

    for value in answer:
        task_id = cast("int", value)
        ignore_cfg.remove_task(project_name, task_id)
        logger.info(f"Задача id={task_id} удалена")

    return True
