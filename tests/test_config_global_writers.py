"""Writers of the global file and of the personal local overrides."""

import os
from pathlib import Path

import pytest
import yaml

from cveta2.adapters.config.project import (
    SharedConfigConflictError,
    SharedIdentityMismatchError,
    create_global_config,
    find_project_key,
    load_global_config,
    load_project_config,
    project_key_for,
    read_config,
    write_local_overrides,
    write_shared_project_fields,
)
from cveta2.domain.managed.models import CvatIdentity, ManagedError, ProjectConfig, ProjectDefinition
from cveta2.domain.managed.overrides import LocalOverridesDisabledError

_HOST = "https://cvat.example.com"
_ORGANIZATION = "my-team"
_API = "https://classes.example.com/api"
_PUBLICATION: dict[str, object] = {
    "clearml": {"project": "Retail/Datasets", "dataset": "retail-shelves"},
    "api_url": _API,
    "empty_classes": [12, 13],
}


@pytest.fixture(autouse=True)
def _no_global_file_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Let the personal file alone select the global file in these tests."""
    monkeypatch.delenv("CVETA2_GLOBAL_CONFIG", raising=False)
    monkeypatch.delenv("CVETA2_PROJECT_CONFIG", raising=False)


def write(path: Path, data: dict[str, object]) -> Path:
    """Write test-owned YAML without touching the real user configuration."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def team(
    path: Path,
    *,
    local_overrides: bool | None = True,
    publication: dict[str, object] | None = None,
    datasets: dict[str, object] | None = None,
) -> Path:
    """Write a global file with one ``retail`` project, published only when *publication* is given."""
    retail: dict[str, object] = {"id": 123, "name": "Retail shelves", "sync_root": "s3://my-bucket/images"}
    if publication is not None:
        retail["publication"] = publication
    data: dict[str, object] = {
        "schema_version": 1,
        "cvat": {"host": _HOST, "organization": _ORGANIZATION},
        "projects": {"retail": retail},
        "datasets": datasets or {},
    }
    if local_overrides is not None:
        data["local_overrides"] = local_overrides
    return write(path, data)


def personal(path: Path, reference: Path | None, overrides: dict[str, object] | None = None) -> Path:
    """Write a personal file; versioned and attached to *reference* when one is given."""
    data: dict[str, object] = {"cvat": {"username": "alice", "password": "private"}}
    if reference is not None:
        data = {"schema_version": 1, "global_config": str(reference), **data}
    if overrides is not None:
        data["overrides"] = overrides
    return write(path, data)


def _setup(
    tmp_path: Path,
    *,
    local_overrides: bool | None = True,
    publication: dict[str, object] | None = None,
    datasets: dict[str, object] | None = None,
) -> tuple[Path, Path]:
    global_file = team(
        tmp_path / "team.yaml", local_overrides=local_overrides, publication=publication, datasets=datasets
    )
    return personal(tmp_path / "config.yaml", global_file), global_file


def _publication(cfg: Path) -> object:
    return load_global_config(cfg).projects["retail"].model_dump(mode="json")["publication"]


def test_writer_sets_one_nested_publication_leaf(tmp_path: Path) -> None:
    cfg, _ = _setup(tmp_path, publication=_PUBLICATION)

    write_shared_project_fields(cfg, {"retail": {"publication.clearml.dataset": "v2"}})

    assert _publication(cfg) == {
        "clearml": {"project": "Retail/Datasets", "dataset": "v2"},
        "api_url": _API,
        "empty_classes": [12, 13],
    }


def test_writer_creates_a_publication_block_from_three_leaves(tmp_path: Path) -> None:
    cfg, global_file = _setup(tmp_path)

    write_shared_project_fields(
        cfg,
        {
            "retail": {
                "publication.clearml.project": "Retail/Datasets",
                "publication.clearml.dataset": "retail-shelves",
                "publication.api_url": _API,
            }
        },
    )

    config = ProjectConfig.model_validate(read_config(global_file))
    publication = config.projects["retail"].publication
    assert publication is not None
    assert (publication.clearml.project, publication.clearml.dataset, publication.api_url) == (
        "Retail/Datasets",
        "retail-shelves",
        _API,
    )


def test_writer_refuses_an_incomplete_publication_block(tmp_path: Path) -> None:
    cfg, global_file = _setup(tmp_path)
    before = global_file.read_bytes()
    with pytest.raises(ManagedError, match="publication"):
        write_shared_project_fields(cfg, {"retail": {"publication.clearml.project": "Retail/Datasets"}})
    assert global_file.read_bytes() == before

    team(global_file, publication=_PUBLICATION)
    before = global_file.read_bytes()
    with pytest.raises(ManagedError, match="publication"):
        write_shared_project_fields(cfg, {"retail": {"publication.api_url": None}})
    assert global_file.read_bytes() == before

    write_shared_project_fields(cfg, {"retail": {"publication": None}})
    assert "publication" not in read_config(global_file)["projects"]["retail"]  # type: ignore[index]


def test_writer_expected_conflict_per_leaf(tmp_path: Path) -> None:
    publication = {**_PUBLICATION, "clearml": {"project": "Retail/Datasets", "dataset": "other"}}
    cfg, global_file = _setup(tmp_path, publication=publication)
    before = global_file.read_bytes()

    with pytest.raises(SharedConfigConflictError):
        write_shared_project_fields(
            cfg,
            {"retail": {"publication.clearml.dataset": "new"}},
            expected={"retail": {"publication.clearml.dataset": "old"}},
        )

    assert global_file.read_bytes() == before


def test_writer_sets_and_unsets_local_overrides(tmp_path: Path) -> None:
    cfg, global_file = _setup(tmp_path, local_overrides=None)

    write_shared_project_fields(cfg, {}, settings={"local_overrides": True})
    assert read_config(global_file)["local_overrides"] is True

    write_shared_project_fields(cfg, {}, settings={"local_overrides": None})
    assert "local_overrides" not in read_config(global_file)


def test_writer_refuses_an_unknown_setting(tmp_path: Path) -> None:
    cfg, global_file = _setup(tmp_path)
    before = global_file.read_bytes()

    with pytest.raises(ManagedError, match=r"cvat\.username"):
        write_shared_project_fields(cfg, {}, settings={"cvat.username": "bob"})

    assert global_file.read_bytes() == before


def test_writer_adds_a_new_project_definition(tmp_path: Path) -> None:
    global_file = write(
        tmp_path / "team.yaml",
        {"schema_version": 1, "cvat": {"host": _HOST, "organization": _ORGANIZATION}, "projects": {}, "datasets": {}},
    )
    cfg = personal(tmp_path / "config.yaml", global_file)

    write_shared_project_fields(cfg, {}, new_projects={"retail": ProjectDefinition(id=123, name="Retail shelves")})
    assert load_global_config(cfg).projects["retail"] == ProjectDefinition(id=123, name="Retail shelves")

    before = global_file.read_bytes()
    with pytest.raises(ManagedError, match="123"):
        write_shared_project_fields(cfg, {}, new_projects={"other": ProjectDefinition(id=123, name="Other")})
    with pytest.raises(ManagedError, match="retail"):
        write_shared_project_fields(cfg, {}, new_projects={"retail": ProjectDefinition(id=124)})
    assert global_file.read_bytes() == before


def test_writer_changes_a_definition_it_adds_in_the_same_write(tmp_path: Path) -> None:
    cfg, _ = _setup(tmp_path)

    write_shared_project_fields(
        cfg,
        {"project-321": {"sync_root": "s3://b/n"}},
        new_projects={"project-321": ProjectDefinition(id=321, name="New shelves")},
    )

    added = load_global_config(cfg).projects["project-321"]
    assert (added.id, added.name, added.sync_root) == (321, "New shelves", "s3://b/n")


def test_writer_writes_an_unattached_file_by_explicit_path(tmp_path: Path) -> None:
    global_file = team(tmp_path / "team.yaml", local_overrides=None)
    cfg = personal(tmp_path / "config.yaml", None)
    before = cfg.read_bytes()

    write_shared_project_fields(cfg, {}, settings={"local_overrides": True}, global_path=global_file)

    assert read_config(global_file)["local_overrides"] is True
    assert cfg.read_bytes() == before


def test_project_key_for_follows_the_migration_rule() -> None:
    assert project_key_for("Retail shelves", 123) == "project-123"
    assert project_key_for("retail", 123) == "retail"


def test_find_project_key_by_key_name_or_id(tmp_path: Path) -> None:
    cfg, _ = _setup(tmp_path)
    config = load_global_config(cfg)

    assert [find_project_key(config, spec) for spec in ("retail", "Retail shelves", "123")] == ["retail"] * 3
    assert find_project_key(config, "999") is None


def test_find_project_key_refuses_an_ambiguous_name() -> None:
    config = ProjectConfig.model_validate(
        {
            "cvat": {"host": _HOST, "organization": _ORGANIZATION},
            "projects": {"a": {"id": 1, "name": "Shelves"}, "b": {"id": 2, "name": "Shelves"}},
        }
    )

    with pytest.raises(ManagedError, match="Ambiguous shared project name"):
        find_project_key(config, "Shelves")


def test_create_global_config_writes_switch_on_and_attaches(tmp_path: Path) -> None:
    cfg = personal(tmp_path / "config.yaml", None)
    global_file = tmp_path / "shared" / "team.yaml"
    identity = CvatIdentity(host=_HOST, organization=_ORGANIZATION)
    previous = os.umask(0o022)
    try:
        assert create_global_config(cfg, global_file, identity) == global_file.resolve()
    finally:
        os.umask(previous)

    assert read_config(global_file) == {
        "schema_version": 1,
        "local_overrides": True,
        "cvat": {"host": _HOST, "organization": _ORGANIZATION},
        "projects": {},
        "datasets": {},
    }
    assert global_file.stat().st_mode & 0o777 == 0o644
    assert read_config(cfg)["global_config"] == str(global_file.resolve())
    assert [p.name for p in global_file.parent.iterdir()] == ["team.yaml"]

    before = global_file.read_bytes()
    with pytest.raises(ManagedError, match="--global-config"):
        create_global_config(cfg, global_file, identity)
    assert global_file.read_bytes() == before


def test_create_global_config_removes_the_file_on_identity_mismatch(tmp_path: Path) -> None:
    cfg = write(
        tmp_path / "config.yaml",
        {"cvat": {"host": "https://other.example.com", "organization": _ORGANIZATION, "username": "alice"}},
    )
    global_file = tmp_path / "team.yaml"
    before = cfg.read_bytes()

    with pytest.raises(SharedIdentityMismatchError):
        create_global_config(cfg, global_file, CvatIdentity(host=_HOST, organization=_ORGANIZATION))

    assert not global_file.exists()
    assert cfg.read_bytes() == before


def test_write_local_overrides_writes_only_the_personal_file(tmp_path: Path) -> None:
    cfg, global_file = _setup(tmp_path, publication=_PUBLICATION)
    before = global_file.read_bytes()

    write_local_overrides(cfg, "retail", {"publication.clearml.dataset": "mine"})
    assert read_config(cfg)["overrides"] == {"projects": {"retail": {"publication": {"clearml": {"dataset": "mine"}}}}}

    write_local_overrides(cfg, "retail", {"publication.clearml.dataset": None})
    assert "overrides" not in read_config(cfg)
    assert global_file.read_bytes() == before


def test_write_local_overrides_refused_when_switch_off(tmp_path: Path) -> None:
    cfg, _ = _setup(tmp_path, local_overrides=None, publication=_PUBLICATION)
    before = cfg.read_bytes()

    with pytest.raises(LocalOverridesDisabledError, match="cveta2 setup --global --local-overrides on"):
        write_local_overrides(cfg, "retail", {"publication.clearml.dataset": "mine"})

    assert cfg.read_bytes() == before


def test_removing_an_override_works_when_switch_off(tmp_path: Path) -> None:
    global_file = team(tmp_path / "team.yaml", local_overrides=None, publication=_PUBLICATION)
    overrides: dict[str, object] = {"projects": {"retail": {"publication": {"clearml": {"dataset": "mine"}}}}}
    cfg = personal(tmp_path / "config.yaml", global_file, overrides)

    write_local_overrides(cfg, "retail", {"publication.clearml.dataset": None})

    assert "overrides" not in read_config(cfg)
    assert read_config(cfg)["global_config"] == str(global_file)


@pytest.mark.parametrize(
    "changes",
    [
        {"ignore": []},
        {"id": 1},
        {"sync_root": "s3://x/y"},
        {"ignored_prefix": "a/"},
        {"task_cache_s3": "s3://x/c"},
    ],
)
def test_write_local_overrides_refuses_a_team_only_field(tmp_path: Path, changes: dict[str, object]) -> None:
    cfg, _ = _setup(tmp_path, publication=_PUBLICATION)
    before = cfg.read_bytes()

    with pytest.raises(ManagedError, match="Локально переопределяются только настройки публикации"):
        write_local_overrides(cfg, "retail", changes)

    assert cfg.read_bytes() == before


def test_write_local_overrides_refuses_an_unknown_project(tmp_path: Path) -> None:
    cfg, _ = _setup(tmp_path, publication=_PUBLICATION)
    before = cfg.read_bytes()

    with pytest.raises(ManagedError, match="Нет описания проекта other"):
        write_local_overrides(cfg, "other", {"publication.clearml.dataset": "mine"})

    assert cfg.read_bytes() == before


def test_removing_an_override_of_a_project_no_longer_in_the_global_file(tmp_path: Path) -> None:
    global_file = team(tmp_path / "team.yaml", publication=_PUBLICATION)
    overrides: dict[str, object] = {"projects": {"gone": {"publication": {"clearml": {"dataset": "mine"}}}}}
    cfg = personal(tmp_path / "config.yaml", global_file, overrides)
    with pytest.raises(ManagedError, match="gone"):
        load_project_config(cfg)

    write_local_overrides(cfg, "gone", {"publication.clearml.dataset": None})

    assert "overrides" not in read_config(cfg)
    assert load_project_config(cfg).projects["retail"].publication is not None


def test_override_write_that_collides_is_refused_before_writing(tmp_path: Path) -> None:
    shelves = {
        "sources": [{"name": "retail", "type": "cvat", "project": "retail"}],
        "api_url": _API,
        "clearml": {"project": "Retail/Datasets", "dataset": "retail-shelves-alice"},
    }
    publication: dict[str, object] = {
        "clearml": {"project": "Retail/Datasets", "dataset": "retail-shelves"},
        "api_url": _API,
    }
    cfg, _ = _setup(tmp_path, publication=publication, datasets={"shelves": shelves})
    before = cfg.read_bytes()

    with pytest.raises(ManagedError, match="Retail/Datasets/retail-shelves-alice"):
        write_local_overrides(cfg, "retail", {"publication.clearml.dataset": "retail-shelves-alice"})

    assert cfg.read_bytes() == before
