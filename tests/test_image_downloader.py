"""Tests for image_downloader module with fake S3 and SDK stubs."""

from __future__ import annotations

import errno
import os
import stat
import threading
from typing import TYPE_CHECKING, Any, NamedTuple
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

from cveta2.fs_utils import write_shared_bytes
from cveta2.image_downloader import (
    CloudStorageInfo,
    ImageDownloader,
    S3Syncer,
    _download_one_s3,
    parse_cloud_storage,
)
from cveta2.models import (
    DeletedImage,
    ImageWithoutAnnotations,
    ProjectAnnotations,
)
from cveta2.s3_utils import build_s3_key, list_s3_objects, parse_sync_root
from tests.fixtures.fake_s3 import FakeS3Client
from tests.helpers import make_bbox, make_cs_info, patch_recording_s3

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


class _BareCloudStorage:
    """A CVAT cloud-storage object exposing none of the expected attributes."""


class _DenyingHeadS3Client(FakeS3Client):
    """Fake S3 that refuses every HEAD, the way a denied bucket does.

    S3 answers 403 rather than 404 for a caller without ListBucket, so
    "denied" and "absent" are only told apart by the error code.
    """

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:  # noqa: N803
        raise ClientError(
            {"Error": {"Code": "AccessDenied", "Message": f"{Bucket}/{Key}"}},
            "HeadObject",
        )


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


class _UnreadableKeysS3Client(FakeS3Client):
    """Lists every seeded object but raises on ``get_object`` for some keys.

    :class:`FakeS3Client` serves whatever it lists, so no test could ever
    produce a non-zero ``stats.failed`` from a transfer.  ``KeyError`` is
    in ``s3_utils.S3_TRANSFER_ERRORS`` but not in the ``s3_retry`` set, so
    it is counted as a failure without burning the retry backoff.
    """

    def __init__(
        self,
        objects: dict[str, bytes],
        *,
        unreadable: set[str],
        keyed_by_bucket: bool = True,
    ) -> None:
        """Seed the store and mark *unreadable* keys as un-gettable."""
        super().__init__(objects, keyed_by_bucket=keyed_by_bucket)
        self._unreadable = frozenset(unreadable)

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:  # noqa: N803
        """Serve the object unless its key was marked unreadable."""
        if Key in self._unreadable:
            raise KeyError(Key)
        return super().get_object(Bucket=Bucket, Key=Key)


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


def test_parse_cloud_storage_no_endpoint_url() -> None:
    """A storage without endpoint_url falls back to the empty string.

    The mirror case (no prefix) was covered, so only the ``prefix``
    fallback list was pinned; the ``endpoint_url`` one could hold any
    placeholder.
    """
    cs = _FakeCloudStorage(
        cs_id=3, resource="bucket", specific_attributes="prefix=imgs"
    )
    info = parse_cloud_storage(cs)
    assert info.endpoint_url == ""
    assert info.prefix == "imgs"


def test_parse_cloud_storage_missing_attributes_uses_defaults() -> None:
    """Every ``getattr`` default is load-bearing on an older SDK object.

    All fixtures supplied ``id``, ``resource`` and ``specific_attributes``,
    so the three defaults were never read: dropping them, or changing 0/""
    to anything else, went unnoticed.
    """
    info = parse_cloud_storage(_BareCloudStorage())
    assert info.id == 0
    assert info.bucket == ""
    assert info.prefix == ""
    assert info.endpoint_url == ""


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


def test_download_creates_group_writable_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    annotations = ProjectAnnotations(
        annotations=[_ann(10, 0, "a.jpg")],
        deleted_images=[],
    )
    s3_data = {"test-bucket/images/a.jpg": b"data-a"}
    downloader = _make_downloader_env(tmp_path, annotations, s3_data)
    _patch_boto(monkeypatch, FakeS3Client(s3_data))

    old_umask = os.umask(0o077)
    try:
        downloader.download(annotations, project_cloud_storage=_project_cs())
    finally:
        os.umask(old_umask)

    target = tmp_path / "images"
    assert stat.S_IMODE(target.stat().st_mode) == 0o775
    assert stat.S_IMODE((target / "a.jpg").stat().st_mode) == 0o664


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


def _raise_no_space(path: Path, data: bytes) -> None:
    """Fail like a full disk after only a prefix of *data* reached *path*."""
    path.write_bytes(data[:3])
    raise OSError(errno.ENOSPC, "No space left on device")


def _temp_leftovers(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir() if ".tmp" in p.name)


def test_failed_write_leaves_no_partial_file_and_is_retried_next_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    annotations = ProjectAnnotations(
        annotations=[_ann(10, 0, "a.jpg")], deleted_images=[]
    )
    s3_data = {"test-bucket/images/a.jpg": b"full-data"}
    downloader = _make_downloader_env(tmp_path, annotations, s3_data)
    _patch_boto(monkeypatch, FakeS3Client(s3_data))
    target = tmp_path / "images"

    with monkeypatch.context() as patched:
        patched.setattr("cveta2.image_downloader.write_shared_bytes", _raise_no_space)
        failed_run = downloader.download(
            annotations, project_cloud_storage=_project_cs()
        )

    assert failed_run.failed == 1
    assert failed_run.downloaded == 0
    assert not (target / "a.jpg").exists()
    assert _temp_leftovers(target) == []

    retry_run = downloader.download(annotations, project_cloud_storage=_project_cs())

    assert retry_run.cached == 0
    assert retry_run.downloaded == 1
    assert (target / "a.jpg").read_bytes() == b"full-data"


def test_download_one_s3_reraises_the_write_error_when_no_temp_file_was_created(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse_to_write(_path: Path, _data: bytes) -> None:
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr("cveta2.image_downloader.write_shared_bytes", refuse_to_write)
    dest = tmp_path / "images" / "a.jpg"

    with pytest.raises(OSError, match="No space left"):
        _download_one_s3(
            FakeS3Client({"test-bucket/images/a.jpg": b"data"}),
            "test-bucket",
            "images/a.jpg",
            dest,
        )

    assert not dest.exists()
    assert _temp_leftovers(dest.parent) == []


def test_download_writes_through_a_temp_name_unique_to_the_writing_thread(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writes: list[tuple[Path, int]] = []

    def record_then_write(path: Path, data: bytes) -> None:
        writes.append((path, threading.get_ident()))
        write_shared_bytes(path, data)

    monkeypatch.setattr("cveta2.image_downloader.write_shared_bytes", record_then_write)
    annotations = ProjectAnnotations(
        annotations=[_ann(10, 0, "a.jpg")], deleted_images=[]
    )
    s3_data = {"test-bucket/images/a.jpg": b"data-a"}
    downloader = _make_downloader_env(tmp_path, annotations, s3_data)
    _patch_boto(monkeypatch, FakeS3Client(s3_data))
    dest = tmp_path / "images" / "a.jpg"

    stats = downloader.download(annotations, project_cloud_storage=_project_cs())

    assert stats.downloaded == 1
    [(temp_path, writer_thread)] = writes
    assert temp_path == dest.with_name(f"a.jpg.tmp{os.getpid()}-{writer_thread}")
    assert dest.read_bytes() == b"data-a"
    assert _temp_leftovers(dest.parent) == []


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
            {
                "images/2026-01/": b"",
                "images/2026-01/a.jpg": b"data-a",
                "images/b.jpg": b"data-b",
            },
            {},
            (2, 2, 0, 0),
            {"2026-01/a.jpg": b"data-a", "b.jpg": b"data-b"},
        ),
        id="skips-console-folder-markers",
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


def test_download_nested_frame_mirrors_s3_layout_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nested CVAT frame names keep their S3 subfolders locally."""
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
    assert (target / "2026-01" / "a.jpg").read_bytes() == b"data-a"

    rerun_stats = ImageDownloader(target).download(
        annotations, project_cloud_storage=_project_cs()
    )
    assert rerun_stats.cached == 1


def test_download_ignored_prefix_keeps_prefix_remainder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ignored_prefix must strip *less* of the key than the storage prefix.

    The earlier version of this test used ``ignored_prefix`` equal to the
    storage prefix, which makes the stripped layout byte-identical to the
    default ``target_dir / frame_ref`` one.  It therefore could not tell
    the two branches of ``_dest_path`` apart, nor notice ``__init__``
    throwing ``ignored_prefix`` away, nor ``_filter_cached`` /
    ``_download_all`` passing ``None`` for the storage.
    """
    annotations = ProjectAnnotations(
        annotations=[_ann(10, 0, "2026-01/a.jpg"), _ann(10, 1, "b.jpg")],
        deleted_images=[],
    )
    s3_data = {
        "test-bucket/data/projA/2026-01/a.jpg": b"data-a",
        "test-bucket/data/projA/b.jpg": b"data-b",
    }
    _patch_boto(monkeypatch, FakeS3Client(s3_data))
    cs_info = make_cs_info(bucket="test-bucket", prefix="data/projA")

    target = tmp_path / "images"
    downloader = ImageDownloader(target, ignored_prefix="data")
    stats = downloader.download(annotations, project_cloud_storage=cs_info)

    assert stats.downloaded == 2
    assert (target / "projA" / "2026-01" / "a.jpg").read_bytes() == b"data-a"
    assert (target / "projA" / "b.jpg").read_bytes() == b"data-b"

    rerun = downloader.download(annotations, project_cloud_storage=cs_info)
    assert rerun.cached == 2
    assert rerun.downloaded == 0


def test_download_uses_storage_endpoint_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The storage endpoint reaches make_s3_client verbatim.

    Every fake replaced make_s3_client with a lambda that ignored its
    arguments, so connecting to the wrong (or default) S3 endpoint was
    invisible.
    """
    annotations = ProjectAnnotations(
        annotations=[_ann(10, 0, "a.jpg")],
        deleted_images=[],
    )
    s3_data = {"test-bucket/images/a.jpg": b"data-a"}
    factory = patch_recording_s3(
        monkeypatch, "cveta2.image_downloader", FakeS3Client(s3_data)
    )
    cs_info = make_cs_info(
        bucket="test-bucket", prefix="images", endpoint_url="http://minio:9000"
    )

    stats = ImageDownloader(tmp_path / "images").download(
        annotations, project_cloud_storage=cs_info
    )

    assert stats.downloaded == 1
    assert factory.endpoints == ["http://minio:9000"]


def test_download_missing_from_s3_listing_counts_as_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An annotated image absent from the S3 listing is failed, not skipped.

    Every fixture listed exactly the images it annotated, so the whole
    ``missing`` block never ran: ``stats.failed += len(missing)`` and the
    ``continue`` that keeps the remaining images downloading were free.
    """
    annotations = ProjectAnnotations(
        annotations=[_ann(10, 0, "gone.jpg"), _ann(10, 1, "here.jpg")],
        deleted_images=[],
    )
    s3_data = {"test-bucket/images/here.jpg": b"data-here"}
    _patch_boto(monkeypatch, FakeS3Client(s3_data))

    target = tmp_path / "images"
    stats = ImageDownloader(target).download(
        annotations, project_cloud_storage=_project_cs()
    )

    assert stats.total == 2
    assert stats.failed == 1
    assert stats.downloaded == 1
    assert (target / "here.jpg").read_bytes() == b"data-here"
    assert not (target / "gone.jpg").exists()


def test_download_adds_listing_misses_and_transfer_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capture_logs: list[str],
) -> None:
    """stats.failed accumulates listing misses *and* failed transfers.

    Two separate ``+=`` writers feed that counter, and with only one of
    them ever non-zero a plain ``=`` was indistinguishable.  The failure
    log is the only place the transfer's display name is used, so it also
    pins ``Transfer(name=...)`` and the describe callable.
    """
    annotations = ProjectAnnotations(
        annotations=[
            _ann(10, 0, "gone.jpg"),
            _ann(10, 1, "broken.jpg"),
            _ann(10, 2, "ok.jpg"),
        ],
        deleted_images=[],
    )
    s3_data = {
        "test-bucket/images/broken.jpg": b"unreadable",
        "test-bucket/images/ok.jpg": b"data-ok",
    }
    _patch_boto(
        monkeypatch,
        _UnreadableKeysS3Client(s3_data, unreadable={"images/broken.jpg"}),
    )

    target = tmp_path / "images"
    stats = ImageDownloader(target).download(
        annotations, project_cloud_storage=_project_cs()
    )

    assert stats.total == 3
    assert stats.failed == 2
    assert stats.downloaded == 1
    assert (target / "ok.jpg").read_bytes() == b"data-ok"
    assert "broken.jpg (key=images/broken.jpg)" in "\n".join(capture_logs)


def test_download_key_lookup_prefers_frame_path_over_image_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """frame_path picks the key; image_name is only the basename fallback.

    Every earlier fixture left ``frame_path`` equal to ``image_name``, so
    the two lookups resolved to one and the same entry and their order was
    unobservable.  ``one.jpg`` exists twice on S3 (nested and flat) so the
    two tiers return *different* bytes; ``two.jpg`` has a stale
    ``frame_path`` that only the second tier can rescue.  The bucket also
    holds a same-basename object *outside* the storage prefix, listed
    first, so that listing without the prefix poisons the basename entry
    of the name map instead of going unnoticed.
    """
    s3_data = {
        "test-bucket/archive/one.jpg": b"archived-one",
        "test-bucket/images/2026-01/one.jpg": b"nested-one",
        "test-bucket/images/one.jpg": b"flat-one",
        "test-bucket/images/2026-02/two.jpg": b"wanted-two",
    }
    annotations = ProjectAnnotations(
        annotations=[
            make_bbox(image_name="one.jpg", frame_path="2026-01/one.jpg", task_id=10),
            make_bbox(image_name="two.jpg", frame_path="stale/two.jpg", task_id=10),
        ],
        deleted_images=[],
    )
    _patch_boto(monkeypatch, FakeS3Client(s3_data))

    target = tmp_path / "images"
    stats = ImageDownloader(target).download(
        annotations, project_cloud_storage=_project_cs()
    )

    assert stats.downloaded == 2
    assert stats.failed == 0
    assert (target / "2026-01" / "one.jpg").read_bytes() == b"nested-one"
    assert (target / "stale" / "two.jpg").read_bytes() == b"wanted-two"


def test_s3_syncer_scopes_to_bucket_and_reports_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capture_logs: list[str],
) -> None:
    """Sync reads one bucket over the configured endpoint and counts failures.

    The parametrized syncer cases all used a bucket-blind fake, so passing
    ``None`` for the bucket (to either the listing or the transfer) changed
    nothing, the endpoint argument was never observed, and no case ever
    produced a failed transfer — which is the only reader of a
    ``Transfer``'s display name.
    """
    s3_data = {
        "test-bucket/images/ok.jpg": b"data-ok",
        "test-bucket/images/broken.jpg": b"unreadable",
        "other-bucket/images/elsewhere.jpg": b"data-elsewhere",
    }
    client = _UnreadableKeysS3Client(s3_data, unreadable={"images/broken.jpg"})
    factory = patch_recording_s3(monkeypatch, "cveta2.image_downloader", client)
    cs_info = make_cs_info(
        bucket="test-bucket", prefix="images", endpoint_url="http://minio:9000"
    )

    target = tmp_path / "sync-dir"
    stats = S3Syncer(target).sync(cs_info)

    assert factory.endpoints == ["http://minio:9000"]
    assert stats.total == 2
    assert stats.downloaded == 1
    assert stats.failed == 1
    assert (target / "ok.jpg").read_bytes() == b"data-ok"
    assert not (target / "elsewhere.jpg").exists()
    assert "broken.jpg (key=images/broken.jpg)" in "\n".join(capture_logs)


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


# ---------------------------------------------------------------------------
# S3 key resolution: probe the expected key before walking the whole prefix
# ---------------------------------------------------------------------------


def test_expected_keys_skip_the_whole_prefix_listing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Images sitting at their expected key are found without a listing.

    The prefix holds every task's images, so listing it to place a couple
    of them is what made a one-task fetch cost as much as a whole-project
    one.  The key CVAT's frame name implies is checked first instead.
    """
    annotations = ProjectAnnotations(
        annotations=[_ann(10, 0, "a.jpg"), _ann(10, 1, "b.jpg")],
        deleted_images=[],
    )
    fake_s3 = FakeS3Client(
        {
            "test-bucket/images/a.jpg": b"data-a",
            "test-bucket/images/b.jpg": b"data-b",
            "test-bucket/images/someone-elses.jpg": b"data-other",
        }
    )
    _patch_boto(monkeypatch, fake_s3)

    target = tmp_path / "images"
    stats = ImageDownloader(target).download(
        annotations, project_cloud_storage=_project_cs()
    )

    assert stats.downloaded == 2
    assert fake_s3.list_requests == []
    assert fake_s3.head_calls == [
        "test-bucket/images/a.jpg",
        "test-bucket/images/b.jpg",
    ]
    assert (target / "a.jpg").read_bytes() == b"data-a"
    assert (target / "b.jpg").read_bytes() == b"data-b"


def test_a_key_the_frame_name_misses_falls_back_to_the_listing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bare name stored under a subfolder still resolves, via the listing.

    Only the listing carries the basename fallback, so a probe that comes
    back empty must hand the name over to it rather than report the image
    as missing from S3.  The listing stays scoped to the project prefix:
    the decoy sorts before the real key, so a listing widened to the whole
    bucket would claim the basename first and hand back the wrong bytes.
    """
    annotations = ProjectAnnotations(
        annotations=[_ann(10, 0, "flat.jpg"), _ann(10, 1, "nested.jpg")],
        deleted_images=[],
    )
    fake_s3 = FakeS3Client(
        {
            "test-bucket/images/flat.jpg": b"data-flat",
            "test-bucket/images/2026-02/nested.jpg": b"data-nested",
            "test-bucket/another-project/nested.jpg": b"data-decoy",
        }
    )
    _patch_boto(monkeypatch, fake_s3)

    target = tmp_path / "images"
    stats = ImageDownloader(target).download(
        annotations, project_cloud_storage=_project_cs()
    )

    assert stats.downloaded == 2
    assert stats.failed == 0
    assert fake_s3.list_requests != []
    assert (target / "flat.jpg").read_bytes() == b"data-flat"
    assert (target / "nested.jpg").read_bytes() == b"data-nested"


def test_a_denied_head_is_raised_rather_than_read_as_absent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bucket that refuses the probe is a broken setup, not a missing image.

    Reading 403 as "not there" would turn a wrong endpoint or a denied
    bucket into a quiet list of images reported as missing from S3.
    """
    annotations = ProjectAnnotations(
        annotations=[_ann(10, 0, "a.jpg")], deleted_images=[]
    )
    _patch_boto(monkeypatch, _DenyingHeadS3Client())

    with pytest.raises(ClientError):
        ImageDownloader(tmp_path / "images").download(
            annotations, project_cloud_storage=_project_cs()
        )


def test_the_probe_limit_is_inclusive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A batch exactly at the limit still probes; one past it lists."""
    annotations = ProjectAnnotations(
        annotations=[_ann(10, 0, "a.jpg"), _ann(10, 1, "b.jpg")],
        deleted_images=[],
    )
    fake_s3 = FakeS3Client(
        {
            "test-bucket/images/a.jpg": b"data-a",
            "test-bucket/images/b.jpg": b"data-b",
        }
    )
    _patch_boto(monkeypatch, fake_s3)
    monkeypatch.setattr("cveta2.image_downloader._DIRECT_KEY_PROBE_LIMIT", 2)

    stats = ImageDownloader(tmp_path / "images").download(
        annotations, project_cloud_storage=_project_cs()
    )

    assert stats.downloaded == 2
    assert fake_s3.head_calls != []
    assert fake_s3.list_requests == []


def test_the_listing_prefers_the_frame_path_over_a_same_named_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On the listing path the full frame path outranks the bare basename.

    Two months hold a file of the same name; the basename fallback keeps
    the first it sees, so only the full path picks the right one.
    """
    annotation = make_bbox(
        image_name="x.jpg",
        task_id=10,
        task_name="task",
        frame_id=0,
        frame_path="2026-02/x.jpg",
    )
    fake_s3 = FakeS3Client(
        {
            "test-bucket/images/2026-01/x.jpg": b"data-january",
            "test-bucket/images/2026-02/x.jpg": b"data-february",
        }
    )
    _patch_boto(monkeypatch, fake_s3)
    monkeypatch.setattr("cveta2.image_downloader._DIRECT_KEY_PROBE_LIMIT", 0)

    target = tmp_path / "images"
    stats = ImageDownloader(target).download(
        ProjectAnnotations(annotations=[annotation], deleted_images=[]),
        project_cloud_storage=_project_cs(),
    )

    assert stats.downloaded == 1
    assert fake_s3.head_calls == []
    assert (target / "2026-02" / "x.jpg").read_bytes() == b"data-february"


def test_a_batch_past_the_probe_limit_lists_instead(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Wanting most of the bucket is what the single listing is still for."""
    annotations = ProjectAnnotations(
        annotations=[_ann(10, 0, "a.jpg"), _ann(10, 1, "b.jpg")],
        deleted_images=[],
    )
    fake_s3 = FakeS3Client(
        {
            "test-bucket/images/a.jpg": b"data-a",
            "test-bucket/images/b.jpg": b"data-b",
        }
    )
    _patch_boto(monkeypatch, fake_s3)
    monkeypatch.setattr("cveta2.image_downloader._DIRECT_KEY_PROBE_LIMIT", 1)

    target = tmp_path / "images"
    stats = ImageDownloader(target).download(
        annotations, project_cloud_storage=_project_cs()
    )

    assert stats.downloaded == 2
    assert fake_s3.head_calls == []
    assert fake_s3.list_requests != []
