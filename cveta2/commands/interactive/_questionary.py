"""The single module that touches ``questionary``.

Every other command module goes through :mod:`cveta2.commands.interactive`;
questionary is imported here and nowhere else so the prompt library can be
swapped or mocked at one seam.  Shared list/checkbox keyword arguments live
here too, since they were previously copy-pasted at every call site.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import questionary

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from prompt_toolkit.history import History

Choice = questionary.Choice


def ask_select(message: str, choices: Sequence[Choice]) -> object | None:
    """Single-choice picker.  Returns the selected value or None on cancel."""
    result: object | None = questionary.select(
        message,
        choices=list(choices),
        use_shortcuts=False,
        use_indicator=True,
        use_search_filter=True,
        use_jk_keys=False,
    ).ask()
    return result


def ask_checkbox(message: str, choices: Sequence[Choice]) -> list[object] | None:
    """Multi-choice picker.  Returns selected values or None on cancel."""
    result: list[object] | None = questionary.checkbox(
        message,
        choices=list(choices),
        use_search_filter=True,
        use_jk_keys=False,
    ).ask()
    return result


def ask_text(
    message: str,
    *,
    validate: Callable[[str], bool | str] | None = None,
    history: History | None = None,
) -> str | None:
    """Free-text prompt.  Returns the entered string or None on cancel.

    *history* (a prompt_toolkit history) enables arrow-up recall of
    previously entered values; accepted input is appended automatically.
    """
    result: str | None = questionary.text(
        message, validate=validate, history=history
    ).ask()
    return result


def ask_confirm(message: str, *, default: bool = False) -> bool | None:
    """Yes/No prompt.  Returns the answer or None on cancel."""
    result: bool | None = questionary.confirm(message, default=default).ask()
    return result
