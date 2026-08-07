"""Low-level interactive primitives shared by every command.

Each primitive folds together three things that used to be repeated at every
prompt site: the :func:`require_interactive` guard, the questionary call, and
the cancellation handling.  The ``on_cancel`` knob decides whether a cancelled
prompt terminates the program (one-shot commands) or returns ``None`` so a
CRUD loop can continue.
"""

from __future__ import annotations

import getpass
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from cveta2.commands.interactive import _questionary
from cveta2.commands.interactive._history import history_for
from cveta2.config import require_interactive

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from cveta2.commands.interactive._questionary import Choice

OnCancel = Literal["exit", "none"]

# Default captions live at module level so mutation testing cannot generate
# unkillable "change the wording" mutants inside the primitives below.
_CANCELLED = "Отменено."
_VALUE_NOT_SET = "Значение не указано."
_NOTHING_SELECTED = "Ничего не выбрано."


def _handle_cancel(on_cancel: OnCancel) -> None:
    """Exit or fall through when a prompt is cancelled."""
    if on_cancel == "exit":
        sys.exit(_CANCELLED)


def confirm(message: str, *, default: bool = False, hint: str) -> bool:
    """Ask a yes/no question.  A cancelled prompt counts as No."""
    require_interactive(hint)
    answer = _questionary.ask_confirm(message, default=default)
    return bool(answer)


def confirm_or_exit(
    message: str,
    *,
    yes: bool,
    hint: str,
    on_no: str = _CANCELLED,
) -> None:
    """Confirm before a destructive action; exit unless confirmed.

    Proceeds silently when *yes* is set.  In noninteractive mode
    :func:`require_interactive` raises with *hint*.
    """
    if yes:
        return
    require_interactive(hint)
    if not _questionary.ask_confirm(f"{message} [y/N]", default=False):
        sys.exit(on_no)


def text(  # noqa: PLR0913
    message: str,
    *,
    hint: str,
    default: str = "",
    allow_empty: bool = True,
    empty_message: str = _VALUE_NOT_SET,
    on_cancel: OnCancel = "exit",
    validate: Callable[[str], bool | str] | None = None,
    history_key: str | None = None,
) -> str | None:
    """Prompt for free text.

    Returns the stripped value.  On cancel, exits or returns ``None`` per
    *on_cancel*.  When *allow_empty* is False an empty value exits with
    *empty_message* (``on_cancel="exit"``) or returns ``None``.
    *history_key* enables arrow-up recall of values from previous runs.
    """
    require_interactive(hint)
    history = history_for(history_key) if history_key else None
    answer = _questionary.ask_text(message, validate=validate, history=history)
    if answer is None:
        _handle_cancel(on_cancel)
        return None
    value = answer.strip() or default
    if not value and not allow_empty:
        if on_cancel == "exit":
            sys.exit(empty_message)
        return None
    return value


def path(
    message: str,
    *,
    hint: str,
    on_cancel: OnCancel = "exit",
    history_key: str | None = None,
) -> Path | None:
    """Prompt for a filesystem path.  Returns a resolved ``Path`` or ``None``."""
    raw = text(
        message,
        hint=hint,
        on_cancel=on_cancel,
        history_key=history_key,
    )
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def select_one(
    message: str,
    choices: Sequence[Choice],
    *,
    hint: str,
    on_cancel: OnCancel = "exit",
) -> object | None:
    """Single-choice picker.  Returns the chosen value or ``None`` on cancel."""
    require_interactive(hint)
    answer = _questionary.ask_select(message, choices)
    if answer is None:
        _handle_cancel(on_cancel)
        return None
    return answer


def select_many(  # noqa: PLR0913
    message: str,
    choices: Sequence[Choice],
    *,
    hint: str,
    on_cancel: OnCancel = "exit",
    allow_empty: bool = False,
    empty_message: str = _NOTHING_SELECTED,
) -> list[object] | None:
    """Multi-choice picker.  Returns selected values or ``None`` on cancel."""
    require_interactive(hint)
    answer = _questionary.ask_checkbox(message, choices)
    if answer is None:
        _handle_cancel(on_cancel)
        return None
    if not answer and not allow_empty:
        if on_cancel == "exit":
            sys.exit(empty_message)
        return None
    return answer


def prompt_password(message: str) -> str:
    """Prompt for a secret without echo.  Caller guards interactivity."""
    return getpass.getpass(message)
