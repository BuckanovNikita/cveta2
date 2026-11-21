"""CLI behavior smokes for image download flags.

Images-dir resolution itself is covered by
``tests/test_fetch_task.py::TestResolveImagesDir``; these two tests only
assert the wiring reaches (or skips) ``download_images``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, override
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import NoCredentialsError

from cveta2.adapters.s3.images import S3ImageReader
from cveta2.composition.client import FetchContext
from cveta2.domain.models import ProjectAnnotations
from cveta2.interfaces.cli import CliApp
from tests.fixtures.fake_s3 import FakeS3Client
from tests.helpers import (
    assert_clean_s3_exit,
    make_bbox,
    make_cs_info,
    mock_client_ctx,
    patch_cli_client,
    write_test_config,
)

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
    with patch_cli_client(mock_client):
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
    with patch_cli_client(mock_client):
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


@pytest.mark.usefixtures("test_config")
def test_fetch_reports_missing_s3_credentials_without_traceback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An image request without credentials ends as a message naming the storage."""
    missing = NoCredentialsError()

    class _NoCredentials(FakeS3Client):
        @override
        def get_object(self, **_request: str) -> dict[str, Any]:
            raise missing

    monkeypatch.setattr("cveta2.adapters.s3.download.make_s3_client", lambda _url=None: _NoCredentials())
    storage = make_cs_info(bucket="frames-bucket", prefix="project/raw")

    def download(_annotations: object, target_dir: Path, **_kwargs: object) -> object:
        annotations = ProjectAnnotations(annotations=[make_bbox(image_name="a.jpg")], deleted_images=[])
        return S3ImageReader().download(annotations, target_dir, project_cloud_storage=storage)

    mock_client = _fetch_images_client()
    mock_client.download_images.side_effect = download
    with patch_cli_client(mock_client), pytest.raises(SystemExit) as exited:
        CliApp().run(
            ["fetch", "--project", "1", "--output-dir", str(tmp_path / "out"), "--images-dir", str(tmp_path / "img")]
        )

    assert_clean_s3_exit(exited, missing, "frames-bucket", "project/raw")
