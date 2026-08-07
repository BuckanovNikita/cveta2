"""Storage-resolution contract of ``_ImageMixin``.

Both methods are two lines of plumbing around a decision the callers do
not repeat: *when* to ask CVAT for the project's cloud storage, and what
to hand the downloader once it is known.  The service-level tests all go
through ``api.s3_sync`` / ``services.fetch``, which pass the storage in
already, so the fallback branch and the prefix argument were unpinned.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from cveta2._client.ports import CvatApiPort
from cveta2.models import ProjectAnnotations
from tests.fixtures.fake_s3 import FakeS3Client
from tests.helpers import client_with_api, make_bbox, make_cs_info

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

    from cveta2.client import CvatClient

_EMPTY_STORAGE = make_cs_info(bucket="other-bucket", prefix="nothing-here")


def _bucket(monkeypatch: pytest.MonkeyPatch, objects: dict[str, bytes]) -> FakeS3Client:
    """Serve *objects* (bare S3 keys) to every ``make_s3_client`` caller."""
    s3 = FakeS3Client(objects, keyed_by_bucket=False)
    monkeypatch.setattr(
        "cveta2.image_downloader.make_s3_client", lambda _endpoint=None: s3
    )
    return s3


def _client(detected: object = None) -> tuple[CvatClient, MagicMock]:
    """Build a client over a mock port whose detection returns *detected*."""
    api = MagicMock(spec=CvatApiPort)
    api.get_project_cloud_storage.return_value = detected
    return client_with_api(api), api


def _one_image(name: str = "img.jpg") -> ProjectAnnotations:
    return ProjectAnnotations(
        annotations=[make_bbox(image_name=name)], deleted_images=[]
    )


class TestDownloadImagesStorageResolution:
    """``project_cloud_storage`` wins; ``project_id`` is only the fallback."""

    def test_given_storage_is_used_without_asking_cvat(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A caller-supplied storage must suppress the detection round-trip.

        Both operands of the ``and`` were unpinned: widening it to ``or``
        re-detects on every call, throwing away the storage the caller
        resolved (``api.s3_sync`` applies ``sync_roots`` overrides there)
        and spending a CVAT request to do it.
        """
        _bucket(monkeypatch, {"images/img.jpg": b"IMG"})
        client, api = _client(detected=_EMPTY_STORAGE)

        stats = client.download_images(
            _one_image(),
            tmp_path,
            project_id=7,
            project_cloud_storage=make_cs_info(bucket="bkt", prefix="images"),
        )

        api.get_project_cloud_storage.assert_not_called()
        assert stats.downloaded == 1
        assert (tmp_path / "img.jpg").read_bytes() == b"IMG"

    def test_missing_storage_is_detected_from_the_project_id(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The detected storage must reach the downloader, not just be fetched.

        ``ImageDownloader.download(project_cloud_storage=None)`` does not
        fail loudly -- it counts every image as ``failed`` -- so dropping
        the assignment or the keyword degrades a working fetch into a
        silent zero-download run.
        """
        _bucket(monkeypatch, {"images/img.jpg": b"IMG"})
        client, api = _client(detected=make_cs_info(bucket="bkt", prefix="images"))

        stats = client.download_images(_one_image(), tmp_path, project_id=7)

        api.get_project_cloud_storage.assert_called_once_with(7)
        assert (stats.downloaded, stats.failed) == (1, 0)
        assert (tmp_path / "img.jpg").read_bytes() == b"IMG"

    def test_without_a_project_id_nothing_is_detected(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """There is no project to ask about, so CVAT must not be called.

        Inverting the ``project_id`` test sends ``None`` down as a project
        id; a real port answers that with a 404 rather than the documented
        "everything counts as failed" outcome.
        """
        _bucket(monkeypatch, {"images/img.jpg": b"IMG"})
        client, api = _client()

        stats = client.download_images(_one_image(), tmp_path)

        api.get_project_cloud_storage.assert_not_called()
        assert (stats.downloaded, stats.failed) == (0, 1)

    def test_ignored_prefix_reaches_the_downloader(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The prefix decides the *local* layout, so only the tree shows it.

        With ``ignored_prefix`` dropped, ``ImageDownloader`` strips the whole
        storage prefix instead and flattens the S3 hierarchy -- the same file
        count, at different paths, which no counter-based assertion notices.
        """
        _bucket(monkeypatch, {"raw/sub/b.jpg": b"B"})
        client, _api = _client()

        client.download_images(
            _one_image("b.jpg"),
            tmp_path,
            project_cloud_storage=make_cs_info(bucket="bkt", prefix="raw/sub"),
            ignored_prefix="raw",
        )

        assert (tmp_path / "sub" / "b.jpg").read_bytes() == b"B"
        assert not (tmp_path / "b.jpg").exists()


class TestSyncProjectImagesStorageResolution:
    """The full-prefix sync detects its own storage when given none."""

    def test_missing_storage_is_detected_from_the_project_id(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Only a detection that is *kept* distinguishes a sync from a no-op.

        Every caller of ``sync_project_images`` resolves the storage first,
        and the one test that leaves it ``None`` has no storage to detect
        either -- so blanking the fallback returned the same empty
        ``DownloadStats(total=0)`` the tests already expected.
        """
        _bucket(monkeypatch, {"synced/a.jpg": b"A"})
        client, api = _client(detected=make_cs_info(bucket="bkt", prefix="synced"))

        stats = client.sync_project_images(11, tmp_path)

        api.get_project_cloud_storage.assert_called_once_with(11)
        assert (stats.total, stats.downloaded) == (1, 1)
        assert (tmp_path / "a.jpg").read_bytes() == b"A"
