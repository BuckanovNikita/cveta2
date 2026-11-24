"""Selecting the global configuration with --global-config, CVETA2_GLOBAL_CONFIG and global_config."""

from pathlib import Path

import pytest
import yaml

from cveta2.adapters.config.project import migration_proposal, project_config_path, read_config
from cveta2.domain.managed.models import ManagedError
from cveta2.interfaces.commands.setup import run_setup
from tests.helpers import parse_cli_args


def _write(path: Path, data: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def _global(path: Path) -> Path:
    return _write(
        path,
        {
            "schema_version": 1,
            "cvat": {"host": "https://cvat.example", "organization": "team"},
            "projects": {"main": {"id": 7, "name": "Main project"}},
            "datasets": {},
        },
    )


def _personal(path: Path, **keys: str) -> Path:
    return _write(path, {"schema_version": 1, "cvat": {"username": "alice"}, **keys})


def test_new_spellings_select_the_global_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    flag = _global(tmp_path / "flag.yaml")
    env = _global(tmp_path / "env.yaml")
    key = _global(tmp_path / "team" / "key.yaml")
    cfg = _write(tmp_path / "personal.yaml", {"cvat": {"username": "alice"}})

    assert project_config_path(cfg, flag) == flag.resolve()

    monkeypatch.setenv("CVETA2_GLOBAL_CONFIG", str(env))
    assert project_config_path(cfg) == env.resolve()
    monkeypatch.delenv("CVETA2_GLOBAL_CONFIG")

    _personal(cfg, global_config="team/key.yaml")
    assert project_config_path(cfg) == key.resolve()


def test_precedence_flag_then_env_then_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    flag = _global(tmp_path / "flag.yaml")
    env = _global(tmp_path / "env.yaml")
    key = _global(tmp_path / "key.yaml")
    cfg = _personal(tmp_path / "personal.yaml", global_config=str(key))
    monkeypatch.setenv("CVETA2_GLOBAL_CONFIG", str(env))

    assert project_config_path(cfg, flag) == flag.resolve()
    assert project_config_path(cfg) == env.resolve()
    monkeypatch.delenv("CVETA2_GLOBAL_CONFIG")
    assert project_config_path(cfg) == key.resolve()


@pytest.mark.parametrize("command", [["dataset", "list"], ["setup"]])
def test_the_old_project_config_flag_is_an_unknown_argument(tmp_path: Path, command: list[str]) -> None:
    with pytest.raises(SystemExit) as exited:
        parse_cli_args(*command, "--project-config", str(_global(tmp_path / "g.yaml")))

    assert exited.value.code == 2


def test_the_old_environment_variable_selects_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _write(tmp_path / "personal.yaml", {"cvat": {"username": "alice"}})
    monkeypatch.delenv("CVETA2_GLOBAL_CONFIG", raising=False)
    monkeypatch.setenv("CVETA2_PROJECT_CONFIG", str(_global(tmp_path / "g.yaml")))

    assert project_config_path(cfg) is None


def test_a_versioned_personal_file_with_the_old_key_is_rejected(tmp_path: Path) -> None:
    cfg = _personal(tmp_path / "personal.yaml", project_config=str(_global(tmp_path / "g.yaml")))

    with pytest.raises(ManagedError, match="project_config"):
        project_config_path(cfg, tmp_path / "g.yaml")


def test_attachment_writes_global_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    new = _global(tmp_path / "new.yaml")
    cfg = _write(tmp_path / "personal.yaml", {"cvat": {"username": "alice"}})
    monkeypatch.setenv("CVETA2_NO_INTERACTIVE", "true")

    run_setup(parse_cli_args("setup", "--config", str(cfg), "--global-config", str(new)))

    assert read_config(cfg) == {
        "cvat": {"username": "alice"},
        "schema_version": 1,
        "global_config": str(new.resolve()),
    }


def _legacy(path: Path, **extra: str) -> Path:
    return _write(
        path,
        {"cvat": {"host": "https://cvat.example", "organization": "team", "username": "alice"}, **extra},
    )


def test_migration_writes_global_config(tmp_path: Path) -> None:
    proposal = migration_proposal(_legacy(tmp_path / "personal.yaml"))

    assert proposal.personal["global_config"] == str(tmp_path.resolve() / "project-config.yaml")
    assert "project_config" not in proposal.personal


def test_migration_reports_the_old_key_of_a_legacy_file_as_unclassified(tmp_path: Path) -> None:
    proposal = migration_proposal(_legacy(tmp_path / "personal.yaml", project_config="team.yaml"))

    assert any("project_config" in item for item in proposal.unresolved)


def test_migration_accepts_a_legacy_file_that_selects_with_global_config(tmp_path: Path) -> None:
    proposal = migration_proposal(_legacy(tmp_path / "personal.yaml", global_config="team.yaml"))

    assert proposal.unresolved == ()


def test_a_versioned_personal_file_without_a_reference_names_the_key_and_the_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CVETA2_GLOBAL_CONFIG", raising=False)
    cfg = _personal(tmp_path / "personal.yaml")

    with pytest.raises(ManagedError) as caught:
        project_config_path(cfg)

    assert "global_config" in str(caught.value)
    assert "cveta2 setup --global-config PATH" in str(caught.value)
