"""CLI integration tests for image download flags."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from cveta2.cli import CliApp
from cveta2.models import ProjectAnnotations


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


def _mock_client_ctx(
    project_id: int = 1,
) -> MagicMock:
    """Build a mock CvatClient that returns empty annotations."""
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.resolve_project_id.return_value = project_id
    client.fetch_annotations.return_value = ProjectAnnotations(
        annotations=[],
        deleted_images=[],
    )
    client.download_images.return_value = MagicMock(
        downloaded=0,
        cached=0,
        failed=0,
        total=0,
    )
    return client


def test_fetch_no_images_flag_skips_download(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--no-images prevents any image download attempt."""
    cfg_path = tmp_path / "config.yaml"
    _write_config(cfg_path)
    monkeypatch.setenv("CVETA2_CONFIG", str(cfg_path))
    monkeypatch.delenv("CVAT_HOST", raising=False)
    monkeypatch.delenv("CVAT_TOKEN", raising=False)

    mock_client = _mock_client_ctx()
    with (
        patch("cveta2.cli.CvatClient", return_value=mock_client),
        patch("cveta2.cli.load_projects_cache", return_value=[]),
    ):
        app = CliApp()
        app.run(
            [
                "fetch",
                "--project",
                "1",
                "--output-dir",
                str(tmp_path / "out"),
                "--no-images",
            ]
        )

    mock_client.download_images.assert_not_called()


def test_fetch_images_dir_overrides_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--images-dir is passed to download_images, ignoring config mapping."""
    cfg_path = tmp_path / "config.yaml"
    _write_config(cfg_path, image_cache={"coco8-dev": "/other/path"})
    monkeypatch.setenv("CVETA2_CONFIG", str(cfg_path))
    monkeypatch.delenv("CVAT_HOST", raising=False)
    monkeypatch.delenv("CVAT_TOKEN", raising=False)

    custom_dir = tmp_path / "custom-images"

    mock_client = _mock_client_ctx()
    with (
        patch("cveta2.cli.CvatClient", return_value=mock_client),
        patch("cveta2.cli.load_projects_cache", return_value=[]),
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
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-interactive mode + no configured path = error exit."""
    cfg_path = tmp_path / "config.yaml"
    _write_config(cfg_path)  # No image_cache section
    monkeypatch.setenv("CVETA2_CONFIG", str(cfg_path))
    monkeypatch.setenv("CVETA2_NO_INTERACTIVE", "true")
    monkeypatch.delenv("CVAT_HOST", raising=False)
    monkeypatch.delenv("CVAT_TOKEN", raising=False)

    mock_client = _mock_client_ctx()
    with (
        patch("cveta2.cli.CvatClient", return_value=mock_client),
        patch("cveta2.cli.load_projects_cache", return_value=[]),
    ):
        app = CliApp()
        with pytest.raises(SystemExit):
            app.run(
                [
                    "fetch",
                    "--project",
                    "coco8-dev",
                    "--output-dir",
                    str(tmp_path / "out"),
                ]
            )


def test_fetch_configured_path_downloads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When image_cache has the project, download_images is called with that path."""
    cfg_path = tmp_path / "config.yaml"
    _write_config(cfg_path, image_cache={"coco8-dev": "/mnt/data/coco8"})
    monkeypatch.setenv("CVETA2_CONFIG", str(cfg_path))
    monkeypatch.delenv("CVAT_HOST", raising=False)
    monkeypatch.delenv("CVAT_TOKEN", raising=False)

    mock_client = _mock_client_ctx()
    with (
        patch("cveta2.cli.CvatClient", return_value=mock_client),
        patch("cveta2.cli.load_projects_cache", return_value=[]),
    ):
        app = CliApp()
        app.run(
            [
                "fetch",
                "--project",
                "coco8-dev",
                "--output-dir",
                str(tmp_path / "out"),
            ]
        )

    mock_client.download_images.assert_called_once()
    call_args = mock_client.download_images.call_args
    assert call_args[0][1] == Path("/mnt/data/coco8")


def test_fetch_noninteractive_no_images_skips(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-interactive + --no-images works without error."""
    cfg_path = tmp_path / "config.yaml"
    _write_config(cfg_path)
    monkeypatch.setenv("CVETA2_CONFIG", str(cfg_path))
    monkeypatch.setenv("CVETA2_NO_INTERACTIVE", "true")
    monkeypatch.delenv("CVAT_HOST", raising=False)
    monkeypatch.delenv("CVAT_TOKEN", raising=False)

    mock_client = _mock_client_ctx()
    with (
        patch("cveta2.cli.CvatClient", return_value=mock_client),
        patch("cveta2.cli.load_projects_cache", return_value=[]),
    ):
        app = CliApp()
        app.run(
            [
                "fetch",
                "--project",
                "1",
                "--output-dir",
                str(tmp_path / "out"),
                "--no-images",
            ]
        )

    mock_client.download_images.assert_not_called()
