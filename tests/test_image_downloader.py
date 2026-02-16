"""Tests for image_downloader module with fake S3 and SDK stubs."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

from cveta2.image_downloader import (
    CloudStorageInfo,
    ImageDownloader,
    S3Syncer,
    _build_s3_key,
    _list_s3_objects,
    parse_cloud_storage,
)
from cveta2.models import (
    BBoxAnnotation,
    DeletedImage,
    ImageWithoutAnnotations,
    ProjectAnnotations,
)

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


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


def _make_s3_client(objects: dict[str, bytes]) -> MagicMock:
    """Build a mock S3 client backed by a dict."""

    def get_object(Bucket: str, Key: str) -> dict[str, Any]:  # noqa: N803
        full_key = f"{Bucket}/{Key}"
        if full_key not in objects:
            msg = f"NoSuchKey: {full_key}"
            raise KeyError(msg)
        body = MagicMock()
        body.read.return_value = objects[full_key]
        return {"Body": body}

    mock = MagicMock()
    mock.get_object.side_effect = get_object
    return mock


def _ann(task_id: int, frame_id: int, image_name: str) -> BBoxAnnotation:
    return BBoxAnnotation(
        image_name=image_name,
        image_width=640,
        image_height=480,
        instance_label="cat",
        bbox_x_tl=0.0,
        bbox_y_tl=0.0,
        bbox_x_br=100.0,
        bbox_y_br=100.0,
        task_id=task_id,
        task_name="task",
        frame_id=frame_id,
        subset="",
        occluded=False,
        z_order=0,
        rotation=0.0,
        source="manual",
        annotation_id=1,
        attributes={},
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


def _patch_boto(monkeypatch: pytest.MonkeyPatch, fake_s3: MagicMock) -> None:
    """Patch boto3.Session to return the fake S3 client."""
    monkeypatch.setattr(
        "cveta2.image_downloader.boto3.Session",
        lambda: MagicMock(client=lambda *_a, **_kw: fake_s3),
    )


def _make_downloader_env(
    tmp_path: Path,
    annotations: ProjectAnnotations,
    s3_data: dict[str, bytes],
    prefix: str = "images",
) -> tuple[ImageDownloader, _FakeSdkClient]:
    """Build an ImageDownloader + fake SDK for testing."""
    task_ids = set()
    for record in annotations.annotations:
        task_ids.add(record.task_id)

    cloud_storage = _FakeCloudStorage(
        cs_id=1,
        resource="test-bucket",
        specific_attributes=f"prefix={prefix}&endpoint_url=http://minio:9000",
    )
    task_storages: dict[int, dict[str, Any] | None] = {
        tid: {"cloud_storage_id": 1} for tid in task_ids
    }
    sdk = _FakeSdkClient(
        task_storages=task_storages,
        cloud_storages={1: cloud_storage},
        s3_objects=s3_data,
    )
    downloader = ImageDownloader(tmp_path / "images")
    return downloader, sdk


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
    assert _build_s3_key("data/images", "cat.jpg") == "data/images/cat.jpg"


def test_s3_key_without_prefix() -> None:
    assert _build_s3_key("", "cat.jpg") == "cat.jpg"


def test_s3_key_frame_already_has_prefix() -> None:
    assert _build_s3_key("data/images", "data/images/cat.jpg") == "data/images/cat.jpg"


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
    downloader, sdk = _make_downloader_env(tmp_path, annotations, s3_data)
    _patch_boto(monkeypatch, _make_s3_client(s3_data))

    stats = downloader.download(sdk, annotations)

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

    downloader, sdk = _make_downloader_env(tmp_path, annotations, s3_data)
    _patch_boto(monkeypatch, _make_s3_client(s3_data))

    stats = downloader.download(sdk, annotations)

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

    cloud_storage = _FakeCloudStorage(
        cs_id=1,
        resource="test-bucket",
        specific_attributes="prefix=images&endpoint_url=http://minio:9000",
    )
    task_storages: dict[int, dict[str, Any] | None] = {10: {"cloud_storage_id": 1}}
    sdk = _FakeSdkClient(
        task_storages=task_storages,
        cloud_storages={1: cloud_storage},
        s3_objects=s3_data,
    )
    _patch_boto(monkeypatch, _make_s3_client(s3_data))

    downloader = ImageDownloader(target)
    stats = downloader.download(sdk, annotations)

    assert stats.downloaded == 1
    assert target.exists()
    assert (target / "img.jpg").read_bytes() == b"data"


def test_download_empty_annotations(tmp_path: Path) -> None:
    annotations = ProjectAnnotations(
        annotations=[],
        deleted_images=[],
    )
    downloader = ImageDownloader(tmp_path / "images")
    stats = downloader.download(MagicMock(), annotations)
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
    downloader, sdk = _make_downloader_env(tmp_path, annotations, s3_data)
    _patch_boto(monkeypatch, _make_s3_client(s3_data))

    stats = downloader.download(sdk, annotations)

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
    downloader, sdk = _make_downloader_env(tmp_path, annotations, s3_data)
    _patch_boto(monkeypatch, _make_s3_client(s3_data))

    stats = downloader.download(sdk, annotations)

    assert stats.total == 3
    assert stats.cached == 1
    assert stats.downloaded == 2
    assert stats.failed == 0


def test_download_no_cloud_storage_marks_failed(tmp_path: Path) -> None:
    """When task has no source_storage, images are counted as failed."""
    annotations = ProjectAnnotations(
        annotations=[_ann(10, 0, "img.jpg")],
        deleted_images=[],
    )
    task_storages: dict[int, dict[str, Any] | None] = {10: None}
    sdk = _FakeSdkClient(
        task_storages=task_storages,
        cloud_storages={},
        s3_objects={},
    )
    downloader = ImageDownloader(tmp_path / "images")

    stats = downloader.download(sdk, annotations)

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
    task_storages: dict[int, dict[str, Any] | None] = {10: None}
    sdk = _FakeSdkClient(
        task_storages=task_storages,
        cloud_storages={},
        s3_objects={},
    )
    project_cs = CloudStorageInfo(
        id=1,
        bucket="test-bucket",
        prefix="proj/",
        endpoint_url="http://minio:9000",
    )
    # S3 keys under project prefix; get_object receives Key as S3 key
    s3_objects_by_key: dict[str, bytes] = {"proj/img.jpg": b"project-data"}

    def list_objects_v2(
        Bucket: str = "",  # noqa: N803, ARG001
        Prefix: str = "",  # noqa: N803
        **_kwargs: object,
    ) -> dict[str, Any]:
        contents = [
            {"Key": k, "Size": len(v)}
            for k, v in s3_objects_by_key.items()
            if k.startswith(Prefix)
        ]
        return {"Contents": contents, "IsTruncated": False}

    def get_object(Bucket: str = "", Key: str = "") -> dict[str, Any]:  # noqa: N803, ARG001
        if Key not in s3_objects_by_key:
            raise KeyError(f"NoSuchKey: {Key}")
        body = MagicMock()
        body.read.return_value = s3_objects_by_key[Key]
        return {"Body": body}

    fake_s3 = MagicMock()
    fake_s3.list_objects_v2.side_effect = list_objects_v2
    fake_s3.get_object.side_effect = get_object
    _patch_boto(monkeypatch, fake_s3)

    downloader = ImageDownloader(tmp_path / "images")
    stats = downloader.download(sdk, annotations, project_cloud_storage=project_cs)

    assert stats.total == 1
    assert stats.downloaded == 1
    assert stats.failed == 0
    assert (tmp_path / "images" / "img.jpg").read_bytes() == b"project-data"


# ======================================================================
# S3 sync tests
# ======================================================================


def _make_list_s3_client(
    objects: dict[str, bytes],
) -> MagicMock:
    """Build a mock S3 client that supports list_objects_v2 and get_object."""

    def list_objects_v2(
        Bucket: str = "",  # noqa: N803, ARG001
        Prefix: str = "",  # noqa: N803
        **_kwargs: object,
    ) -> dict[str, Any]:
        contents = []
        for key, data in objects.items():
            if key.startswith(Prefix):
                contents.append({"Key": key, "Size": len(data)})
        return {"Contents": contents, "IsTruncated": False}

    def get_object(Bucket: str = "", Key: str = "") -> dict[str, Any]:  # noqa: N803, ARG001
        if Key not in objects:
            msg = f"NoSuchKey: {Key}"
            raise KeyError(msg)
        body = MagicMock()
        body.read.return_value = objects[Key]
        return {"Body": body}

    mock = MagicMock()
    mock.list_objects_v2.side_effect = list_objects_v2
    mock.get_object.side_effect = get_object
    return mock


def _patch_boto_sync(
    monkeypatch: pytest.MonkeyPatch,
    fake_s3: MagicMock,
) -> None:
    """Patch boto3.Session to return the fake S3 client (for sync tests)."""
    monkeypatch.setattr(
        "cveta2.image_downloader.boto3.Session",
        lambda: MagicMock(client=lambda *_a, **_kw: fake_s3),
    )


# --- _list_s3_objects tests ---


def test_list_s3_objects_returns_keys_stripped_of_prefix() -> None:
    """_list_s3_objects strips the prefix from keys."""
    s3_objects = {
        "images/a.jpg": b"data-a",
        "images/b.jpg": b"data-b",
    }
    fake_s3 = _make_list_s3_client(s3_objects)
    result = _list_s3_objects(fake_s3, "test-bucket", "images")
    assert sorted(result) == [("images/a.jpg", "a.jpg"), ("images/b.jpg", "b.jpg")]


def test_list_s3_objects_no_prefix() -> None:
    """_list_s3_objects with empty prefix returns keys as-is."""
    s3_objects = {
        "cat.jpg": b"cat",
        "dog.jpg": b"dog",
    }
    fake_s3 = _make_list_s3_client(s3_objects)
    result = _list_s3_objects(fake_s3, "bucket", "")
    assert sorted(result) == [("cat.jpg", "cat.jpg"), ("dog.jpg", "dog.jpg")]


def test_list_s3_objects_empty_bucket() -> None:
    """_list_s3_objects returns empty list for empty bucket."""
    fake_s3 = _make_list_s3_client({})
    result = _list_s3_objects(fake_s3, "bucket", "prefix")
    assert result == []


def test_list_s3_objects_skips_prefix_marker() -> None:
    """_list_s3_objects skips the prefix directory marker (empty name after strip)."""
    s3_objects = {
        "images/": b"",  # directory marker
        "images/a.jpg": b"data",
    }
    fake_s3 = _make_list_s3_client(s3_objects)
    result = _list_s3_objects(fake_s3, "bucket", "images/")
    assert result == [("images/a.jpg", "a.jpg")]


# --- S3Syncer tests ---


def test_s3_syncer_downloads_all_objects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S3Syncer downloads all objects from the prefix."""
    s3_objects = {
        "images/a.jpg": b"data-a",
        "images/b.jpg": b"data-b",
        "images/c.png": b"data-c",
    }
    fake_s3 = _make_list_s3_client(s3_objects)
    _patch_boto_sync(monkeypatch, fake_s3)

    cs_info = CloudStorageInfo(
        id=1,
        bucket="test-bucket",
        prefix="images",
        endpoint_url="http://minio:9000",
    )
    target = tmp_path / "sync-dir"
    syncer = S3Syncer(target)
    stats = syncer.sync(cs_info)

    assert stats.total == 3
    assert stats.downloaded == 3
    assert stats.cached == 0
    assert stats.failed == 0
    assert (target / "a.jpg").read_bytes() == b"data-a"
    assert (target / "b.jpg").read_bytes() == b"data-b"
    assert (target / "c.png").read_bytes() == b"data-c"


def test_s3_syncer_skips_already_cached(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S3Syncer skips files that already exist locally."""
    s3_objects = {
        "images/a.jpg": b"data-a",
        "images/b.jpg": b"data-b",
    }
    target = tmp_path / "sync-dir"
    target.mkdir(parents=True)
    (target / "a.jpg").write_bytes(b"old-data-a")

    fake_s3 = _make_list_s3_client(s3_objects)
    _patch_boto_sync(monkeypatch, fake_s3)

    cs_info = CloudStorageInfo(
        id=1,
        bucket="test-bucket",
        prefix="images",
        endpoint_url="http://minio:9000",
    )
    syncer = S3Syncer(target)
    stats = syncer.sync(cs_info)

    assert stats.total == 2
    assert stats.cached == 1
    assert stats.downloaded == 1
    assert stats.failed == 0
    # Cached file should NOT be overwritten
    assert (target / "a.jpg").read_bytes() == b"old-data-a"
    assert (target / "b.jpg").read_bytes() == b"data-b"


def test_s3_syncer_all_cached(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S3Syncer reports all cached when everything is already local."""
    s3_objects = {
        "images/a.jpg": b"data-a",
    }
    target = tmp_path / "sync-dir"
    target.mkdir(parents=True)
    (target / "a.jpg").write_bytes(b"existing")

    fake_s3 = _make_list_s3_client(s3_objects)
    _patch_boto_sync(monkeypatch, fake_s3)

    cs_info = CloudStorageInfo(
        id=1,
        bucket="test-bucket",
        prefix="images",
        endpoint_url="http://minio:9000",
    )
    syncer = S3Syncer(target)
    stats = syncer.sync(cs_info)

    assert stats.total == 1
    assert stats.cached == 1
    assert stats.downloaded == 0


def test_s3_syncer_empty_bucket(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S3Syncer handles empty bucket gracefully."""
    fake_s3 = _make_list_s3_client({})
    _patch_boto_sync(monkeypatch, fake_s3)

    cs_info = CloudStorageInfo(
        id=1,
        bucket="test-bucket",
        prefix="images",
        endpoint_url="http://minio:9000",
    )
    syncer = S3Syncer(tmp_path / "sync-dir")
    stats = syncer.sync(cs_info)

    assert stats.total == 0
    assert stats.downloaded == 0


def test_s3_syncer_creates_target_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S3Syncer creates the target directory if it doesn't exist."""
    s3_objects = {"prefix/img.jpg": b"data"}
    fake_s3 = _make_list_s3_client(s3_objects)
    _patch_boto_sync(monkeypatch, fake_s3)

    cs_info = CloudStorageInfo(
        id=1,
        bucket="bucket",
        prefix="prefix",
        endpoint_url="http://s3:9000",
    )
    target = tmp_path / "deep" / "nested" / "dir"
    syncer = S3Syncer(target)
    stats = syncer.sync(cs_info)

    assert stats.downloaded == 1
    assert target.exists()
    assert (target / "img.jpg").read_bytes() == b"data"


def test_s3_syncer_never_deletes_local_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S3Syncer never deletes files that exist locally but not in S3."""
    s3_objects = {"images/a.jpg": b"data-a"}
    target = tmp_path / "sync-dir"
    target.mkdir(parents=True)
    (target / "a.jpg").write_bytes(b"existing-a")
    (target / "local-only.jpg").write_bytes(b"local-data")

    fake_s3 = _make_list_s3_client(s3_objects)
    _patch_boto_sync(monkeypatch, fake_s3)

    cs_info = CloudStorageInfo(
        id=1,
        bucket="test-bucket",
        prefix="images",
        endpoint_url="http://minio:9000",
    )
    syncer = S3Syncer(target)
    syncer.sync(cs_info)

    # Local-only file must still exist
    assert (target / "local-only.jpg").read_bytes() == b"local-data"
    assert (target / "a.jpg").read_bytes() == b"existing-a"
