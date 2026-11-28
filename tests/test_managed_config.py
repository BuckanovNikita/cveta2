"""Strict configuration ownership and user-reviewed migration regressions."""

import json
import multiprocessing
import os
import secrets
import stat
import sys
from collections.abc import Callable
from multiprocessing.connection import Connection as ProcessConnection
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from pydantic import ValidationError

from cveta2.adapters.config import project as project_config
from cveta2.adapters.config.project import (
    SharedConfigConflictError,
    SharedIdentityMismatchError,
    activate_migration,
    attach_project_config,
    load_global_config,
    load_project_config,
    migration_proposal,
    project_config_path,
    read_config,
    recover_migration,
    write_shared_project_fields,
)
from cveta2.adapters.config.settings import (
    CacheConfig,
    CacheProjectSettings,
    CvatConfig,
    IgnoreConfig,
    ImageCacheConfig,
    NetworkConfig,
    SyncRootsConfig,
    _split_cache_policy,
)
from cveta2.domain.managed.models import (
    CvatIdentity,
    ManagedError,
    MigrationRequired,
    ProjectConfig,
    ProjectDefinition,
)
from cveta2.domain.models import ProjectInfo
from cveta2.interfaces.commands import setup
from cveta2.interfaces.commands.interactive import primitives, wizard
from tests.helpers import parse_cli_args, write_config_yaml, write_split_config_yaml


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
            "global_config": str(reference),
            "cvat": {"username": "alice", "password": "private"},
            "cache": {"images_root": "/local/images"},
        },
    )


def legacy(path: Path) -> Path:
    """Supply real identities for legacy name mappings through the discovery cache."""
    write(
        path.parent / "projects.yaml",
        {"organizations": [{"slug": "team", "projects": [{"id": 7, "name": "Main project"}]}]},
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


def test_selection_precedence_and_relative_saved_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Selection chooses one file, not a merge, and saved paths are anchored."""
    saved = shared(tmp_path / "saved.yaml")
    env = shared(tmp_path / "env.yaml", "https://env.example")
    explicit = shared(tmp_path / "explicit.yaml", "https://explicit.example")
    cfg = personal(tmp_path / "personal.yaml", Path("saved.yaml"))
    monkeypatch.delenv("CVETA2_GLOBAL_CONFIG", raising=False)
    assert project_config_path(cfg) == saved
    monkeypatch.setenv("CVETA2_GLOBAL_CONFIG", str(env))
    assert load_project_config(cfg).cvat.host == "https://env.example"
    assert load_project_config(cfg, explicit).cvat.host == "https://explicit.example"
    monkeypatch.setenv("CVETA2_GLOBAL_CONFIG", str(tmp_path / "missing.yaml"))
    with pytest.raises(ManagedError, match="Cannot read"):
        load_project_config(cfg)


def test_attach_is_noninteractive_and_does_not_modify_shared(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Attach-only setup does not prompt for credentials or write shared data."""
    target = shared(tmp_path / "shared.yaml")
    cfg = write(tmp_path / "personal.yaml", {"network": {"s3_workers": 2}})
    before = target.read_bytes()
    monkeypatch.setenv("CVETA2_NO_INTERACTIVE", "true")
    setup.run_setup(parse_cli_args("setup", "--config", str(cfg), "--global-config", str(target)))
    assert target.read_bytes() == before
    assert read_config(cfg)["global_config"] == str(target)
    assert read_config(cfg)["network"] == {"s3_workers": 2}


@pytest.mark.parametrize(
    "fields",
    [
        {"sync_roots": {"main": "bad"}},
        {"cvat": {"host": "https://other"}},
        {"cache": {"projects": {"main": {"ignored_prefix": "bad"}}}},
    ],
)
def test_personal_cannot_override_shared(tmp_path: Path, fields: dict[str, object]) -> None:
    """Shared ownership is enforced before resolving effective settings."""
    target = shared(tmp_path / "shared.yaml")
    cfg = write(
        tmp_path / "personal.yaml",
        {"schema_version": 1, "global_config": str(target), **fields},
    )
    with pytest.raises(ManagedError, match=r"Shared|shared"):
        CvatConfig.load(cfg)


def test_shared_identity_and_policy_readers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
    assert SyncRootsConfig.load(cfg).get_root("main") == "s3://bucket/images"
    assert IgnoreConfig.load(cfg).get_ignored_tasks("main") == [4]
    cache = CacheConfig.load(cfg).for_project("main")
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
    roots.projects["main"] = "s3://bucket/new"
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
    roots.projects["main"] = "s3://bucket/blocked"
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
    assert read_config(cfg)["image_cache"] == {"project-7": "/local/images"}
    assert "name" not in project.model_dump()
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


def test_migration_cancel_and_stale_preview(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Cancel is no-op; approval cannot activate a proposal of changed bytes."""
    cfg = legacy(tmp_path / "personal.yaml")
    original = cfg.read_bytes()
    monkeypatch.setattr(primitives, "confirm", lambda *_args, **_kwargs: False)
    setup.run_setup(parse_cli_args("setup", "--config", str(cfg), "--migrate-config"))
    assert cfg.read_bytes() == original
    assert not (tmp_path / "project-config.yaml").exists()
    proposal = migration_proposal(cfg)
    cfg.write_bytes(original + b"\n# changed\n")
    with pytest.raises(ManagedError, match="changed after"):
        activate_migration(proposal)


def test_interrupted_approved_activation_recovers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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


@pytest.mark.parametrize(
    "document",
    [
        "cvat: {password: DO_NOT_LOG_SECRET, password: duplicate}\n",
        "ignore: [{7: DO_NOT_LOG_SECRET}]\n",
        "cvat: &recursive {password: DO_NOT_LOG_SECRET, nested: *recursive}\n",
        "ignore: &recursive [DO_NOT_LOG_SECRET, *recursive]\n",
    ],
    ids=["nested-duplicate", "sequence-non-string-key", "recursive-mapping", "recursive-sequence"],
)
def test_config_rejects_ambiguous_or_recursive_nested_yaml(tmp_path: Path, document: str) -> None:
    config = tmp_path / "config.yaml"
    config.write_text(document, encoding="utf-8")
    before = config.read_bytes()

    with pytest.raises(ManagedError) as caught:
        read_config(config)

    assert str(config) in str(caught.value)
    assert "DO_NOT_LOG_SECRET" not in str(caught.value)
    assert config.read_bytes() == before


def test_config_accepts_reused_nonrecursive_yaml_aliases(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text("first: &shared {name: cat}\nsecond: *shared\n", encoding="utf-8")

    assert read_config(config) == {"first": {"name": "cat"}, "second": {"name": "cat"}}


def test_migration_creates_missing_shared_destination_ancestors(tmp_path: Path) -> None:
    config = legacy(tmp_path / "personal.yaml")
    original = config.read_bytes()
    target = tmp_path / "new" / "team" / "shared.yaml"
    proposal = migration_proposal(config, project_path=target)

    assert activate_migration(proposal) == target

    assert load_project_config(config).projects["project-7"].id == 7
    assert next(tmp_path.glob("*.bak")).read_bytes() == original
    assert project_config_path(config) == target


def test_recovery_after_shared_activation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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


def test_migration_preserves_preexisting_hidden_stage_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Only unique task-owned stages may be written or cleaned up."""
    cfg = legacy(tmp_path / "personal.yaml")
    proposal = migration_proposal(cfg)
    sentinels = [
        cfg.with_name(f".{cfg.name}.migration-{'0' * 16}"),
        proposal.shared_path.with_name(f".{proposal.shared_path.name}.migration-{'0' * 16}"),
    ]
    for path in sentinels:
        path.write_bytes(b"pre-existing user data")
    # Backup, colliding personal stage, retry, colliding shared stage, retry, journal.
    tokens = iter(str(number) * 16 for number in (1, 0, 2, 0, 3, 4))
    monkeypatch.setattr(secrets, "token_hex", lambda _size: next(tokens))
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
    roots.projects["main"] = "s3://bucket/revised"
    roots.save(cfg)
    assert target.stat().st_mode & 0o777 == mode
    assert target.stat().st_gid == group
    assert load_project_config(cfg).projects["main"].sync_root == "s3://bucket/revised"


@pytest.mark.skipif(os.name != "posix", reason="POSIX supplementary group ownership")
def test_shared_policy_edit_preserves_a_different_team_group(tmp_path: Path) -> None:
    target = shared(tmp_path / "shared.yaml")
    groups = set(os.getgroups()) - {target.stat().st_gid}
    if not groups:
        pytest.skip("No supplementary group differs from the destination directory's group")
    team_group = min(groups)
    os.chown(target, -1, team_group)
    target.chmod(0o660)
    cfg = personal(tmp_path / "personal.yaml", target)
    roots = SyncRootsConfig.load(cfg)
    roots.projects["main"] = "s3://bucket/team"

    roots.save(cfg)

    assert target.stat().st_gid == team_group
    assert stat.S_IMODE(target.stat().st_mode) == 0o660
    assert load_project_config(cfg).projects["main"].sync_root == "s3://bucket/team"


def test_shared_policy_save_without_posix_ownership_capabilities(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exercise the Windows ownership guard with real IO, not native Windows locking."""
    target = shared(tmp_path / "shared.yaml")
    cfg = personal(tmp_path / "personal.yaml", target)
    mode = stat.S_IMODE(target.stat().st_mode)
    roots = SyncRootsConfig.load(cfg)
    roots.projects["main"] = "s3://bucket/windows"
    windows_os = SimpleNamespace(
        name="nt",
        environ=os.environ,
        O_RDWR=os.O_RDWR,
        O_WRONLY=os.O_WRONLY,
        O_CREAT=os.O_CREAT,
        O_EXCL=os.O_EXCL,
        SEEK_SET=os.SEEK_SET,
        open=os.open,
        close=os.close,
        fstat=os.fstat,
        write=os.write,
        lseek=os.lseek,
        fdopen=os.fdopen,
        fsync=os.fsync,
    )
    monkeypatch.setattr(project_config, "os", windows_os)

    roots.save(cfg)

    assert stat.S_IMODE(target.stat().st_mode) == mode
    assert load_project_config(cfg).projects["main"].sync_root == "s3://bucket/windows"


def test_explicit_shared_path_without_saved_reference(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
    monkeypatch.delenv("CVETA2_GLOBAL_CONFIG", raising=False)
    before = cfg.read_bytes()
    assert CvatConfig.load(cfg, project_path=target).host == "https://cvat.example"
    assert ImageCacheConfig.load(cfg, project_path=target).get_cache_dir("main") == Path("/local/images")
    assert CacheConfig.load(cfg, project_path=target).for_project("Renamed", 7).task_cache_s3 == "s3://bucket/cache"
    assert NetworkConfig.resolve(cfg, project_path=target).cvat_workers == 2
    assert cfg.read_bytes() == before
    assert "CVETA2_GLOBAL_CONFIG" not in os.environ


def test_concurrent_journal_is_not_overwritten(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A transaction racing after preview cannot overwrite another journal."""
    cfg = legacy(tmp_path / "personal.yaml")
    proposal = migration_proposal(cfg)
    journal = cfg.with_name(f"{cfg.name}.migration.json")
    original_write = project_config._private_write

    def racing_write(path: Path, content: bytes, **kwargs: bool) -> None:
        if path == journal:
            path.write_bytes(b"another transaction")
        original_write(path, content, **kwargs)

    monkeypatch.setattr(project_config, "_private_write", racing_write)
    with pytest.raises(ManagedError, match="Another approved migration"):
        activate_migration(proposal)
    assert journal.read_bytes() == b"another transaction"
    assert not list(tmp_path.glob(".*.migration-*"))
    assert not proposal.shared_path.exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX owner-only file mode")
def test_interrupted_migration_claim_is_private_and_cleaned_up(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = legacy(tmp_path / "personal.yaml")
    original = cfg.read_bytes()
    proposal = migration_proposal(cfg)
    claimed: list[Path] = []

    def interrupted_stage(path: Path, _content: bytes, _purpose: str) -> Path:
        claimed.append(path)
        assert path.read_bytes() == b""
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        raise OSError("stage unavailable")

    monkeypatch.setattr(project_config, "_stage_bytes", interrupted_stage)
    previous_umask = os.umask(0)
    try:
        with pytest.raises(OSError, match="stage unavailable"):
            activate_migration(proposal)
    finally:
        os.umask(previous_umask)

    assert claimed
    assert all(not path.exists() for path in claimed)
    assert cfg.read_bytes() == original
    assert not proposal.shared_path.exists()


# ---------------------------------------------------------------------------
# Legacy migration review and attachment validation
# ---------------------------------------------------------------------------


def _legacy_registry(tmp_path: Path, names: dict[str, int], ignore: dict[str, object] | None = None) -> Path:
    path = tmp_path / "personal.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "cvat": {"host": "https://cvat.example"},
                "sync_roots": {name: f"s3://bucket/{identity}" for name, identity in names.items()},
                "ignore": ignore or {},
            }
        )
    )
    (tmp_path / "projects.yaml").write_text(
        yaml.safe_dump(
            {
                "organizations": [
                    {
                        "slug": "",
                        "projects": [{"id": identity, "name": name} for name, identity in names.items()],
                    }
                ]
            }
        )
    )
    return path


def test_migration_key_collision_requires_review_without_losing_active_policy(
    tmp_path: Path,
) -> None:
    """Generated and literal project keys cannot silently overwrite each other."""
    path = _legacy_registry(tmp_path, {"A B": 7, "project-7": 8})
    original = path.read_bytes()
    proposal = migration_proposal(path)
    assert any("collision" in reason.lower() for reason in proposal.unresolved)
    with pytest.raises(ManagedError, match="unresolved"):
        activate_migration(proposal)
    assert path.read_bytes() == original
    assert not proposal.shared_path.exists()


@pytest.mark.parametrize("legacy_key", ["sync_roots", "ignore", "unknown_section"])
def test_attachment_validates_final_versioned_bytes_before_write(tmp_path: Path, legacy_key: str) -> None:
    """Empty obsolete sections must not become invalid version-one state."""
    personal = tmp_path / "personal.yaml"
    personal.write_text(yaml.safe_dump({"cvat": {"username": "alice"}, legacy_key: {}}))
    shared = tmp_path / "shared.yaml"
    shared.write_text(yaml.safe_dump({"schema_version": 1, "cvat": {"host": "https://cvat.example"}}))
    original = personal.read_bytes()
    with pytest.raises(MigrationRequired):
        attach_project_config(personal, shared)
    assert personal.read_bytes() == original


def test_numeric_string_ignore_entries_survive_reviewed_migration(
    tmp_path: Path,
) -> None:
    """Legacy scalar and dictionary IDs retain the same exclusion semantics."""
    path = _legacy_registry(
        tmp_path,
        {"main": 7},
        {"main": [" 42 ", {"id": "43", "name": "old", "silent": True}]},
    )
    proposal = migration_proposal(path)
    assert not proposal.unresolved
    activate_migration(proposal)
    shared = yaml.safe_load(proposal.shared_path.read_bytes())
    assert shared["projects"]["main"]["ignore"] == [
        {"id": 42, "name": ""},
        {"id": 43, "name": "old", "description": "", "silent": True},
    ]


# ---------------------------------------------------------------------------
# Shared policy writers: registry keys and cache policy ownership
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["sync", "ignore", "cache"])
def test_shared_policy_writers_reject_unknown_registry_keys(tmp_path: Path, kind: str) -> None:
    """A rejected edit names the unknown source and leaves both files untouched."""
    personal = write_split_config_yaml(tmp_path / "personal.yaml", project_ids={"Friendly project": 7})
    shared = personal.with_name("personal-projects.yaml")
    before = personal.read_bytes(), shared.read_bytes()
    config: SyncRootsConfig | IgnoreConfig | CacheConfig
    if kind == "sync":
        config = SyncRootsConfig(projects={"unknown-project": "s3://bucket/new"})
    elif kind == "ignore":
        config = IgnoreConfig()
        config.add_task("unknown-project", 42, "ignored")
    else:
        config = CacheConfig(projects={"unknown-project": CacheProjectSettings(ignored_prefix="raw/")})
    with pytest.raises(ManagedError, match="unknown-project"):
        config.save(personal)
    assert (personal.read_bytes(), shared.read_bytes()) == before


def test_shared_policy_writers_accept_registry_key_alias(tmp_path: Path) -> None:
    """Both shared policy types accept stable keys when display names differ."""
    personal = write_split_config_yaml(tmp_path / "personal.yaml", project_ids={"Friendly project": 7})
    SyncRootsConfig(projects={"project-7": "s3://bucket/new"}).save(personal)
    ignored = IgnoreConfig()
    ignored.add_task("project-7", 42, "ignored")
    ignored.save(personal)
    project = load_project_config(personal).projects["project-7"]
    assert project.sync_root == "s3://bucket/new"
    assert project.ignore[0]["id"] == 42


def test_personal_cache_key_binding_survives_display_name_resolution(
    tmp_path: Path,
) -> None:
    """A shared registry key resolves to one display-name entry without path loss."""
    images = tmp_path / "personal-images"
    tasks = tmp_path / "personal-tasks"
    personal = write_split_config_yaml(
        tmp_path / "personal.yaml",
        project_ids={"Friendly project": 7},
        cache={
            "projects": {
                "project-7": {
                    "images_root": str(images),
                    "tasks_root": str(tasks),
                }
            }
        },
    )
    loaded = CacheConfig.load(personal)
    assert set(loaded.projects) == {"project-7"}
    effective = loaded.for_project("Renamed", 7)
    assert effective.images_root == images
    assert effective.tasks_root == tasks


def test_cache_writer_prunes_policy_only_bindings_from_personal_output(
    tmp_path: Path,
) -> None:
    """Shared-only updates leave neither shadow policy nor empty local aliases."""
    global_tasks = tmp_path / "global-tasks"
    other_tasks = tmp_path / "other-tasks"
    personal = write_split_config_yaml(
        tmp_path / "personal.yaml",
        project_ids={"Friendly project": 7, "Other project": 8},
        cache={"tasks_root": str(global_tasks)},
    )
    cache = CacheConfig.load(personal)
    cache.projects["project-7"] = CacheProjectSettings(ignored_prefix="raw/", task_cache_s3="s3://bucket/shared-cache")
    cache.projects["Other project"] = CacheProjectSettings(tasks_root=other_tasks)
    cache.save(personal)

    shared = load_project_config(personal)
    assert shared.projects["project-7"].ignored_prefix == "raw/"
    assert shared.projects["project-7"].task_cache_s3 == "s3://bucket/shared-cache"
    assert read_config(personal)["cache"] == {
        "tasks_root": str(global_tasks),
        "projects": {"Other project": {"tasks_root": str(other_tasks)}},
    }


def test_malformed_cache_entry_does_not_skip_a_later_valid_policy(
    tmp_path: Path,
) -> None:
    """Defensive normalization must not discard later valid project changes."""
    shared = ProjectConfig(
        cvat=CvatIdentity(host="https://cvat.example"),
        projects={"main": ProjectDefinition(id=7)},
    )
    images = tmp_path / "images"
    values: dict[str, object] = {
        "projects": {
            "malformed": None,
            "main": {"ignored_prefix": "raw/", "images_root": str(images)},
        }
    }
    changes = _split_cache_policy(values, shared)
    assert changes == {"main": {"ignored_prefix": "raw/"}}
    assert values == {"projects": {"main": {"images_root": str(images)}}}


def test_global_cache_save_ignores_duplicate_legacy_project_names(
    tmp_path: Path,
) -> None:
    """The project IDs distinguish definitions even when two cached names coincide."""
    shared = write_config_yaml(
        tmp_path / "shared.yaml",
        schema_version=1,
        cvat={"host": "https://cvat.example"},
        projects={
            "first": {"id": 7, "name": "Collision"},
            "second": {"id": 8, "name": "Collision"},
        },
        datasets={},
    )
    personal = write_config_yaml(tmp_path / "personal.yaml", schema_version=1, global_config=str(shared))
    shared_before = shared.read_bytes()
    with pytest.warns(UserWarning, match="name is obsolete"):
        CacheConfig(images_root=tmp_path / "local-images").save(personal)
    assert CacheConfig.load(personal).images_root == tmp_path / "local-images"
    assert shared.read_bytes() == shared_before


# ---------------------------------------------------------------------------
# Shared identity and credential load/save boundaries
# ---------------------------------------------------------------------------


def shared_personal(path: Path) -> Path:
    """Create an explicit shared identity with independently owned credentials."""
    return write_split_config_yaml(
        path,
        project_ids={"Source": 71},
        cvat={
            "host": "https://shared.example",
            "organization": "team",
            "username": "old-user",
            "password": "old-password",
        },
        image_cache={"Source": "/local/images"},
    )


@pytest.mark.parametrize("organization", ["team", "other-team"])
def test_shared_loader_accepts_only_matching_environment_organization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, organization: str
) -> None:
    """Organization identity is checked independently from the matching host."""
    path = shared_personal(tmp_path / "personal.yaml")
    monkeypatch.setenv("CVAT_HOST", "https://shared.example/")
    monkeypatch.setenv("CVAT_ORGANIZATION", organization)
    monkeypatch.setenv("CVAT_USERNAME", "env-user")
    monkeypatch.setenv("CVAT_PASSWORD", "env-password")
    monkeypatch.setenv("CVETA2_DATA_TIMEOUT", "7.5")
    if organization != "team":
        with pytest.raises(ManagedError) as error:
            CvatConfig.load(path)
        assert str(error.value)
    else:
        config = CvatConfig.load(path)
        assert config.host == "https://shared.example"
        assert config.organization == "team"
        assert config.username == "env-user"
        assert config.password == "env-password"
        assert config.request_timeout == 7.5


@pytest.mark.parametrize(
    ("host", "organization"),
    [("https://different.example", "team"), ("https://shared.example", "other")],
)
def test_shared_credentials_save_refuses_either_identity_change(tmp_path: Path, host: str, organization: str) -> None:
    """A host-only or organization-only mismatch must refuse before writing."""
    path = shared_personal(tmp_path / "personal.yaml")
    original = path.read_bytes()
    with pytest.raises(ManagedError) as error:
        CvatConfig(host=host, organization=organization, username="new").save_to_file(path)
    assert str(error.value)
    assert path.read_bytes() == original
    assert load_project_config(path).cvat.host == "https://shared.example"


def test_shared_credentials_save_omits_identity_and_preserves_local_settings(
    tmp_path: Path,
) -> None:
    """Saving credentials cannot copy either shared identity field personally."""
    path = shared_personal(tmp_path / "personal.yaml")
    config = CvatConfig(
        host="https://shared.example",
        organization="team",
        username="new-user",
        password="new-password",
        request_timeout=15,
    )
    config.save_to_file(path)
    saved = yaml.safe_load(path.read_bytes())
    assert saved["cvat"] == {
        "username": "new-user",
        "password": "new-password",
        "request_timeout": 15,
    }
    assert saved["image_cache"] == {"Source": "/local/images"}
    assert saved["schema_version"] == 1
    assert CvatConfig.load(path).host == "https://shared.example"
    assert CvatConfig.load(path).organization == "team"


@pytest.mark.parametrize("section", ["sync", "ignore", "ignored_prefix", "task_cache_s3"])
def test_new_policy_save_requires_attached_shared_file(tmp_path: Path, section: str) -> None:
    """Policy writers cannot manufacture a fresh personal policy section."""
    path = tmp_path / "personal.yaml"
    config: SyncRootsConfig | IgnoreConfig | CacheConfig
    if section == "sync":
        config = SyncRootsConfig(projects={"Source": "s3://bucket/images"})
    elif section == "ignore":
        config = IgnoreConfig()
        config.add_task("Source", 73, "ignored")
    else:
        settings = CacheProjectSettings.model_validate({section: "s3://bucket/images"})
        config = CacheConfig(projects={"Source": settings})
    with pytest.raises(MigrationRequired) as error:
        config.save(path)
    if section in {"sync", "ignore"}:
        assert {"setup", "--global-config"}.issubset(str(error.value).split())
    assert not path.exists()


def test_unattached_local_cache_save_preserves_only_supported_nonempty_fields(
    tmp_path: Path,
) -> None:
    """Local cache records are legal without shared policy and have one schema."""
    path = write_config_yaml(tmp_path / "personal.yaml")
    cache = CacheConfig(
        images_root=Path("/local/root"),
        projects={
            "kept": CacheProjectSettings(images_root=Path("/local/kept")),
            "empty": CacheProjectSettings(),
        },
    )
    cache.save(path)
    saved = yaml.safe_load(path.read_bytes())
    assert saved["cache"] == {
        "images_root": "/local/root",
        "projects": {"kept": {"images_root": "/local/kept"}},
    }
    assert CacheConfig.load(path).projects == {"kept": CacheProjectSettings(images_root=Path("/local/kept"))}


def test_empty_local_cache_save_does_not_invent_policy_or_raise(tmp_path: Path) -> None:
    """Empty serialized local settings must not enter cache-policy inspection."""
    path = tmp_path / "personal.yaml"
    CacheConfig().save(path)
    assert yaml.safe_load(path.read_bytes()) == {}
    assert CacheConfig.load(path) == CacheConfig()


# ---------------------------------------------------------------------------
# Load-time validation of S3 roots
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("field", ["task_cache_s3", "sync_root"])
@pytest.mark.parametrize("value", ["s3://", "s3:///DO_NOT_LOG", "/", "   ", ""])
def test_shared_malformed_s3_root_is_rejected_at_load(tmp_path: Path, field: str, value: str) -> None:
    target = shared(tmp_path / "shared.yaml")
    data = read_config(target)
    projects = data["projects"]
    assert isinstance(projects, dict)
    projects["main"][field] = value
    write(target, data)
    cfg = personal(tmp_path / "personal.yaml", target)

    with pytest.raises(ManagedError) as caught:
        load_project_config(cfg)

    assert f"projects.main.{field}" in str(caught.value)
    assert "DO_NOT_LOG" not in str(caught.value)


@pytest.mark.parametrize("value", ["s3://bucket", "s3://bucket/prefix/", "prefix/sub"])
def test_shared_valid_s3_roots_still_load(tmp_path: Path, value: str) -> None:
    target = shared(tmp_path / "shared.yaml")
    data = read_config(target)
    projects = data["projects"]
    assert isinstance(projects, dict)
    projects["main"]["task_cache_s3"] = value
    write(target, data)

    assert load_project_config(personal(tmp_path / "personal.yaml", target)).projects["main"].task_cache_s3 == value


@pytest.mark.parametrize("value", ["s3://", "s3:///DO_NOT_LOG", "/", "   "])
def test_personal_malformed_task_cache_s3_is_rejected_at_load(value: str) -> None:
    with pytest.raises(ValidationError) as caught:
        CacheConfig.model_validate({"projects": {"alpha": {"task_cache_s3": value}}})

    issues = caught.value.errors(include_input=False, include_url=False)
    assert [issue["loc"] for issue in issues] == [("projects", "alpha", "task_cache_s3")]
    assert "DO_NOT_LOG" not in str(issues)


def test_personal_blank_task_cache_s3_still_means_unset() -> None:
    assert CacheProjectSettings(task_cache_s3="").task_cache_s3 is None


@pytest.mark.parametrize(("umask", "shared_mode"), [(0o022, 0o644), (0o002, 0o664), (0o077, 0o600)])
def test_approved_migration_creates_the_shared_file_with_the_umask_mode(
    tmp_path: Path, umask: int, shared_mode: int
) -> None:
    """Colleagues must be able to read the team file; credentials stay private."""
    cfg = legacy(tmp_path / "personal.yaml")
    proposal = migration_proposal(cfg)
    previous = os.umask(umask)
    try:
        activate_migration(proposal)
    finally:
        os.umask(previous)
    assert proposal.shared_path.stat().st_mode & 0o777 == shared_mode
    assert cfg.stat().st_mode & 0o777 == 0o600
    assert next(iter(tmp_path.glob("*.bak"))).stat().st_mode & 0o777 == 0o600


def _journal_with_stages(cfg: Path, *, drop: str) -> Path:
    """Write a journal whose named stage file is missing, as after a cleanup."""
    stages = {
        "staged_shared": cfg.with_name(f".{cfg.name}.shared-stage"),
        "staged_personal": cfg.with_name(f".{cfg.name}.personal-stage"),
    }
    for name, stage in stages.items():
        if name != drop:
            stage.write_bytes(b"schema_version: 1\n")
    journal = cfg.with_name(f"{cfg.name}.migration.json")
    journal.write_text(
        json.dumps(
            {
                "shared_path": str(cfg.with_name("project-config.yaml")),
                "staged_shared": str(stages["staged_shared"]),
                "staged_personal": str(stages["staged_personal"]),
                "shared_hash": "0",
                "personal_hash": "0",
                "original_hash": project_config._digest(cfg.read_bytes()),
            }
        ),
        encoding="utf-8",
    )
    return journal


@pytest.mark.parametrize("damage", ["truncated", "empty", "wrong-shape", "missing-shared-stage"])
def test_damaged_migration_journal_is_a_recoverable_typed_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, damage: str
) -> None:
    """A damaged journal names itself and the recovery instead of a raw traceback."""
    cfg = legacy(tmp_path / "personal.yaml")
    journal = cfg.with_name(f"{cfg.name}.migration.json")
    if damage == "truncated":
        journal.write_bytes(b'{"shared_path": "/x", "stag')
    elif damage == "empty":
        journal.write_bytes(b"")
    elif damage == "wrong-shape":
        journal.write_text(json.dumps({"shared_path": str(tmp_path / "project-config.yaml")}), encoding="utf-8")
    else:
        _journal_with_stages(cfg, drop="staged_shared")
    monkeypatch.setattr(primitives, "confirm", lambda *_args, **_kwargs: True)

    with pytest.raises(ManagedError) as caught:
        setup.run_setup(parse_cli_args("setup", "--config", str(cfg), "--migrate-config"))

    assert str(journal) in str(caught.value)
    assert "setup --migrate-config" in str(caught.value)
    assert journal.exists()


def test_journal_with_a_missing_personal_stage_is_a_recoverable_typed_error(tmp_path: Path) -> None:
    cfg = legacy(tmp_path / "personal.yaml")
    journal = _journal_with_stages(cfg, drop="staged_personal")
    shared_path = cfg.with_name("project-config.yaml")
    shared_path.write_bytes(b"schema_version: 1\n")
    data = json.loads(journal.read_bytes())
    data["shared_hash"] = project_config._digest(shared_path.read_bytes())
    journal.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ManagedError) as caught:
        recover_migration(cfg)

    assert str(journal) in str(caught.value)
    assert "personal-stage" in str(caught.value)


# ---------------------------------------------------------------------------
# Wizard attachment of an existing shared file
# ---------------------------------------------------------------------------


def _team_file(path: Path) -> Path:
    """Write a hand-written team file that omits null and empty defaults."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "schema_version: 1\ncvat:\n  host: https://cvat.example/\n  organization: team\n"
        "projects:\n  main:\n    id: 12\n    name: Main\n",
        encoding="utf-8",
    )
    return path


def _run_wizard(monkeypatch: pytest.MonkeyPatch, cfg: Path, team: Path, organization: str) -> None:
    monkeypatch.delenv("CVETA2_NO_INTERACTIVE", raising=False)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(wizard, "prompt_host", lambda _default: "https://cvat.example")
    monkeypatch.setattr(wizard, "prompt_organization", lambda _existing: organization)
    monkeypatch.setattr(wizard, "prompt_username", lambda _default: "alice")
    monkeypatch.setattr(wizard, "prompt_password", lambda: "private")
    # Only the global-file prompt gets a path; the cache prompts that follow are skipped.
    monkeypatch.setattr(
        primitives, "path", lambda message, **_kwargs: team if message.startswith("Общий YAML") else None
    )
    monkeypatch.setattr(primitives, "confirm", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(setup, "load_projects_cache", lambda _path: [ProjectInfo(id=12, name="Main")])
    setup.run_setup(parse_cli_args("setup", "--config", str(cfg)))


def test_wizard_attaches_an_existing_shared_file_with_the_same_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team = _team_file(tmp_path / "team" / "project-config.yaml")
    before = team.read_bytes()
    cfg = tmp_path / "config.yaml"

    _run_wizard(monkeypatch, cfg, team, "team")

    assert team.read_bytes() == before
    saved = read_config(cfg)
    assert saved["schema_version"] == 1
    assert saved["global_config"] == str(team.resolve())
    assert saved["cvat"] == {"username": "alice", "password": "private"}
    loaded = CvatConfig.load(cfg)
    assert (loaded.host, loaded.organization, loaded.password) == ("https://cvat.example", "team", "private")


def test_wizard_refuses_an_existing_shared_file_with_another_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team = _team_file(tmp_path / "team" / "project-config.yaml")
    before = team.read_bytes()
    cfg = tmp_path / "config.yaml"

    with pytest.raises(SharedIdentityMismatchError) as caught:
        _run_wizard(monkeypatch, cfg, team, "other-team")

    assert str(team.resolve()) in str(caught.value)
    assert "other-team" not in str(caught.value)
    assert team.read_bytes() == before
    assert "global_config" not in read_config(cfg)


def test_migration_accepts_a_semantically_equal_hand_written_shared_file(tmp_path: Path) -> None:
    """Omitted null defaults do not make an existing shared file differ."""
    cfg = write(
        tmp_path / "personal.yaml",
        {"cvat": {"host": "https://cvat.example", "organization": "team", "username": "a", "password": "p"}},
    )
    team = tmp_path / "team.yaml"
    team.write_text("cvat: {organization: team, host: 'https://cvat.example/'}\nschema_version: 1\n", encoding="utf-8")
    before = team.read_bytes()

    proposal = migration_proposal(cfg, team)

    assert proposal.unresolved == ()
    activate_migration(proposal)
    assert team.read_bytes() == before
    assert read_config(cfg)["global_config"] == str(team.resolve())


# ---------------------------------------------------------------------------
# Concurrent shared-policy writers
# ---------------------------------------------------------------------------


def _two_writers(tmp_path: Path) -> tuple[Path, Path]:
    """Two personal files attached to one shared file whose projects A and B carry policy."""
    alice = write_split_config_yaml(
        tmp_path / "alice.yaml",
        project_ids={"A": 1, "B": 2},
        sync_roots={"A": "s3://bucket/1", "B": "s3://bucket/2"},
        cache={"projects": {name: {"task_cache_s3": f"s3://cache/{name}"} for name in ("A", "B")}},
    )
    bob = write(
        tmp_path / "bob.yaml",
        {"schema_version": 1, "global_config": str(alice.with_name("alice-projects.yaml"))},
    )
    return alice, bob


def _edit(kind: str, config: SyncRootsConfig | IgnoreConfig | CacheConfig, project: str, value: int) -> None:
    if isinstance(config, IgnoreConfig):
        config.add_task(project, value, f"task-{value}")
    elif isinstance(config, SyncRootsConfig):
        config.projects[project] = f"s3://bucket/{value}"
    else:
        current = config.projects.get(project) or CacheProjectSettings()
        config.projects[project] = current.model_copy(update={kind: f"s3://cache/{value}"})


def _policy(config: ProjectConfig, kind: str, key: str) -> object:
    value = getattr(config.projects[key], kind)
    return [entry["id"] for entry in value] if kind == "ignore" else value


_SECTIONS: dict[str, type[SyncRootsConfig | IgnoreConfig | CacheConfig]] = {
    "ignore": IgnoreConfig,
    "sync_root": SyncRootsConfig,
    "task_cache_s3": CacheConfig,
}
_WRITTEN: dict[str, Callable[[int], object]] = {
    "ignore": lambda value: [value],
    "sync_root": "s3://bucket/{}".format,
    "task_cache_s3": "s3://cache/{}".format,
}


@pytest.mark.parametrize("kind", list(_SECTIONS))
def test_interleaved_policy_saves_keep_both_writers_changes(tmp_path: Path, kind: str) -> None:
    alice, bob = _two_writers(tmp_path)
    section = _SECTIONS[kind]
    alice_config = section.load(alice)
    bob_config = section.load(bob)
    _edit(kind, bob_config, "B", 200)
    bob_config.save(bob)
    _edit(kind, alice_config, "A", 100)
    alice_config.save(alice)

    shared = load_project_config(alice)
    assert _policy(shared, kind, "A") == _WRITTEN[kind](100)
    assert _policy(shared, kind, "B") == _WRITTEN[kind](200)


@pytest.mark.parametrize("kind", ["sync_root", "task_cache_s3"])
def test_conflicting_policy_save_is_refused_and_keeps_the_first_value(tmp_path: Path, kind: str) -> None:
    alice, bob = _two_writers(tmp_path)
    section = _SECTIONS[kind]
    alice_config = section.load(alice)
    bob_config = section.load(bob)
    _edit(kind, bob_config, "A", 200)
    bob_config.save(bob)
    _edit(kind, alice_config, "A", 100)
    shared_file = alice.with_name("alice-projects.yaml")
    before = shared_file.read_bytes()

    with pytest.raises(SharedConfigConflictError) as caught:
        alice_config.save(alice)

    assert str(shared_file.resolve()) in str(caught.value)
    assert "s3://" not in str(caught.value)
    assert shared_file.read_bytes() == before


@pytest.mark.parametrize("kind", list(_SECTIONS))
@pytest.mark.parametrize("aliased", [False, True])
def test_overlapping_policy_saves_refuse_contention_then_preserve_both_edits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str, *, aliased: bool
) -> None:
    alice, bob = _two_writers(tmp_path)
    if aliased:
        alias = tmp_path / "team-alias.yaml"
        alias.symlink_to(alice.with_name("alice-projects.yaml"))
        write(bob, {"schema_version": 1, "global_config": str(alias)})
    alice_config = _SECTIONS[kind].load(alice)
    bob_config = _SECTIONS[kind].load(bob)
    _edit(kind, alice_config, "A", 100)
    _edit(kind, bob_config, "B", 200)
    original_write = project_config._private_write
    shared_file = alice.with_name("alice-projects.yaml")
    overlapping = False

    def overlap_before_replace(
        path: Path, content: bytes, *, replace: bool = False, preserve_permissions: bool = False
    ) -> None:
        nonlocal overlapping
        if path == shared_file and not overlapping:
            overlapping = True
            with pytest.raises(SharedConfigConflictError):
                bob_config.save(bob)
        original_write(path, content, replace=replace, preserve_permissions=preserve_permissions)

    monkeypatch.setattr(project_config, "_private_write", overlap_before_replace)
    alice_config.save(alice)
    bob_config.save(bob)

    shared_config = load_project_config(alice)
    assert _policy(shared_config, kind, "A") == _WRITTEN[kind](100)
    assert _policy(shared_config, kind, "B") == _WRITTEN[kind](200)


def test_failed_policy_save_releases_the_hold_and_keeps_the_lock_inode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    alice, _bob = _two_writers(tmp_path)
    config = SyncRootsConfig.load(alice)
    config.projects["A"] = "s3://bucket/100"

    def fail_write(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated save failure")

    with monkeypatch.context() as patched:
        patched.setattr(project_config, "_private_write", fail_write)
        with pytest.raises(OSError, match="simulated save failure"):
            config.save(alice)

    shared_path = alice.with_name("alice-projects.yaml")
    lock_path = shared_path.with_name(f".{shared_path.name}.lock")
    inode = lock_path.stat().st_ino
    config.save(alice)

    assert lock_path.stat().st_ino == inode
    assert load_project_config(alice).projects["A"].sync_root == "s3://bucket/100"


def _hold_shared_policy_save(personal: Path, ready: ProcessConnection) -> None:
    """Pause a real writer immediately before its atomic replacement."""
    config = SyncRootsConfig.load(personal)
    config.projects["A"] = "s3://bucket/100"
    original_write = project_config._private_write

    def pause_before_replace(
        path: Path, content: bytes, *, replace: bool = False, preserve_permissions: bool = False
    ) -> None:
        ready.send("locked")
        ready.recv()
        original_write(path, content, replace=replace, preserve_permissions=preserve_permissions)

    with pytest.MonkeyPatch.context() as patched:
        patched.setattr(project_config, "_private_write", pause_before_replace)
        config.save(personal)


def test_terminated_policy_writer_releases_its_lock(tmp_path: Path) -> None:
    alice, bob = _two_writers(tmp_path)
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    process = context.Process(target=_hold_shared_policy_save, args=(alice, child))
    process.start()
    child.close()
    try:
        assert parent.poll(10), "Writer did not reach the replacement boundary"
        assert parent.recv() == "locked"
        config = SyncRootsConfig.load(bob)
        config.projects["B"] = "s3://bucket/200"
        with pytest.raises(SharedConfigConflictError):
            config.save(bob)
    finally:
        process.terminate()
        process.join(timeout=5)
        if process.is_alive():
            process.kill()
            process.join(timeout=5)
        parent.close()
        process.close()

    config.save(bob)
    shared_config = load_project_config(bob)
    assert shared_config.projects["A"].sync_root == "s3://bucket/1"
    assert shared_config.projects["B"].sync_root == "s3://bucket/200"


def test_policy_lock_preserves_shared_access_under_restrictive_umask(tmp_path: Path) -> None:
    alice, _bob = _two_writers(tmp_path)
    shared_path = alice.with_name("alice-projects.yaml")
    shared_path.chmod(0o664)
    config = SyncRootsConfig.load(alice)
    config.projects["A"] = "s3://bucket/100"
    previous_umask = os.umask(0o077)
    try:
        config.save(alice)
    finally:
        os.umask(previous_umask)

    lock_path = shared_path.with_name(f".{shared_path.name}.lock")
    assert stat.S_IMODE(lock_path.stat().st_mode) == 0o664
    assert lock_path.stat().st_gid == shared_path.stat().st_gid
    assert stat.S_IMODE(shared_path.stat().st_mode) == 0o664


def test_policy_save_refuses_a_symlinked_lock_without_touching_its_target(tmp_path: Path) -> None:
    alice, _bob = _two_writers(tmp_path)
    shared_path = alice.with_name("alice-projects.yaml")
    original = shared_path.read_bytes()
    victim = tmp_path / "private.txt"
    victim.write_bytes(b"untouched")
    lock_path = shared_path.with_name(f".{shared_path.name}.lock")
    lock_path.symlink_to(victim)
    config = SyncRootsConfig.load(alice)
    config.projects["A"] = "s3://bucket/100"

    with pytest.raises(ManagedError, match="lock"):
        config.save(alice)

    assert victim.read_bytes() == b"untouched"
    assert lock_path.is_symlink()
    assert shared_path.read_bytes() == original


@pytest.mark.parametrize(
    "section",
    [{"sync_roots": {"main": ""}}, {"cache": {"projects": {"main": {"task_cache_s3": "", "ignored_prefix": ""}}}}],
    ids=["sync-root", "cache-policy"],
)
def test_migration_treats_blank_legacy_roots_as_unset(tmp_path: Path, section: dict[str, object]) -> None:
    """Legacy readers ignore blank values, so migration must not turn them into invalid policy."""
    path = _legacy_registry(tmp_path, {"main": 7})
    raw = read_config(path)
    raw.pop("sync_roots")
    write(path, {**raw, **section})

    proposal = migration_proposal(path)

    assert proposal.unresolved == ()
    activate_migration(proposal)
    project = load_project_config(path).projects["main"]
    assert (project.sync_root, project.task_cache_s3, project.ignored_prefix) == (None, None, None)


def test_migration_reports_an_unusable_legacy_root_for_review(tmp_path: Path) -> None:
    path = _legacy_registry(tmp_path, {"main": 7})
    raw = read_config(path)
    raw["sync_roots"] = {"main": "s3:///DO_NOT_LOG"}
    write(path, raw)
    original = path.read_bytes()

    proposal = migration_proposal(path)

    assert any("projects.main.sync_root" in item for item in proposal.unresolved)
    assert "DO_NOT_LOG" not in json.dumps(proposal.unresolved)
    with pytest.raises(ManagedError, match="unresolved"):
        activate_migration(proposal)
    assert path.read_bytes() == original


# Team writes use the raw global file as their baseline
# ---------------------------------------------------------------------------

_RETAIL_PUBLICATION: dict[str, object] = {
    "clearml": {"project": "Retail/Datasets", "dataset": "retail-shelves"},
    "api_url": "https://classes.example.com/api",
}


def _overridden(tmp_path: Path) -> tuple[Path, Path]:
    """Write a global file that allows overrides and a personal file overriding one leaf."""
    team = write(
        tmp_path / "team.yaml",
        {
            "schema_version": 1,
            "local_overrides": True,
            "cvat": {"host": "https://cvat.example.com", "organization": "my-team"},
            "projects": {
                "retail": {
                    "id": 123,
                    "name": "Retail shelves",
                    "sync_root": "s3://my-bucket/images",
                    "publication": _RETAIL_PUBLICATION,
                }
            },
            "datasets": {},
        },
    )
    cfg = write(
        tmp_path / "config.yaml",
        {
            "schema_version": 1,
            "global_config": str(team),
            "cvat": {"username": "alice", "password": "private"},
            "overrides": {"projects": {"retail": {"publication": {"clearml": {"dataset": "retail-shelves-alice"}}}}},
        },
    )
    return cfg, team


def _dataset_name(path: Path) -> object:
    return yaml.safe_load(path.read_text(encoding="utf-8"))["projects"]["retail"]["publication"]["clearml"]["dataset"]


def test_team_write_never_copies_a_local_override_into_the_global_file(tmp_path: Path) -> None:
    cfg, team = _overridden(tmp_path)

    ignore = IgnoreConfig.load(cfg)
    ignore.add_task("retail", 9, "t9")
    ignore.save(cfg)

    document = yaml.safe_load(team.read_text(encoding="utf-8"))
    assert [entry["id"] for entry in document["projects"]["retail"]["ignore"]] == [9]
    assert _dataset_name(team) == "retail-shelves"

    before = team.read_bytes()
    cache = CacheConfig.load(cfg)
    cache.images_root = Path("/local/images")
    cache.save(cfg)
    assert team.read_bytes() == before

    write_shared_project_fields(cfg, {"retail": {"sync_root": "s3://my-bucket/new"}})
    assert load_global_config(cfg).projects["retail"].sync_root == "s3://my-bucket/new"
    assert _dataset_name(team) == "retail-shelves"


def test_override_does_not_trip_the_conflict_check(tmp_path: Path) -> None:
    cfg, team = _overridden(tmp_path)
    roots = SyncRootsConfig.load(cfg)

    write_shared_project_fields(cfg, {"retail": {"ignore": [{"id": 5, "name": "five"}]}})
    roots.projects["retail"] = "s3://my-bucket/moved"
    roots.save(cfg)

    document = yaml.safe_load(team.read_text(encoding="utf-8"))["projects"]["retail"]
    assert document["sync_root"] == "s3://my-bucket/moved"
    assert [entry["id"] for entry in document["ignore"]] == [5]
    assert _dataset_name(team) == "retail-shelves"


def test_team_write_adds_no_new_keys_to_an_untouched_file(tmp_path: Path) -> None:
    target = shared(tmp_path / "shared.yaml")
    cfg = personal(tmp_path / "personal.yaml", target)

    ignore = IgnoreConfig.load(cfg)
    ignore.add_task("main", 9, "t9")
    ignore.save(cfg)

    document = yaml.safe_load(target.read_text(encoding="utf-8"))
    assert {"schema_version", "cvat", "projects", "datasets"} >= set(document)
    assert all("publication" not in project for project in document["projects"].values())


def test_migration_preview_of_a_versioned_file_shows_the_raw_global_file(tmp_path: Path) -> None:
    cfg, _team = _overridden(tmp_path)

    proposal = migration_proposal(cfg)

    assert proposal.shared == load_global_config(cfg).model_dump()
