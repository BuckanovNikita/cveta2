"""Tests for preset config loading priority: preset < user config < env."""

from __future__ import annotations

from typing import TYPE_CHECKING

import yaml

from cveta2.config import CvatConfig

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


_CVAT_ENV_VARS = (
    "CVAT_HOST",
    "CVAT_ORGANIZATION",
    "CVAT_TOKEN",
    "CVAT_USERNAME",
    "CVAT_PASSWORD",
)


def _clear_cvat_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in _CVAT_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def test_preset_provides_defaults(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no user config file and no env vars, preset values are used."""
    _clear_cvat_env(monkeypatch)

    cfg_path = tmp_path / "nonexistent.yaml"
    cfg = CvatConfig.load(config_path=cfg_path)

    assert cfg.host == "http://localhost:8080"


def test_user_config_overrides_preset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """User config file values override the preset."""
    _clear_cvat_env(monkeypatch)

    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        yaml.safe_dump({"cvat": {"host": "https://custom-cvat.example.com"}}),
        encoding="utf-8",
    )

    cfg = CvatConfig.load(config_path=cfg_path)
    assert cfg.host == "https://custom-cvat.example.com"


def test_env_overrides_all(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Env vars override both preset and user config."""
    monkeypatch.setenv("CVAT_HOST", "https://env-cvat.example.com")
    for var in ("CVAT_ORGANIZATION", "CVAT_TOKEN", "CVAT_USERNAME", "CVAT_PASSWORD"):
        monkeypatch.delenv(var, raising=False)

    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        yaml.safe_dump({"cvat": {"host": "https://file-cvat.example.com"}}),
        encoding="utf-8",
    )

    cfg = CvatConfig.load(config_path=cfg_path)
    assert cfg.host == "https://env-cvat.example.com"


def test_preset_does_not_override_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preset has no credentials; user-provided ones are preserved."""
    _clear_cvat_env(monkeypatch)

    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        yaml.safe_dump(
            {
                "cvat": {
                    "host": "http://localhost:8080",
                    "username": "admin",
                    "password": "secret",
                }
            }
        ),
        encoding="utf-8",
    )

    cfg = CvatConfig.load(config_path=cfg_path)
    assert cfg.username == "admin"
    assert cfg.password == "secret"
