"""Cache policy ownership, canonical bindings and actionable writer failures."""

from pathlib import Path

import pytest

from cveta2.adapters.config.project import load_project_config, read_config
from cveta2.adapters.config.settings import (
    CacheConfig,
    IgnoreConfig,
    SyncRootsConfig,
    _split_cache_policy,
)
from cveta2.application.settings import CacheProjectSettings
from cveta2.domain.managed.models import (
    CvatIdentity,
    ManagedError,
    ProjectConfig,
    ProjectDefinition,
)
from tests.helpers import write_config_yaml, write_split_config_yaml


@pytest.mark.parametrize("kind", ["sync", "ignore"])
def test_shared_policy_writers_reject_unknown_registry_keys(
    tmp_path: Path, kind: str
) -> None:
    """A rejected edit names the unknown source and leaves both files untouched."""
    personal = write_split_config_yaml(
        tmp_path / "personal.yaml", project_ids={"Friendly project": 7}
    )
    shared = personal.with_name("personal-projects.yaml")
    before = personal.read_bytes(), shared.read_bytes()
    config: SyncRootsConfig | IgnoreConfig
    if kind == "sync":
        config = SyncRootsConfig(projects={"unknown-project": "s3://bucket/new"})
    else:
        config = IgnoreConfig()
        config.add_task("unknown-project", 42, "ignored")
    with pytest.raises(ManagedError, match="unknown-project"):
        config.save(personal)
    assert (personal.read_bytes(), shared.read_bytes()) == before


def test_shared_policy_writers_accept_registry_key_alias(tmp_path: Path) -> None:
    """Both shared policy types accept stable keys when display names differ."""
    personal = write_split_config_yaml(
        tmp_path / "personal.yaml", project_ids={"Friendly project": 7}
    )
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


def test_unknown_policy_writer_reports_the_missing_project_identity(
    tmp_path: Path,
) -> None:
    """An actionable rejection names the unresolved mapping without writing it."""
    personal = write_split_config_yaml(
        tmp_path / "personal.yaml", project_ids={"Friendly project": 7}
    )
    before = personal.read_bytes()
    cache = CacheConfig(
        projects={"unknown-project": CacheProjectSettings(ignored_prefix="raw/")}
    )
    with pytest.raises(ManagedError, match="unknown-project"):
        cache.save(personal)
    assert personal.read_bytes() == before


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
    personal = write_config_yaml(
        tmp_path / "personal.yaml", schema_version=1, project_config=str(shared)
    )
    personal_before, shared_before = personal.read_bytes(), shared.read_bytes()
    with pytest.raises(ManagedError, match="Collision"):
        CacheConfig(images_root=tmp_path / "local-images").save(personal)
    assert personal.read_bytes() == personal_before
    assert shared.read_bytes() == shared_before
