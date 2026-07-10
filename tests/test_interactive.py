"""Tests for the shared interactive primitives."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from cveta2.commands.interactive import primitives
from cveta2.exceptions import InteractiveModeRequiredError

_HINT = "pass a flag instead"


class TestRequireInteractive:
    def test_text_raises_when_noninteractive(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CVETA2_NO_INTERACTIVE", "true")
        with pytest.raises(InteractiveModeRequiredError):
            primitives.text("Имя:", hint=_HINT)

    def test_confirm_raises_when_noninteractive(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CVETA2_NO_INTERACTIVE", "true")
        with pytest.raises(InteractiveModeRequiredError):
            primitives.confirm("Удалить?", hint=_HINT)


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
        monkeypatch.delenv("CVETA2_NO_INTERACTIVE", raising=False)
        with (
            patch(
                "cveta2.commands.interactive._questionary.ask_text",
                return_value=None,
            ),
            pytest.raises(SystemExit),
        ):
            primitives.text("Имя:", hint=_HINT, on_cancel="exit")

    def test_empty_disallowed_exits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CVETA2_NO_INTERACTIVE", raising=False)
        with (
            patch("cveta2.commands.interactive._questionary.ask_text", return_value=""),
            pytest.raises(SystemExit),
        ):
            primitives.text("Имя:", hint=_HINT, allow_empty=False)


class TestConfirm:
    def test_cancel_counts_as_no(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CVETA2_NO_INTERACTIVE", raising=False)
        with patch(
            "cveta2.commands.interactive._questionary.ask_confirm",
            return_value=None,
        ):
            assert primitives.confirm("Удалить?", hint=_HINT) is False


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
        with patch(
            "cveta2.commands.interactive._questionary.ask_confirm",
            return_value=True,
        ):
            primitives.confirm_or_exit("Удалить?", yes=False, hint=_HINT)

    def test_interactive_no_exits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CVETA2_NO_INTERACTIVE", raising=False)
        with (
            patch(
                "cveta2.commands.interactive._questionary.ask_confirm",
                return_value=False,
            ),
            pytest.raises(SystemExit),
        ):
            primitives.confirm_or_exit("Удалить?", yes=False, hint=_HINT)


class TestSelectMany:
    def test_empty_disallowed_exits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CVETA2_NO_INTERACTIVE", raising=False)
        with (
            patch(
                "cveta2.commands.interactive._questionary.ask_checkbox",
                return_value=[],
            ),
            pytest.raises(SystemExit),
        ):
            primitives.select_many("Выберите:", [], hint=_HINT)

    def test_empty_allowed_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CVETA2_NO_INTERACTIVE", raising=False)
        with patch(
            "cveta2.commands.interactive._questionary.ask_checkbox",
            return_value=[],
        ):
            result = primitives.select_many(
                "Выберите:", [], hint=_HINT, on_cancel="none", allow_empty=True
            )
        assert result == []
