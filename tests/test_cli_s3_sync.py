"""CLI integration tests for the s3-sync command."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest
import yaml

if TYPE_CHECKING:
    from pathlib import Path

from cveta2.cli import CliApp
from cveta2.image_downloader import DownloadStats


def _write_config(
    path: Path,
    *,
    image_cache: dict[str, str] | None = None,
) -> None:
    """Write a minimal config YAML for testing."""
    data: dict[str, object] = {
        "cvat": {
            "host": "http://localhost:8080",
            "token": "test-token",
        },
    }
    if image_cache:
        data["image_cache"] = image_cache
    path.write_text(yaml.safe_dump(data), encoding="utf-8")


def _mock_client_ctx() -> MagicMock:
    """Build a mock CvatClient for s3-sync tests."""
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.resolve_project_id.return_value = 1
    client.sync_project_images.return_value = DownloadStats(
        downloaded=5, cached=10, failed=0, total=15
    )
    return client


def test_s3_sync_no_image_cache_exits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """s3-sync exits with error when no image_cache is configured."""
    cfg_path = tmp_path / "config.yaml"
    _write_config(cfg_path)  # no image_cache
    monkeypatch.setenv("CVETA2_CONFIG", str(cfg_path))
    monkeypatch.delenv("CVAT_HOST", raising=False)
    monkeypatch.delenv("CVAT_TOKEN", raising=False)

    app = CliApp()
    with pytest.raises(SystemExit):
        app.run(["s3-sync"])


def test_s3_sync_all_projects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """s3-sync syncs all configured projects."""
    cfg_path = tmp_path / "config.yaml"
    _write_config(
        cfg_path,
        image_cache={
            "project-a": str(tmp_path / "images-a"),
            "project-b": str(tmp_path / "images-b"),
        },
    )
    monkeypatch.setenv("CVETA2_CONFIG", str(cfg_path))
    monkeypatch.delenv("CVAT_HOST", raising=False)
    monkeypatch.delenv("CVAT_TOKEN", raising=False)

    mock_client = _mock_client_ctx()
    # resolve_project_id returns different IDs per project
    mock_client.resolve_project_id.side_effect = [1, 2]

    with (
        patch("cveta2.cli.CvatClient", return_value=mock_client),
        patch("cveta2.cli.load_projects_cache", return_value=[]),
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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """s3-sync --project syncs only the specified project."""
    cfg_path = tmp_path / "config.yaml"
    _write_config(
        cfg_path,
        image_cache={
            "project-a": str(tmp_path / "images-a"),
            "project-b": str(tmp_path / "images-b"),
        },
    )
    monkeypatch.setenv("CVETA2_CONFIG", str(cfg_path))
    monkeypatch.delenv("CVAT_HOST", raising=False)
    monkeypatch.delenv("CVAT_TOKEN", raising=False)

    mock_client = _mock_client_ctx()
    with (
        patch("cveta2.cli.CvatClient", return_value=mock_client),
        patch("cveta2.cli.load_projects_cache", return_value=[]),
    ):
        app = CliApp()
        app.run(["s3-sync", "--project", "project-a"])

    mock_client.sync_project_images.assert_called_once()
    call_args = mock_client.sync_project_images.call_args
    assert call_args[0][1] == tmp_path / "images-a"


def test_s3_sync_unknown_project_exits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """s3-sync --project with unknown project name exits with error."""
    cfg_path = tmp_path / "config.yaml"
    _write_config(
        cfg_path,
        image_cache={"project-a": str(tmp_path / "images-a")},
    )
    monkeypatch.setenv("CVETA2_CONFIG", str(cfg_path))
    monkeypatch.delenv("CVAT_HOST", raising=False)
    monkeypatch.delenv("CVAT_TOKEN", raising=False)

    app = CliApp()
    with pytest.raises(SystemExit):
        app.run(["s3-sync", "--project", "nonexistent"])


def test_s3_sync_continues_on_resolve_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """s3-sync continues to next project when one fails to resolve."""
    from cveta2.exceptions import ProjectNotFoundError

    cfg_path = tmp_path / "config.yaml"
    _write_config(
        cfg_path,
        image_cache={
            "bad-project": str(tmp_path / "images-bad"),
            "good-project": str(tmp_path / "images-good"),
        },
    )
    monkeypatch.setenv("CVETA2_CONFIG", str(cfg_path))
    monkeypatch.delenv("CVAT_HOST", raising=False)
    monkeypatch.delenv("CVAT_TOKEN", raising=False)

    mock_client = _mock_client_ctx()

    def resolve_side_effect(name: str, **_kwargs: object) -> int:
        if name == "bad-project":
            raise ProjectNotFoundError(f"Project not found: {name!r}")
        return 2

    mock_client.resolve_project_id.side_effect = resolve_side_effect

    with (
        patch("cveta2.cli.CvatClient", return_value=mock_client),
        patch("cveta2.cli.load_projects_cache", return_value=[]),
    ):
        app = CliApp()
        app.run(["s3-sync"])

    # Only good-project should be synced
    mock_client.sync_project_images.assert_called_once()
    call_args = mock_client.sync_project_images.call_args
    assert call_args[0][1] == tmp_path / "images-good"
