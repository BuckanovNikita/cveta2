"""Unit tests for ClearML config section in cveta2.config."""

from __future__ import annotations

from typing import TYPE_CHECKING

import yaml

from cveta2.config import ClearmlConfig, ClearmlProjectMapping
from tests.helpers import write_config_yaml

if TYPE_CHECKING:
    from pathlib import Path


def _parse_clearml_section(raw: object) -> ClearmlConfig:
    """Mirror ``ClearmlConfig.load``'s section handling for an in-memory value."""
    if not isinstance(raw, dict):
        return ClearmlConfig()
    return ClearmlConfig.model_validate(ClearmlConfig._wrap_raw(raw))


class TestParseClearmlSection:
    """Tests for the clearml section parsing (load path)."""

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

    def test_missing_enabled_key_reads_as_enabled(self) -> None:
        """A section written by hand without ``enabled:`` still turns ClearML on.

        Only the explicit ``enabled: false`` case was pinned, so the absent-key
        fallback could flip to ``False`` and silently disable publishing for
        everyone who configured only ``projects:``.
        """
        cfg = _parse_clearml_section(
            {"projects": {"P": {"clearml_project": "p", "clearml_dataset": "d"}}}
        )
        assert cfg.enabled is True
        assert "P" in cfg.projects

    def test_uncoercible_enabled_value_is_replaced_not_forwarded(self) -> None:
        """The normalized ``enabled`` must overwrite the raw one, not sit beside it.

        ``{"enabled": "yes"}`` could not show this: pydantic parses ``"yes"`` as
        a bool on its own, so leaving the raw value in place looked identical.
        A value pydantic cannot coerce does show it — forwarding it raises.
        """
        cfg = _parse_clearml_section({"enabled": "maybe"})
        assert cfg.enabled is True


class TestSerializeClearmlSection:
    """Tests for the clearml section serialization (save path)."""

    def test_default_disabled_returns_none(self) -> None:
        cfg = ClearmlConfig(enabled=False, projects={})
        assert cfg._to_raw() is None

    def test_enabled_no_projects_serializes(self) -> None:
        cfg = ClearmlConfig(enabled=True, projects={})
        result = cfg._to_raw()
        assert isinstance(result, dict)
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
        serialized = original._to_raw()
        assert isinstance(serialized, dict)
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
    """Tests for ClearmlConfig.load / ClearmlConfig.save."""

    def test_load_missing_file(self, tmp_path: Path) -> None:
        cfg = ClearmlConfig.load(tmp_path / "nonexistent.yaml")
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
        original.save(config_path)
        loaded = ClearmlConfig.load(config_path)
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
        cfg.save(config_path)

        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        assert raw["cvat"]["host"] == "https://example.com"
        assert raw["clearml"]["enabled"] is False
