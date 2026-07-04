"""CLI behavior smokes for image download flags.

Images-dir resolution itself is covered by
``tests/test_fetch_task.py::TestResolveImagesDir``; these two tests only
assert the wiring reaches (or skips) ``download_images``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from cveta2.cli import CliApp
from cveta2.client import FetchContext
from tests.helpers import mock_client_ctx, write_test_config

if TYPE_CHECKING:
    from pathlib import Path


def _fetch_images_client(project_id: int = 1) -> MagicMock:
    client = mock_client_ctx(project_id=project_id)
    client.detect_project_cloud_storage.return_value = None
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


def test_fetch_no_images_flag_skips_download(test_config: Path) -> None:
    mock_client = _fetch_images_client()
    with (
        patch("cveta2.commands._bootstrap.CvatClient", return_value=mock_client),
        patch("cveta2.commands._helpers.load_projects_cache", return_value=[]),
    ):
        CliApp().run(
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


def test_fetch_images_dir_reaches_download(
    tmp_path: Path,
    test_config: Path,
) -> None:
    write_test_config(test_config, image_cache={"coco8-dev": "/other/path"})
    custom_dir = tmp_path / "custom-images"

    mock_client = _fetch_images_client()
    with (
        patch("cveta2.commands._bootstrap.CvatClient", return_value=mock_client),
        patch("cveta2.commands._helpers.load_projects_cache", return_value=[]),
    ):
        CliApp().run(
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
    assert mock_client.download_images.call_args[0][1] == custom_dir
