"""Tests for image_downloader module with fake S3 and SDK stubs."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple
from unittest.mock import MagicMock

import pytest

from cveta2.image_downloader import (
    CloudStorageInfo,
    ImageDownloader,
    S3Syncer,
    parse_cloud_storage,
)
from cveta2.models import (
    DeletedImage,
    ImageWithoutAnnotations,
    ProjectAnnotations,
)
from cveta2.s3_utils import build_s3_key, list_s3_objects, parse_sync_root
from tests.fixtures.fake_s3 import FakeS3Client
from tests.helpers import make_bbox, make_cs_info

if TYPE_CHECKING:
    from pathlib import Path


class _FakeCloudStorage:
    """Minimal stand-in for a CVAT cloud storage SDK object."""

    def __init__(
        self,
        cs_id: int,
        resource: str,
        specific_attributes: str,
    ) -> None:
        self.id = cs_id
        self.resource = resource
        self.specific_attributes = specific_attributes


class _FakeTask:
    """Minimal SDK task with source_storage."""

    def __init__(self, source_storage: dict[str, Any] | None) -> None:
        self.source_storage = source_storage


class _FakeSdkClient:
    """Fake CVAT SDK client for image download tests."""

    def __init__(
        self,
        task_storages: dict[int, dict[str, Any] | None],
        cloud_storages: dict[int, _FakeCloudStorage],
        s3_objects: dict[str, bytes],
    ) -> None:
        self._task_storages = task_storages
        self._cloud_storages = cloud_storages
        self._s3_objects = s3_objects

        self.tasks = MagicMock()
        self.tasks.retrieve.side_effect = self._retrieve_task

        cs_api = MagicMock()
        cs_api.retrieve.side_effect = self._retrieve_cs
        api_client = MagicMock()
        api_client.cloudstorages_api = cs_api
        self.api_client = api_client

    def _retrieve_task(self, task_id: int) -> _FakeTask:
        return _FakeTask(self._task_storages.get(task_id))

    def _retrieve_cs(self, cs_id: int) -> tuple[_FakeCloudStorage, Any]:
        return self._cloud_storages[cs_id], None


def _patch_boto(monkeypatch: pytest.MonkeyPatch, fake_s3: FakeS3Client) -> None:
    """Route make_s3_client to the fake S3 client."""
    monkeypatch.setattr(
        "cveta2.image_downloader.make_s3_client",
        lambda *_a, **_kw: fake_s3,
    )


def _ann(task_id: int, frame_id: int, image_name: str) -> Any:
    return make_bbox(
        image_name=image_name,
        task_id=task_id,
        task_name="task",
        frame_id=frame_id,
    )


def _img_no_ann(
    task_id: int, frame_id: int, image_name: str
) -> ImageWithoutAnnotations:
    return ImageWithoutAnnotations(
        image_name=image_name,
        image_width=640,
        image_height=480,
        task_id=task_id,
        task_name="task",
        frame_id=frame_id,
    )


def _project_cs() -> CloudStorageInfo:
    return make_cs_info(bucket="test-bucket", prefix="images")


def _make_downloader_env(
    tmp_path: Path,
    annotations: ProjectAnnotations,
    s3_data: dict[str, bytes],
    prefix: str = "images",
) -> ImageDownloader:
    """Build an ImageDownloader with a fake SDK backing its task lookups."""
    task_ids = {record.task_id for record in annotations.annotations}
    cloud_storage = _FakeCloudStorage(
        cs_id=1,
        resource="test-bucket",
        specific_attributes=f"prefix={prefix}&endpoint_url=http://minio:9000",
    )
    task_storages: dict[int, dict[str, Any] | None] = {
        tid: {"cloud_storage_id": 1} for tid in task_ids
    }
    _FakeSdkClient(
        task_storages=task_storages,
        cloud_storages={1: cloud_storage},
        s3_objects=s3_data,
    )
    return ImageDownloader(tmp_path / "images")


def test_parse_cloud_storage() -> None:
    cs = _FakeCloudStorage(
        cs_id=5,
        resource="my-bucket",
        specific_attributes="prefix=data/images&endpoint_url=http://minio:9000",
    )
    info = parse_cloud_storage(cs)
    assert info.id == 5
    assert info.bucket == "my-bucket"
    assert info.prefix == "data/images"
    assert info.endpoint_url == "http://minio:9000"


def test_parse_cloud_storage_no_prefix() -> None:
    cs = _FakeCloudStorage(
        cs_id=1,
        resource="bucket",
        specific_attributes="endpoint_url=http://s3.example.com",
    )
    info = parse_cloud_storage(cs)
    assert info.prefix == ""
    assert info.bucket == "bucket"
    assert info.endpoint_url == "http://s3.example.com"


def test_s3_key_with_prefix() -> None:
    assert build_s3_key("data/images", "cat.jpg") == "data/images/cat.jpg"


def test_s3_key_without_prefix() -> None:
    assert build_s3_key("", "cat.jpg") == "cat.jpg"


def test_s3_key_frame_already_has_prefix() -> None:
    assert build_s3_key("data/images", "data/images/cat.jpg") == "data/images/cat.jpg"


def test_download_saves_to_target_dir_flat(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    annotations = ProjectAnnotations(
        annotations=[_ann(10, 0, "a.jpg"), _ann(10, 1, "b.jpg")],
        deleted_images=[],
    )
    s3_data = {
        "test-bucket/images/a.jpg": b"data-a",
        "test-bucket/images/b.jpg": b"data-b",
    }
    downloader = _make_downloader_env(tmp_path, annotations, s3_data)
    _patch_boto(monkeypatch, FakeS3Client(s3_data))

    stats = downloader.download(annotations, project_cloud_storage=_project_cs())

    assert stats.downloaded == 2
    assert stats.cached == 0
    assert stats.total == 2
    target = tmp_path / "images"
    assert (target / "a.jpg").read_bytes() == b"data-a"
    assert (target / "b.jpg").read_bytes() == b"data-b"
    assert sorted(f.name for f in target.iterdir()) == ["a.jpg", "b.jpg"]


def test_download_skips_already_cached(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    annotations = ProjectAnnotations(
        annotations=[_ann(10, 0, "a.jpg"), _ann(10, 1, "b.jpg")],
        deleted_images=[],
    )
    s3_data = {
        "test-bucket/images/a.jpg": b"data-a",
        "test-bucket/images/b.jpg": b"data-b",
    }
    target = tmp_path / "images"
    target.mkdir(parents=True)
    (target / "a.jpg").write_bytes(b"old-data-a")

    downloader = _make_downloader_env(tmp_path, annotations, s3_data)
    _patch_boto(monkeypatch, FakeS3Client(s3_data))

    stats = downloader.download(annotations, project_cloud_storage=_project_cs())

    assert stats.cached == 1
    assert stats.downloaded == 1
    assert stats.total == 2
    assert (target / "a.jpg").read_bytes() == b"old-data-a"
    assert (target / "b.jpg").read_bytes() == b"data-b"


def test_download_creates_target_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "deep" / "nested" / "dir"
    annotations = ProjectAnnotations(
        annotations=[_ann(10, 0, "img.jpg")],
        deleted_images=[],
    )
    s3_data = {"test-bucket/images/img.jpg": b"data"}
    _make_downloader_env(tmp_path, annotations, s3_data)
    _patch_boto(monkeypatch, FakeS3Client(s3_data))

    downloader = ImageDownloader(target)
    stats = downloader.download(annotations, project_cloud_storage=_project_cs())

    assert stats.downloaded == 1
    assert target.exists()
    assert (target / "img.jpg").read_bytes() == b"data"


def test_download_empty_annotations(tmp_path: Path) -> None:
    annotations = ProjectAnnotations(annotations=[], deleted_images=[])
    downloader = ImageDownloader(tmp_path / "images")
    stats = downloader.download(annotations)
    assert stats.total == 0
    assert stats.downloaded == 0
    assert stats.cached == 0


def test_download_skips_deleted_images(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deleted images should not be in the download list."""
    annotations = ProjectAnnotations(
        annotations=[_ann(10, 0, "alive.jpg")],
        deleted_images=[
            DeletedImage(
                task_id=10,
                task_name="task",
                frame_id=1,
                image_name="dead.jpg",
            )
        ],
    )
    s3_data = {
        "test-bucket/images/alive.jpg": b"data",
        "test-bucket/images/dead.jpg": b"should-not-download",
    }
    downloader = _make_downloader_env(tmp_path, annotations, s3_data)
    _patch_boto(monkeypatch, FakeS3Client(s3_data))

    stats = downloader.download(annotations, project_cloud_storage=_project_cs())

    assert stats.total == 1
    assert stats.downloaded == 1
    target = tmp_path / "images"
    assert (target / "alive.jpg").exists()
    assert not (target / "dead.jpg").exists()


def test_download_stats_counts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify all stat counters are correct after a mixed run."""
    annotations = ProjectAnnotations(
        annotations=[
            _ann(10, 0, "new.jpg"),
            _ann(10, 1, "cached.jpg"),
            _img_no_ann(10, 2, "also-new.jpg"),
        ],
        deleted_images=[],
    )
    target = tmp_path / "images"
    target.mkdir(parents=True)
    (target / "cached.jpg").write_bytes(b"existing")

    s3_data = {
        "test-bucket/images/new.jpg": b"data-new",
        "test-bucket/images/also-new.jpg": b"data-also-new",
    }
    downloader = _make_downloader_env(tmp_path, annotations, s3_data)
    _patch_boto(monkeypatch, FakeS3Client(s3_data))

    stats = downloader.download(annotations, project_cloud_storage=_project_cs())

    assert stats.total == 3
    assert stats.cached == 1
    assert stats.downloaded == 2
    assert stats.failed == 0


def test_download_no_cloud_storage_marks_failed(tmp_path: Path) -> None:
    """When project_cloud_storage is not provided, all pending images are failed."""
    annotations = ProjectAnnotations(
        annotations=[_ann(10, 0, "img.jpg")],
        deleted_images=[],
    )
    _FakeSdkClient(task_storages={10: None}, cloud_storages={}, s3_objects={})
    downloader = ImageDownloader(tmp_path / "images")

    stats = downloader.download(annotations)

    assert stats.total == 1
    assert stats.failed == 1
    assert stats.downloaded == 0


def test_download_fallback_project_storage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No task storage + project_cloud_storage -> images loaded from project."""
    annotations = ProjectAnnotations(
        annotations=[_ann(10, 0, "img.jpg")],
        deleted_images=[],
    )
    _FakeSdkClient(task_storages={10: None}, cloud_storages={}, s3_objects={})
    project_cs = make_cs_info(bucket="test-bucket", prefix="proj/")
    # Project-storage path receives S3 keys directly (not "bucket/key").
    s3_data = {"proj/img.jpg": b"project-data"}
    _patch_boto(monkeypatch, FakeS3Client(s3_data, keyed_by_bucket=False))

    downloader = ImageDownloader(tmp_path / "images")
    stats = downloader.download(annotations, project_cloud_storage=project_cs)

    assert stats.total == 1
    assert stats.downloaded == 1
    assert stats.failed == 0
    assert (tmp_path / "images" / "img.jpg").read_bytes() == b"project-data"


# ======================================================================
# S3 sync tests
# ======================================================================


# --- list_s3_objects tests ---


def testlist_s3_objects_returns_keys_stripped_of_prefix() -> None:
    """list_s3_objects strips the prefix from keys."""
    fake_s3 = FakeS3Client(
        {"images/a.jpg": b"data-a", "images/b.jpg": b"data-b"}, keyed_by_bucket=False
    )
    result = list_s3_objects(fake_s3, "test-bucket", "images")
    assert sorted(result) == [("images/a.jpg", "a.jpg"), ("images/b.jpg", "b.jpg")]


def testlist_s3_objects_no_prefix() -> None:
    """list_s3_objects with empty prefix returns keys as-is."""
    fake_s3 = FakeS3Client(
        {"cat.jpg": b"cat", "dog.jpg": b"dog"}, keyed_by_bucket=False
    )
    result = list_s3_objects(fake_s3, "bucket", "")
    assert sorted(result) == [("cat.jpg", "cat.jpg"), ("dog.jpg", "dog.jpg")]


def testlist_s3_objects_empty_bucket() -> None:
    """list_s3_objects returns empty list for empty bucket."""
    fake_s3 = FakeS3Client({}, keyed_by_bucket=False)
    result = list_s3_objects(fake_s3, "bucket", "prefix")
    assert result == []


def testlist_s3_objects_skips_prefix_marker() -> None:
    """list_s3_objects skips the prefix directory marker (empty name after strip)."""
    fake_s3 = FakeS3Client(
        {"images/": b"", "images/a.jpg": b"data"}, keyed_by_bucket=False
    )
    result = list_s3_objects(fake_s3, "bucket", "images/")
    assert result == [("images/a.jpg", "a.jpg")]


# --- S3Syncer tests ---


class _SyncCase(NamedTuple):
    s3_objects: dict[str, bytes]
    pre_cached: dict[str, bytes]
    expected: tuple[int, int, int, int]  # total, downloaded, cached, failed
    expected_files: dict[str, bytes]
    absent_files: tuple[str, ...] = ()
    sync_root: str | None = None


_SYNC_CASES = [
    pytest.param(
        _SyncCase(
            {
                "images/a.jpg": b"data-a",
                "images/b.jpg": b"data-b",
                "images/c.png": b"data-c",
            },
            {},
            (3, 3, 0, 0),
            {"a.jpg": b"data-a", "b.jpg": b"data-b", "c.png": b"data-c"},
        ),
        id="downloads-all",
    ),
    pytest.param(
        _SyncCase(
            {"images/a.jpg": b"data-a", "images/b.jpg": b"data-b"},
            {"a.jpg": b"old-data-a"},
            (2, 1, 1, 0),
            {"a.jpg": b"old-data-a", "b.jpg": b"data-b"},
        ),
        id="skips-already-cached",
    ),
    pytest.param(
        _SyncCase(
            {"images/a.jpg": b"data-a"},
            {"a.jpg": b"existing"},
            (1, 0, 1, 0),
            {"a.jpg": b"existing"},
        ),
        id="all-cached",
    ),
    pytest.param(
        _SyncCase({}, {}, (0, 0, 0, 0), {}),
        id="empty-bucket",
    ),
    pytest.param(
        _SyncCase(
            {"images/my_favourite/a.jpg": b"data-a", "images/other/b.jpg": b"data-b"},
            {},
            (1, 1, 0, 0),
            {"a.jpg": b"data-a"},
            absent_files=("b.jpg",),
            sync_root="s3://custom-bucket/images/my_favourite",
        ),
        id="custom-sync-root-scopes-subtree",
    ),
    pytest.param(
        _SyncCase(
            {"images/a.jpg": b"data-a"},
            {"a.jpg": b"existing-a", "local-only.jpg": b"local-data"},
            (1, 0, 1, 0),
            {"a.jpg": b"existing-a", "local-only.jpg": b"local-data"},
        ),
        id="never-deletes-local-only",
    ),
]


@pytest.mark.parametrize("case", _SYNC_CASES)
def test_s3_syncer_stats(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: _SyncCase,
) -> None:
    """S3Syncer accounting, subtree scoping, and on-disk contents."""
    target = tmp_path / "sync-dir"
    if case.pre_cached:
        target.mkdir(parents=True)
        for name, data in case.pre_cached.items():
            (target / name).write_bytes(data)

    _patch_boto(monkeypatch, FakeS3Client(case.s3_objects, keyed_by_bucket=False))

    if case.sync_root is not None:
        bucket, prefix = parse_sync_root(case.sync_root)
        assert bucket is not None
    else:
        bucket, prefix = "test-bucket", "images"
    cs_info = make_cs_info(
        bucket=bucket, prefix=prefix, endpoint_url="http://minio:9000"
    )

    stats = S3Syncer(target).sync(cs_info)

    total, downloaded, cached, failed = case.expected
    assert stats.total == total
    assert stats.downloaded == downloaded
    assert stats.cached == cached
    assert stats.failed == failed
    for name, data in case.expected_files.items():
        assert (target / name).read_bytes() == data
    for name in case.absent_files:
        assert not (target / name).exists()


def test_s3_syncer_creates_target_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S3Syncer creates the target directory if it doesn't exist."""
    _patch_boto(
        monkeypatch, FakeS3Client({"prefix/img.jpg": b"data"}, keyed_by_bucket=False)
    )
    cs_info = make_cs_info(
        bucket="bucket", prefix="prefix", endpoint_url="http://s3:9000"
    )
    target = tmp_path / "deep" / "nested" / "dir"

    stats = S3Syncer(target).sync(cs_info)

    assert stats.downloaded == 1
    assert target.exists()
    assert (target / "img.jpg").read_bytes() == b"data"


def test_download_nested_frame_saves_flat_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nested CVAT frame names download into a flat layout when unconfigured."""
    annotations = ProjectAnnotations(
        annotations=[_ann(10, 0, "2026-01/a.jpg")],
        deleted_images=[],
    )
    s3_data = {"test-bucket/images/2026-01/a.jpg": b"data-a"}
    _patch_boto(monkeypatch, FakeS3Client(s3_data))

    target = tmp_path / "images"
    stats = ImageDownloader(target).download(
        annotations, project_cloud_storage=_project_cs()
    )

    assert stats.downloaded == 1
    assert (target / "a.jpg").read_bytes() == b"data-a"


def test_download_ignored_prefix_preserves_subfolders(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With ignored_prefix set, the local layout mirrors the key below it."""
    annotations = ProjectAnnotations(
        annotations=[_ann(10, 0, "2026-01/a.jpg"), _ann(10, 1, "b.jpg")],
        deleted_images=[],
    )
    s3_data = {
        "test-bucket/images/2026-01/a.jpg": b"data-a",
        "test-bucket/images/b.jpg": b"data-b",
    }
    _patch_boto(monkeypatch, FakeS3Client(s3_data))

    target = tmp_path / "images"
    downloader = ImageDownloader(target, ignored_prefix="images")
    stats = downloader.download(annotations, project_cloud_storage=_project_cs())

    assert stats.downloaded == 2
    assert (target / "2026-01" / "a.jpg").read_bytes() == b"data-a"
    assert (target / "b.jpg").read_bytes() == b"data-b"

    rerun = downloader.download(annotations, project_cloud_storage=_project_cs())
    assert rerun.cached == 2


def test_s3_syncer_ignored_prefix_keeps_remainder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S3Syncer strips only the ignored prefix and keeps the rest as dirs."""
    s3_objects = {
        "data/projA/2026-01/a.jpg": b"data-a",
        "data/projA/b.jpg": b"data-b",
    }
    _patch_boto(monkeypatch, FakeS3Client(s3_objects, keyed_by_bucket=False))
    cs_info = make_cs_info(
        bucket="test-bucket", prefix="data/projA", endpoint_url="http://minio:9000"
    )

    target = tmp_path / "sync-dir"
    stats = S3Syncer(target, ignored_prefix="data").sync(cs_info)

    assert stats.downloaded == 2
    assert (target / "projA" / "2026-01" / "a.jpg").read_bytes() == b"data-a"
    assert (target / "projA" / "b.jpg").read_bytes() == b"data-b"
