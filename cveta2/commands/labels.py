"""Implementation of the ``cveta2 labels`` command."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from loguru import logger

from cveta2.commands import interactive
from cveta2.commands._bootstrap import open_client
from cveta2.commands._helpers import (
    resolve_project_or_exit,
)
from cveta2.config import require_interactive

if TYPE_CHECKING:
    import argparse

    from cveta2.client import CvatClient
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
    with open_client() as client:
        project_id, project_name = resolve_project_or_exit(args.project, client)

        if args.list_labels:
            labels = client.get_project_labels(project_id)
            _print_labels(labels, project_name)
            return

        _interactive_loop(client, project_id, project_name)


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
            interactive.Choice(
                title="Добавить метку",
                value=_ACTION_ADD,
            ),
        ]
        if labels:
            choices.append(
                interactive.Choice(
                    title="Переименовать метку",
                    value=_ACTION_RENAME,
                ),
            )
            choices.append(
                interactive.Choice(
                    title="Изменить цвет метки",
                    value=_ACTION_RECOLOR,
                ),
            )
            choices.append(
                interactive.Choice(
                    title="Удалить метку",
                    value=_ACTION_DELETE,
                ),
            )
        choices.append(
            interactive.Choice(title="Готово", value=_ACTION_EXIT),
        )

        action = interactive.select_one(
            "Что сделать?",
            choices,
            hint="Pass --list to view labels non-interactively.",
            on_cancel="none",
        )

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

    name = interactive.text(
        "Имя новой метки (Enter — отмена):",
        hint="Pass --list to view labels non-interactively.",
        on_cancel="none",
    )

    if not name:
        return labels

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
    label_id = interactive.select_label(labels, message="Какую метку переименовать?")

    if label_id is None:
        return labels

    old_label = next(lbl for lbl in labels if lbl.id == label_id)
    existing_names = {lbl.name.casefold() for lbl in labels if lbl.id != label_id}

    new_name = interactive.text(
        f"Новое имя для {old_label.name!r} (Enter — отмена):",
        hint="Pass --list to view labels non-interactively.",
        on_cancel="none",
    )

    if not new_name:
        return labels

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
    label_id = interactive.select_label(labels, message="Какой метке изменить цвет?")

    if label_id is None:
        return labels

    old_label = next(lbl for lbl in labels if lbl.id == label_id)
    default_color = old_label.color or ""

    new_color = interactive.text(
        f"Новый цвет для {old_label.name!r} (текущий: {default_color or 'не задан'}, "
        "Enter — отмена):",
        hint="Pass --list to view labels non-interactively.",
        on_cancel="none",
        validate=lambda val: (
            True if not val.strip() else _validate_hex_color(val.strip())
        ),
    )

    if not new_color:
        return labels

    new_color = new_color.lower()
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
    selected_ids = interactive.select_labels(
        labels, message="Выберите метки для удаления:"
    )

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
        confirm = interactive.text(
            f"Для подтверждения введите имена меток через запятую "
            f"({names_to_confirm}):",
            hint="Pass --list to view labels non-interactively.",
            on_cancel="none",
        )

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
        confirm_delete = interactive.confirm(
            f"Удалить {len(selected_labels)} меток (аннотаций нет)?",
            hint="Pass --list to view labels non-interactively.",
        )
        if not confirm_delete:
            logger.info("Удаление отменено")
            return labels

    client.update_project_labels(project_id, delete=selected_ids)
    deleted_names = ", ".join(lbl.name for lbl in selected_labels)
    logger.info(f"Удалены метки: {deleted_names}")
    return client.get_project_labels(project_id)
