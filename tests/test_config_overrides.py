"""Local overrides of publication settings and the effective configuration."""

from pathlib import Path

import pytest
import yaml

from cveta2.adapters.config.project import (
    load_global_config,
    load_project_config,
    validate_personal,
    write_shared_project_fields,
)
from cveta2.adapters.config.settings import CacheConfig, CvatConfig, SyncRootsConfig
from cveta2.composition.configuration import project_publication
from cveta2.domain.managed.models import ManagedError
from cveta2.domain.managed.overrides import LocalOverridesDisabledError

_DESTINATION = {"project": "Retail/Datasets", "dataset": "retail-shelves"}


@pytest.fixture(autouse=True)
def _no_global_file_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Let the personal file alone select the global file in these tests."""
    monkeypatch.delenv("CVETA2_PROJECT_CONFIG", raising=False)


def write(path: Path, data: dict[str, object]) -> Path:
    """Write test-owned YAML without touching the real user configuration."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def _retail(*, publication: dict[str, object] | None) -> dict[str, object]:
    project: dict[str, object] = {
        "id": 123,
        "name": "Retail shelves",
        "sync_root": "s3://my-bucket/images",
        "ignored_prefix": "shelves/",
    }
    if publication is not None:
        project["publication"] = publication
    return project


def shared(
    path: Path,
    *,
    local_overrides: bool | None = True,
    publication: dict[str, object] | None = None,
    datasets: dict[str, object] | None = None,
    with_publication: bool = True,
) -> Path:
    """Write the design's global file: one ``retail`` project that may publish."""
    if publication is None and with_publication:
        publication = {"clearml": dict(_DESTINATION), "api_url": "https://classes.example.com/api"}
    data: dict[str, object] = {
        "schema_version": 1,
        "cvat": {"host": "https://cvat.example.com", "organization": "my-team"},
        "projects": {"retail": _retail(publication=publication)},
        "datasets": datasets or {},
    }
    if local_overrides is not None:
        data["local_overrides"] = local_overrides
    return write(path, data)


def personal(path: Path, reference: Path, overrides: dict[str, object] | None = None) -> Path:
    """Write a versioned personal file that selects *reference* and may carry overrides."""
    data: dict[str, object] = {
        "schema_version": 1,
        "project_config": str(reference),
        "cvat": {"username": "alice", "password": "private"},
    }
    if overrides is not None:
        data["overrides"] = overrides
    return write(path, data)


def _publication_override(publication: dict[str, object]) -> dict[str, object]:
    return {"projects": {"retail": {"publication": publication}}}


_ALICE = _publication_override({"clearml": {"dataset": "retail-shelves-alice"}})


def test_override_replaces_one_publication_leaf(tmp_path: Path) -> None:
    cfg = personal(tmp_path / "config.yaml", shared(tmp_path / "team.yaml"), _ALICE)

    effective = load_project_config(cfg).projects["retail"].publication
    raw = load_global_config(cfg).projects["retail"].publication

    assert effective is not None
    assert effective.clearml.project == "Retail/Datasets"
    assert effective.clearml.dataset == "retail-shelves-alice"
    assert effective.api_url == "https://classes.example.com/api"
    assert raw is not None
    assert raw.clearml.dataset == "retail-shelves"


def test_override_list_replaces_the_global_list(tmp_path: Path) -> None:
    team = shared(
        tmp_path / "team.yaml",
        publication={
            "clearml": dict(_DESTINATION),
            "api_url": "https://classes.example.com/api",
            "empty_classes": [12, 13],
        },
    )
    cfg = personal(tmp_path / "config.yaml", team, _publication_override({"empty_classes": [5]}))

    publication = load_project_config(cfg).projects["retail"].publication

    assert publication is not None
    assert publication.empty_classes == [5]


def test_section_readers_never_see_overrides_of_fetch_settings(tmp_path: Path) -> None:
    cfg = personal(tmp_path / "config.yaml", shared(tmp_path / "team.yaml"), _ALICE)

    assert SyncRootsConfig.load(cfg).get_root("Retail shelves") == "s3://my-bucket/images"
    assert CacheConfig.load(cfg).for_project("Retail shelves").ignored_prefix == "shelves/"


@pytest.mark.parametrize("local_overrides", [None, False], ids=["absent", "false"])
def test_overrides_rejected_when_global_file_does_not_allow_them(
    tmp_path: Path,
    local_overrides: bool | None,  # noqa: FBT001 - pytest parameter
) -> None:
    team = shared(tmp_path / "team.yaml", local_overrides=local_overrides)
    cfg = personal(tmp_path / "config.yaml", team, _ALICE)
    before = (cfg.read_bytes(), team.read_bytes())

    for load in (CacheConfig.load, CvatConfig.load, load_project_config):
        with pytest.raises(LocalOverridesDisabledError) as caught:
            load(cfg)
        message = str(caught.value)
        assert "overrides.projects.retail.publication.clearml.dataset" in message
        assert "Удалите" in message
        assert "cveta2 setup --global --local-overrides on" in message

    assert (cfg.read_bytes(), team.read_bytes()) == before


@pytest.mark.parametrize(
    "fields",
    [
        {"id": 9},
        {"name": "x"},
        {"ignore": []},
        {"sync_root": "s3://other/x"},
        {"ignored_prefix": "alt/"},
        {"task_cache_s3": "s3://c/x"},
    ],
    ids=lambda fields: next(iter(fields)),
)
def test_override_of_a_team_only_field_is_rejected_by_shape(tmp_path: Path, fields: dict[str, object]) -> None:
    base: dict[str, object] = {"schema_version": 1, "project_config": str(tmp_path / "team.yaml")}

    with pytest.raises(ManagedError, match="overrides"):
        validate_personal({**base, "overrides": {"projects": {"retail": fields}}}, attached=True)
    with pytest.raises(ManagedError, match="overrides"):
        validate_personal({**base, "overrides": {"cvat": {"host": "https://x.example"}}}, attached=True)


def test_override_for_unknown_project_key_is_rejected(tmp_path: Path) -> None:
    overrides: dict[str, object] = {"projects": {"nope": {"publication": {"clearml": {"dataset": "x"}}}}}
    cfg = personal(tmp_path / "config.yaml", shared(tmp_path / "team.yaml"), overrides)

    with pytest.raises(ManagedError, match="nope"):
        load_project_config(cfg)


def test_override_that_collides_with_another_destination_is_rejected(tmp_path: Path) -> None:
    datasets: dict[str, object] = {
        "shelves": {
            "sources": [{"name": "retail", "type": "cvat", "project": "retail"}],
            "api_url": "https://classes.example.com/api",
            "clearml": {"project": "Retail/Datasets", "dataset": "retail-shelves-alice"},
        }
    }
    team = shared(tmp_path / "team.yaml", datasets=datasets)
    cfg = personal(tmp_path / "config.yaml", team, _ALICE)
    assert load_global_config(cfg).datasets["shelves"].clearml.dataset == "retail-shelves-alice"

    with pytest.raises(ManagedError) as caught:
        load_project_config(cfg)

    assert "Локальные переопределения" in str(caught.value)
    assert "Retail/Datasets/retail-shelves-alice" in str(caught.value)


def test_override_that_leaves_publication_incomplete_is_rejected(tmp_path: Path) -> None:
    team = shared(tmp_path / "team.yaml", with_publication=False)
    cfg = personal(tmp_path / "config.yaml", team, _ALICE)

    with pytest.raises(ManagedError, match=r"publication\.clearml\.project"):
        load_project_config(cfg)


def test_team_write_keeps_overrides_out_of_the_global_file(tmp_path: Path) -> None:
    team = shared(tmp_path / "team.yaml")
    cfg = personal(tmp_path / "config.yaml", team, _ALICE)

    write_shared_project_fields(cfg, {"retail": {"sync_root": "s3://my-bucket/new"}})

    raw = load_global_config(cfg).projects["retail"]
    assert raw.sync_root == "s3://my-bucket/new"
    assert raw.publication is not None
    assert raw.publication.clearml.dataset == "retail-shelves"
    assert "retail-shelves-alice" not in team.read_text(encoding="utf-8")


def test_overrides_need_a_versioned_personal_file(tmp_path: Path) -> None:
    team = shared(tmp_path / "team.yaml")
    cfg = write(tmp_path / "config.yaml", {"project_config": str(team), "overrides": _ALICE})

    with pytest.raises(ManagedError, match="schema_version: 1"):
        load_project_config(cfg)


def test_project_publication_by_cvat_id(tmp_path: Path) -> None:
    cfg = personal(tmp_path / "config.yaml", shared(tmp_path / "team.yaml"), _ALICE)

    publication = project_publication(123, config_path=cfg)

    assert publication is not None
    assert publication.clearml.dataset == "retail-shelves-alice"
    assert project_publication(999, config_path=cfg) is None

    bare = personal(tmp_path / "bare.yaml", shared(tmp_path / "bare-team.yaml", with_publication=False))
    assert project_publication(123, config_path=bare) is None

    legacy = write(tmp_path / "legacy.yaml", {"cvat": {"username": "alice"}})
    assert project_publication(123, config_path=legacy) is None
