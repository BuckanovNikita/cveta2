"""Unit tests for ClearML config section in cveta2.config."""

from __future__ import annotations

from typing import TYPE_CHECKING

import yaml

from cveta2.config import (
    ClearmlConfig,
    ClearmlProjectMapping,
    _parse_clearml_section,
    _serialize_clearml_section,
    is_clearml_disabled,
    load_clearml_config,
    save_clearml_config,
)
from tests.helpers import write_config_yaml

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


class TestParseClearmlSection:
    """Tests for _parse_clearml_section."""

    def test_none_returns_defaults(self) -> None:
        cfg = _parse_clearml_section(None)
        assert cfg.enabled is False
        assert cfg.projects == {}

    def test_non_dict_returns_defaults(self) -> None:
        cfg = _parse_clearml_section("invalid")
        assert cfg.enabled is False

    def test_enabled_false(self) -> None:
        cfg = _parse_clearml_section({"enabled": False})
        assert cfg.enabled is False

    def test_full_mapping(self) -> None:
        raw = {
            "enabled": True,
            "projects": {
                "My Project": {
                    "clearml_project": "team/datasets",
                    "clearml_dataset": "annotations-v2",
                }
            },
        }
        cfg = _parse_clearml_section(raw)
        assert cfg.enabled is True
        assert "My Project" in cfg.projects
        mapping = cfg.projects["My Project"]
        assert mapping.clearml_project == "team/datasets"
        assert mapping.clearml_dataset == "annotations-v2"

    def test_invalid_mapping_entry_skipped(self) -> None:
        raw = {
            "projects": {
                "Good": {
                    "clearml_project": "p",
                    "clearml_dataset": "d",
                },
                "Bad": "not a dict",
                "Missing": {"clearml_project": "p"},
            },
        }
        cfg = _parse_clearml_section(raw)
        assert len(cfg.projects) == 1
        assert "Good" in cfg.projects

    def test_non_bool_enabled_defaults_to_true(self) -> None:
        cfg = _parse_clearml_section({"enabled": "yes"})
        assert cfg.enabled is True


class TestSerializeClearmlSection:
    """Tests for _serialize_clearml_section."""

    def test_default_disabled_returns_none(self) -> None:
        cfg = ClearmlConfig(enabled=False, projects={})
        assert _serialize_clearml_section(cfg) is None

    def test_enabled_no_projects_serializes(self) -> None:
        cfg = ClearmlConfig(enabled=True, projects={})
        result = _serialize_clearml_section(cfg)
        assert result is not None
        assert result["enabled"] is True

    def test_roundtrip(self) -> None:
        original = ClearmlConfig(
            enabled=True,
            projects={
                "Proj": ClearmlProjectMapping(
                    clearml_project="team/ds",
                    clearml_dataset="annot",
                )
            },
        )
        serialized = _serialize_clearml_section(original)
        assert serialized is not None
        parsed = _parse_clearml_section(serialized)
        assert parsed.enabled == original.enabled
        assert parsed.projects["Proj"].clearml_project == "team/ds"
        assert parsed.projects["Proj"].clearml_dataset == "annot"


class TestGetMapping:
    """Tests for ClearmlConfig.get_mapping."""

    def test_existing_project(self) -> None:
        cfg = ClearmlConfig(
            projects={
                "A": ClearmlProjectMapping(clearml_project="p", clearml_dataset="d")
            }
        )
        mapping = cfg.get_mapping("A")
        assert mapping is not None
        assert mapping.clearml_project == "p"

    def test_missing_project(self) -> None:
        cfg = ClearmlConfig()
        assert cfg.get_mapping("nonexistent") is None


class TestLoadSaveClearmlConfig:
    """Tests for load_clearml_config and save_clearml_config."""

    def test_load_missing_file(self, tmp_path: Path) -> None:
        cfg = load_clearml_config(tmp_path / "nonexistent.yaml")
        assert cfg.enabled is False
        assert cfg.projects == {}

    def test_save_and_load(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.yaml"
        original = ClearmlConfig(
            enabled=True,
            projects={
                "Proj": ClearmlProjectMapping(
                    clearml_project="team/ds",
                    clearml_dataset="annot",
                )
            },
        )
        save_clearml_config(original, config_path)
        loaded = load_clearml_config(config_path)
        assert loaded.enabled is True
        assert "Proj" in loaded.projects
        assert loaded.projects["Proj"].clearml_dataset == "annot"

    def test_save_preserves_other_sections(self, tmp_path: Path) -> None:
        config_path = write_config_yaml(
            tmp_path / "config.yaml", cvat={"host": "https://example.com"}
        )
        cfg = ClearmlConfig(
            enabled=False,
            projects={
                "P": ClearmlProjectMapping(clearml_project="cp", clearml_dataset="cd")
            },
        )
        save_clearml_config(cfg, config_path)

        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        assert raw["cvat"]["host"] == "https://example.com"
        assert raw["clearml"]["enabled"] is False


class TestIsClearmlDisabled:
    """Tests for is_clearml_disabled."""

    def test_not_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CVETA2_CLEARML", raising=False)
        assert is_clearml_disabled() is False

    def test_set_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CVETA2_CLEARML", "false")
        assert is_clearml_disabled() is True

    def test_set_false_uppercase(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CVETA2_CLEARML", "FALSE")
        assert is_clearml_disabled() is True

    def test_set_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CVETA2_CLEARML", "true")
        assert is_clearml_disabled() is False
