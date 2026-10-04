"""Regressions for reviewed configuration and command interfaces."""

import argparse
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from cveta2.config import ClearmlConfig, CvatConfig, IgnoreConfig
from cveta2.exceptions import MissingCredentialsError


@pytest.mark.parametrize("value", [-1, float("inf"), float("-inf"), float("nan")])
def test_invalid_timeout_rejected(value: float) -> None:
    with pytest.raises(ValidationError):
        CvatConfig(request_timeout=value)


def test_selected_config_credential_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    selected = tmp_path / "selected.yaml"
    selected.write_text("cvat:\n  host: https://cvat.example\n")
    monkeypatch.setenv("CVETA2_CONFIG", str(tmp_path / "ambient.yaml"))
    with pytest.raises(MissingCredentialsError) as error:
        CvatConfig.load(selected).require_credentials()
    assert str(selected) in str(error.value)
    assert "ambient.yaml" not in str(error.value)


def test_cli_typed_config_has_no_traceback(tmp_path: Path) -> None:
    cfg = tmp_path / "bad.yaml"
    cfg.write_text("cvat:\n  host: https://cvat.example\n  request_timeout: -1\n")
    result = subprocess.run(  # noqa: S603 - fixed module with isolated arguments
        [
            sys.executable,
            "-m",
            "cveta2.cli",
            "fetch",
            "-p",
            "1",
            "-o",
            str(tmp_path / "output"),
        ],
        env={**os.environ, "CVETA2_CONFIG": str(cfg), "CVETA2_NO_INTERACTIVE": "true"},
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "Traceback" not in result.stderr
    assert "request_timeout" in result.stderr


def test_clearml_enabled_only_saved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cveta2.commands import setup_clearml
    from cveta2.commands.interactive import wizard
    from cveta2.models import ProjectInfo

    path = tmp_path / "config.yaml"
    monkeypatch.setattr(
        setup_clearml,
        "load_projects_cache",
        lambda *_args: [ProjectInfo(id=1, name="project")],
    )
    monkeypatch.setattr(wizard, "prompt_clearml_enabled", lambda **_kwargs: True)
    monkeypatch.setattr(setup_clearml, "_prompt_project_mapping", lambda *_args: None)
    setup_clearml.run_setup_clearml(
        argparse.Namespace(config=str(path), list_only=False)
    )
    assert ClearmlConfig.load(path).enabled


def test_stale_ignore_cli_removes_without_task_listing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from contextlib import contextmanager

    from cveta2.commands import ignore

    cfg = IgnoreConfig()
    cfg.add_task("project", 99, "deleted")
    cfg.save()
    client = Mock()
    client.list_project_tasks.side_effect = AssertionError("must not list deleted task")

    @contextmanager
    def open_client() -> Iterator[Mock]:
        yield client

    monkeypatch.setattr(ignore, "open_client", open_client)
    monkeypatch.setattr(ignore, "_resolve_project", lambda *_args: (1, "project"))
    ignore.run_ignore(
        argparse.Namespace(project="project", remove=["99"], add=None, list_only=False)
    )
    assert IgnoreConfig.load().get_ignored_tasks("project") == []


def test_doctor_required_failure_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    from cveta2.commands import doctor

    monkeypatch.setattr(doctor, "check_config", lambda: False)
    monkeypatch.setattr(doctor, "check_aws_credentials", lambda: True)
    monkeypatch.setattr(doctor, "check_cache_permissions", lambda **_kwargs: True)
    with pytest.raises(SystemExit) as e:
        doctor.run_doctor()
    assert e.value.code == 1


def test_doctor_optional_failure_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    from cveta2.commands import doctor

    monkeypatch.setattr(doctor, "check_config", lambda: True)
    monkeypatch.setattr(doctor, "check_aws_credentials", lambda: False)
    monkeypatch.setattr(doctor, "check_cache_permissions", lambda **_kwargs: False)
    doctor.run_doctor()


@pytest.mark.parametrize(("credentials", "code"), [(True, 0), (False, 1)])
def test_doctor_subprocess_exit_contract(
    tmp_path: Path, code: int, *, credentials: bool
) -> None:
    config = tmp_path / "doctor.yaml"
    config.write_text(
        "cvat:\n  host: https://cvat.example\n"
        + ("  username: user\n  password: pass\n" if credentials else "")
    )
    environment = {
        **os.environ,
        "CVETA2_CONFIG": str(config),
        "AWS_EC2_METADATA_DISABLED": "true",
        "CVETA2_DISABLE_CACHE": "true",
        "AWS_SHARED_CREDENTIALS_FILE": str(tmp_path / "absent"),
        "AWS_CONFIG_FILE": str(tmp_path / "absent-config"),
        "CVAT_USERNAME": "",
        "CVAT_PASSWORD": "",
    }
    environment.pop("AWS_ACCESS_KEY_ID", None)
    environment.pop("AWS_SECRET_ACCESS_KEY", None)
    result = subprocess.run(
        [sys.executable, "-m", "cveta2.cli", "doctor"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    assert result.returncode == code
    assert "Traceback" not in result.stderr
    assert "необязательная" in result.stderr
    assert "отключена" in result.stderr


def test_doctor_required_unavailable_and_optional_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from botocore.exceptions import NoCredentialsError

    from cveta2.commands import doctor

    monkeypatch.setattr(
        doctor, "check_config", Mock(side_effect=PermissionError("denied"))
    )
    monkeypatch.setattr(
        doctor, "check_aws_credentials", Mock(side_effect=NoCredentialsError())
    )
    monkeypatch.setattr(doctor, "check_cache_permissions", Mock(return_value=True))
    with pytest.raises(SystemExit) as error:
        doctor.run_doctor()
    assert error.value.code == 1


@pytest.mark.parametrize("value", [None, 0, 1.5])
def test_valid_timeout_semantics_preserved(value: float | None) -> None:
    assert CvatConfig(request_timeout=value).request_timeout == value


@pytest.mark.parametrize("raw", ["-1", "nan", "inf"])
def test_invalid_environment_timeout_rejected(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    monkeypatch.setenv("CVETA2_DATA_TIMEOUT", raw)
    with pytest.raises(ValidationError):
        CvatConfig.from_env()


def test_doctor_malformed_optional_image_cache_subprocess(tmp_path: Path) -> None:
    config = tmp_path / "doctor.yaml"
    config.write_text(
        "cvat:\n  host: https://cvat.example\n  username: user\n  password: pass\n"
        "image_cache:\n  project: 123\n"
    )
    environment = {
        **os.environ,
        "CVETA2_CONFIG": str(config),
        "AWS_EC2_METADATA_DISABLED": "true",
        "AWS_SHARED_CREDENTIALS_FILE": str(tmp_path / "absent"),
        "AWS_CONFIG_FILE": str(tmp_path / "absent-config"),
        "CVAT_USERNAME": "",
        "CVAT_PASSWORD": "",
    }
    result = subprocess.run(
        [sys.executable, "-m", "cveta2.cli", "doctor"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    assert result.returncode == 0
    assert "Traceback" not in result.stderr
    assert "image_cache" in result.stderr
    assert "необязательная" in result.stderr


def test_doctor_optional_validation_failure_subprocess(tmp_path: Path) -> None:
    config = tmp_path / "doctor.yaml"
    config.write_text(
        "cvat:\n  host: https://cvat.example\n  username: user\n  password: pass\n"
    )
    script = """
from cveta2.config import ImageCacheConfig
from cveta2.cli import main

def invalid_optional_loader(cls, config_path=None):
    return cls.model_validate({'projects': []})

ImageCacheConfig.load = classmethod(invalid_optional_loader)
main(['doctor'])
"""
    result = subprocess.run(  # noqa: S603 - fixed script injecting a typed optional failure
        [sys.executable, "-c", script],
        env={
            **os.environ,
            "CVETA2_CONFIG": str(config),
            "AWS_EC2_METADATA_DISABLED": "true",
            "CVAT_USERNAME": "",
            "CVAT_PASSWORD": "",
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    assert result.returncode == 0
    assert "Traceback" not in result.stderr
    assert "image_cache" in result.stderr
    assert "необязательная" in result.stderr
