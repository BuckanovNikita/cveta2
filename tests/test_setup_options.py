"""``cveta2 setup`` option flags: set, unset and create configuration values without prompts."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import yaml

from cveta2.adapters.config.project import load_global_config, load_project_config, read_config
from cveta2.adapters.config.settings import CacheConfig, CvatConfig, ImageCacheConfig
from cveta2.domain.errors import Cveta2Error, InteractiveModeRequiredError, ProjectNotFoundError
from cveta2.domain.managed.models import MigrationRequired
from cveta2.domain.models import ProjectInfo
from cveta2.interfaces.commands.interactive import primitives
from cveta2.interfaces.commands.setup import run_setup
from tests.helpers import CFG, mock_client_ctx, parse_cli_args, patch_cli_client

if TYPE_CHECKING:
    from collections.abc import Mapping

_HOST = "https://cvat.example"
_ORGANIZATION = "team"
_API = "https://classes.example.com/api"
_PUBLICATION: dict[str, object] = {
    "clearml": {"project": "Retail/Datasets", "dataset": "retail-shelves"},
    "api_url": _API,
}
_CREATION_FORM = "cveta2 setup --global --global-config PATH --host URL [--organization SLUG]"


@pytest.fixture(autouse=True)
def _isolated_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Select files only through the test's own arguments, and fail on any prompt."""
    for name in (
        "CVETA2_GLOBAL_CONFIG",
        "CVETA2_PROJECT_CONFIG",
        "CVETA2_CONFIG",
        "CVAT_HOST",
        "CVAT_ORGANIZATION",
        "CVAT_USERNAME",
        "CVAT_PASSWORD",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CVETA2_NO_INTERACTIVE", "true")


def write(path: Path, data: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def team(
    path: Path,
    *,
    local_overrides: bool | None = True,
    publication: dict[str, object] | None = None,
) -> Path:
    """Write a global file with one ``retail`` project."""
    retail: dict[str, object] = {"id": 123, "name": "Retail shelves", "sync_root": "s3://my-bucket/images"}
    if publication is not None:
        retail["publication"] = publication
    data: dict[str, object] = {
        "schema_version": 1,
        "cvat": {"host": _HOST, "organization": _ORGANIZATION},
        "projects": {"retail": retail},
    }
    if local_overrides is not None:
        data["local_overrides"] = local_overrides
    return write(path, data)


def attached(
    tmp_path: Path,
    *,
    local_overrides: bool | None = True,
    publication: dict[str, object] | None = None,
    overrides: Mapping[str, object] | None = None,
) -> tuple[Path, Path]:
    """Write a versioned personal file attached to a fresh global file."""
    global_file = team(tmp_path / "team.yaml", local_overrides=local_overrides, publication=publication)
    data: dict[str, object] = {
        "schema_version": 1,
        "global_config": str(global_file),
        "cvat": {"username": "alice", "password": "private"},
    }
    if overrides is not None:
        data["overrides"] = overrides
    return write(tmp_path / "config.yaml", data), global_file


def unattached(tmp_path: Path) -> Path:
    """Write the personal file a first ``cveta2 setup`` leaves: unversioned, with the CVAT identity."""
    return write(
        tmp_path / "config.yaml",
        {"cvat": {"host": _HOST, "organization": _ORGANIZATION, "username": "alice", "password": "private"}},
    )


def dataset_override(dataset: str = "mine") -> dict[str, object]:
    return {"projects": {"retail": {"publication": {"clearml": {"dataset": dataset}}}}}


def run(cfg: Path, *argv: str) -> None:
    run_setup(parse_cli_args("setup", "--config", str(cfg), *argv))


def files(root: Path) -> dict[str, bytes]:
    """Every file under *root* with its bytes, so a refusal can be shown to change nothing."""
    return {str(path.relative_to(root)): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}


def write_projects_cache(cfg: Path, projects: list[dict[str, object]]) -> None:
    write(
        cfg.parent / "projects.yaml",
        {"organizations": [{"slug": _ORGANIZATION, "name": "Team", "projects": projects}]},
    )


# ---------------------------------------------------------------------------
# Refused combinations
# ---------------------------------------------------------------------------

_MISSING = "{missing}"

_REFUSED: list[tuple[str, list[str], tuple[str, ...]]] = [
    ("attached", ["--migrate-config", "--username", "bob"], ("--migrate-config",)),
    ("attached", ["--migrate-config", "--unset", "username"], ("--migrate-config",)),
    ("attached", ["--migrate-config", "--global"], ("--migrate-config",)),
    ("attached", ["--migrate-config", "-p", "retail"], ("--migrate-config",)),
    ("attached", ["--migrate-config", "--reset"], ("--migrate-config",)),
    ("attached", ["--username", "bob", "--unset", "tasks-root"], ("--unset",)),
    ("attached", ["--reset", "--username", "bob"], ("--reset",)),
    ("attached", ["--reset", "--unset", "username"], ("--reset",)),
    ("attached", ["--reset", "--global"], ("--reset",)),
    ("attached", ["--global", "--username", "bob"], ("--username", "личной конфигурации")),
    ("attached", ["--global", "--password"], ("--password", "личной конфигурации")),
    ("attached", ["--global", "--images-root", "/data/img"], ("--images-root", "личной конфигурации")),
    ("attached", ["--global", "--tasks-root", "/data/t"], ("--tasks-root", "личной конфигурации")),
    ("attached", ["--global", "-p", "retail", "--images-dir", "/d"], ("--images-dir", "личной конфигурации")),
    ("attached", ["--global", "--unset", "username"], ("--username", "личной конфигурации")),
    ("attached", ["--local-overrides", "on"], ("--global",)),
    ("attached", ["--unset", "local-overrides"], ("--global",)),
    ("attached", ["-p", "retail", "--sync-root", "s3://b/x"], ("--sync-root", "cveta2 setup --global")),
    ("attached", ["-p", "retail", "--ignored-prefix", "x/"], ("--ignored-prefix", "cveta2 setup --global")),
    ("attached", ["-p", "retail", "--task-cache-s3", "s3://b/c"], ("--task-cache-s3", "cveta2 setup --global")),
    ("attached", ["-p", "retail", "--unset", "sync-root"], ("--sync-root", "cveta2 setup --global")),
    ("unattached", ["-p", "retail", "--dataset-name", "x"], ("общей конфигурации", "verify")),
    ("unattached", ["-p", "retail", "--unset", "api-url"], ("общей конфигурации", "verify")),
    ("attached", ["--dataset-name", "x"], ("--project",)),
    ("attached", ["--unset", "dataset-name"], ("--project",)),
    ("attached", ["--unset", "publication"], ("--project",)),
    ("attached", ["--global", "--unset", "publication"], ("--project",)),
    ("attached", ["--global", "--sync-root", "s3://b/x"], ("--project",)),
    ("attached", ["--images-dir", "/data/r"], ("--project",)),
    ("attached", ["--host", "https://other.example"], ("cveta2 setup --global --host",)),
    ("attached", ["--organization", "other"], ("cveta2 setup --global --host",)),
    ("attached", ["--unset", "organization"], ("cveta2 setup --global --host",)),
    ("unattached", ["--global", "-p", "retail", "--sync-root", "s3://b/x"], (_CREATION_FORM,)),
    ("unattached", ["--global", "--unset", "organization"], (_CREATION_FORM,)),
    ("unattached", ["--global", "--global-config", _MISSING, "--local-overrides", "on"], (_CREATION_FORM,)),
    ("attached", ["--global", "--global-config", _MISSING, "--local-overrides", "on"], (_CREATION_FORM,)),
    ("unattached", ["--global", "--host", _HOST], (_CREATION_FORM,)),
    # Refused before the new file is created, not after.
    (
        "unattached",
        ["--global", "--global-config", _MISSING, "--host", _HOST, "--username", "bob"],
        ("--username", "личной конфигурации"),
    ),
]


@pytest.mark.parametrize(("state", "argv", "messages"), _REFUSED)
def test_invalid_combinations_are_refused(
    tmp_path: Path, state: str, argv: list[str], messages: tuple[str, ...]
) -> None:
    cfg = attached(tmp_path)[0] if state == "attached" else unattached(tmp_path)
    before = files(tmp_path)
    arguments = [str(tmp_path / "new.yaml") if value == _MISSING else value for value in argv]

    with pytest.raises(Cveta2Error) as caught:
        run(cfg, *arguments)

    for message in messages:
        assert message in str(caught.value)
    assert files(tmp_path) == before


def test_migrate_config_runs_before_any_selection_check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CVETA2_NO_INTERACTIVE")
    write_projects_cache(tmp_path / "config.yaml", [{"id": 7, "name": "Main project"}])
    cfg = write(
        tmp_path / "config.yaml",
        {
            "cvat": {"host": _HOST, "organization": _ORGANIZATION, "username": "alice", "password": "private"},
            "sync_roots": {"Main project": "s3://bucket/images"},
        },
    )
    before = cfg.read_bytes()
    asked: list[str] = []

    def decline(message: str, **_kwargs: object) -> bool:
        asked.append(message)
        return False

    monkeypatch.setattr(primitives, "confirm", decline)

    run(cfg, "--migrate-config", "--global-config", str(tmp_path / "team.yaml"))

    assert asked == ["Подтвердить показанное разделение конфигурации?"]
    assert cfg.read_bytes() == before


def test_unknown_unset_operand_is_a_usage_error() -> None:
    with pytest.raises(SystemExit) as caught:
        parse_cli_args("setup", "--unset", "nope")
    assert caught.value.code == 2


# ---------------------------------------------------------------------------
# Personal options
# ---------------------------------------------------------------------------


def test_personal_options_write_only_the_personal_file(tmp_path: Path) -> None:
    cfg, global_file = attached(tmp_path)
    before = global_file.read_bytes()

    run(
        cfg,
        *("--username", "bob", "--images-root", "/data/img", "--tasks-root", "/data/t"),
        *("--project", "Retail shelves", "--images-dir", "/data/r"),
    )

    assert CvatConfig.from_file(cfg).username == "bob"
    assert CvatConfig.from_file(cfg).password == "private"
    assert CacheConfig.load(cfg).images_root == Path("/data/img")
    assert CacheConfig.load(cfg).tasks_root == Path("/data/t")
    assert ImageCacheConfig.load(cfg).get_cache_dir("Retail shelves") == Path("/data/r")
    assert global_file.read_bytes() == before


def test_unset_of_personal_options(tmp_path: Path) -> None:
    cfg, _ = attached(tmp_path)
    run(cfg, "--images-root", "/data/img", "-p", "retail", "--images-dir", "/data/r")

    run(cfg, "-p", "retail", "--unset", "username", "images-root", "images-dir")

    assert CvatConfig.from_file(cfg).username is None
    assert CvatConfig.from_file(cfg).password == "private"
    assert CacheConfig.load(cfg).images_root is None
    assert ImageCacheConfig.load(cfg).get_cache_dir("Retail shelves") is None


def test_images_dir_of_an_unattached_project_is_named_from_the_projects_cache(tmp_path: Path) -> None:
    cfg = unattached(tmp_path)
    write_projects_cache(cfg, [{"id": 321, "name": "New shelves"}])

    run(cfg, "-p", "321", "--images-dir", "/data/n")

    assert ImageCacheConfig.load(cfg).get_cache_dir("New shelves") == Path("/data/n")


def test_personal_options_first_then_attach(tmp_path: Path) -> None:
    """The documented order: credentials on a fresh machine, then the team's global file."""
    global_file = team(tmp_path / "team.yaml")
    cfg = tmp_path / "config.yaml"

    run(cfg, "--username", "bob")
    assert read_config(cfg)["cvat"] == {"username": "bob"}
    run(cfg, "--global-config", str(global_file))

    assert read_config(cfg)["global_config"] == str(global_file.resolve())
    assert CvatConfig.from_file(cfg).username == "bob"


def test_personal_options_first_then_create(tmp_path: Path) -> None:
    cfg = tmp_path / "config.yaml"
    target = tmp_path / "new.yaml"

    run(cfg, "--username", "bob")
    run(cfg, "--global", "--global-config", str(target), "--host", _HOST)

    assert load_global_config(cfg).cvat.host == _HOST
    assert CvatConfig.from_file(cfg).username == "bob"


def test_each_written_file_is_logged_once(tmp_path: Path, capture_info_logs: list[str]) -> None:
    cfg, global_file = attached(tmp_path, publication=_PUBLICATION, overrides=dataset_override())

    run(cfg, "--global", "-p", "retail", "--ignored-prefix", "skip/")
    run(cfg, "-p", "retail", "--unset", "dataset-name")

    assert f"Записано в общую конфигурацию {global_file.resolve()}: projects.retail.ignored_prefix" in capture_info_logs
    assert (
        f"Удалено из личной конфигурации {cfg}: overrides.projects.retail.publication.clearml.dataset"
        in capture_info_logs
    )


def test_host_in_legacy_mode_writes_the_personal_file(tmp_path: Path) -> None:
    cfg = write(tmp_path / "config.yaml", {"cvat": {"username": "alice", "password": "private"}})

    run(cfg, "--host", "https://h.example", "--organization", "o")

    saved = CvatConfig.from_file(cfg)
    assert (saved.host, saved.organization, saved.username) == ("https://h.example", "o", "alice")


def test_password_flag_refuses_without_terminal(tmp_path: Path) -> None:
    cfg, _ = attached(tmp_path)
    before = cfg.read_bytes()

    with pytest.raises(InteractiveModeRequiredError) as caught:
        run(cfg, "--password")

    assert "CVAT_PASSWORD" in str(caught.value)
    assert cfg.read_bytes() == before


def test_password_flag_prompts_hidden(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CVETA2_NO_INTERACTIVE")
    cfg, _ = attached(tmp_path)
    prompts: list[str] = []

    def hidden(message: str) -> str:
        prompts.append(message)
        return "s3cret"

    monkeypatch.setattr(primitives, "prompt_password", hidden)
    for visible in ("text", "path", "confirm"):
        monkeypatch.setattr(primitives, visible, lambda *_a, **_k: pytest.fail("unexpected prompt"))

    run(cfg, "--password")

    assert len(prompts) == 1
    assert CvatConfig.from_file(cfg).password == "s3cret"
    assert CvatConfig.from_file(cfg).username == "alice"


# ---------------------------------------------------------------------------
# Global options
# ---------------------------------------------------------------------------


def test_global_project_options_write_the_global_file(tmp_path: Path) -> None:
    cfg, _ = attached(tmp_path)
    before = cfg.read_bytes()

    run(
        cfg,
        *("--global", "--project", "retail", "--clearml-project", "Retail/Datasets"),
        *("--dataset-name", "retail-shelves", "--api-url", _API),
        *("--empty-class", "12", "--empty-class", "13", "--s3-root", "s3://b/i"),
    )

    publication = load_global_config(cfg).projects["retail"].publication
    assert publication is not None
    assert publication.model_dump(mode="json") == {
        "clearml": {"project": "Retail/Datasets", "dataset": "retail-shelves"},
        "api_url": _API,
        "empty_classes": [12, 13],
        "s3_roots": ["s3://b/i"],
    }
    assert cfg.read_bytes() == before


def test_repeated_empty_class_replaces_the_list(tmp_path: Path) -> None:
    cfg, _ = attached(tmp_path, publication={**_PUBLICATION, "empty_classes": [12, 13]})

    run(cfg, "--global", "-p", "retail", "--empty-class", "5")

    publication = load_global_config(cfg).projects["retail"].publication
    assert publication is not None
    assert publication.empty_classes == [5]


def test_global_team_options_by_project_name(tmp_path: Path) -> None:
    cfg, _ = attached(tmp_path)

    run(cfg, "--global", "-p", "Retail shelves", "--ignored-prefix", "skip/", "--task-cache-s3", "s3://b/c")

    retail = load_global_config(cfg).projects["retail"]
    assert (retail.ignored_prefix, retail.task_cache_s3) == ("skip/", "s3://b/c")


def test_global_host_updates_the_attached_file(tmp_path: Path) -> None:
    cfg, _ = attached(tmp_path)

    run(cfg, "--global", "--host", "https://new.example", "--organization", "other")

    identity = load_global_config(cfg).cvat
    assert (identity.host, identity.organization) == ("https://new.example", "other")


def test_local_overrides_switch(tmp_path: Path) -> None:
    cfg, global_file = attached(tmp_path, local_overrides=None)

    run(cfg, "--global", "--local-overrides", "on")
    assert load_global_config(cfg).local_overrides is True
    assert read_config(global_file)["local_overrides"] is True

    run(cfg, "--global", "--local-overrides", "off")
    assert load_global_config(cfg).local_overrides is False
    assert "local_overrides" not in read_config(global_file)


def test_switch_on_repairs_a_personal_file_with_disallowed_overrides(tmp_path: Path) -> None:
    cfg, _ = attached(tmp_path, local_overrides=None, publication=_PUBLICATION, overrides=dataset_override())

    run(cfg, "--global", "--local-overrides", "on")

    publication = load_project_config(cfg).projects["retail"].publication
    assert publication is not None
    assert publication.clearml.dataset == "mine"


# ---------------------------------------------------------------------------
# Local overrides
# ---------------------------------------------------------------------------


def test_project_option_without_global_writes_a_local_override(tmp_path: Path) -> None:
    cfg, global_file = attached(tmp_path, publication=_PUBLICATION)
    before = global_file.read_bytes()

    run(cfg, "--project", "retail", "--dataset-name", "mine")

    assert read_config(cfg)["overrides"] == dataset_override()
    assert global_file.read_bytes() == before


def test_project_option_without_global_refused_when_switch_off(tmp_path: Path) -> None:
    cfg, _ = attached(tmp_path, local_overrides=None, publication=_PUBLICATION)
    before = files(tmp_path)

    with pytest.raises(Cveta2Error, match="cveta2 setup --global --local-overrides on"):
        run(cfg, "--project", "retail", "--dataset-name", "mine")

    assert files(tmp_path) == before


def test_local_override_of_a_project_without_definition_is_refused(tmp_path: Path) -> None:
    cfg, _ = attached(tmp_path, publication=_PUBLICATION)
    before = files(tmp_path)

    with pytest.raises(Cveta2Error, match="cveta2 setup --global --project other"):
        run(cfg, "--project", "other", "--dataset-name", "mine")

    assert files(tmp_path) == before


def test_unset_of_an_override_works_when_switch_off(tmp_path: Path) -> None:
    cfg, global_file = attached(tmp_path, local_overrides=None, publication=_PUBLICATION, overrides=dataset_override())
    before = global_file.read_bytes()

    run(cfg, "-p", "retail", "--unset", "dataset-name")

    assert "overrides" not in read_config(cfg)
    assert global_file.read_bytes() == before


def test_unset_publication_removes_the_whole_override_block_and_repairs_the_readers(tmp_path: Path) -> None:
    overrides = {
        "projects": {"retail": {"publication": {"clearml": {"dataset": "mine"}, "empty_classes": [1]}}},
    }
    cfg, _ = attached(tmp_path, local_overrides=None, publication=_PUBLICATION, overrides=overrides)

    run(cfg, "-p", "retail", "--unset", "publication")

    assert "overrides" not in read_config(cfg)
    assert CvatConfig.load(cfg).username == "alice"
    assert load_project_config(cfg).projects["retail"].publication is not None


def test_unset_of_a_stale_override_of_a_removed_project(tmp_path: Path) -> None:
    overrides = {"projects": {"gone": {"publication": {"clearml": {"dataset": "mine"}}}}}
    cfg, _ = attached(tmp_path, publication=_PUBLICATION, overrides=overrides)

    run(cfg, "-p", "gone", "--unset", "dataset-name")

    assert "overrides" not in read_config(cfg)


def test_unset_of_one_leaf_that_leaves_an_incomplete_block_is_refused(tmp_path: Path) -> None:
    overrides = {"projects": {"retail": {"publication": _PUBLICATION}}}
    cfg, _ = attached(tmp_path, overrides=overrides)
    before = files(tmp_path)

    with pytest.raises(Cveta2Error, match="--unset publication"):
        run(cfg, "-p", "retail", "--unset", "api-url")
    assert files(tmp_path) == before

    run(cfg, "-p", "retail", "--unset", "publication")
    assert "overrides" not in read_config(cfg)
    assert load_project_config(cfg).projects["retail"].publication is None


def two_published_projects(tmp_path: Path, overrides: Mapping[str, object]) -> Path:
    """Attach a global file with projects ``a`` and ``b`` published to ``R/a`` and ``R/b``."""
    projects = {
        name: {
            "id": project_id,
            "name": name,
            "publication": {"clearml": {"project": "R", "dataset": name}, "api_url": _API},
        }
        for name, project_id in (("a", 1), ("b", 2))
    }
    global_file = write(
        tmp_path / "team.yaml",
        {"schema_version": 1, "local_overrides": True, "cvat": {"host": _HOST}, "projects": projects},
    )
    return write(
        tmp_path / "config.yaml",
        {"schema_version": 1, "global_config": str(global_file), "overrides": dict(overrides)},
    )


def _dataset_overrides(**datasets: str) -> dict[str, object]:
    return {
        "projects": {name: {"publication": {"clearml": {"dataset": dataset}}} for name, dataset in datasets.items()}
    }


def test_unset_that_collides_with_another_projects_override_is_refused(tmp_path: Path) -> None:
    cfg = two_published_projects(tmp_path, _dataset_overrides(a="x", b="a"))
    before = cfg.read_bytes()

    with pytest.raises(Cveta2Error) as caught:
        run(cfg, "-p", "a", "--unset", "dataset-name")

    assert "R/a" in str(caught.value)
    assert "--unset publication" in str(caught.value)
    assert cfg.read_bytes() == before
    assert load_project_config(cfg).projects["a"].publication is not None


def test_unset_of_a_whole_block_that_collides_with_another_projects_override_is_refused(tmp_path: Path) -> None:
    cfg = two_published_projects(tmp_path, _dataset_overrides(a="x", b="a"))
    before = cfg.read_bytes()

    with pytest.raises(Cveta2Error) as caught:
        run(cfg, "-p", "a", "--unset", "publication")

    assert "R/a" in str(caught.value)
    assert "переопределение другого проекта" in str(caught.value)
    assert cfg.read_bytes() == before

    run(cfg, "-p", "b", "--unset", "publication")
    run(cfg, "-p", "a", "--unset", "publication")
    assert "overrides" not in read_config(cfg)


def test_unset_is_accepted_when_the_overrides_are_already_invalid(tmp_path: Path) -> None:
    cfg = two_published_projects(tmp_path, _dataset_overrides(a="b"))
    with pytest.raises(Cveta2Error, match="R/b"):
        load_project_config(cfg)

    run(cfg, "-p", "a", "--unset", "dataset-name")

    assert "overrides" not in read_config(cfg)
    assert load_project_config(cfg).projects["a"].publication is not None


def test_fetch_settings_are_never_written_locally(tmp_path: Path) -> None:
    cfg, _ = attached(tmp_path, publication=_PUBLICATION)
    before = files(tmp_path)

    with pytest.raises(Cveta2Error, match="cveta2 setup --global"):
        run(cfg, "-p", "retail", "--sync-root", "s3://b/x")

    assert files(tmp_path) == before


# ---------------------------------------------------------------------------
# Unset in the global file
# ---------------------------------------------------------------------------


def test_unset_removes_from_the_selected_file(tmp_path: Path) -> None:
    cfg, global_file = attached(tmp_path, publication=_PUBLICATION, overrides=dataset_override())

    run(cfg, "--global", "--project", "retail", "--unset", "sync-root")
    assert load_global_config(cfg).projects["retail"].sync_root is None
    assert read_config(cfg)["overrides"] == dataset_override()

    global_before = global_file.read_bytes()
    run(cfg, "--project", "retail", "--unset", "dataset-name")
    assert "overrides" not in read_config(cfg)
    assert global_file.read_bytes() == global_before

    complete = global_file.read_bytes()
    with pytest.raises(Cveta2Error, match="publication"):
        run(cfg, "--global", "--project", "retail", "--unset", "dataset-name")
    assert global_file.read_bytes() == complete

    run(cfg, "--global", "--project", "retail", "--unset", "publication")
    assert load_global_config(cfg).projects["retail"].publication is None


def test_global_unset_of_an_unknown_project_adds_no_definition(tmp_path: Path) -> None:
    cfg, global_file = attached(tmp_path)
    write_projects_cache(cfg, [{"id": 321, "name": "New shelves"}])
    before = global_file.read_bytes()

    with pytest.raises(Cveta2Error, match="321"):
        run(cfg, "--global", "-p", "321", "--unset", "sync-root")

    assert global_file.read_bytes() == before


# ---------------------------------------------------------------------------
# New definitions and new global files
# ---------------------------------------------------------------------------


def test_global_adds_a_definition_from_the_projects_cache(tmp_path: Path) -> None:
    cfg, _ = attached(tmp_path)
    write_projects_cache(cfg, [{"id": 321, "name": "New shelves"}, {"id": 322, "name": "shelves"}])

    run(cfg, "--global", "--project", "321", "--sync-root", "s3://b/n")
    run(cfg, "--global", "--project", "shelves", "--sync-root", "s3://b/s")

    projects = load_global_config(cfg).projects
    assert (projects["project-321"].id, projects["project-321"].name) == (321, "New shelves")
    assert projects["project-321"].sync_root == "s3://b/n"
    assert (projects["shelves"].id, projects["shelves"].name) == (322, "shelves")


def test_global_adds_a_definition_named_by_cvat(tmp_path: Path) -> None:
    cfg, _ = attached(tmp_path)

    with patch_cli_client(mock_client_ctx(project_id=400), config=CFG):
        run(cfg, "--global", "--project", "Remote", "--ignored-prefix", "skip/")

    remote = load_global_config(cfg).projects["Remote"]
    assert (remote.id, remote.name, remote.ignored_prefix) == (400, "Remote", "skip/")


@pytest.mark.parametrize("answer", ["missing", "unnamed"])
def test_global_refuses_a_project_nobody_knows(tmp_path: Path, answer: str) -> None:
    cfg, _ = attached(tmp_path)
    before = files(tmp_path)
    client = mock_client_ctx(project_id=400)
    if answer == "missing":
        client.find_project_by_name.side_effect = ProjectNotFoundError("Проект не найден")
    else:
        client.find_project_by_name.side_effect = lambda *_a, **_k: ProjectInfo(id=400, name="")

    with patch_cli_client(client, config=CFG), pytest.raises(Cveta2Error, match="Не удалось определить имя проекта"):
        run(cfg, "--global", "--project", "Remote", "--sync-root", "s3://b/r")

    assert files(tmp_path) == before


def test_global_creates_a_new_global_file(tmp_path: Path) -> None:
    cfg = unattached(tmp_path)
    target = tmp_path / "new.yaml"

    run(cfg, "--global", "--global-config", str(target), "--host", _HOST, "--organization", _ORGANIZATION)

    created = read_config(target)
    assert created["local_overrides"] is True
    assert created["cvat"] == {"host": _HOST, "organization": _ORGANIZATION}
    saved = read_config(cfg)
    assert saved["schema_version"] == 1
    assert saved["global_config"] == str(target.resolve())
    assert saved["cvat"] == {"username": "alice", "password": "private"}


def test_global_creates_a_new_global_file_at_the_environment_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = unattached(tmp_path)
    target = tmp_path / "env.yaml"
    monkeypatch.setenv("CVETA2_GLOBAL_CONFIG", str(target))

    run(cfg, "--global", "--host", _HOST, "--organization", _ORGANIZATION)

    assert read_config(target)["local_overrides"] is True
    assert read_config(cfg)["global_config"] == str(target.resolve())


def test_global_creation_applies_the_remaining_options(tmp_path: Path) -> None:
    cfg = unattached(tmp_path)
    write_projects_cache(cfg, [{"id": 123, "name": "retail"}])
    target = tmp_path / "new.yaml"

    run(
        cfg,
        *("--global", "--global-config", str(target), "--host", _HOST, "--organization", _ORGANIZATION),
        *("-p", "retail", "--sync-root", "s3://b/r"),
    )

    created = load_global_config(cfg)
    assert created.cvat.host == _HOST
    assert created.projects["retail"].sync_root == "s3://b/r"


def test_global_creation_without_host_is_refused(tmp_path: Path) -> None:
    cfg = unattached(tmp_path)
    before = files(tmp_path)

    with pytest.raises(Cveta2Error) as caught:
        run(cfg, "--global", "--global-config", str(tmp_path / "new.yaml"), "--local-overrides", "on")

    assert _CREATION_FORM in str(caught.value)
    assert files(tmp_path) == before


def test_global_config_alone_still_attaches(tmp_path: Path) -> None:
    global_file = team(tmp_path / "team.yaml")
    cfg = write(tmp_path / "config.yaml", {"cvat": {"username": "alice", "password": "private"}})
    before = global_file.read_bytes()

    run(cfg, "--global-config", str(global_file))

    assert read_config(cfg)["global_config"] == str(global_file.resolve())
    assert global_file.read_bytes() == before


def test_global_config_with_options_attaches_then_writes(tmp_path: Path) -> None:
    global_file = team(tmp_path / "team.yaml")
    cfg = write(tmp_path / "config.yaml", {"cvat": {"username": "alice", "password": "private"}})

    run(cfg, "--global-config", str(global_file), "--username", "bob")

    assert read_config(cfg)["global_config"] == str(global_file.resolve())
    assert CvatConfig.from_file(cfg).username == "bob"


def test_global_config_attaches_a_personal_file_with_the_same_cvat_identity(tmp_path: Path) -> None:
    # What `cveta2 setup --host … --organization …` or the personal wizard leaves behind.
    cfg = unattached(tmp_path)
    global_file = team(tmp_path / "team.yaml")
    before = global_file.read_bytes()

    run(cfg, "--global-config", str(global_file))

    saved = read_config(cfg)
    assert saved["schema_version"] == 1
    assert saved["global_config"] == str(global_file.resolve())
    assert saved["cvat"] == {"username": "alice", "password": "private"}
    assert global_file.read_bytes() == before


def test_global_config_refuses_a_personal_file_with_another_cvat_identity(tmp_path: Path) -> None:
    cfg = write(
        tmp_path / "config.yaml",
        {"cvat": {"host": "https://other.example", "organization": _ORGANIZATION, "username": "alice"}},
    )
    global_file = team(tmp_path / "team.yaml")
    before = files(tmp_path)

    with pytest.raises(Cveta2Error, match="differ from shared configuration"):
        run(cfg, "--global-config", str(global_file))

    assert files(tmp_path) == before


def test_global_config_still_requires_migration_for_shared_keys_in_the_personal_file(tmp_path: Path) -> None:
    cfg = write(
        tmp_path / "config.yaml",
        {
            "cvat": {"host": _HOST, "organization": _ORGANIZATION, "username": "alice"},
            "sync_roots": {"Retail shelves": "s3://my-bucket/images"},
        },
    )
    global_file = team(tmp_path / "team.yaml")
    before = files(tmp_path)

    with pytest.raises(MigrationRequired):
        run(cfg, "--global-config", str(global_file))

    assert files(tmp_path) == before


def moved_global_file(tmp_path: Path) -> tuple[Path, Path]:
    """Write a personal file whose ``global_config`` names a global file that is gone."""
    missing = tmp_path / "team dir" / "moved.yaml"
    missing.parent.mkdir()
    cfg = write(
        tmp_path / "config.yaml",
        {"schema_version": 1, "global_config": str(missing), "cvat": {"username": "alice", "password": "private"}},
    )
    return cfg, missing


@pytest.mark.parametrize(
    "argv",
    [["--local-overrides", "on"], ["--host", _HOST], ["-p", "retail", "--sync-root", "s3://b/r"], []],
)
def test_global_write_to_a_missing_file_selected_by_the_personal_key_is_refused(
    tmp_path: Path, argv: list[str]
) -> None:
    cfg, missing = moved_global_file(tmp_path)
    before = files(tmp_path)

    with pytest.raises(Cveta2Error) as caught:
        run(cfg, "--global", *argv)

    message = str(caught.value)
    assert f"Файла общей конфигурации {missing} нет" in message
    assert f"cveta2 setup --global --global-config '{missing}' --host URL" in message
    # No lock file is left beside the missing file.
    assert files(tmp_path) == before


def test_the_suggested_command_creates_the_missing_global_file(tmp_path: Path) -> None:
    cfg, missing = moved_global_file(tmp_path)

    run(cfg, "--global", "--global-config", str(missing), "--host", _HOST, "--organization", _ORGANIZATION)
    run(cfg, "--global", "--local-overrides", "off")

    assert load_global_config(cfg).cvat.host == _HOST
    assert read_config(cfg)["global_config"] == str(missing.resolve())


def test_suggested_commands_quote_the_project(tmp_path: Path) -> None:
    cfg, _ = attached(tmp_path, publication=_PUBLICATION)

    with pytest.raises(Cveta2Error) as caught:
        run(cfg, "--project", "Bakery shelves", "--dataset-name", "mine")

    assert "cveta2 setup --global --project 'Bakery shelves'" in str(caught.value)


def test_legacy_mixed_personal_file_still_requires_migration(tmp_path: Path) -> None:
    cfg = write(
        tmp_path / "config.yaml",
        {"cvat": {"host": _HOST, "username": "alice"}, "sync_roots": {"Main project": "s3://bucket/images"}},
    )

    with pytest.raises(MigrationRequired):
        run(cfg, "--username", "bob")
