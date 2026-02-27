"""Implementation of the ``cveta2 labels`` command."""

from __future__ import annotations

import re
import sys
from typing import TYPE_CHECKING

import questionary
from loguru import logger

from cveta2.client import CvatClient
from cveta2.commands._helpers import (
    load_config,
    require_host,
    resolve_project_from_args,
    select_project_tui,
)
from cveta2.config import require_interactive
from cveta2.exceptions import Cveta2Error

if TYPE_CHECKING:
    import argparse

    from cveta2.models import LabelInfo

_ACTION_ADD = "add"
_ACTION_RENAME = "rename"
_ACTION_RECOLOR = "recolor"
_ACTION_DELETE = "delete"
_ACTION_EXIT = "exit"

_HEX_COLOR_RE = r"^#[0-9a-fA-F]{6}$"


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------


def run_labels(args: argparse.Namespace) -> None:
    """Run the ``labels`` command: list or interactively edit project labels."""
    cfg = load_config()
    require_host(cfg)

    with CvatClient(cfg) as client:
        project_id, project_name = _resolve_project(args, client)

        if args.list_labels:
            labels = client.get_project_labels(project_id)
            _print_labels(labels, project_name)
            return

        _interactive_loop(client, project_id, project_name)


# ------------------------------------------------------------------
# Project resolution
# ------------------------------------------------------------------


def _resolve_project(
    args: argparse.Namespace,
    client: CvatClient,
) -> tuple[int, str]:
    """Resolve project ID and name from CLI args or interactive TUI."""
    try:
        resolved = resolve_project_from_args(args.project, client)
    except Cveta2Error as e:
        sys.exit(str(e))

    if resolved is not None:
        return resolved
    return select_project_tui(client)


# ------------------------------------------------------------------
# Display helpers
# ------------------------------------------------------------------


def _print_labels(labels: list[LabelInfo], project_name: str) -> None:
    """Display current labels for a project."""
    if not labels:
        logger.info(f"Проект {project_name!r}: нет меток")
        return
    logger.info(f"Проект {project_name!r}: {len(labels)} меток:")
    for label in sorted(labels, key=lambda lbl: lbl.name):
        logger.info(f"  - {label.format_display()}")


# ------------------------------------------------------------------
# Interactive loop
# ------------------------------------------------------------------


def _interactive_loop(
    client: CvatClient,
    project_id: int,
    project_name: str,
) -> None:
    """Run the interactive TUI loop for managing project labels."""
    require_interactive("Pass --list to view labels non-interactively.")

    labels = client.get_project_labels(project_id)

    while True:
        _print_labels(labels, project_name)

        choices = [
            questionary.Choice(
                title="Добавить метку",
                value=_ACTION_ADD,
            ),
        ]
        if labels:
            choices.append(
                questionary.Choice(
                    title="Переименовать метку",
                    value=_ACTION_RENAME,
                ),
            )
            choices.append(
                questionary.Choice(
                    title="Изменить цвет метки",
                    value=_ACTION_RECOLOR,
                ),
            )
            choices.append(
                questionary.Choice(
                    title="Удалить метку",
                    value=_ACTION_DELETE,
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
            labels = _interactive_add(client, project_id, labels)

        elif action == _ACTION_RENAME:
            labels = _interactive_rename(client, project_id, labels)

        elif action == _ACTION_RECOLOR:
            labels = _interactive_recolor(client, project_id, labels)

        elif action == _ACTION_DELETE:
            labels = _interactive_delete(client, project_id, labels)


# ------------------------------------------------------------------
# Add
# ------------------------------------------------------------------


def _interactive_add(
    client: CvatClient,
    project_id: int,
    labels: list[LabelInfo],
) -> list[LabelInfo]:
    """Prompt for a new label name and add it to the project."""
    existing_names = {lbl.name.casefold() for lbl in labels}

    name: str | None = questionary.text("Имя новой метки (Enter — отмена):").ask()

    if not name or not name.strip():
        return labels

    name = name.strip()
    if name.casefold() in existing_names:
        logger.warning(f"Метка {name!r} уже существует")
        return labels

    client.update_project_labels(project_id, add=[name])
    logger.info(f"Метка {name!r} добавлена")
    return client.get_project_labels(project_id)


# ------------------------------------------------------------------
# Rename
# ------------------------------------------------------------------


def _interactive_rename(
    client: CvatClient,
    project_id: int,
    labels: list[LabelInfo],
) -> list[LabelInfo]:
    """Select a label and rename it."""
    sorted_labels = sorted(labels, key=lambda lbl: lbl.name)
    choices = [
        questionary.Choice(title=lbl.format_display(), value=lbl.id)
        for lbl in sorted_labels
    ]

    label_id: int | None = questionary.select(
        "Какую метку переименовать?",
        choices=choices,
        use_shortcuts=False,
        use_indicator=True,
        use_search_filter=True,
        use_jk_keys=False,
    ).ask()

    if label_id is None:
        return labels

    old_label = next(lbl for lbl in labels if lbl.id == label_id)
    existing_names = {lbl.name.casefold() for lbl in labels if lbl.id != label_id}

    new_name: str | None = questionary.text(
        f"Новое имя для {old_label.name!r} (Enter — отмена):"
    ).ask()

    if not new_name or not new_name.strip():
        return labels

    new_name = new_name.strip()
    if new_name.casefold() in existing_names:
        logger.warning(f"Метка {new_name!r} уже существует")
        return labels

    if new_name == old_label.name:
        logger.info("Имя не изменилось")
        return labels

    client.update_project_labels(project_id, rename={label_id: new_name})
    logger.info(f"Метка {old_label.name!r} → {new_name!r}")
    return client.get_project_labels(project_id)


# ------------------------------------------------------------------
# Recolor
# ------------------------------------------------------------------


def _validate_hex_color(value: str) -> bool | str:
    """Validate that value is a hex color like ``#rrggbb``."""
    if re.match(_HEX_COLOR_RE, value):
        return True
    return "Введите цвет в формате #rrggbb (например, #ff0000)"


def _interactive_recolor(
    client: CvatClient,
    project_id: int,
    labels: list[LabelInfo],
) -> list[LabelInfo]:
    """Select a label and change its color."""
    sorted_labels = sorted(labels, key=lambda lbl: lbl.name)
    choices = [
        questionary.Choice(title=lbl.format_display(), value=lbl.id)
        for lbl in sorted_labels
    ]

    label_id: int | None = questionary.select(
        "Какой метке изменить цвет?",
        choices=choices,
        use_shortcuts=False,
        use_indicator=True,
        use_search_filter=True,
        use_jk_keys=False,
    ).ask()

    if label_id is None:
        return labels

    old_label = next(lbl for lbl in labels if lbl.id == label_id)
    default_color = old_label.color or ""

    new_color: str | None = questionary.text(
        f"Новый цвет для {old_label.name!r} (текущий: {default_color or 'не задан'}, "
        "Enter — отмена):",
        validate=lambda val: (
            True if not val.strip() else _validate_hex_color(val.strip())
        ),
    ).ask()

    if not new_color or not new_color.strip():
        return labels

    new_color = new_color.strip().lower()
    if new_color == old_label.color.lower():
        logger.info("Цвет не изменился")
        return labels

    client.update_project_labels(project_id, recolor={label_id: new_color})
    logger.info(f"Цвет метки {old_label.name!r}: {default_color} → {new_color}")
    return client.get_project_labels(project_id)


# ------------------------------------------------------------------
# Delete (with safety checks)
# ------------------------------------------------------------------


def _interactive_delete(
    client: CvatClient,
    project_id: int,
    labels: list[LabelInfo],
) -> list[LabelInfo]:
    """Select labels to delete with annotation-count safety checks."""
    sorted_labels = sorted(labels, key=lambda lbl: lbl.name)
    choices = [
        questionary.Choice(title=lbl.format_display(), value=lbl.id)
        for lbl in sorted_labels
    ]

    selected_ids: list[int] | None = questionary.checkbox(
        "Выберите метки для удаления:",
        choices=choices,
        use_jk_keys=False,
        use_search_filter=True,
    ).ask()

    if not selected_ids:
        return labels

    selected_labels = [lbl for lbl in labels if lbl.id in set(selected_ids)]

    logger.info("Подсчёт аннотаций, использующих выбранные метки...")
    usage = client.count_label_usage(project_id)

    has_annotations = False
    for label in selected_labels:
        count = usage.get(label.id, 0)
        if count > 0:
            has_annotations = True
            logger.warning(
                f"Метка {label.name!r} (id={label.id}): "
                f"{count} аннотаций будет УНИЧТОЖЕНО"
            )
        else:
            logger.info(f"Метка {label.name!r} (id={label.id}): 0 аннотаций")

    if has_annotations:
        logger.warning(
            "ВНИМАНИЕ: удаление меток НЕОБРАТИМО уничтожит все "
            "аннотации (shapes), использующие эти метки!"
        )
        names_to_confirm = ", ".join(lbl.name for lbl in selected_labels)
        confirm: str | None = questionary.text(
            f"Для подтверждения введите имена меток через запятую ({names_to_confirm}):"
        ).ask()

        if confirm is None:
            logger.info("Удаление отменено")
            return labels

        expected = {lbl.name.strip() for lbl in selected_labels}
        entered = {s.strip() for s in confirm.split(",")}
        if entered != expected:
            logger.warning(
                f"Введённые имена не совпадают. "
                f"Ожидалось: {names_to_confirm}. Удаление отменено."
            )
            return labels
    else:
        confirm_delete: bool | None = questionary.confirm(
            f"Удалить {len(selected_labels)} меток (аннотаций нет)?",
            default=False,
        ).ask()
        if not confirm_delete:
            logger.info("Удаление отменено")
            return labels

    client.update_project_labels(project_id, delete=selected_ids)
    deleted_names = ", ".join(lbl.name for lbl in selected_labels)
    logger.info(f"Удалены метки: {deleted_names}")
    return client.get_project_labels(project_id)
