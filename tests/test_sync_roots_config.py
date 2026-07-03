"""Tests for SyncRootsConfig model and config load/save."""

from __future__ import annotations

from typing import TYPE_CHECKING

import yaml

from cveta2.config import (
    SyncRootsConfig,
    load_sync_roots_config,
    save_sync_roots_config,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_load_config_with_sync_roots(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        yaml.safe_dump(
            {
                "cvat": {"host": "http://localhost:8080"},
                "sync_roots": {
                    "coco8-dev": "s3://bucket/images/my_favourite",
                    "other-project": "bare/prefix",
                },
            }
        ),
        encoding="utf-8",
    )
    cfg = load_sync_roots_config(cfg_path)
    assert cfg.get_root("coco8-dev") == "s3://bucket/images/my_favourite"
    assert cfg.get_root("other-project") == "bare/prefix"


def test_load_config_without_sync_roots(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        yaml.safe_dump({"cvat": {"host": "http://localhost:8080"}}),
        encoding="utf-8",
    )
    cfg = load_sync_roots_config(cfg_path)
    assert cfg.projects == {}


def test_load_config_missing_file(tmp_path: Path) -> None:
    cfg = load_sync_roots_config(tmp_path / "nonexistent.yaml")
    assert cfg.projects == {}


def test_load_config_invalid_section(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        yaml.safe_dump({"sync_roots": ["not", "a", "dict"]}),
        encoding="utf-8",
    )
    cfg = load_sync_roots_config(cfg_path)
    assert cfg.projects == {}


def test_save_load_round_trip_preserves_other_sections(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        yaml.safe_dump(
            {
                "cvat": {"host": "http://localhost:8080"},
                "image_cache": {"proj-a": "/data/a"},
            }
        ),
        encoding="utf-8",
    )

    save_sync_roots_config(
        SyncRootsConfig(projects={"proj-a": "s3://custom/images"}),
        cfg_path,
    )

    reloaded = load_sync_roots_config(cfg_path)
    assert reloaded.projects == {"proj-a": "s3://custom/images"}

    with cfg_path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    assert data["cvat"]["host"] == "http://localhost:8080"
    assert data["image_cache"]["proj-a"] == "/data/a"
    assert data["sync_roots"]["proj-a"] == "s3://custom/images"


def test_save_empty_config_removes_section(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        yaml.safe_dump({"sync_roots": {"proj": "old/root"}}),
        encoding="utf-8",
    )

    save_sync_roots_config(SyncRootsConfig(), cfg_path)

    with cfg_path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    assert "sync_roots" not in data


def test_get_root_unknown_project() -> None:
    cfg = SyncRootsConfig(projects={"known": "some/root"})
    assert cfg.get_root("unknown") is None
