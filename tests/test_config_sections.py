"""Tests for config sections: image_cache, sync_roots, and preset priority."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from cveta2.config import (
    CacheProjectSettings,
    CvatConfig,
    ImageCacheConfig,
    SyncRootsConfig,
    load_cache_config,
    load_image_cache_config,
    load_sync_roots_config,
    save_cache_config,
    save_image_cache_config,
    save_sync_roots_config,
)

if TYPE_CHECKING:
    import pytest


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


def test_image_cache_missing_file(tmp_path: Path) -> None:
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


def test_sync_roots_missing_file(tmp_path: Path) -> None:
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


_CVAT_ENV_VARS = (
    "CVAT_HOST",
    "CVAT_ORGANIZATION",
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
    for var in ("CVAT_ORGANIZATION", "CVAT_USERNAME", "CVAT_PASSWORD"):
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


# ---------------------------------------------------------------------------
# cache section
# ---------------------------------------------------------------------------


def _write_cache_yaml(cfg_path: Path) -> None:
    cfg_path.write_text(
        yaml.safe_dump(
            {
                "cvat": {"host": "http://localhost:8080"},
                "cache": {
                    "images_root": "/mnt/datasets",
                    "tasks_root": "/mnt/task-cache",
                    "projects": {
                        "projA": {
                            "ignored_prefix": "data/projA",
                            "task_cache_s3": "s3://ml-cache/projA",
                        },
                        "projB": {"images_root": "/mnt/projB-images"},
                    },
                },
            }
        ),
        encoding="utf-8",
    )


def test_load_cache_config_resolves_overrides(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.yaml"
    _write_cache_yaml(cfg_path)
    cache = load_cache_config(cfg_path)

    proj_a = cache.for_project("projA")
    assert proj_a.images_root == Path("/mnt/datasets")
    assert proj_a.tasks_root == Path("/mnt/task-cache")
    assert proj_a.ignored_prefix == "data/projA"
    assert proj_a.task_cache_s3 == "s3://ml-cache/projA"

    proj_b = cache.for_project("projB")
    assert proj_b.images_root == Path("/mnt/projB-images")
    assert proj_b.tasks_root == Path("/mnt/task-cache")
    assert proj_b.ignored_prefix is None
    assert proj_b.task_cache_s3 is None

    unknown = cache.for_project("unknown")
    assert unknown.images_root == Path("/mnt/datasets")
    assert unknown.ignored_prefix is None


def test_cache_config_missing_section_and_file(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        yaml.safe_dump({"cvat": {"host": "http://localhost:8080"}}),
        encoding="utf-8",
    )
    assert load_cache_config(cfg_path).for_project("x") == CacheProjectSettings()
    missing = load_cache_config(tmp_path / "nonexistent.yaml")
    assert missing.images_root is None
    assert missing.tasks_root is None
    assert missing.projects == {}


def test_save_cache_config_round_trip(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.yaml"
    _write_cache_yaml(cfg_path)
    cache = load_cache_config(cfg_path)

    save_cache_config(cache, cfg_path)

    reloaded = load_cache_config(cfg_path)
    assert reloaded == cache
    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    assert data["cvat"]["host"] == "http://localhost:8080"


def test_setup_save_preserves_cache_section(tmp_path: Path) -> None:
    """CvatConfig.save_to_file (the ``setup`` path) keeps the cache section."""
    cfg_path = tmp_path / "config.yaml"
    _write_cache_yaml(cfg_path)

    CvatConfig(host="http://new-host:8080").save_to_file(cfg_path)

    reloaded = load_cache_config(cfg_path)
    assert reloaded.images_root == Path("/mnt/datasets")
    assert reloaded.for_project("projA").ignored_prefix == "data/projA"
    assert CvatConfig.from_file(cfg_path).host == "http://new-host:8080"
