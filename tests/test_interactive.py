"""Tests for the shared interactive primitives."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from prompt_toolkit.history import FileHistory

from cveta2.commands.interactive import Choice, primitives
from cveta2.commands.interactive._history import history_for
from cveta2.exceptions import InteractiveModeRequiredError

if TYPE_CHECKING:
    from pathlib import Path

_HINT = "pass a flag instead"

_ASK_TEXT = "cveta2.commands.interactive._questionary.ask_text"
_ASK_CONFIRM = "cveta2.commands.interactive._questionary.ask_confirm"
_ASK_SELECT = "cveta2.commands.interactive._questionary.ask_select"
_ASK_CHECKBOX = "cveta2.commands.interactive._questionary.ask_checkbox"


def _choices() -> list[Choice]:
    return [Choice(title="Первый", value="one")]


class TestRequireInteractive:
    """Every primitive must forward its own *hint* to ``require_interactive``.

    Each ``match=_HINT`` pins that pass-through: the mutants replacing the
    argument with ``None`` still raise, just without the one sentence that
    tells the user which flag to pass instead.
    """

    def test_text_raises_when_noninteractive(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CVETA2_NO_INTERACTIVE", "true")
        with pytest.raises(InteractiveModeRequiredError, match=_HINT):
            primitives.text("Имя:", hint=_HINT)

    def test_confirm_raises_when_noninteractive(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CVETA2_NO_INTERACTIVE", "true")
        with pytest.raises(InteractiveModeRequiredError, match=_HINT):
            primitives.confirm("Удалить?", hint=_HINT)

    def test_path_raises_when_noninteractive(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CVETA2_NO_INTERACTIVE", "true")
        with pytest.raises(InteractiveModeRequiredError, match=_HINT):
            primitives.path("Путь:", hint=_HINT)

    def test_select_one_raises_when_noninteractive(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CVETA2_NO_INTERACTIVE", "true")
        with pytest.raises(InteractiveModeRequiredError, match=_HINT):
            primitives.select_one("Выберите:", _choices(), hint=_HINT)

    def test_select_many_raises_when_noninteractive(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CVETA2_NO_INTERACTIVE", "true")
        with pytest.raises(InteractiveModeRequiredError, match=_HINT):
            primitives.select_many("Выберите:", _choices(), hint=_HINT)


class TestText:
    def test_strips_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CVETA2_NO_INTERACTIVE", raising=False)
        with patch(
            "cveta2.commands.interactive._questionary.ask_text",
            return_value="  fish  ",
        ):
            assert primitives.text("Имя:", hint=_HINT) == "fish"

    def test_default_used_on_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CVETA2_NO_INTERACTIVE", raising=False)
        with patch(
            "cveta2.commands.interactive._questionary.ask_text", return_value=""
        ):
            assert primitives.text("Имя:", hint=_HINT, default="cat") == "cat"

    def test_cancel_none_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CVETA2_NO_INTERACTIVE", raising=False)
        with patch(
            "cveta2.commands.interactive._questionary.ask_text", return_value=None
        ):
            assert primitives.text("Имя:", hint=_HINT, on_cancel="none") is None

    def test_cancel_exit_raises_systemexit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A cancelled prompt must exit *non-zero*.

        ``sys.exit(None)`` — the mutant of ``sys.exit(_CANCELLED)`` — also
        raises ``SystemExit``, but with status 0, so the shell would treat a
        cancelled run as a success.  Only the exit code catches it.
        """
        monkeypatch.delenv("CVETA2_NO_INTERACTIVE", raising=False)
        with (
            patch(_ASK_TEXT, return_value=None),
            pytest.raises(SystemExit) as excinfo,
        ):
            primitives.text("Имя:", hint=_HINT, on_cancel="exit")
        assert excinfo.value.code == primitives._CANCELLED

    def test_empty_disallowed_exits_with_the_empty_message(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The caller's *empty_message* must become the exit status.

        Pins ``sys.exit(empty_message)`` against ``sys.exit(None)``, which
        would end the run silently and successfully.
        """
        monkeypatch.delenv("CVETA2_NO_INTERACTIVE", raising=False)
        with (
            patch(_ASK_TEXT, return_value=""),
            pytest.raises(SystemExit) as excinfo,
        ):
            primitives.text(
                "Имя:", hint=_HINT, allow_empty=False, empty_message="нет имени"
            )
        assert excinfo.value.code == "нет имени"

    def test_empty_allowed_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Without *allow_empty* an empty answer comes back as ``""``.

        Pins the ``allow_empty: bool = True`` default: flipped to ``False``
        this call would exit instead of returning.
        """
        monkeypatch.delenv("CVETA2_NO_INTERACTIVE", raising=False)
        with patch(_ASK_TEXT, return_value=""):
            assert primitives.text("Имя:", hint=_HINT) == ""

    def test_validate_callback_is_forwarded(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The *validate* callback must reach questionary.

        The fake prompt never validates anything, so dropping the argument
        or passing ``None`` is invisible in the return value — the recorded
        call is the only place it shows.
        """
        monkeypatch.delenv("CVETA2_NO_INTERACTIVE", raising=False)

        def _accept(_value: str) -> bool:
            return True

        with patch(_ASK_TEXT, return_value="v") as ask:
            primitives.text("Имя:", hint=_HINT, validate=_accept)
        assert ask.call_args.kwargs["validate"] is _accept


class TestPromptHistory:
    def test_history_for_creates_dir_and_points_into_it(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        history = history_for("task-name")
        expected_dir = tmp_path / "cveta2" / "prompt_history"
        assert expected_dir.is_dir()
        assert history.filename == str(expected_dir / "task-name")

    def test_text_with_history_key_forwards_history(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.delenv("CVETA2_NO_INTERACTIVE", raising=False)
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        with patch(
            "cveta2.commands.interactive._questionary.ask_text",
            return_value="v",
        ) as ask:
            primitives.text("Имя:", hint=_HINT, history_key="task-name")
        history = ask.call_args.kwargs["history"]
        assert isinstance(history, FileHistory)
        assert str(history.filename).endswith("task-name")

    def test_text_without_history_key_passes_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("CVETA2_NO_INTERACTIVE", raising=False)
        with patch(
            "cveta2.commands.interactive._questionary.ask_text",
            return_value="v",
        ) as ask:
            primitives.text("Имя:", hint=_HINT)
        assert ask.call_args.kwargs["history"] is None

    def test_noninteractive_raises_before_history(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("CVETA2_NO_INTERACTIVE", "true")
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        with pytest.raises(InteractiveModeRequiredError):
            primitives.text("Имя:", hint=_HINT, history_key="task-name")
        assert not (tmp_path / "cveta2" / "prompt_history").exists()


class TestConfirm:
    def test_cancel_counts_as_no(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CVETA2_NO_INTERACTIVE", raising=False)
        with patch(_ASK_CONFIRM, return_value=None):
            assert primitives.confirm("Удалить?", hint=_HINT) is False

    def test_answer_is_returned(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CVETA2_NO_INTERACTIVE", raising=False)
        with patch(_ASK_CONFIRM, return_value=True):
            assert primitives.confirm("Удалить?", hint=_HINT) is True

    def test_enter_means_no_unless_asked_otherwise(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The unspecified *default* must reach questionary as ``False``.

        It decides what pressing Enter does; the mutant flipping the
        parameter default to ``True`` changes that and nothing else, so
        only the recorded call can see it.
        """
        monkeypatch.delenv("CVETA2_NO_INTERACTIVE", raising=False)
        with patch(_ASK_CONFIRM, return_value=False) as ask:
            primitives.confirm("Удалить?", hint=_HINT)
        assert ask.call_args.kwargs["default"] is False


class TestConfirmOrExit:
    def test_yes_flag_skips_prompt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CVETA2_NO_INTERACTIVE", "true")
        primitives.confirm_or_exit("Удалить?", yes=True, hint=_HINT)

    def test_noninteractive_raises_with_hint(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CVETA2_NO_INTERACTIVE", "true")
        with pytest.raises(InteractiveModeRequiredError, match=_HINT):
            primitives.confirm_or_exit("Удалить?", yes=False, hint=_HINT)

    def test_interactive_yes_proceeds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CVETA2_NO_INTERACTIVE", raising=False)
        with patch(_ASK_CONFIRM, return_value=True):
            primitives.confirm_or_exit("Удалить?", yes=False, hint=_HINT)

    def test_prompt_shows_the_message_and_defaults_to_no(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Pins the whole ``ask_confirm`` call for a destructive action.

        A ``MagicMock`` swallows any signature, so dropping the message,
        replacing it with ``None``, dropping ``default`` or flipping it to
        ``True`` all leave the happy path looking identical — yet the last
        two would make Enter mean "yes, delete".
        """
        monkeypatch.delenv("CVETA2_NO_INTERACTIVE", raising=False)
        with patch(_ASK_CONFIRM, return_value=True) as ask:
            primitives.confirm_or_exit("Удалить проект?", yes=False, hint=_HINT)
        assert "Удалить проект?" in ask.call_args.args[0]
        assert ask.call_args.kwargs["default"] is False

    def test_interactive_no_exits_with_the_given_status(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Declining must fail the run with the caller's *on_no* text.

        ``sys.exit(None)`` exits 0, so a declined destructive action would
        look like a successful one to any script wrapping the CLI.
        """
        monkeypatch.delenv("CVETA2_NO_INTERACTIVE", raising=False)
        with (
            patch(_ASK_CONFIRM, return_value=False),
            pytest.raises(SystemExit) as excinfo,
        ):
            primitives.confirm_or_exit(
                "Удалить?", yes=False, hint=_HINT, on_no="прервано"
            )
        assert excinfo.value.code == "прервано"


class TestPath:
    def test_expands_user_and_resolves(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """``path()`` returns an absolute, ``~``-expanded, normalised Path."""
        monkeypatch.delenv("CVETA2_NO_INTERACTIVE", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        with patch(_ASK_TEXT, return_value="~/sub/../file.txt"):
            assert primitives.path("Путь:", hint=_HINT) == tmp_path / "file.txt"

    def test_empty_input_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Empty input means "no path", not the current directory.

        Without the guard ``Path("").resolve()`` would silently hand the
        caller the cwd.
        """
        monkeypatch.delenv("CVETA2_NO_INTERACTIVE", raising=False)
        with patch(_ASK_TEXT, return_value="   "):
            assert primitives.path("Путь:", hint=_HINT) is None

    def test_cancel_exits_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The default ``on_cancel="exit"`` must survive the hand-off to ``text``.

        Mutating the default literal, or passing ``None`` instead of it,
        turns a cancelled prompt into a plain ``None`` return that the
        caller then treats as "no path given".
        """
        monkeypatch.delenv("CVETA2_NO_INTERACTIVE", raising=False)
        with patch(_ASK_TEXT, return_value=None), pytest.raises(SystemExit) as excinfo:
            primitives.path("Путь:", hint=_HINT)
        assert excinfo.value.code == primitives._CANCELLED

    def test_cancel_none_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``on_cancel="none"`` must be forwarded, not dropped."""
        monkeypatch.delenv("CVETA2_NO_INTERACTIVE", raising=False)
        with patch(_ASK_TEXT, return_value=None):
            assert primitives.path("Путь:", hint=_HINT, on_cancel="none") is None

    def test_history_key_is_forwarded(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Arrow-up recall only works if *history_key* reaches ``text``."""
        monkeypatch.delenv("CVETA2_NO_INTERACTIVE", raising=False)
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        with patch(_ASK_TEXT, return_value="/x") as ask:
            primitives.path("Путь:", hint=_HINT, history_key="dataset-path")
        history = ask.call_args.kwargs["history"]
        assert isinstance(history, FileHistory)
        assert str(history.filename).endswith("dataset-path")


class TestSelectOne:
    def test_returns_the_chosen_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Message and choices must reach questionary, answer must come back.

        Kills the mutants that null out either argument, drop one of them
        (shifting the other into its place) or discard the answer — none of
        which the ``MagicMock`` prompt would otherwise object to.
        """
        monkeypatch.delenv("CVETA2_NO_INTERACTIVE", raising=False)
        choices = _choices()
        with patch(_ASK_SELECT, return_value="one") as ask:
            assert primitives.select_one("Выберите:", choices, hint=_HINT) == "one"
        assert ask.call_args.args[0] == "Выберите:"
        assert ask.call_args.args[1] is choices

    def test_cancel_exits_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CVETA2_NO_INTERACTIVE", raising=False)
        with (
            patch(_ASK_SELECT, return_value=None),
            pytest.raises(SystemExit) as excinfo,
        ):
            primitives.select_one("Выберите:", _choices(), hint=_HINT)
        assert excinfo.value.code == primitives._CANCELLED

    def test_cancel_none_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CVETA2_NO_INTERACTIVE", raising=False)
        with patch(_ASK_SELECT, return_value=None):
            answer = primitives.select_one(
                "Выберите:", _choices(), hint=_HINT, on_cancel="none"
            )
        assert answer is None


class TestSelectMany:
    def test_returns_the_selection(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Message and choices must reach questionary, selection must come back."""
        monkeypatch.delenv("CVETA2_NO_INTERACTIVE", raising=False)
        choices = _choices()
        with patch(_ASK_CHECKBOX, return_value=["one"]) as ask:
            selected = primitives.select_many("Выберите:", choices, hint=_HINT)
        assert selected == ["one"]
        assert ask.call_args.args[0] == "Выберите:"
        assert ask.call_args.args[1] is choices

    def test_cancel_exits_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CVETA2_NO_INTERACTIVE", raising=False)
        with (
            patch(_ASK_CHECKBOX, return_value=None),
            pytest.raises(SystemExit) as excinfo,
        ):
            primitives.select_many("Выберите:", _choices(), hint=_HINT)
        assert excinfo.value.code == primitives._CANCELLED

    def test_empty_disallowed_exits_with_the_empty_message(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Selecting nothing must fail the run with the caller's message."""
        monkeypatch.delenv("CVETA2_NO_INTERACTIVE", raising=False)
        with (
            patch(_ASK_CHECKBOX, return_value=[]),
            pytest.raises(SystemExit) as excinfo,
        ):
            primitives.select_many("Выберите:", [], hint=_HINT, empty_message="ничего")
        assert excinfo.value.code == "ничего"

    def test_empty_disallowed_uses_the_default_message(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("CVETA2_NO_INTERACTIVE", raising=False)
        with (
            patch(_ASK_CHECKBOX, return_value=[]),
            pytest.raises(SystemExit) as excinfo,
        ):
            primitives.select_many("Выберите:", [], hint=_HINT)
        assert excinfo.value.code == primitives._NOTHING_SELECTED

    def test_empty_allowed_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CVETA2_NO_INTERACTIVE", raising=False)
        with patch(_ASK_CHECKBOX, return_value=[]):
            result = primitives.select_many(
                "Выберите:", [], hint=_HINT, on_cancel="none", allow_empty=True
            )
        assert result == []


def test_prompt_password_forwards_the_caption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The caption must reach ``getpass``; ``None`` prints its own default."""
    monkeypatch.delenv("CVETA2_NO_INTERACTIVE", raising=False)
    with patch("getpass.getpass", return_value="s3cret") as getpass_mock:
        assert primitives.prompt_password("Пароль: ") == "s3cret"
    assert getpass_mock.call_args.args == ("Пароль: ",)
