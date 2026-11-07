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
from cveta2.interfaces.commands import setup
from cveta2.interfaces.commands.interactive import primitives
from tests.helpers import write_config_yaml, write_split_config_yaml


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
    monkeypatch.delenv("CVETA2_PROJECT_CONFIG", raising=False)
    assert project_config_path(cfg) == saved
    monkeypatch.setenv("CVETA2_PROJECT_CONFIG", str(env))
    assert load_project_config(cfg).cvat.host == "https://env.example"
    assert load_project_config(cfg, explicit).cvat.host == "https://explicit.example"
    monkeypatch.setenv("CVETA2_PROJECT_CONFIG", str(tmp_path / "missing.yaml"))
    with pytest.raises(ManagedError, match="Cannot read"):
        load_project_config(cfg)


def test_attach_is_noninteractive_and_does_not_modify_shared(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Attach-only setup does not prompt for credentials or write shared data."""
    target = shared(tmp_path / "shared.yaml")
    cfg = write(tmp_path / "personal.yaml", {"network": {"s3_workers": 2}})
    before = target.read_bytes()
    monkeypatch.setenv("CVETA2_NO_INTERACTIVE", "true")
    setup.run_setup(argparse.Namespace(config=str(cfg), project_config=target, migrate_config=False))
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
def test_personal_cannot_override_shared(tmp_path: Path, fields: dict[str, object]) -> None:
    """Shared ownership is enforced before resolving effective settings."""
    target = shared(tmp_path / "shared.yaml")
    cfg = write(
        tmp_path / "personal.yaml",
        {"schema_version": 1, "project_config": str(target), **fields},
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


def test_migration_cancel_and_stale_preview(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Cancel is no-op; approval cannot activate a proposal of changed bytes."""
    cfg = legacy(tmp_path / "personal.yaml")
    original = cfg.read_bytes()
    monkeypatch.setattr(primitives, "confirm", lambda *_args, **_kwargs: False)
    setup.run_setup(argparse.Namespace(config=str(cfg), migrate_config=True, project_config=None))
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
    monkeypatch.delenv("CVETA2_PROJECT_CONFIG", raising=False)
    before = cfg.read_bytes()
    assert CvatConfig.load(cfg, project_path=target).host == "https://cvat.example"
    assert ImageCacheConfig.load(cfg, project_path=target).get_cache_dir("Main project") == Path("/local/images")
    assert CacheConfig.load(cfg, project_path=target).for_project("Main project").task_cache_s3 == "s3://bucket/cache"
    assert NetworkConfig.resolve(cfg, project_path=target).cvat_workers == 2
    assert cfg.read_bytes() == before
    assert "CVETA2_PROJECT_CONFIG" not in os.environ


def test_concurrent_journal_is_not_overwritten(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
        original_write(path, content, replace=replace, preserve_permissions=preserve_permissions)

    monkeypatch.setattr(project_config, "_private_write", racing_write)
    with pytest.raises(ManagedError, match="Another approved migration"):
        activate_migration(proposal)
    assert journal.read_bytes() == b"another transaction"
    assert not list(tmp_path.glob(".*.migration-*"))
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
    assert set(loaded.projects) == {"Friendly project"}
    effective = loaded.for_project("Friendly project")
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
    cache.projects["Friendly project"] = CacheProjectSettings(
        ignored_prefix="raw/", task_cache_s3="s3://bucket/shared-cache"
    )
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
        projects={"main": ProjectDefinition(id=7, name="Friendly project")},
    )
    images = tmp_path / "images"
    values: dict[str, object] = {
        "projects": {
            "malformed": None,
            "Friendly project": {"ignored_prefix": "raw/", "images_root": str(images)},
        }
    }
    changes = _split_cache_policy(values, shared)
    assert changes == {"Friendly project": {"ignored_prefix": "raw/"}}
    assert values == {"projects": {"Friendly project": {"images_root": str(images)}}}


def test_global_cache_save_still_rejects_ambiguous_shared_project_names(
    tmp_path: Path,
) -> None:
    """Even a global local-path save must not bless an ambiguous shared registry."""
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
    personal = write_config_yaml(tmp_path / "personal.yaml", schema_version=1, project_config=str(shared))
    personal_before, shared_before = personal.read_bytes(), shared.read_bytes()
    with pytest.raises(ManagedError, match="Collision"):
        CacheConfig(images_root=tmp_path / "local-images").save(personal)
    assert personal.read_bytes() == personal_before
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
        assert {"setup", "--project-config"}.issubset(str(error.value).split())
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
