"""Smoke tests for doctor and setup commands."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from cveta2.adapters.config.settings import CvatConfig, ImageCacheConfig
from cveta2.interfaces.commands.doctor import run_doctor


def _use_clearml_file(monkeypatch: pytest.MonkeyPatch, config_file: Path) -> None:
    """Hide the developer's ClearML setup and point the SDK at *config_file*."""
    for name in list(os.environ):
        if name.startswith(("CLEARML_", "TRAINS_")):
            monkeypatch.delenv(name)
    monkeypatch.setenv("CLEARML_CONFIG_FILE", str(config_file))


def test_run_doctor_no_crash() -> None:
    """run_doctor completes without crashing when config is mocked."""
    cfg = CvatConfig(host="https://fake.cvat.ai", username="user", password="pass")
    ic_cfg = ImageCacheConfig()

    with (
        patch(
            "cveta2.interfaces.commands.doctor.get_config_path",
            return_value=Path("/nonexistent"),
        ),
        patch("cveta2.interfaces.commands.doctor.CvatConfig.from_env", return_value=cfg),
        patch("cveta2.interfaces.commands.doctor.CvatConfig.load", return_value=cfg),
        patch("cveta2.adapters.config.settings.ImageCacheConfig.load", return_value=ic_cfg),
        patch("cveta2.interfaces.commands.doctor.check_aws_credentials", return_value=True),
        patch("cveta2.interfaces.commands.doctor.check_clearml_configuration", return_value=True),
        patch("cveta2.interfaces.commands.doctor.collect_cache_roots", return_value={}),
    ):
        run_doctor()


def test_run_doctor_cache_flag_requests_a_fix() -> None:
    """``doctor --cache`` reaches the permission check in fixing mode."""
    import argparse

    with (
        patch("cveta2.interfaces.commands.doctor.check_config", return_value=True),
        patch("cveta2.interfaces.commands.doctor.check_aws_credentials", return_value=True),
        patch("cveta2.interfaces.commands.doctor.check_clearml_configuration", return_value=True),
        patch(
            "cveta2.interfaces.commands.doctor.check_cache_permissions",
            return_value=True,
        ) as check,
    ):
        run_doctor(argparse.Namespace(cache=True))
    check.assert_called_once_with(fix=True)


@pytest.mark.filterwarnings("ignore::pyparsing.warnings.PyparsingDeprecationWarning")  # the SDK's own parser
def test_run_doctor_missing_clearml_configuration_only_warns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capture_info_logs: list[str]
) -> None:
    """Without a ClearML setup doctor warns and keeps the exit code of the required check."""
    _use_clearml_file(monkeypatch, tmp_path / "absent.conf")

    with (
        patch("cveta2.interfaces.commands.doctor.check_config", return_value=True),
        patch("cveta2.interfaces.commands.doctor.check_aws_credentials", return_value=True),
        patch("cveta2.interfaces.commands.doctor.check_cache_permissions", return_value=True),
    ):
        run_doctor()

    assert "doctor: ClearML — необязательная проверка" in capture_info_logs
    assert any(message.startswith("ClearML: не настроен") for message in capture_info_logs)
    assert "doctor: необязательная проверка ClearML не пройдена" in capture_info_logs
    assert capture_info_logs[-1] == "doctor: обязательные проверки пройдены"


@pytest.mark.filterwarnings("ignore::pyparsing.warnings.PyparsingDeprecationWarning")  # the SDK's own parser
def test_run_doctor_binary_clearml_configuration_only_warns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capture_logs: list[str]
) -> None:
    """A ClearML file the SDK cannot even decode is a warning, not a traceback or a failed doctor."""
    config_file = tmp_path / "clearml.conf"
    config_file.write_bytes(b"\xff\xfe\x00\x81SKCLEARMLSECRET0002")
    _use_clearml_file(monkeypatch, config_file)

    with (
        patch("cveta2.interfaces.commands.doctor.check_config", return_value=True),
        patch("cveta2.interfaces.commands.doctor.check_aws_credentials", return_value=True),
        patch("cveta2.interfaces.commands.doctor.check_cache_permissions", return_value=True),
    ):
        run_doctor()

    unreadable = f"ClearML: файл конфигурации не читается ({config_file}): UnicodeDecodeError"
    assert capture_logs == [f"doctor: необязательная проверка ClearML недоступна: {unreadable}"]


def test_run_setup_requires_interactive(tmp_path: Path) -> None:
    """run_setup raises when interactive mode is disabled."""
    from cveta2.domain.errors import InteractiveModeRequiredError
    from cveta2.interfaces.commands.setup import run_setup
    from tests.helpers import parse_cli_args

    args = parse_cli_args("setup", "--config", str(tmp_path / "fake-config.yaml"))
    with (
        patch(
            "cveta2.interfaces.commands.setup.require_interactive",
            side_effect=InteractiveModeRequiredError("non-interactive"),
        ),
        pytest.raises(InteractiveModeRequiredError),
    ):
        run_setup(args)
