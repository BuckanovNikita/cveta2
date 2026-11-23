"""``cveta2 setup --list``: the effective configuration and where each value comes from."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import yaml

from cveta2.composition.configuration import ListedValue, list_configuration
from cveta2.domain.errors import Cveta2Error
from cveta2.interfaces.cli import CliApp
from cveta2.interfaces.commands.setup import run_setup
from tests.helpers import parse_cli_args

if TYPE_CHECKING:
    from pathlib import Path

_SECRET = "s3cr3t-DO-NOT-SHOW"
_PUBLICATION: dict[str, object] = {
    "clearml": {"project": "Retail/Datasets", "dataset": "retail-shelves"},
    "api_url": "https://classes.example.com/api",
}


@pytest.fixture(autouse=True)
def _isolated_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Select files only through the test's own arguments; no value comes from the shell."""
    for name in (
        "CVETA2_GLOBAL_CONFIG",
        "CVETA2_PROJECT_CONFIG",
        "CVETA2_CONFIG",
        "CVAT_HOST",
        "CVAT_ORGANIZATION",
        "CVAT_USERNAME",
        "CVAT_PASSWORD",
        "CVETA2_DATA_TIMEOUT",
        "CVETA2_S3_WORKERS",
        "CVETA2_CVAT_WORKERS",
        "CVETA2_RETRY_ATTEMPTS",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CVETA2_NO_INTERACTIVE", "true")


def write(path: Path, data: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def team(path: Path, *, local_overrides: bool | None = True) -> Path:
    """Write a global file with the retail publication and a second project without one."""
    data: dict[str, object] = {
        "schema_version": 1,
        "cvat": {"host": "https://cvat.example.com", "organization": "my-team"},
        "projects": {
            "retail": {
                "id": 123,
                "name": "Retail shelves",
                "sync_root": "s3://my-bucket/images",
                "publication": _PUBLICATION,
            },
            "bakery": {"id": 7, "name": "Bakery", "sync_root": "s3://my-bucket/bakery"},
        },
    }
    if local_overrides is not None:
        data["local_overrides"] = local_overrides
    return write(path, data)


def personal(tmp_path: Path, *, local_overrides: bool | None = True) -> Path:
    """Write a personal file attached to :func:`team`, with one override of the retail dataset name."""
    global_file = team(tmp_path / "team" / "project-config.yaml", local_overrides=local_overrides)
    return write(
        tmp_path / "config.yaml",
        {
            "schema_version": 1,
            "global_config": str(global_file),
            "cvat": {"username": "alice", "password": _SECRET},
            "cache": {"images_root": "/data/img"},
            "image_cache": {"Retail shelves": "/data/retail", "Bakery": "/data/bakery"},
            "overrides": {"projects": {"retail": {"publication": {"clearml": {"dataset": "retail-shelves-alice"}}}}},
        },
    )


def test_list_shows_origins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = personal(tmp_path)
    monkeypatch.setenv("CVETA2_S3_WORKERS", "3")
    listed = list_configuration(cfg)
    for expected in (
        ListedValue("cvat.host", "https://cvat.example.com", "global"),
        ListedValue("cvat.username", "alice", "personal"),
        ListedValue("cvat.password", "***", "personal"),
        ListedValue("cache.images_root", "/data/img", "personal"),
        ListedValue("projects.retail.publication.clearml.project", "Retail/Datasets", "global"),
        ListedValue("projects.retail.publication.clearml.dataset", "retail-shelves-alice", "override"),
        ListedValue("network.s3_workers", "3", "environment"),
        ListedValue("network.cvat_workers", "4", "default"),
    ):
        assert expected in listed
    assert ListedValue("local_overrides", "True", "global") in listed
    assert ListedValue("image_cache.Retail shelves", "/data/retail", "personal") in listed
    # The overridden global value is not listed a second time.
    assert [v.key for v in listed].count("projects.retail.publication.clearml.dataset") == 1
    assert all(_SECRET not in v.value for v in listed)


def test_list_hides_password_from_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = personal(tmp_path)
    monkeypatch.setenv("CVAT_PASSWORD", "x")
    listed = list_configuration(cfg)
    assert ListedValue("cvat.password", "***", "environment") in listed
    # "x" is a substring of ordinary values (the host); the secret must be no value of its own.
    assert all(v.value != "x" for v in listed)


def test_list_with_project_prints_one_project(tmp_path: Path) -> None:
    cfg = personal(tmp_path)
    listed = list_configuration(cfg, project="Retail shelves")
    assert listed
    assert all(v.key.startswith("projects.retail.") or v.key == "image_cache.Retail shelves" for v in listed)
    assert ListedValue("image_cache.Retail shelves", "/data/retail", "personal") in listed
    assert ListedValue("projects.retail.id", "123", "global") in listed


def test_list_of_an_unknown_project_is_refused(tmp_path: Path) -> None:
    cfg = personal(tmp_path)
    with pytest.raises(Cveta2Error, match="Nowhere"):
        list_configuration(cfg, project="Nowhere")


def test_setup_list_cli_prints_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = personal(tmp_path)
    monkeypatch.setenv("CVETA2_CONFIG", str(cfg))
    CliApp().run(["setup", "--list"])
    out = capsys.readouterr().out.splitlines()
    assert out[0] == f"Общая конфигурация: {(tmp_path / 'team' / 'project-config.yaml').resolve()}"
    assert "projects.retail.publication.clearml.dataset = retail-shelves-alice  (локальное переопределение)" in out
    assert "cvat.password = ***  (личная)" in out
    assert "network.cvat_workers = 4  (по умолчанию)" in out
    assert "projects.retail.publication.clearml.project = Retail/Datasets  (общая)" in out


def test_list_refuses_option_flags(tmp_path: Path) -> None:
    cfg = personal(tmp_path)
    with pytest.raises(Cveta2Error, match="--list"):
        run_setup(parse_cli_args("setup", "--config", str(cfg), "--list", "--username", "x"))


@pytest.mark.parametrize(
    "extra",
    [["--unset", "username"], ["--reset"], ["--global"], ["--migrate-config"]],
)
def test_list_refuses_writing_modes(tmp_path: Path, extra: list[str]) -> None:
    cfg = personal(tmp_path)
    before = cfg.read_bytes()
    with pytest.raises(Cveta2Error, match="--list"):
        run_setup(parse_cli_args("setup", "--config", str(cfg), "--list", *extra))
    assert cfg.read_bytes() == before


def test_list_with_global_config_attaches_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    other = team(tmp_path / "other.yaml")
    cfg = write(tmp_path / "config.yaml", {"cvat": {"username": "alice"}})
    before = cfg.read_bytes()
    run_setup(parse_cli_args("setup", "--config", str(cfg), "--list", "--global-config", str(other)))
    assert cfg.read_bytes() == before
    out = capsys.readouterr().out.splitlines()
    assert out[0] == f"Общая конфигурация: {other.resolve()}"
    assert "projects.bakery.sync_root = s3://my-bucket/bakery  (общая)" in out


def test_list_shows_overrides_the_global_file_does_not_allow(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = personal(tmp_path, local_overrides=None)
    listed = list_configuration(cfg)
    key = "projects.retail.publication.clearml.dataset"
    assert ListedValue(key, "retail-shelves", "global") in listed
    assert ListedValue(key, "retail-shelves-alice", "override", applied=False) in listed
    assert ListedValue("local_overrides", "False", "default") in listed
    run_setup(parse_cli_args("setup", "--config", str(cfg), "--list"))
    out = capsys.readouterr().out.splitlines()
    assert f"{key} = retail-shelves  (общая)" in out
    assert (
        f"{key} = retail-shelves-alice  (локальное переопределение; не применяется: общая конфигурация "
        "не разрешает переопределения)"
    ) in out


def test_list_without_a_global_file_reads_the_personal_identity(tmp_path: Path) -> None:
    cfg = write(
        tmp_path / "config.yaml",
        {"cvat": {"host": "https://cvat.example.com", "username": "alice"}, "upload": {"images_per_job": 50}},
    )
    listed = list_configuration(cfg)
    assert ListedValue("cvat.host", "https://cvat.example.com", "personal") in listed
    assert ListedValue("upload.images_per_job", "50", "personal") in listed
    assert ListedValue("upload.image_quality", "100", "default") in listed
    assert not any(v.key.startswith("projects.") or v.key == "local_overrides" for v in listed)
    assert not any(v.key == "cvat.password" for v in listed)


def test_list_prefers_honoured_environment_values(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = personal(tmp_path)
    monkeypatch.setenv("CVAT_USERNAME", "bob")
    monkeypatch.setenv("CVAT_HOST", "https://elsewhere.example.com")
    monkeypatch.setenv("CVETA2_CVAT_WORKERS", "not-a-number")
    listed = list_configuration(cfg)
    assert ListedValue("cvat.username", "bob", "environment") in listed
    # With a global file attached, the identity comes from it and the environment is not taken.
    assert ListedValue("cvat.host", "https://cvat.example.com", "global") in listed
    # A value the reader ignores is not reported as coming from the environment.
    assert ListedValue("network.cvat_workers", "4", "default") in listed
