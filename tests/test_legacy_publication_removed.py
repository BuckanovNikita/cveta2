"""Removed automatic publication interfaces fail before performing effects."""

from pathlib import Path

import pytest

from cveta2.domain.managed.models import MigrationRequired
from tests.helpers import parse_cli_args


@pytest.mark.parametrize(
    "arguments",
    [
        ["fetch", "-p", "1", "-o", "out", "--no-clearml"],
        ["setup-clearml"],
    ],
)
def test_removed_cli_interfaces_are_rejected(arguments: list[str]) -> None:
    """Argparse reports removed flags and commands as usage errors."""
    with pytest.raises(SystemExit) as error:
        parse_cli_args(*arguments)
    assert error.value.code == 2


def test_legacy_config_requires_review_without_rewriting(tmp_path: Path) -> None:
    """Retired publication mappings require reviewed migration, never effects."""
    from cveta2.adapters.config.settings import CacheConfig

    config = tmp_path / "config.yaml"
    original = b"clearml:\n  enabled: true\n  projects:\n    P: {clearml_project: p, clearml_dataset: d}\n"
    config.write_bytes(original)
    with pytest.raises(MigrationRequired, match="setup --migrate-config"):
        CacheConfig.load(config)
    assert config.read_bytes() == original
