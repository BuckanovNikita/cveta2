"""Regressions for reviewed configuration and command interfaces."""

import argparse
import os
import subprocess
import sys
from collections.abc import Iterator
from math import isfinite
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError
from yaml.error import Mark

from cveta2.adapters.config.settings import CvatConfig, IgnoreConfig
from cveta2.domain.errors import Cveta2Error, MissingCredentialsError
from tests.helpers import write_split_config_yaml


@given(
    value=st.one_of(
        st.none(),
        st.sampled_from([0, 1.5, -1, float("inf"), float("-inf"), float("nan")]),
        st.floats(),
    )
)
def test_request_timeout_must_be_finite_and_non_negative(value: float | None) -> None:
    """``None`` disables the timeout; any other value must be finite and >= 0."""
    if value is None or (isfinite(value) and value >= 0):
        assert CvatConfig(request_timeout=value).request_timeout == value
    else:
        with pytest.raises(ValidationError):
            CvatConfig(request_timeout=value)


def test_selected_config_credential_hint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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


@pytest.mark.parametrize(
    ("document", "category", "line", "column"),
    [
        ("cvat:\n  password: [DO_NOT_LOG_SECRET\n", "ParserError", 3, 1),
        ('cvat:\n  password: "\\qDO_NOT_LOG_SECRET"\n', "ScannerError", 2, 15),
        ("cvat:\n  password: !DO_NOT_LOG_SECRET value\n", "ConstructorError", 2, 13),
    ],
)
def test_malformed_yaml_reports_location_without_credential_values(
    tmp_path: Path, document: str, category: str, line: int, column: int
) -> None:
    config = tmp_path / "private.yaml"
    config.write_text(document, encoding="utf-8")

    with pytest.raises(Cveta2Error) as caught:
        CvatConfig.from_file(config)

    message = str(caught.value)
    assert str(config) in message
    assert category in message
    assert f"строка {line}, столбец {column}" in message
    assert "DO_NOT_LOG_SECRET" not in message
    assert "password" not in message
    assert isinstance(caught.value.__cause__, yaml.YAMLError)
    assert "DO_NOT_LOG_SECRET" in str(caught.value.__cause__)


@pytest.mark.parametrize(
    ("error", "location"),
    [
        (yaml.YAMLError("DO_NOT_LOG_SECRET"), ""),
        (yaml.MarkedYAMLError(problem="DO_NOT_LOG_SECRET"), ""),
        (
            yaml.MarkedYAMLError(
                context="DO_NOT_LOG_SECRET",
                context_mark=Mark("DO_NOT_LOG_SECRET", 0, 4, 6, None, 0),
            ),
            ", строка 5, столбец 7",
        ),
    ],
    ids=["unmarked", "missing-marks", "context-mark-only"],
)
def test_yaml_diagnostic_uses_only_category_and_available_location(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error: yaml.YAMLError,
    location: str,
) -> None:
    config = tmp_path / "private.yaml"
    config.write_text("cvat: {}", encoding="utf-8")
    monkeypatch.setattr(yaml, "safe_load", Mock(side_effect=error))

    with pytest.raises(Cveta2Error) as caught:
        CvatConfig.from_file(config)

    assert str(caught.value) == (f"Ошибка чтения YAML-конфигурации {config}: {type(error).__name__}{location}.")
    assert caught.value.__cause__ is error


def test_cli_malformed_config_omits_credential_values(tmp_path: Path) -> None:
    config = tmp_path / "private.yaml"
    config.write_text("cvat:\n  password: [DO_NOT_LOG_SECRET\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "cveta2.cli", "fetch", "-p", "1", "-o", "unused"],
        env={
            **os.environ,
            "CVETA2_CONFIG": str(config),
            "CVETA2_NO_INTERACTIVE": "true",
        },
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert result.returncode != 0
    assert str(config) in result.stderr
    assert "строка 3, столбец 1" in result.stderr
    assert "Traceback" not in result.stderr
    assert "DO_NOT_LOG_SECRET" not in result.stdout + result.stderr


def test_stale_ignore_cli_removes_without_task_listing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from contextlib import contextmanager

    from cveta2.interfaces.commands import ignore

    config = tmp_path / "personal.yaml"
    write_split_config_yaml(config, project_ids={"project": 1})
    monkeypatch.setenv("CVETA2_CONFIG", str(config))
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
    ignore.run_ignore(argparse.Namespace(project="project", remove=["99"], add=None, list_only=False))
    assert IgnoreConfig.load().get_ignored_tasks("project") == []


def test_doctor_required_failure_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    from cveta2.interfaces.commands import doctor

    monkeypatch.setattr(doctor, "check_config", lambda: False)
    monkeypatch.setattr(doctor, "check_aws_credentials", lambda: True)
    monkeypatch.setattr(doctor, "check_cache_permissions", lambda **_kwargs: True)
    with pytest.raises(SystemExit) as e:
        doctor.run_doctor()
    assert e.value.code == 1


def test_doctor_optional_failure_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    from cveta2.interfaces.commands import doctor

    monkeypatch.setattr(doctor, "check_config", lambda: True)
    monkeypatch.setattr(doctor, "check_aws_credentials", lambda: False)
    monkeypatch.setattr(doctor, "check_cache_permissions", lambda **_kwargs: False)
    doctor.run_doctor()


@pytest.mark.parametrize(("credentials", "code"), [(True, 0), (False, 1)])
def test_doctor_subprocess_exit_contract(tmp_path: Path, code: int, *, credentials: bool) -> None:
    config = tmp_path / "doctor.yaml"
    config.write_text(
        "cvat:\n  host: https://cvat.example\n" + ("  username: user\n  password: pass\n" if credentials else "")
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
    from cveta2.domain.errors import Cveta2Error
    from cveta2.interfaces.commands import doctor

    monkeypatch.setattr(doctor, "check_config", Mock(side_effect=PermissionError("denied")))
    monkeypatch.setattr(
        doctor,
        "check_aws_credentials",
        Mock(side_effect=Cveta2Error("Unable to locate credentials")),
    )
    monkeypatch.setattr(doctor, "check_cache_permissions", Mock(return_value=True))
    with pytest.raises(SystemExit) as error:
        doctor.run_doctor()
    assert error.value.code == 1


@pytest.mark.parametrize("raw", ["-1", "nan", "inf"])
def test_invalid_environment_timeout_rejected(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv("CVETA2_DATA_TIMEOUT", raw)
    with pytest.raises(ValidationError):
        CvatConfig.from_env()


def test_doctor_malformed_optional_image_cache_subprocess(tmp_path: Path) -> None:
    config = tmp_path / "doctor.yaml"
    config.write_text(
        "cvat:\n  host: https://cvat.example\n  username: user\n  password: pass\nimage_cache:\n  project: 123\n"
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
    config.write_text("cvat:\n  host: https://cvat.example\n  username: user\n  password: pass\n")
    script = """
from cveta2.adapters.config.settings import ImageCacheConfig
from cveta2.interfaces.cli import main

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
