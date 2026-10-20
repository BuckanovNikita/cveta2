"""Removed automatic publication interfaces fail before performing effects."""

import inspect
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from cveta2.interfaces.api import fetch
from tests.helpers import parse_cli_args

if TYPE_CHECKING:
    from collections.abc import Callable


def test_fetch_has_no_automatic_publication_keyword() -> None:
    """Callers must select explicit preparation and publication instead."""
    assert "publish_clearml" not in inspect.signature(fetch).parameters


def test_removed_fetch_keyword_is_rejected_before_connecting(tmp_path: Path) -> None:
    """The former keyword fails at the public call boundary."""
    removed_options = {"publish_clearml": False}
    with pytest.raises(TypeError, match="publish_clearml"):
        cast("Callable[..., object]", fetch)(1, tmp_path / "out", **removed_options)
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize(
    "arguments",
    [["fetch", "-p", "1", "-o", "out", "--no-clearml"], ["setup-clearml"]],
)
def test_removed_cli_interfaces_are_rejected(arguments: list[str]) -> None:
    """Argparse reports removed flags and commands as usage errors."""
    with pytest.raises(SystemExit) as error:
        parse_cli_args(*arguments)
    assert error.value.code == 2


def test_legacy_config_is_ignored_without_rewriting(tmp_path: Path) -> None:
    """Loading supported settings leaves legacy configuration bytes untouched."""
    from cveta2.adapters.config.settings import CacheConfig

    config = tmp_path / "config.yaml"
    original = (
        b"clearml:\n  enabled: true\n  projects:\n"
        b"    P: {clearml_project: p, clearml_dataset: d}\n"
    )
    config.write_bytes(original)
    CacheConfig.load(config)
    assert config.read_bytes() == original
