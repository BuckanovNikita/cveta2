"""CLI dispatch/behavior smokes for the s3-sync command.

Sync-root override behavior (``--root`` and the ``sync_roots`` config
section) is covered by ``tests/test_sync_root_override.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from cveta2.cli import CliApp
from cveta2.image_downloader import DownloadStats
from tests.helpers import mock_client_ctx, patch_cli_client, write_test_config


def _s3_sync_client() -> MagicMock:
    client = mock_client_ctx()
    client.detect_project_cloud_storage.return_value = MagicMock()
    client.sync_project_images.return_value = DownloadStats(
        downloaded=5, cached=10, failed=0, total=15
    )
    return client


@pytest.mark.usefixtures("test_config")
def test_s3_sync_no_image_cache_exits() -> None:
    app = CliApp()
    # Match on the identifier, not the surrounding Russian prose: this is what
    # tells the two guards apart, and a copy edit must not break it.
    with pytest.raises(SystemExit, match="image_cache"):
        app.run(["s3-sync"])


def test_s3_sync_all_projects(
    tmp_path: Path,
    test_config: Path,
) -> None:
    write_test_config(
        test_config,
        image_cache={
            "project-a": str(tmp_path / "images-a"),
            "project-b": str(tmp_path / "images-b"),
        },
    )

    mock_client = _s3_sync_client()
    mock_client.resolve_project_id.side_effect = [1, 2]

    with patch_cli_client(mock_client):
        app = CliApp()
        app.run(["s3-sync"])

    assert mock_client.sync_project_images.call_count == 2
    call_dirs = {str(c[0][1]) for c in mock_client.sync_project_images.call_args_list}
    assert str(tmp_path / "images-a") in call_dirs
    assert str(tmp_path / "images-b") in call_dirs


def test_s3_sync_root_without_project_exits(
    tmp_path: Path,
    test_config: Path,
) -> None:
    write_test_config(
        test_config,
        image_cache={"project-a": str(tmp_path / "images-a")},
    )

    app = CliApp()
    with pytest.raises(SystemExit, match="--root"):
        app.run(["s3-sync", "--root", "s3://bucket/prefix"])
