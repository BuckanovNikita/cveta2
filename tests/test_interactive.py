"""Tests for the shared interactive primitives."""

from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

import pytest
from prompt_toolkit.history import FileHistory

from cveta2.domain.errors import InteractiveModeRequiredError
from cveta2.interfaces.commands.interactive import Choice, primitives
from cveta2.interfaces.commands.interactive._history import history_for

_HINT = "pass a flag instead"

_ASK_TEXT = "cveta2.interfaces.commands.interactive._questionary.ask_text"
_ASK_CONFIRM = "cveta2.interfaces.commands.interactive._questionary.ask_confirm"
_ASK_SELECT = "cveta2.interfaces.commands.interactive._questionary.ask_select"
_ASK_CHECKBOX = "cveta2.interfaces.commands.interactive._questionary.ask_checkbox"


def _choices() -> list[Choice]:
    return [Choice(title="Первый", value="one")]


# Each prompt invoked with only its required arguments, plus the questionary
# call it delegates to.
_PROMPTS: dict[str, tuple[str, Callable[..., object]]] = {
    "text": (_ASK_TEXT, lambda **kw: primitives.text("Имя:", hint=_HINT, **kw)),
    "path": (_ASK_TEXT, lambda **kw: primitives.path("Путь:", hint=_HINT, **kw)),
    "select_one": (
        _ASK_SELECT,
        lambda **kw: primitives.select_one("Выберите:", _choices(), hint=_HINT, **kw),
    ),
    "select_many": (
        _ASK_CHECKBOX,
        lambda **kw: primitives.select_many("Выберите:", _choices(), hint=_HINT, **kw),
    ),
}


@pytest.fixture
def interactive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CVETA2_NO_INTERACTIVE", raising=False)


@pytest.mark.parametrize(
    "prompt",
    [
        lambda: primitives.text("Имя:", hint=_HINT),
        lambda: primitives.confirm("Удалить?", hint=_HINT),
        lambda: primitives.path("Путь:", hint=_HINT),
        lambda: primitives.select_one("Выберите:", _choices(), hint=_HINT),
        lambda: primitives.select_many("Выберите:", _choices(), hint=_HINT),
        lambda: primitives.confirm_or_exit("Удалить?", yes=False, hint=_HINT),
    ],
    ids=["text", "confirm", "path", "select_one", "select_many", "confirm_or_exit"],
)
def test_noninteractive_raises_with_the_callers_hint(
    monkeypatch: pytest.MonkeyPatch, prompt: Callable[[], object]
) -> None:
    """The hint tells the user which flag replaces the prompt."""
    monkeypatch.setenv("CVETA2_NO_INTERACTIVE", "true")
    with pytest.raises(InteractiveModeRequiredError, match=_HINT):
        prompt()


@pytest.mark.usefixtures("interactive")
@pytest.mark.parametrize("name", list(_PROMPTS))
def test_cancel_exits_non_zero_by_default(name: str) -> None:
    target, prompt = _PROMPTS[name]
    with patch(target, return_value=None), pytest.raises(SystemExit) as excinfo:
        prompt()
    assert excinfo.value.code == primitives._CANCELLED


@pytest.mark.usefixtures("interactive")
@pytest.mark.parametrize("name", ["text", "path", "select_one"])
def test_cancel_none_returns_none(name: str) -> None:
    target, prompt = _PROMPTS[name]
    with patch(target, return_value=None):
        assert prompt(on_cancel="none") is None


@pytest.mark.usefixtures("interactive")
@pytest.mark.parametrize(
    ("name", "answer", "expected"),
    [("select_one", "one", "one"), ("select_many", ["one"], ["one"])],
)
def test_select_passes_message_and_choices_and_returns_the_answer(
    name: str, answer: object, expected: object
) -> None:
    target, _ = _PROMPTS[name]
    choices = _choices()
    select = getattr(primitives, name)
    with patch(target, return_value=answer) as ask:
        assert select("Выберите:", choices, hint=_HINT) == expected
    assert ask.call_args.args[0] == "Выберите:"
    assert ask.call_args.args[1] is choices


@pytest.mark.usefixtures("interactive")
@pytest.mark.parametrize("name", ["text", "path"])
def test_history_key_reaches_the_prompt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, name: str
) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    target, prompt = _PROMPTS[name]
    with patch(target, return_value="/x") as ask:
        prompt(history_key="task-name")
    history = ask.call_args.kwargs["history"]
    assert isinstance(history, FileHistory)
    assert str(history.filename).endswith("task-name")


class TestText:
    @pytest.mark.usefixtures("interactive")
    @pytest.mark.parametrize(
        ("answer", "default", "expected"),
        [
            ("  fish  ", None, "fish"),
            ("", "cat", "cat"),
            ("", None, ""),
        ],
        ids=["strips", "default-on-empty", "empty-allowed"],
    )
    def test_answer(self, answer: str, default: str | None, expected: str) -> None:
        with patch(_ASK_TEXT, return_value=answer):
            result = (
                primitives.text("Имя:", hint=_HINT)
                if default is None
                else primitives.text("Имя:", hint=_HINT, default=default)
            )
        assert result == expected

    @pytest.mark.usefixtures("interactive")
    def test_empty_disallowed_exits_with_the_empty_message(self) -> None:
        with patch(_ASK_TEXT, return_value=""), pytest.raises(SystemExit) as excinfo:
            primitives.text(
                "Имя:", hint=_HINT, allow_empty=False, empty_message="нет имени"
            )
        assert excinfo.value.code == "нет имени"

    @pytest.mark.usefixtures("interactive")
    def test_validate_callback_and_absent_history_are_forwarded(self) -> None:
        def _accept(_value: str) -> bool:
            return True

        with patch(_ASK_TEXT, return_value="v") as ask:
            primitives.text("Имя:", hint=_HINT, validate=_accept)
        assert ask.call_args.kwargs["validate"] is _accept
        assert ask.call_args.kwargs["history"] is None


class TestPromptHistory:
    def test_history_for_creates_dir_and_points_into_it(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        history = history_for("task-name")
        expected_dir = tmp_path / "cveta2" / "prompt_history"
        assert expected_dir.is_dir()
        assert history.filename == str(expected_dir / "task-name")

    def test_history_follows_default_cache_base(self, tmp_path: Path) -> None:
        with patch(
            "cveta2.interfaces.commands.interactive._history.default_cache_base",
            return_value=tmp_path / "elsewhere",
        ):
            history = history_for("k")
        assert history.filename == str(tmp_path / "elsewhere" / "prompt_history" / "k")

    def test_noninteractive_raises_before_history(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("CVETA2_NO_INTERACTIVE", "true")
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        with pytest.raises(InteractiveModeRequiredError):
            primitives.text("Имя:", hint=_HINT, history_key="task-name")
        assert not (tmp_path / "cveta2" / "prompt_history").exists()


@pytest.mark.usefixtures("interactive")
@pytest.mark.parametrize(
    ("answer", "expected"), [(None, False), (True, True), (False, False)]
)
def test_confirm_returns_the_answer_and_enter_means_no(
    *, answer: bool | None, expected: bool
) -> None:
    """A cancelled confirm counts as no; Enter defaults to no."""
    with patch(_ASK_CONFIRM, return_value=answer) as ask:
        assert primitives.confirm("Удалить?", hint=_HINT) is expected
    assert ask.call_args.kwargs["default"] is False


class TestConfirmOrExit:
    def test_yes_flag_skips_prompt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CVETA2_NO_INTERACTIVE", "true")
        primitives.confirm_or_exit("Удалить?", yes=True, hint=_HINT)

    @pytest.mark.usefixtures("interactive")
    def test_yes_proceeds_after_showing_the_message_with_no_default(self) -> None:
        """Enter must never mean "yes, delete" for a destructive action."""
        with patch(_ASK_CONFIRM, return_value=True) as ask:
            primitives.confirm_or_exit("Удалить проект?", yes=False, hint=_HINT)
        assert "Удалить проект?" in ask.call_args.args[0]
        assert ask.call_args.kwargs["default"] is False

    @pytest.mark.usefixtures("interactive")
    def test_interactive_no_exits_with_the_given_status(self) -> None:
        with (
            patch(_ASK_CONFIRM, return_value=False),
            pytest.raises(SystemExit) as excinfo,
        ):
            primitives.confirm_or_exit(
                "Удалить?", yes=False, hint=_HINT, on_no="прервано"
            )
        assert excinfo.value.code == "прервано"


class TestPath:
    @pytest.mark.usefixtures("interactive")
    def test_expands_user_and_resolves(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        with patch(_ASK_TEXT, return_value="~/sub/../file.txt"):
            assert primitives.path("Путь:", hint=_HINT) == tmp_path / "file.txt"

    @pytest.mark.usefixtures("interactive")
    def test_empty_input_returns_none(self) -> None:
        """Empty input means "no path", not the current directory."""
        with patch(_ASK_TEXT, return_value="   "):
            assert primitives.path("Путь:", hint=_HINT) is None


class TestSelectMany:
    @pytest.mark.usefixtures("interactive")
    @pytest.mark.parametrize(
        ("empty_message", "code"),
        [("ничего", "ничего"), (None, primitives._NOTHING_SELECTED)],
    )
    def test_empty_disallowed_exits_with_the_empty_message(
        self, empty_message: str | None, code: str
    ) -> None:
        def select() -> list[object] | None:
            if empty_message is None:
                return primitives.select_many("Выберите:", [], hint=_HINT)
            return primitives.select_many(
                "Выберите:", [], hint=_HINT, empty_message=empty_message
            )

        with (
            patch(_ASK_CHECKBOX, return_value=[]),
            pytest.raises(SystemExit) as excinfo,
        ):
            select()
        assert excinfo.value.code == code

    @pytest.mark.usefixtures("interactive")
    def test_empty_allowed_returns_empty(self) -> None:
        with patch(_ASK_CHECKBOX, return_value=[]):
            result = primitives.select_many(
                "Выберите:", [], hint=_HINT, on_cancel="none", allow_empty=True
            )
        assert result == []


@pytest.mark.usefixtures("interactive")
def test_prompt_password_forwards_the_caption() -> None:
    with patch("getpass.getpass", return_value="s3cret") as getpass_mock:
        assert primitives.prompt_password("Пароль: ") == "s3cret"
    assert getpass_mock.call_args.args == ("Пароль: ",)
