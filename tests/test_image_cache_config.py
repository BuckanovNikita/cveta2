"""Tests for ImageCacheConfig model and config load/save."""

from __future__ import annotations

from pathlib import Path

import yaml

from cveta2.config import (
    ImageCacheConfig,
    load_image_cache_config,
    save_image_cache_config,
)


def test_load_config_with_image_cache(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        yaml.safe_dump(
            {
                "cvat": {"host": "http://localhost:8080"},
                "image_cache": {
                    "coco8-dev": "/mnt/data/coco8",
                    "other-project": "/mnt/data/other",
                },
            }
        ),
        encoding="utf-8",
    )
    ic = load_image_cache_config(cfg_path)
    assert ic.get_cache_dir("coco8-dev") == Path("/mnt/data/coco8")
    assert ic.get_cache_dir("other-project") == Path("/mnt/data/other")


def test_load_config_without_image_cache(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        yaml.safe_dump({"cvat": {"host": "http://localhost:8080"}}),
        encoding="utf-8",
    )
    ic = load_image_cache_config(cfg_path)
    assert ic.projects == {}


def test_load_config_missing_file(tmp_path: Path) -> None:
    ic = load_image_cache_config(tmp_path / "nonexistent.yaml")
    assert ic.projects == {}


def test_save_config_preserves_image_cache(tmp_path: Path) -> None:
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

    ic = load_image_cache_config(cfg_path)
    ic.set_cache_dir("proj-b", Path("/data/b"))
    save_image_cache_config(ic, cfg_path)

    # Reload and verify both sections exist
    with cfg_path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    assert data["cvat"]["host"] == "http://localhost:8080"
    assert data["image_cache"]["proj-a"] == "/data/a"
    assert data["image_cache"]["proj-b"] == "/data/b"


def test_get_cache_dir_known_project() -> None:
    ic = ImageCacheConfig(projects={"coco8-dev": Path("/mnt/data/coco8")})
    assert ic.get_cache_dir("coco8-dev") == Path("/mnt/data/coco8")


def test_get_cache_dir_unknown_project() -> None:
    ic = ImageCacheConfig(projects={"coco8-dev": Path("/mnt/data/coco8")})
    assert ic.get_cache_dir("unknown") is None


def test_set_cache_dir_adds_project() -> None:
    ic = ImageCacheConfig()
    ic.set_cache_dir("new-proj", Path("/data/new"))
    assert ic.get_cache_dir("new-proj") == Path("/data/new")


def test_set_cache_dir_overwrites_existing() -> None:
    ic = ImageCacheConfig(projects={"proj": Path("/old")})
    ic.set_cache_dir("proj", Path("/new"))
    assert ic.get_cache_dir("proj") == Path("/new")
