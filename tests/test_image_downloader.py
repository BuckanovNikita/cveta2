"""Tests for image_downloader module with fake S3 and SDK stubs."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

from cveta2.image_downloader import (
    ImageDownloader,
    _build_s3_key,
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
    for ann in annotations.annotations:
        task_ids.add(ann.task_id)
    for img in annotations.images_without_annotations:
        task_ids.add(img.task_id)

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
        ],
        deleted_images=[],
        images_without_annotations=[
            _img_no_ann(10, 2, "also-new.jpg"),
        ],
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
