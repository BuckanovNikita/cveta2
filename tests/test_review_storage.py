"""Regressions for reviewed storage failure boundaries."""

from pathlib import Path
from unittest.mock import Mock

import pytest
from boto3.exceptions import S3UploadFailedError

from cveta2.config import cache_dir_for_project
from cveta2.exceptions import Cveta2Error
from cveta2.image_downloader import CloudStorageInfo, S3Syncer
from cveta2.s3_utils import run_s3_transfers
from cveta2.task_cache import TaskAnnotationCache


def test_upload_wrapper_accounted_and_peer_finishes() -> None:
    seen = []

    def transfer(name: str) -> None:
        seen.append(name)
        if name == "bad":
            raise S3UploadFailedError("AccessDenied")

    assert run_s3_transfers(
        ["bad", "good"], transfer, str, desc="test", unit="file"
    ) == (1, 1)
    assert sorted(seen) == ["bad", "good"]


def test_invalid_local_cache_cannot_unlink_is_miss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cveta2.models import TaskInfo

    task = TaskInfo(
        id=1, name="task", status="completed", updated_date="today", subset=""
    )
    (tmp_path / "task_1.json").write_text("broken")
    monkeypatch.setattr(Path, "unlink", Mock(side_effect=PermissionError("readonly")))
    assert TaskAnnotationCache(tmp_path).get(task) is None


@pytest.mark.parametrize("key", ["root//a.jpg", "root/./a.jpg", "root/../a.jpg"])
def test_sync_preflight_rejects_before_any_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, key: str
) -> None:
    monkeypatch.setattr("cveta2.image_downloader.make_s3_client", Mock())
    monkeypatch.setattr(
        "cveta2.image_downloader.list_s3_objects",
        lambda *_args: [("root/good.jpg", "good.jpg"), (key, key)],
    )
    with pytest.raises(Cveta2Error):
        S3Syncer(tmp_path).sync(
            CloudStorageInfo(id=1, bucket="bucket", prefix="root", endpoint_url="")
        )
    assert list(tmp_path.iterdir()) == []


def test_directory_not_cached_or_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = tmp_path / "a.jpg"
    directory.mkdir()
    client = Mock()
    client.get_object.return_value = {"Body": Mock(read=lambda: b"image")}
    monkeypatch.setattr("cveta2.image_downloader.make_s3_client", lambda *_args: client)
    monkeypatch.setattr(
        "cveta2.image_downloader.list_s3_objects",
        lambda *_args: [("root/a.jpg", "a.jpg")],
    )
    stats = S3Syncer(tmp_path).sync(
        CloudStorageInfo(id=1, bucket="bucket", prefix="root", endpoint_url="")
    )
    assert (stats.cached, stats.failed, stats.downloaded) == (0, 1, 0)
    assert directory.is_dir()


@pytest.mark.parametrize(
    "name", ["", ".", "..", "/", "\\", "../escape", "a/b", "a\\b", "\x00"]
)
def test_project_cache_name_contained(tmp_path: Path, name: str) -> None:
    dest = cache_dir_for_project(tmp_path, name)
    assert dest.resolve().is_relative_to(tmp_path.resolve())
    assert dest != tmp_path
    assert len(dest.relative_to(tmp_path).parts) == 1


def test_real_boto3_upload_wrapper_is_accounted(tmp_path: Path) -> None:
    """Exercise boto3's actual upload_file conversion of ClientError."""
    import boto3
    from botocore.stub import Stubber

    client = boto3.client(
        "s3",
        aws_access_key_id="test",
        aws_secret_access_key="test",
        region_name="us-east-1",
    )
    path = tmp_path / "image.jpg"
    path.write_bytes(b"image")
    with Stubber(client) as stubber:
        stubber.add_client_error("put_object", service_error_code="AccessDenied")
        assert run_s3_transfers(
            [path],
            lambda item: client.upload_file(str(item), "bucket", "image.jpg"),
            str,
            desc="test",
            unit="file",
        ) == (0, 1)


def test_nonroot_corrupt_readonly_cache_falls_back(tmp_path: Path) -> None:
    """Use real directory permissions rather than mocking unlink."""
    import os

    if os.geteuid() == 0:
        pytest.skip("Requires a non-root process to enforce POSIX permissions")
    from cveta2.models import TaskInfo

    directory = tmp_path / "readonly"
    directory.mkdir()
    path = directory / "task_1.json"
    path.write_text("broken")
    directory.chmod(0o555)
    try:
        task = TaskInfo(
            id=1, name="task", status="completed", updated_date="today", subset=""
        )
        assert TaskAnnotationCache(directory).get(task) is None
        assert path.read_text() == "broken"
    finally:
        directory.chmod(0o755)


@pytest.mark.parametrize("workers", [1, 4])
def test_sync_alias_collision_preflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, workers: int
) -> None:
    from cveta2._concurrency import configure_workers

    configure_workers(s3=workers, cvat=1)
    (tmp_path / "alias").symlink_to(tmp_path, target_is_directory=True)
    monkeypatch.setattr("cveta2.image_downloader.make_s3_client", Mock())
    monkeypatch.setattr(
        "cveta2.image_downloader.list_s3_objects",
        lambda *_args: [("root/a.jpg", "a.jpg"), ("root/alias/a.jpg", "alias/a.jpg")],
    )
    with pytest.raises(Cveta2Error, match="одно назначение"):
        S3Syncer(tmp_path).sync(
            CloudStorageInfo(id=1, bucket="bucket", prefix="root", endpoint_url="")
        )
    assert not (tmp_path / "a.jpg").exists()


def test_cache_name_encoding_distinct(tmp_path: Path) -> None:
    names = ["", ".", "..", "%empty", "%2E", "a/b", "a_b", "a\\b", "Проект"]
    paths = [cache_dir_for_project(tmp_path, name) for name in names]
    assert len(set(paths)) == len(names)
    assert paths[-1].name == "Проект"


def test_image_downloader_directory_is_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cveta2.image_downloader import ImageDownloader
    from cveta2.models import ProjectAnnotations
    from tests.fixtures.fake_s3 import FakeS3Client
    from tests.helpers import make_bbox, make_cs_info

    dest = tmp_path / "a.jpg"
    dest.mkdir()
    client = FakeS3Client({"root/a.jpg": b"image"})
    monkeypatch.setattr("cveta2.image_downloader.make_s3_client", lambda *_args: client)
    annotations = ProjectAnnotations(
        annotations=[make_bbox(image_name="a.jpg")], deleted_images=[]
    )
    stats = ImageDownloader(tmp_path).download(annotations, make_cs_info(prefix="root"))
    assert (stats.cached, stats.failed, stats.total) == (0, 1, 1)
    assert dest.is_dir()


@pytest.mark.parametrize(
    ("project_name", "component"),
    [("%", "%25"), ("", "%empty"), (".", "%2E"), ("..", "%2E%2E")],
)
def test_cache_canonical_component_reuses_persisted_file(
    tmp_path: Path, project_name: str, component: str
) -> None:
    """Stable encoding is a persistent cache identity, not display formatting."""
    directory = tmp_path / component
    directory.mkdir()
    (directory / "image.jpg").write_bytes(b"existing cache")
    assert (
        cache_dir_for_project(tmp_path, project_name) / "image.jpg"
    ).read_bytes() == b"existing cache"


def test_missing_cache_invalidation_does_not_warn(
    tmp_path: Path, capture_logs: list[str]
) -> None:
    TaskAnnotationCache(tmp_path).invalidate_local(99)
    assert capture_logs == []


def test_cache_component_rejects_escaping_existing_symlink(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "project").symlink_to(outside, target_is_directory=True)
    with pytest.raises(Cveta2Error):
        cache_dir_for_project(root, "project")
    assert list(outside.iterdir()) == []


def test_sync_ancestor_destination_collision_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("cveta2.image_downloader.make_s3_client", Mock())
    monkeypatch.setattr(
        "cveta2.image_downloader.list_s3_objects",
        lambda *_args: [("root/a", "a"), ("root/a/b.jpg", "a/b.jpg")],
    )
    with pytest.raises(Cveta2Error):
        S3Syncer(tmp_path).sync(
            CloudStorageInfo(id=1, bucket="bucket", prefix="root", endpoint_url="")
        )
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("workers", [1, 4])
def test_public_download_preserves_path_rejection_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, workers: int
) -> None:
    from cveta2._concurrency import configure_workers
    from cveta2.image_downloader import ImageDownloader
    from cveta2.models import ProjectAnnotations
    from tests.fixtures.fake_s3 import FakeS3Client
    from tests.helpers import make_bbox, make_cs_info

    configure_workers(s3=workers, cvat=1)
    client = FakeS3Client({}, keyed_by_bucket=False)
    monkeypatch.setattr("cveta2.image_downloader.make_s3_client", lambda *_args: client)
    annotations = ProjectAnnotations(
        annotations=[make_bbox(image_name="escape.jpg", frame_path="../escape.jpg")],
        deleted_images=[],
    )
    destination = tmp_path / "cache"
    with pytest.raises(Cveta2Error):
        ImageDownloader(destination).download(
            annotations, make_cs_info(prefix="images")
        )
    assert not destination.exists()
    assert client.get_calls == []
    assert client.head_calls == []


@pytest.mark.parametrize("prefix", ["rootX", "Xroot"])
def test_public_download_x_prefix_accepts_rooted_frame_and_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, prefix: str
) -> None:
    from cveta2.image_downloader import ImageDownloader
    from cveta2.models import ProjectAnnotations
    from tests.fixtures.fake_s3 import FakeS3Client
    from tests.helpers import make_bbox, make_cs_info

    client = FakeS3Client({f"{prefix}/a.jpg": b"valid image"}, keyed_by_bucket=False)
    monkeypatch.setattr("cveta2.image_downloader.make_s3_client", lambda *_args: client)
    annotations = ProjectAnnotations(
        annotations=[make_bbox(image_name="a.jpg", frame_path=f"/{prefix}/a.jpg")],
        deleted_images=[],
    )
    downloader = ImageDownloader(tmp_path)
    storage = make_cs_info(prefix=prefix)
    first = downloader.download(annotations, storage)
    assert (first.downloaded, first.cached, first.failed) == (1, 0, 0)
    assert (tmp_path / "a.jpg").read_bytes() == b"valid image"
    assert client.get_calls == [f"{prefix}/a.jpg"]
    second = downloader.download(annotations, storage)
    assert (second.downloaded, second.cached, second.failed) == (0, 1, 0)
    assert client.get_calls == [f"{prefix}/a.jpg"]


def test_public_download_prefix_ending_x_rejects_outside_cached_frame(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cveta2.image_downloader import ImageDownloader
    from cveta2.models import ProjectAnnotations
    from tests.fixtures.fake_s3 import FakeS3Client
    from tests.helpers import make_bbox, make_cs_info

    client = FakeS3Client({"root": b"outside object"}, keyed_by_bucket=False)
    monkeypatch.setattr("cveta2.image_downloader.make_s3_client", lambda *_args: client)
    cached = tmp_path / "root"
    cached.write_bytes(b"outside cached object")
    annotations = ProjectAnnotations(
        annotations=[make_bbox(image_name="root", frame_path="/root")],
        deleted_images=[],
    )
    with pytest.raises(Cveta2Error):
        ImageDownloader(tmp_path).download(annotations, make_cs_info(prefix="rootX"))
    assert cached.read_bytes() == b"outside cached object"
    assert client.get_calls == []
    assert client.head_calls == []


def test_public_download_cached_rooted_frame_needs_no_storage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only pending images require storage; rooted cache names still resolve."""
    from cveta2.image_downloader import ImageDownloader
    from cveta2.models import ProjectAnnotations
    from tests.helpers import make_bbox

    destination = tmp_path / "nested" / "a.jpg"
    destination.parent.mkdir()
    destination.write_bytes(b"cached image")
    factory = Mock(
        side_effect=AssertionError("A complete cache hit needs no S3 client")
    )
    monkeypatch.setattr("cveta2.image_downloader.make_s3_client", factory)
    annotations = ProjectAnnotations(
        annotations=[make_bbox(image_name="a.jpg", frame_path="/nested/a.jpg")],
        deleted_images=[],
    )
    stats = ImageDownloader(tmp_path).download(annotations)
    assert (stats.cached, stats.downloaded, stats.failed, stats.total) == (1, 0, 0, 1)
    assert destination.read_bytes() == b"cached image"
    factory.assert_not_called()
