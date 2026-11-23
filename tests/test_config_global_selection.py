"""Selecting the global configuration by its new and old spellings."""

from pathlib import Path

import pytest
import yaml

from cveta2.adapters.config.project import migration_proposal, project_config_path, read_config
from cveta2.domain.errors import Cveta2Error
from cveta2.domain.managed.models import ManagedError
from cveta2.interfaces.cli import main
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


@pytest.mark.parametrize(
    ("env_name", "key_name"),
    [
        ("CVETA2_GLOBAL_CONFIG", "global_config"),
        ("CVETA2_PROJECT_CONFIG", "project_config"),
        ("CVETA2_GLOBAL_CONFIG", "project_config"),
        ("CVETA2_PROJECT_CONFIG", "global_config"),
    ],
)
def test_precedence_flag_then_env_then_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env_name: str, key_name: str
) -> None:
    flag = _global(tmp_path / "flag.yaml")
    env = _global(tmp_path / "env.yaml")
    key = _global(tmp_path / "key.yaml")
    cfg = _personal(tmp_path / "personal.yaml", **{key_name: str(key)})
    monkeypatch.setenv(env_name, str(env))

    assert project_config_path(cfg, flag) == flag.resolve()
    assert project_config_path(cfg) == env.resolve()
    monkeypatch.delenv(env_name)
    assert project_config_path(cfg) == key.resolve()


@pytest.mark.parametrize("level", ["env", "key"])
def test_old_and_new_spelling_that_differ_stop_the_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, level: str
) -> None:
    first = _global(tmp_path / "first.yaml")
    second = _global(tmp_path / "second.yaml")
    if level == "env":
        cfg = _write(tmp_path / "personal.yaml", {"cvat": {"username": "alice"}})
        monkeypatch.setenv("CVETA2_GLOBAL_CONFIG", str(first))
        monkeypatch.setenv("CVETA2_PROJECT_CONFIG", str(second))
        names = ("CVETA2_GLOBAL_CONFIG", "CVETA2_PROJECT_CONFIG")
    else:
        cfg = _personal(tmp_path / "personal.yaml", global_config=str(first), project_config=str(second))
        names = ("global_config", "project_config")

    with pytest.raises(ManagedError) as caught:
        project_config_path(cfg)

    assert all(name in str(caught.value) for name in names)


def test_a_higher_level_wins_over_a_conflicting_lower_level(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """First match wins: a conflict below the selecting level is not consulted."""
    flag = _global(tmp_path / "flag.yaml")
    cfg = _personal(
        tmp_path / "personal.yaml",
        global_config=str(_global(tmp_path / "a.yaml")),
        project_config=str(_global(tmp_path / "b.yaml")),
    )
    monkeypatch.setenv("CVETA2_GLOBAL_CONFIG", str(tmp_path / "c.yaml"))
    monkeypatch.setenv("CVETA2_PROJECT_CONFIG", str(tmp_path / "d.yaml"))

    assert project_config_path(cfg, flag) == flag.resolve()


def test_old_and_new_flags_that_differ_stop_dataset_commands(tmp_path: Path, capture_logs: list[str]) -> None:
    with pytest.raises(SystemExit) as exited:
        main(["dataset", "list", "--global-config", str(tmp_path / "a"), "--project-config", str(tmp_path / "b")])

    assert exited.value.code == 2
    assert any("--global-config" in line and "--project-config" in line for line in capture_logs)


def test_old_and_new_flags_that_differ_stop_setup(tmp_path: Path) -> None:
    args = parse_cli_args("setup", "--global-config", str(tmp_path / "a"), "--project-config", str(tmp_path / "b"))

    with pytest.raises(Cveta2Error) as caught:
        run_setup(args)

    assert "--global-config" in str(caught.value)
    assert "--project-config" in str(caught.value)


def test_old_and_new_spelling_with_the_same_path_are_accepted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = _global(tmp_path / "g.yaml")
    cfg = _write(tmp_path / "personal.yaml", {"cvat": {"username": "alice"}})
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CVETA2_GLOBAL_CONFIG", "./g.yaml")
    monkeypatch.setenv("CVETA2_PROJECT_CONFIG", str(target.resolve()))

    assert project_config_path(cfg) == target.resolve()


def test_attachment_writes_global_config_and_drops_project_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _global(tmp_path / "old.yaml")
    new = _global(tmp_path / "new.yaml")
    cfg = _write(tmp_path / "personal.yaml", {"project_config": "old.yaml", "cvat": {"username": "alice"}})
    monkeypatch.setenv("CVETA2_NO_INTERACTIVE", "true")

    run_setup(parse_cli_args("setup", "--config", str(cfg), "--global-config", str(new)))

    saved = read_config(cfg)
    assert saved["global_config"] == str(new.resolve())
    assert "project_config" not in saved


def _legacy(path: Path, **extra: str) -> Path:
    return _write(
        path,
        {"cvat": {"host": "https://cvat.example", "organization": "team", "username": "alice"}, **extra},
    )


def test_migration_writes_global_config(tmp_path: Path) -> None:
    proposal = migration_proposal(_legacy(tmp_path / "personal.yaml"))

    assert proposal.personal["global_config"] == str(tmp_path.resolve() / "project-config.yaml")
    assert "project_config" not in proposal.personal


def test_migration_accepts_a_legacy_file_that_selects_with_global_config(tmp_path: Path) -> None:
    proposal = migration_proposal(_legacy(tmp_path / "personal.yaml", global_config="team.yaml"))

    assert proposal.unresolved == ()
