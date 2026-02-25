"""Smoke tests for doctor and setup commands."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from cveta2.commands.doctor import run_doctor
from cveta2.config import CvatConfig, ImageCacheConfig


def test_run_doctor_no_crash() -> None:
    """run_doctor completes without crashing when config is mocked."""
    cfg = CvatConfig(host="https://fake.cvat.ai", token="fake-token")  # noqa: S106
    ic_cfg = ImageCacheConfig()

    with (
        patch(
            "cveta2.commands.doctor.get_config_path", return_value=Path("/nonexistent")
        ),
        patch("cveta2.commands.doctor.CvatConfig.from_env", return_value=cfg),
        patch("cveta2.commands.doctor.CvatConfig.load", return_value=cfg),
        patch("cveta2.commands.doctor.load_image_cache_config", return_value=ic_cfg),
        patch("cveta2.commands.doctor.check_aws_credentials", return_value=True),
    ):
        run_doctor()


def test_run_setup_requires_interactive(tmp_path: Path) -> None:
    """run_setup raises when interactive mode is disabled."""
    from cveta2.commands.setup import run_setup
    from cveta2.exceptions import InteractiveModeRequiredError

    config_path = tmp_path / "fake-config.yaml"
    with (
        patch(
            "cveta2.commands.setup.require_interactive",
            side_effect=InteractiveModeRequiredError("non-interactive"),
        ),
        pytest.raises(InteractiveModeRequiredError),
    ):
        run_setup(config_path)
