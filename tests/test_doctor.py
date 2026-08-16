"""Smoke tests for doctor and setup commands."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from cveta2.commands.doctor import run_doctor
from cveta2.config import CvatConfig, ImageCacheConfig


def test_run_doctor_no_crash() -> None:
    """run_doctor completes without crashing when config is mocked."""
    cfg = CvatConfig(host="https://fake.cvat.ai", username="user", password="pass")
    ic_cfg = ImageCacheConfig()

    with (
        patch(
            "cveta2.commands.doctor.get_config_path", return_value=Path("/nonexistent")
        ),
        patch("cveta2.commands.doctor.CvatConfig.from_env", return_value=cfg),
        patch("cveta2.commands.doctor.CvatConfig.load", return_value=cfg),
        patch("cveta2.config.ImageCacheConfig.load", return_value=ic_cfg),
        patch("cveta2.commands.doctor.check_aws_credentials", return_value=True),
        patch("cveta2.commands.doctor.collect_cache_roots", return_value={}),
    ):
        run_doctor()


def test_run_doctor_cache_flag_requests_a_fix() -> None:
    """``doctor --cache`` reaches the permission check in fixing mode."""
    import argparse

    with (
        patch("cveta2.commands.doctor.check_config", return_value=True),
        patch("cveta2.commands.doctor.check_aws_credentials", return_value=True),
        patch(
            "cveta2.commands.doctor.check_cache_permissions", return_value=True
        ) as check,
    ):
        run_doctor(argparse.Namespace(cache=True))
    check.assert_called_once_with(fix=True)


def test_run_setup_requires_interactive(tmp_path: Path) -> None:
    """run_setup raises when interactive mode is disabled."""
    import argparse

    from cveta2.commands.setup import run_setup
    from cveta2.exceptions import InteractiveModeRequiredError

    args = argparse.Namespace(config=str(tmp_path / "fake-config.yaml"))
    with (
        patch(
            "cveta2.commands.setup.require_interactive",
            side_effect=InteractiveModeRequiredError("non-interactive"),
        ),
        pytest.raises(InteractiveModeRequiredError),
    ):
        run_setup(args)
