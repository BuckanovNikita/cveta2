"""Tests for config sections: image_cache, sync_roots, and preset priority."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from cveta2.config import (
    CacheConfig,
    CacheProjectSettings,
    CvatConfig,
    ImageCacheConfig,
    NetworkConfig,
    SyncRootsConfig,
    _parse_int_env,
)
from tests.helpers import write_config_yaml


def test_load_config_with_image_cache(tmp_path: Path) -> None:
    cfg_path = write_config_yaml(
        tmp_path / "config.yaml",
        cvat={"host": "http://localhost:8080"},
        image_cache={
            "coco8-dev": "/mnt/data/coco8",
            "other-project": "/mnt/data/other",
        },
    )
    ic = ImageCacheConfig.load(cfg_path)
    assert ic.get_cache_dir("coco8-dev") == Path("/mnt/data/coco8")
    assert ic.get_cache_dir("other-project") == Path("/mnt/data/other")


def test_load_config_without_image_cache(tmp_path: Path) -> None:
    cfg_path = write_config_yaml(
        tmp_path / "config.yaml", cvat={"host": "http://localhost:8080"}
    )
    ic = ImageCacheConfig.load(cfg_path)
    assert ic.projects == {}


def test_image_cache_missing_file(tmp_path: Path) -> None:
    ic = ImageCacheConfig.load(tmp_path / "nonexistent.yaml")
    assert ic.projects == {}


def test_save_config_preserves_image_cache(tmp_path: Path) -> None:
    cfg_path = write_config_yaml(
        tmp_path / "config.yaml",
        cvat={"host": "http://localhost:8080"},
        image_cache={"proj-a": "/data/a"},
    )

    ic = ImageCacheConfig.load(cfg_path)
    ic.set_cache_dir("proj-b", Path("/data/b"))
    ic.save(cfg_path)

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
    cfg_path = write_config_yaml(
        tmp_path / "config.yaml",
        cvat={"host": "http://localhost:8080"},
        sync_roots={
            "coco8-dev": "s3://bucket/images/my_favourite",
            "other-project": "bare/prefix",
        },
    )
    cfg = SyncRootsConfig.load(cfg_path)
    assert cfg.get_root("coco8-dev") == "s3://bucket/images/my_favourite"
    assert cfg.get_root("other-project") == "bare/prefix"


def test_load_config_without_sync_roots(tmp_path: Path) -> None:
    cfg_path = write_config_yaml(
        tmp_path / "config.yaml", cvat={"host": "http://localhost:8080"}
    )
    cfg = SyncRootsConfig.load(cfg_path)
    assert cfg.projects == {}


def test_sync_roots_missing_file(tmp_path: Path) -> None:
    cfg = SyncRootsConfig.load(tmp_path / "nonexistent.yaml")
    assert cfg.projects == {}


def test_load_config_invalid_section(tmp_path: Path) -> None:
    cfg_path = write_config_yaml(
        tmp_path / "config.yaml", sync_roots=["not", "a", "dict"]
    )
    cfg = SyncRootsConfig.load(cfg_path)
    assert cfg.projects == {}


def test_save_load_round_trip_preserves_other_sections(tmp_path: Path) -> None:
    cfg_path = write_config_yaml(
        tmp_path / "config.yaml",
        cvat={"host": "http://localhost:8080"},
        image_cache={"proj-a": "/data/a"},
    )

    SyncRootsConfig(projects={"proj-a": "s3://custom/images"}).save(cfg_path)

    reloaded = SyncRootsConfig.load(cfg_path)
    assert reloaded.projects == {"proj-a": "s3://custom/images"}

    with cfg_path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    assert data["cvat"]["host"] == "http://localhost:8080"
    assert data["image_cache"]["proj-a"] == "/data/a"
    assert data["sync_roots"]["proj-a"] == "s3://custom/images"


def test_save_empty_config_removes_section(tmp_path: Path) -> None:
    cfg_path = write_config_yaml(
        tmp_path / "config.yaml", sync_roots={"proj": "old/root"}
    )

    SyncRootsConfig().save(cfg_path)

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


def test_default_config_path_is_not_the_real_home() -> None:
    """The import-time CONFIG_PATH must point inside the throwaway test home.

    ``CvatConfig.save`` and ``CvatConfig.from_file`` take ``path=CONFIG_PATH`` as
    a default argument, bound when the module is imported — no fixture can
    redirect it afterwards. If ``tests/env_isolation.py`` stops being loaded
    (``-p tests.env_isolation`` in addopts), those defaults silently point at the
    developer's real ``~/.config/cveta2/`` and a stray no-path call overwrites it.
    """
    from cveta2.config import CONFIG_DIR, CONFIG_PATH

    assert "cveta2-test-home-" in str(CONFIG_DIR)
    assert CONFIG_PATH == CONFIG_DIR / "config.yaml"


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

    cfg_path = write_config_yaml(
        tmp_path / "config.yaml", cvat={"host": "https://custom-cvat.example.com"}
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

    cfg_path = write_config_yaml(
        tmp_path / "config.yaml", cvat={"host": "https://file-cvat.example.com"}
    )

    cfg = CvatConfig.load(config_path=cfg_path)
    assert cfg.host == "https://env-cvat.example.com"


def test_preset_does_not_override_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preset has no credentials; user-provided ones are preserved."""
    _clear_cvat_env(monkeypatch)

    cfg_path = write_config_yaml(
        tmp_path / "config.yaml",
        cvat={
            "host": "http://localhost:8080",
            "username": "admin",
            "password": "secret",
        },
    )

    cfg = CvatConfig.load(config_path=cfg_path)
    assert cfg.username == "admin"
    assert cfg.password == "secret"


# ---------------------------------------------------------------------------
# cache section
# ---------------------------------------------------------------------------


def _write_cache_yaml(cfg_path: Path) -> None:
    write_config_yaml(
        cfg_path,
        cvat={"host": "http://localhost:8080"},
        cache={
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
    )


def test_load_cache_config_resolves_overrides(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.yaml"
    _write_cache_yaml(cfg_path)
    cache = CacheConfig.load(cfg_path)

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
    cfg_path = write_config_yaml(
        tmp_path / "config.yaml", cvat={"host": "http://localhost:8080"}
    )
    assert CacheConfig.load(cfg_path).for_project("x") == CacheProjectSettings()
    missing = CacheConfig.load(tmp_path / "nonexistent.yaml")
    assert missing.images_root is None
    assert missing.tasks_root is None
    assert missing.projects == {}


def test_save_cache_config_round_trip(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.yaml"
    _write_cache_yaml(cfg_path)
    cache = CacheConfig.load(cfg_path)

    cache.save(cfg_path)

    reloaded = CacheConfig.load(cfg_path)
    assert reloaded == cache
    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    assert data["cvat"]["host"] == "http://localhost:8080"


def test_setup_save_preserves_cache_section(tmp_path: Path) -> None:
    """CvatConfig.save_to_file (the ``setup`` path) keeps the cache section."""
    cfg_path = tmp_path / "config.yaml"
    _write_cache_yaml(cfg_path)

    CvatConfig(host="http://new-host:8080").save_to_file(cfg_path)

    reloaded = CacheConfig.load(cfg_path)
    assert reloaded.images_root == Path("/mnt/datasets")
    assert reloaded.for_project("projA").ignored_prefix == "data/projA"
    assert CvatConfig.from_file(cfg_path).host == "http://new-host:8080"


def test_save_cache_config_drops_all_default_project_entries(tmp_path: Path) -> None:
    """A project whose overrides are all defaults must not reach the file.

    The existing round trip only reloaded what it had just saved, so it could
    not see the pruning at all: an unpruned ``{"empty": {}}`` reloads into an
    equal-looking ``CacheProjectSettings()``.
    """
    cfg_path = tmp_path / "custom.yaml"
    CacheConfig(
        images_root=Path("/root"),
        projects={
            "real": CacheProjectSettings(ignored_prefix="data/real"),
            "empty": CacheProjectSettings(),
        },
    ).save(cfg_path)

    assert set(CacheConfig.load(cfg_path).projects) == {"real"}


def test_save_cache_config_omits_projects_when_every_entry_is_default(
    tmp_path: Path,
) -> None:
    """Pruning everything removes the ``projects`` key rather than leaving ``{}``.

    This is the branch that pops the key, and it also pins ``exclude_defaults``:
    without it the unset ``tasks_root`` would be written back as ``null``.
    """
    cfg_path = tmp_path / "custom.yaml"
    CacheConfig(
        images_root=Path("/root"), projects={"empty": CacheProjectSettings()}
    ).save(cfg_path)

    raw = yaml.safe_load(cfg_path.read_bytes())
    assert raw["cache"] == {"images_root": "/root"}


# ---------------------------------------------------------------------------
# env / merge precedence
# ---------------------------------------------------------------------------


def test_from_env_reads_every_cvat_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    """All four CVAT variables are read, each from its own name.

    Earlier tests either deleted these variables or asserted only ``host``, so
    every other assignment could be dropped, misspelled or replaced by ``None``
    without a single failure.
    """
    monkeypatch.setenv("CVAT_HOST", "https://env.example")
    monkeypatch.setenv("CVAT_ORGANIZATION", "env-org")
    monkeypatch.setenv("CVAT_USERNAME", "env-user")
    monkeypatch.setenv("CVAT_PASSWORD", "env-pass")

    cfg = CvatConfig.from_env()

    assert cfg.host == "https://env.example"
    assert cfg.organization == "env-org"
    assert cfg.username == "env-user"
    assert cfg.password == "env-pass"


@pytest.mark.parametrize(
    "field",
    ["host", "organization", "username", "password"],
    ids=["host", "organization", "username", "password"],
)
def test_merge_prefers_a_set_override_and_keeps_the_base_otherwise(
    field: str,
) -> None:
    """Each string field independently follows ``override or self``.

    ``request_timeout`` had its own precedence table; the four ``or`` fallbacks
    did not, so ``organization`` in particular could become ``and`` (yielding
    the base value even when the override was set) unnoticed.
    """
    base = CvatConfig.model_validate({field: "from-base"})
    override = CvatConfig.model_validate({field: "from-override"})

    assert base.merge(CvatConfig()).model_dump()[field] == "from-base"
    assert base.merge(override).model_dump()[field] == "from-override"


def test_load_prefers_an_explicit_path_over_the_env_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``CvatConfig.load(config_path=...)`` must not read ``CVETA2_CONFIG``.

    Every earlier test wrote its config to ``tmp_path/"config.yaml"``, which is
    exactly where the autouse fixture points ``CVETA2_CONFIG`` — so dropping
    the explicit argument made no observable difference.
    """
    _clear_cvat_env(monkeypatch)
    monkeypatch.setenv(
        "CVETA2_CONFIG",
        str(
            write_config_yaml(
                tmp_path / "env.yaml", cvat={"host": "https://from-env-var.example"}
            )
        ),
    )
    explicit = write_config_yaml(
        tmp_path / "explicit.yaml", cvat={"host": "https://from-argument.example"}
    )

    assert CvatConfig.load(config_path=explicit).host == "https://from-argument.example"


def test_section_load_and_save_prefer_an_explicit_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same argument-over-env rule for the generic section load/save."""
    env_path = write_config_yaml(tmp_path / "env.yaml", sync_roots={"p": "env/root"})
    monkeypatch.setenv("CVETA2_CONFIG", str(env_path))
    explicit = write_config_yaml(
        tmp_path / "explicit.yaml", sync_roots={"p": "explicit/root"}
    )

    assert SyncRootsConfig.load(explicit).get_root("p") == "explicit/root"

    SyncRootsConfig(projects={"p": "written/root"}).save(explicit)

    assert SyncRootsConfig.load(explicit).get_root("p") == "written/root"
    assert SyncRootsConfig.load(env_path).get_root("p") == "env/root"


# ---------------------------------------------------------------------------
# writing the config file
# ---------------------------------------------------------------------------


def test_section_save_creates_missing_directories(tmp_path: Path) -> None:
    """``mkdir(parents=True)`` — a first-run config dir may not exist yet.

    Every earlier save targeted ``tmp_path`` itself, whose parent always
    exists, so ``parents=True`` was never load-bearing.
    """
    target = tmp_path / "nested" / "deeper" / "custom.yaml"

    SyncRootsConfig(projects={"p": "root"}).save(target)

    assert SyncRootsConfig.load(target).get_root("p") == "root"


def test_section_save_keeps_the_existing_section_order(tmp_path: Path) -> None:
    """``sort_keys=False`` keeps a hand-edited config in the order it was in.

    The file is read back by ``safe_load``, which is order-blind, so nothing
    else can see the difference — but a user re-opening their config can.
    """
    cfg_path = tmp_path / "custom.yaml"
    cfg_path.write_bytes(b"cvat:\n  host: http://localhost:8080\ncache:\n  x: 1\n")

    SyncRootsConfig(projects={"p": "root"}).save(cfg_path)

    assert list(yaml.safe_load(cfg_path.read_bytes())) == [
        "cvat",
        "cache",
        "sync_roots",
    ]


def test_save_to_file_keeps_the_cvat_section_first(tmp_path: Path) -> None:
    """``save_to_file`` rebuilds the mapping with ``cvat`` first, on purpose."""
    cfg_path = tmp_path / "custom.yaml"
    cfg_path.write_bytes(b"cache:\n  images_root: /r\ncvat:\n  host: old\n")

    CvatConfig(host="https://new.example").save_to_file(cfg_path)

    assert list(yaml.safe_load(cfg_path.read_bytes())) == ["cvat", "cache"]


def test_save_to_file_creates_missing_directories(tmp_path: Path) -> None:
    """A ``setup`` run into a fresh ``~/.config/cveta2`` must create it."""
    cfg_path = tmp_path / "nested" / "deeper" / "custom.yaml"

    CvatConfig(host="https://new.example").save_to_file(cfg_path)

    assert CvatConfig.from_file(cfg_path).host == "https://new.example"


def test_save_to_file_persists_every_optional_cvat_key(tmp_path: Path) -> None:
    """Every optional ``cvat`` key survives the round trip.

    ``request_timeout`` already had a test; ``organization``/``username``/
    ``password`` did not, so their keys could be misspelled or their values
    replaced by ``None`` undetected.
    """
    cfg_path = tmp_path / "custom.yaml"

    CvatConfig(
        host="https://x.example",
        organization="acme",
        username="user1",
        password="secret",
    ).save_to_file(cfg_path)

    reloaded = CvatConfig.from_file(cfg_path)
    assert reloaded.organization == "acme"
    assert reloaded.username == "user1"
    assert reloaded.password == "secret"


def test_save_to_file_leaves_the_image_cache_section_alone(
    tmp_path: Path,
) -> None:
    """``setup`` writes only ``cvat``; ``setup-cache`` owns ``image_cache``."""
    cfg_path = write_config_yaml(
        tmp_path / "custom.yaml",
        cvat={"host": "http://localhost:8080"},
        image_cache={"proj": "/data/existing"},
    )

    CvatConfig(host="https://new.example").save_to_file(cfg_path)

    assert ImageCacheConfig.load(cfg_path).get_cache_dir("proj") == Path(
        "/data/existing"
    )


# ---------------------------------------------------------------------------
# network section
# ---------------------------------------------------------------------------


def test_network_defaults_keep_cvat_below_s3() -> None:
    """CVAT rate-limits long before object storage does.

    Equal worker counts would spend the extra CVAT parallelism on 429
    backoff sleeps, which is slower than not fanning out at all.
    """
    network = NetworkConfig()

    assert network.cvat_workers < network.s3_workers
    assert network.retry_attempts > 1


def test_network_section_is_read_from_the_config_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every field comes from the file, and the explicit path wins over env."""
    monkeypatch.setenv("CVETA2_CONFIG", str(tmp_path / "env.yaml"))
    explicit = write_config_yaml(
        tmp_path / "explicit.yaml",
        cvat={"host": "http://localhost:8080"},
        network={
            "s3_workers": 32,
            "cvat_workers": 2,
            "retry_attempts": 9,
            "retry_max_wait": 90.0,
        },
    )

    network = NetworkConfig.resolve(explicit)

    assert (network.s3_workers, network.cvat_workers) == (32, 2)
    assert (network.retry_attempts, network.retry_max_wait) == (9, 90.0)


def test_environment_overrides_the_config_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """These are the knobs to turn for one run on a rate-limited link."""
    cfg_path = write_config_yaml(
        tmp_path / "config.yaml",
        cvat={"host": "http://localhost:8080"},
        network={"s3_workers": 32, "cvat_workers": 8, "retry_attempts": 3},
    )
    monkeypatch.setenv("CVETA2_S3_WORKERS", "4")
    monkeypatch.setenv("CVETA2_CVAT_WORKERS", "1")
    monkeypatch.setenv("CVETA2_RETRY_ATTEMPTS", "11")

    network = NetworkConfig.resolve(cfg_path)

    assert (network.s3_workers, network.cvat_workers) == (4, 1)
    assert network.retry_attempts == 11


@pytest.mark.parametrize("raw", ["abc", "0", "-3", ""], ids=list("abcd"))
def test_unusable_environment_values_fall_back_to_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    """A typo must not silently serialize every transfer or crash the run."""
    cfg_path = write_config_yaml(
        tmp_path / "config.yaml",
        cvat={"host": "http://localhost:8080"},
        network={"s3_workers": 12},
    )
    monkeypatch.setenv("CVETA2_S3_WORKERS", raw)

    assert NetworkConfig.resolve(cfg_path).s3_workers == 12


@pytest.mark.parametrize("raw", ["0", "-3"], ids=["zero", "negative"])
def test_a_worker_count_below_one_is_reported_not_swallowed(
    monkeypatch: pytest.MonkeyPatch, capture_logs: list[str], raw: str
) -> None:
    """Falling back silently would look like the setting had been applied.

    Zero is the case worth naming: the fallback also happens to be reached
    because ``0`` is falsy, so nothing downstream can tell an ignored value
    from an honoured one.
    """
    monkeypatch.setenv("CVETA2_S3_WORKERS", raw)

    assert _parse_int_env("CVETA2_S3_WORKERS") is None
    assert any("CVETA2_S3_WORKERS" in message for message in capture_logs)


@pytest.mark.parametrize(
    "section",
    [{"s3_workers": 0}, {"cvat_workers": -1}, {"retry_attempts": 1}],
    ids=["no_s3_workers", "negative_cvat_workers", "retry_attempts_too_low"],
)
def test_worker_counts_that_cannot_work_are_rejected_at_load(
    tmp_path: Path, section: dict[str, int]
) -> None:
    """Zero workers is a hang and one attempt is no retry at all.

    Rejecting at load names the setting; accepting it produces a run that
    quietly does nothing the setting promised.
    """
    cfg_path = write_config_yaml(
        tmp_path / "config.yaml",
        cvat={"host": "http://localhost:8080"},
        network=section,
    )

    with pytest.raises(ValidationError):
        NetworkConfig.resolve(cfg_path)
