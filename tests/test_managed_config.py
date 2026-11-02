"""Strict configuration ownership and user-reviewed migration regressions."""

import argparse
import json
import os
from pathlib import Path

import pytest
import yaml

from cveta2.adapters.config import project as project_config
from cveta2.adapters.config.project import (
    activate_migration,
    attach_project_config,
    load_project_config,
    migration_proposal,
    project_config_path,
    read_config,
    recover_migration,
)
from cveta2.adapters.config.settings import (
    CacheConfig,
    CvatConfig,
    IgnoreConfig,
    ImageCacheConfig,
    NetworkConfig,
    SyncRootsConfig,
)
from cveta2.domain.managed.models import ManagedError, MigrationRequired
from cveta2.interfaces.commands import setup
from cveta2.interfaces.commands.interactive import primitives


def write(path: Path, data: dict[str, object]) -> Path:
    """Write test-owned YAML without touching the real user configuration."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def shared(path: Path, host: str = "https://cvat.example") -> Path:
    """One project exposes every shared policy category."""
    return write(
        path,
        {
            "schema_version": 1,
            "cvat": {"host": host, "organization": "team"},
            "projects": {
                "main": {
                    "id": 7,
                    "name": "Main project",
                    "sync_root": "s3://bucket/images",
                    "ignored_prefix": "images/",
                    "task_cache_s3": "s3://bucket/cache",
                    "ignore": [{"id": 4, "name": "old"}],
                }
            },
            "datasets": {},
        },
    )


def personal(path: Path, reference: Path) -> Path:
    """Only local/authentication fields are present in a versioned personal file."""
    return write(
        path,
        {
            "schema_version": 1,
            "project_config": str(reference),
            "cvat": {"username": "alice", "password": "private"},
            "cache": {"images_root": "/local/images"},
        },
    )


def legacy(path: Path) -> Path:
    """Supply real identities for legacy name mappings through the discovery cache."""
    write(
        path.parent / "projects.yaml",
        {
            "organizations": [
                {"slug": "team", "projects": [{"id": 7, "name": "Main project"}]}
            ]
        },
    )
    return write(
        path,
        {
            "cvat": {
                "host": "https://cvat.example",
                "organization": "team",
                "username": "alice",
                "password": "private",
            },
            "sync_roots": {"Main project": "s3://bucket/images"},
            "ignore": {"Main project": [4]},
            "image_cache": {"Main project": "/local/images"},
            "cache": {
                "tasks_root": "/local/tasks",
                "projects": {
                    "Main project": {
                        "images_root": "/local/override",
                        "ignored_prefix": "images/",
                        "task_cache_s3": "s3://bucket/cache",
                    }
                },
            },
        },
    )


def test_selection_precedence_and_relative_saved_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Selection chooses one file, not a merge, and saved paths are anchored."""
    saved = shared(tmp_path / "saved.yaml")
    env = shared(tmp_path / "env.yaml", "https://env.example")
    explicit = shared(tmp_path / "explicit.yaml", "https://explicit.example")
    cfg = personal(tmp_path / "personal.yaml", Path("saved.yaml"))
    monkeypatch.delenv("CVETA2_PROJECT_CONFIG", raising=False)
    assert project_config_path(cfg) == saved
    monkeypatch.setenv("CVETA2_PROJECT_CONFIG", str(env))
    assert load_project_config(cfg).cvat.host == "https://env.example"
    assert load_project_config(cfg, explicit).cvat.host == "https://explicit.example"
    monkeypatch.setenv("CVETA2_PROJECT_CONFIG", str(tmp_path / "missing.yaml"))
    with pytest.raises(ManagedError, match="Cannot read"):
        load_project_config(cfg)


def test_attach_is_noninteractive_and_does_not_modify_shared(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Attach-only setup does not prompt for credentials or write shared data."""
    target = shared(tmp_path / "shared.yaml")
    cfg = write(tmp_path / "personal.yaml", {"network": {"s3_workers": 2}})
    before = target.read_bytes()
    monkeypatch.setenv("CVETA2_NO_INTERACTIVE", "true")
    setup.run_setup(
        argparse.Namespace(config=str(cfg), project_config=target, migrate_config=False)
    )
    assert target.read_bytes() == before
    assert read_config(cfg)["project_config"] == str(target)
    assert read_config(cfg)["network"] == {"s3_workers": 2}


@pytest.mark.parametrize(
    "fields",
    [
        {"sync_roots": {"main": "bad"}},
        {"cvat": {"host": "https://other"}},
        {"cache": {"projects": {"main": {"ignored_prefix": "bad"}}}},
    ],
)
def test_personal_cannot_override_shared(
    tmp_path: Path, fields: dict[str, object]
) -> None:
    """Shared ownership is enforced before resolving effective settings."""
    target = shared(tmp_path / "shared.yaml")
    cfg = write(
        tmp_path / "personal.yaml",
        {"schema_version": 1, "project_config": str(target), **fields},
    )
    with pytest.raises(ManagedError, match=r"Shared|shared"):
        CvatConfig.load(cfg)


def test_shared_identity_and_policy_readers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Existing readers receive shared policies and personal credentials/local paths."""
    target = shared(tmp_path / "shared.yaml")
    cfg = personal(tmp_path / "personal.yaml", target)
    monkeypatch.delenv("CVAT_HOST", raising=False)
    monkeypatch.delenv("CVAT_ORGANIZATION", raising=False)
    effective = CvatConfig.load(cfg)
    assert (
        effective.host,
        effective.organization,
        effective.username,
        effective.password,
    ) == ("https://cvat.example", "team", "alice", "private")
    assert SyncRootsConfig.load(cfg).get_root("Main project") == "s3://bucket/images"
    assert IgnoreConfig.load(cfg).get_ignored_tasks("Main project") == [4]
    cache = CacheConfig.load(cfg).for_project("Main project")
    assert cache.images_root == Path("/local/images")
    assert cache.task_cache_s3 == "s3://bucket/cache"
    monkeypatch.setenv("CVAT_HOST", "https://wrong.example")
    with pytest.raises(ManagedError, match="conflict"):
        CvatConfig.load(cfg)


def test_policy_writes_shared_and_local_cache_saves_stay_personal(
    tmp_path: Path,
) -> None:
    """No explicit policy operation manufactures a personal shadow setting."""
    target = shared(tmp_path / "shared.yaml")
    cfg = personal(tmp_path / "personal.yaml", target)
    roots = SyncRootsConfig.load(cfg)
    roots.projects["Main project"] = "s3://bucket/new"
    roots.save(cfg)
    assert load_project_config(cfg).projects["main"].sync_root == "s3://bucket/new"
    assert "sync_roots" not in read_config(cfg)
    target.chmod(0o444)
    before = target.read_bytes()
    cache = CacheConfig.load(cfg)
    cache.images_root = Path("/local/new")
    cache.save(cfg)
    assert target.read_bytes() == before
    assert "ignored_prefix" not in json.dumps(read_config(cfg))
    roots.projects["Main project"] = "s3://bucket/blocked"
    with pytest.raises(ManagedError, match="read-only"):
        roots.save(cfg)


def test_preview_has_no_writes_or_secrets_and_activation_preserves_backup(
    tmp_path: Path,
) -> None:
    """The exact split is reviewed first; backups retain original private bytes."""
    cfg = legacy(tmp_path / "personal.yaml")
    original = cfg.read_bytes()
    proposal = migration_proposal(cfg)
    assert not proposal.unresolved
    assert cfg.read_bytes() == original
    assert not proposal.shared_path.exists()
    assert "private" not in json.dumps(proposal.preview())
    activate_migration(proposal)
    assert read_config(cfg)["schema_version"] == 1
    cvat = read_config(cfg)["cvat"]
    assert isinstance(cvat, dict)
    assert "host" not in cvat
    project = load_project_config(cfg).projects["project-7"]
    assert project.id == 7
    assert project.sync_root == "s3://bucket/images"
    assert project.ignore == [{"id": 4, "name": ""}]
    assert "images_root" not in json.dumps(read_config(proposal.shared_path))
    backups = list(tmp_path.glob("*.bak"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == original
    assert backups[0].stat().st_mode & 0o077 == 0
    second = migration_proposal(cfg)
    assert activate_migration(second) == proposal.shared_path
    assert len(list(tmp_path.glob("*.bak"))) == 1


def test_ambiguous_identity_and_existing_shared_conflict_block(tmp_path: Path) -> None:
    """No task/project identity is fabricated from a legacy name."""
    cfg = legacy(tmp_path / "personal.yaml")
    (tmp_path / "projects.yaml").unlink()
    proposal = migration_proposal(cfg)
    assert any("identity" in item for item in proposal.unresolved)
    with pytest.raises(ManagedError, match="unresolved"):
        activate_migration(proposal)
    target = shared(tmp_path / "project-config.yaml", "https://different.example")
    before = target.read_bytes()
    assert migration_proposal(cfg).unresolved
    assert target.read_bytes() == before


def test_migration_cancel_and_stale_preview(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cancel is no-op; approval cannot activate a proposal of changed bytes."""
    cfg = legacy(tmp_path / "personal.yaml")
    original = cfg.read_bytes()
    monkeypatch.setattr(primitives, "confirm", lambda *_args, **_kwargs: False)
    setup.run_setup(
        argparse.Namespace(config=str(cfg), migrate_config=True, project_config=None)
    )
    assert cfg.read_bytes() == original
    assert not (tmp_path / "project-config.yaml").exists()
    proposal = migration_proposal(cfg)
    cfg.write_bytes(original + b"\n# changed\n")
    with pytest.raises(ManagedError, match="changed after"):
        activate_migration(proposal)


def test_interrupted_approved_activation_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A journal allows shared-first activation to resume after interruption."""
    cfg = legacy(tmp_path / "personal.yaml")
    proposal = migration_proposal(cfg)
    original_link = os.link
    monkeypatch.setattr(
        os,
        "link",
        lambda *_args: (_ for _ in ()).throw(OSError("interrupted")),
    )
    with pytest.raises(OSError, match="interrupted"):
        activate_migration(proposal)
    assert not proposal.shared_path.exists()
    assert cfg.read_bytes() == next(iter(tmp_path.glob("*.bak"))).read_bytes()
    monkeypatch.setattr(os, "link", original_link)
    assert recover_migration(cfg)
    assert load_project_config(cfg).projects["project-7"].id == 7
    assert not recover_migration(cfg)


def test_mixed_legacy_requires_review_and_duplicate_yaml_rejected(
    tmp_path: Path,
) -> None:
    """Legacy policies cannot bypass migration; YAML must be unambiguous."""
    cfg = legacy(tmp_path / "personal.yaml")
    with pytest.raises(MigrationRequired, match="migrate-config"):
        CvatConfig.load(cfg)
    shared_file = tmp_path / "duplicate.yaml"
    shared_file.write_text("schema_version: 1\nschema_version: 1\n", encoding="utf-8")
    with pytest.raises(ManagedError, match="unique"):
        attach_project_config(write(tmp_path / "fresh.yaml", {}), shared_file)


def test_unclassified_nested_fields_require_review(tmp_path: Path) -> None:
    """Never discard legacy nested settings from the migration preview."""
    cfg = legacy(tmp_path / "personal.yaml")
    raw = read_config(cfg)
    cvat = raw["cvat"]
    assert isinstance(cvat, dict)
    cvat["unknown_secret"] = "not-in-preview"
    write(cfg, raw)
    proposal = migration_proposal(cfg)
    assert any("cvat.unknown_secret" in item for item in proposal.unresolved)
    assert "not-in-preview" not in json.dumps(proposal.preview())
    with pytest.raises(ManagedError, match="unresolved"):
        activate_migration(proposal)


def test_recovery_after_shared_activation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep the original personal file recoverable if its final switch fails."""
    cfg = legacy(tmp_path / "personal.yaml")
    proposal = migration_proposal(cfg)
    original = cfg.read_bytes()
    replace = Path.replace

    def interrupted(path: Path, target: Path) -> Path:
        if path.name.startswith(f".{cfg.name}.migration-") and target == cfg:
            raise OSError("switch interrupted")
        return replace(path, target)

    monkeypatch.setattr(Path, "replace", interrupted)
    with pytest.raises(OSError, match="switch interrupted"):
        activate_migration(proposal)
    assert proposal.shared_path.exists()
    assert cfg.read_bytes() == original
    monkeypatch.setattr(Path, "replace", replace)
    assert recover_migration(cfg)
    assert load_project_config(cfg).projects["project-7"].id == 7


def test_migration_preserves_preexisting_hidden_stage_files(tmp_path: Path) -> None:
    """Only unique task-owned stages may be written or cleaned up."""
    cfg = legacy(tmp_path / "personal.yaml")
    proposal = migration_proposal(cfg)
    sentinels = [
        cfg.with_name(f".{cfg.name}.migration-next"),
        proposal.shared_path.with_name(f".{proposal.shared_path.name}.migration-next"),
    ]
    for path in sentinels:
        path.write_bytes(b"pre-existing user data")
    activate_migration(proposal)
    for path in sentinels:
        assert path.read_bytes() == b"pre-existing user data"
    stages = list(tmp_path.glob(".*.migration-*"))
    assert sorted(stages) == sorted(sentinels)
    assert cfg.stat().st_mode & 0o777 == 0o600
    assert next(iter(tmp_path.glob("*.bak"))).stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("mode", [0o664, 0o640, 0o660])
def test_shared_policy_edits_preserve_permissions(tmp_path: Path, mode: int) -> None:
    """An atomic policy edit preserves existing group access and ownership."""
    target = shared(tmp_path / "shared.yaml")
    cfg = personal(tmp_path / "personal.yaml", target)
    target.chmod(mode)
    group = target.stat().st_gid
    roots = SyncRootsConfig.load(cfg)
    roots.projects["Main project"] = "s3://bucket/revised"
    roots.save(cfg)
    assert target.stat().st_mode & 0o777 == mode
    assert target.stat().st_gid == group
    assert load_project_config(cfg).projects["main"].sync_root == "s3://bucket/revised"


def test_explicit_shared_path_without_saved_reference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """All explicit loaders use the same selected file without environment edits."""
    target = shared(tmp_path / "shared.yaml")
    cfg = write(
        tmp_path / "personal.yaml",
        {
            "schema_version": 1,
            "cvat": {"username": "alice", "password": "private"},
            "image_cache": {"main": "/local/images"},
            "cache": {"images_root": "/local/cache"},
            "network": {"cvat_workers": 2},
        },
    )
    monkeypatch.delenv("CVETA2_PROJECT_CONFIG", raising=False)
    before = cfg.read_bytes()
    assert CvatConfig.load(cfg, project_path=target).host == "https://cvat.example"
    assert ImageCacheConfig.load(cfg, project_path=target).get_cache_dir(
        "Main project"
    ) == Path("/local/images")
    assert (
        CacheConfig.load(cfg, project_path=target)
        .for_project("Main project")
        .task_cache_s3
        == "s3://bucket/cache"
    )
    assert NetworkConfig.resolve(cfg, project_path=target).cvat_workers == 2
    assert cfg.read_bytes() == before
    assert "CVETA2_PROJECT_CONFIG" not in os.environ


def test_concurrent_journal_is_not_overwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A transaction racing after preview cannot overwrite another journal."""
    cfg = legacy(tmp_path / "personal.yaml")
    proposal = migration_proposal(cfg)
    journal = cfg.with_name(f"{cfg.name}.migration.json")
    original_write = project_config._private_write

    def racing_write(
        path: Path,
        content: bytes,
        *,
        replace: bool = False,
        preserve_permissions: bool = False,
    ) -> None:
        if path == journal:
            path.write_bytes(b"another transaction")
        original_write(
            path, content, replace=replace, preserve_permissions=preserve_permissions
        )

    monkeypatch.setattr(project_config, "_private_write", racing_write)
    with pytest.raises(ManagedError, match="Another approved migration"):
        activate_migration(proposal)
    assert journal.read_bytes() == b"another transaction"
    assert not list(tmp_path.glob(".*.migration-*"))
    assert not proposal.shared_path.exists()
