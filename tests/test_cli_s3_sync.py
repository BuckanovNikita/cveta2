"""CLI integration tests for the s3-sync command."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest
import yaml

if TYPE_CHECKING:
    from pathlib import Path

from cveta2.cli import CliApp
from cveta2.image_downloader import CloudStorageInfo, DownloadStats
from tests.helpers import make_cs_info, mock_client_ctx, write_test_config


def _mock_client_ctx() -> MagicMock:
    """Build a mock CvatClient for s3-sync tests."""
    client = mock_client_ctx()
    client.detect_project_cloud_storage.return_value = MagicMock()
    client.sync_project_images.return_value = DownloadStats(
        downloaded=5, cached=10, failed=0, total=15
    )
    return client


@pytest.mark.usefixtures("test_config")
def test_s3_sync_no_image_cache_exits() -> None:
    """s3-sync exits with error when no image_cache is configured."""
    app = CliApp()
    with pytest.raises(SystemExit):
        app.run(["s3-sync"])


def test_s3_sync_all_projects(
    tmp_path: Path,
    test_config: Path,
) -> None:
    """s3-sync syncs all configured projects."""
    write_test_config(
        test_config,
        image_cache={
            "project-a": str(tmp_path / "images-a"),
            "project-b": str(tmp_path / "images-b"),
        },
    )

    mock_client = _mock_client_ctx()
    # resolve_project_id returns different IDs per project
    mock_client.resolve_project_id.side_effect = [1, 2]

    with (
        patch("cveta2.commands.s3_sync.CvatClient", return_value=mock_client),
        patch("cveta2.commands._helpers.load_projects_cache", return_value=[]),
    ):
        app = CliApp()
        app.run(["s3-sync"])

    assert mock_client.sync_project_images.call_count == 2
    calls = mock_client.sync_project_images.call_args_list
    call_dirs = {str(c[0][1]) for c in calls}
    assert str(tmp_path / "images-a") in call_dirs
    assert str(tmp_path / "images-b") in call_dirs


def test_s3_sync_single_project(
    tmp_path: Path,
    test_config: Path,
) -> None:
    """s3-sync --project syncs only the specified project."""
    write_test_config(
        test_config,
        image_cache={
            "project-a": str(tmp_path / "images-a"),
            "project-b": str(tmp_path / "images-b"),
        },
    )

    mock_client = _mock_client_ctx()
    with (
        patch("cveta2.commands.s3_sync.CvatClient", return_value=mock_client),
        patch("cveta2.commands._helpers.load_projects_cache", return_value=[]),
    ):
        app = CliApp()
        app.run(["s3-sync", "--project", "project-a"])

    mock_client.sync_project_images.assert_called_once()
    call_args = mock_client.sync_project_images.call_args
    assert call_args[0][1] == tmp_path / "images-a"


def test_s3_sync_unknown_project_exits(
    tmp_path: Path,
    test_config: Path,
) -> None:
    """s3-sync --project with unknown project name exits with error."""
    write_test_config(
        test_config,
        image_cache={"project-a": str(tmp_path / "images-a")},
    )

    app = CliApp()
    with pytest.raises(SystemExit):
        app.run(["s3-sync", "--project", "nonexistent"])


def test_s3_sync_continues_on_resolve_error(
    tmp_path: Path,
    test_config: Path,
) -> None:
    """s3-sync continues to next project when one fails to resolve."""
    from cveta2.exceptions import ProjectNotFoundError

    write_test_config(
        test_config,
        image_cache={
            "bad-project": str(tmp_path / "images-bad"),
            "good-project": str(tmp_path / "images-good"),
        },
    )

    mock_client = _mock_client_ctx()

    def resolve_side_effect(name: str, **_kwargs: object) -> int:
        if name == "bad-project":
            raise ProjectNotFoundError(f"Project not found: {name!r}")
        return 2

    mock_client.resolve_project_id.side_effect = resolve_side_effect

    with (
        patch("cveta2.commands.s3_sync.CvatClient", return_value=mock_client),
        patch("cveta2.commands._helpers.load_projects_cache", return_value=[]),
    ):
        app = CliApp()
        app.run(["s3-sync"])

    # Only good-project should be synced
    mock_client.sync_project_images.assert_called_once()
    call_args = mock_client.sync_project_images.call_args
    assert call_args[0][1] == tmp_path / "images-good"


def _run_s3_sync_with_cs(
    mock_client: MagicMock,
    argv: list[str],
) -> CloudStorageInfo:
    """Run s3-sync via CLI and return the cs_info passed to sync_project_images."""
    mock_client.detect_project_cloud_storage.return_value = make_cs_info(
        cs_id=3,
        bucket="cvat-bucket",
        prefix="cvat/prefix",
        endpoint_url="http://minio:9000",
    )
    with (
        patch("cveta2.commands.s3_sync.CvatClient", return_value=mock_client),
        patch("cveta2.commands._helpers.load_projects_cache", return_value=[]),
    ):
        app = CliApp()
        app.run(argv)
    mock_client.sync_project_images.assert_called_once()
    cs_info = mock_client.sync_project_images.call_args.kwargs["project_cloud_storage"]
    assert isinstance(cs_info, CloudStorageInfo)
    return cs_info


def test_s3_sync_root_flag_overrides_cloud_storage(
    tmp_path: Path,
    test_config: Path,
) -> None:
    """s3-sync --root overrides bucket and prefix for the run."""
    write_test_config(
        test_config,
        image_cache={"project-a": str(tmp_path / "images-a")},
    )

    cs_info = _run_s3_sync_with_cs(
        _mock_client_ctx(),
        [
            "s3-sync",
            "--project",
            "project-a",
            "--root",
            "s3://custom-bucket/images/my_favourite",
        ],
    )

    assert cs_info.bucket == "custom-bucket"
    assert cs_info.prefix == "images/my_favourite"
    assert cs_info.endpoint_url == "http://minio:9000"


def test_s3_sync_config_sync_root_applied(
    tmp_path: Path,
    test_config: Path,
) -> None:
    """s3-sync applies the sync_roots config section without --root."""
    test_config.write_text(
        yaml.safe_dump(
            {
                "cvat": {
                    "host": "http://localhost:8080",
                    "username": "test-user",
                    "password": "test-password",
                },
                "image_cache": {"project-a": str(tmp_path / "images-a")},
                "sync_roots": {"project-a": "images/my_favourite"},
            }
        ),
        encoding="utf-8",
    )

    cs_info = _run_s3_sync_with_cs(
        _mock_client_ctx(),
        ["s3-sync", "--project", "project-a"],
    )

    assert cs_info.bucket == "cvat-bucket"
    assert cs_info.prefix == "images/my_favourite"


def test_s3_sync_root_without_project_exits(
    tmp_path: Path,
    test_config: Path,
) -> None:
    """s3-sync --root without --project exits with error."""
    write_test_config(
        test_config,
        image_cache={"project-a": str(tmp_path / "images-a")},
    )

    app = CliApp()
    with pytest.raises(SystemExit):
        app.run(["s3-sync", "--root", "s3://bucket/prefix"])
