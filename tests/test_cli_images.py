"""CLI integration tests for image download flags."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from cveta2.cli import CliApp
from cveta2.client import FetchContext
from tests.conftest import write_test_config


def _mock_client_ctx(
    project_id: int = 1,
) -> MagicMock:
    """Build a mock CvatClient that returns empty annotations."""
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.resolve_project_id.return_value = project_id
    client.prepare_fetch.return_value = FetchContext(
        tasks=[],
        label_names={},
        attr_names={},
    )
    client.download_images.return_value = MagicMock(
        downloaded=0,
        cached=0,
        failed=0,
        total=0,
    )
    return client


def test_fetch_no_images_flag_skips_download(
    test_config: Path,
) -> None:
    """--no-images prevents any image download attempt."""
    mock_client = _mock_client_ctx()
    with (
        patch("cveta2.commands.fetch.CvatClient", return_value=mock_client),
        patch("cveta2.commands._helpers.load_projects_cache", return_value=[]),
    ):
        app = CliApp()
        app.run(
            [
                "fetch",
                "--project",
                "1",
                "--output-dir",
                str(test_config.parent / "out"),
                "--no-images",
            ]
        )

    mock_client.download_images.assert_not_called()


def test_fetch_images_dir_overrides_config(
    tmp_path: Path,
    test_config: Path,
) -> None:
    """--images-dir is passed to download_images, ignoring config mapping."""
    write_test_config(test_config, image_cache={"coco8-dev": "/other/path"})

    custom_dir = tmp_path / "custom-images"

    mock_client = _mock_client_ctx()
    with (
        patch("cveta2.commands.fetch.CvatClient", return_value=mock_client),
        patch("cveta2.commands._helpers.load_projects_cache", return_value=[]),
    ):
        app = CliApp()
        app.run(
            [
                "fetch",
                "--project",
                "coco8-dev",
                "--output-dir",
                str(tmp_path / "out"),
                "--images-dir",
                str(custom_dir),
            ]
        )

    mock_client.download_images.assert_called_once()
    call_args = mock_client.download_images.call_args
    assert call_args[0][1] == custom_dir


def test_fetch_noninteractive_no_path_errors(
    test_config: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-interactive mode + no configured path = error exit."""
    monkeypatch.setenv("CVETA2_NO_INTERACTIVE", "true")

    mock_client = _mock_client_ctx()
    with (
        patch("cveta2.commands.fetch.CvatClient", return_value=mock_client),
        patch("cveta2.commands._helpers.load_projects_cache", return_value=[]),
    ):
        app = CliApp()
        with pytest.raises(SystemExit):
            app.run(
                [
                    "fetch",
                    "--project",
                    "coco8-dev",
                    "--output-dir",
                    str(test_config.parent / "out"),
                ]
            )


def test_fetch_configured_path_downloads(
    test_config: Path,
) -> None:
    """When image_cache has the project, download_images is called with that path."""
    write_test_config(test_config, image_cache={"coco8-dev": "/mnt/data/coco8"})

    mock_client = _mock_client_ctx()
    with (
        patch("cveta2.commands.fetch.CvatClient", return_value=mock_client),
        patch("cveta2.commands._helpers.load_projects_cache", return_value=[]),
    ):
        app = CliApp()
        app.run(
            [
                "fetch",
                "--project",
                "coco8-dev",
                "--output-dir",
                str(test_config.parent / "out"),
            ]
        )

    mock_client.download_images.assert_called_once()
    call_args = mock_client.download_images.call_args
    assert call_args[0][1] == Path("/mnt/data/coco8")


def test_fetch_noninteractive_no_images_skips(
    test_config: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-interactive + --no-images works without error."""
    monkeypatch.setenv("CVETA2_NO_INTERACTIVE", "true")

    mock_client = _mock_client_ctx()
    with (
        patch("cveta2.commands.fetch.CvatClient", return_value=mock_client),
        patch("cveta2.commands._helpers.load_projects_cache", return_value=[]),
    ):
        app = CliApp()
        app.run(
            [
                "fetch",
                "--project",
                "1",
                "--output-dir",
                str(test_config.parent / "out"),
                "--no-images",
            ]
        )

    mock_client.download_images.assert_not_called()
