"""Tests for image_downloader module with fake S3 and SDK stubs."""

from __future__ import annotations

import errno
import os
import stat
from typing import TYPE_CHECKING, Any, NamedTuple

import pytest

from cveta2.adapters.cvat.storage import parse_cloud_storage
from cveta2.adapters.s3.download import ImageDownloader, S3Syncer
from cveta2.domain.errors import Cveta2Error
from cveta2.domain.models import (
    DeletedImage,
    ImageWithoutAnnotations,
    ProjectAnnotations,
)
from cveta2.domain.paths import (
    _canonical_frame_key,
    _local_name_from_key,
    _validate_relative_key,
    parse_sync_root,
)
from tests.fixtures.fake_s3 import FakeS3Client
from tests.helpers import make_bbox, make_cs_info, patch_recording_s3

if TYPE_CHECKING:
    from pathlib import Path

    from cveta2.domain.storage import CloudStorageInfo


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
        "cveta2.adapters.s3.download.make_s3_client",
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


def _project(*records: Any) -> ProjectAnnotations:
    return ProjectAnnotations(annotations=list(records), deleted_images=[])


@pytest.mark.parametrize(
    ("storage", "expected"),
    [
        pytest.param(
            _FakeCloudStorage(
                5, "my-bucket", "prefix=data/images&endpoint_url=http://minio:9000"
            ),
            (5, "my-bucket", "data/images", "http://minio:9000"),
            id="full",
        ),
        pytest.param(
            _FakeCloudStorage(1, "bucket", "endpoint_url=http://s3.example.com"),
            (1, "bucket", "", "http://s3.example.com"),
            id="no-prefix",
        ),
        pytest.param(
            _FakeCloudStorage(3, "bucket", "prefix=imgs"),
            (3, "bucket", "imgs", ""),
            id="no-endpoint-url",
        ),
        # An older SDK object may expose none of the attributes.
        pytest.param(_BareCloudStorage(), (0, "", "", ""), id="missing-attributes"),
    ],
)
def test_parse_cloud_storage(
    storage: object, expected: tuple[int, str, str, str]
) -> None:
    info = parse_cloud_storage(storage)
    assert (info.id, info.bucket, info.prefix, info.endpoint_url) == expected


def test_download_creates_a_group_writable_cache_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    annotations = _project(_ann(10, 0, "a.jpg"))
    _patch_boto(monkeypatch, FakeS3Client({"test-bucket/images/a.jpg": b"data-a"}))
    target = tmp_path / "deep" / "nested" / "dir"

    old_umask = os.umask(0o077)
    try:
        stats = ImageDownloader(target).download(
            annotations, project_cloud_storage=_project_cs()
        )
    finally:
        os.umask(old_umask)

    assert stats.downloaded == 1
    assert (target / "a.jpg").read_bytes() == b"data-a"
    assert stat.S_IMODE(target.stat().st_mode) == 0o775
    assert stat.S_IMODE((target / "a.jpg").stat().st_mode) == 0o664


def test_download_empty_annotations(tmp_path: Path) -> None:
    annotations = _project()
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
    downloader = ImageDownloader(tmp_path / "images")
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
    """A mixed run counts every image once; a cached file is never rewritten."""
    annotations = _project(
        _ann(10, 0, "new.jpg"),
        _ann(10, 1, "cached.jpg"),
        _img_no_ann(10, 2, "also-new.jpg"),
    )
    target = tmp_path / "images"
    target.mkdir(parents=True)
    (target / "cached.jpg").write_bytes(b"existing")

    s3_data = {
        "test-bucket/images/new.jpg": b"data-new",
        "test-bucket/images/also-new.jpg": b"data-also-new",
    }
    downloader = ImageDownloader(tmp_path / "images")
    _patch_boto(monkeypatch, FakeS3Client(s3_data))

    stats = downloader.download(annotations, project_cloud_storage=_project_cs())

    assert stats.total == 3
    assert stats.cached == 1
    assert stats.downloaded == 2
    assert stats.failed == 0
    assert (target / "cached.jpg").read_bytes() == b"existing"
    assert (target / "also-new.jpg").read_bytes() == b"data-also-new"


def test_download_no_cloud_storage_marks_failed(tmp_path: Path) -> None:
    """When project_cloud_storage is not provided, all pending images are failed."""
    annotations = _project(_ann(10, 0, "img.jpg"))
    downloader = ImageDownloader(tmp_path / "images")

    stats = downloader.download(annotations)

    assert stats.total == 1
    assert stats.failed == 1
    assert stats.downloaded == 0


def test_download_fallback_project_storage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A storage prefix with a trailing slash still yields the right key."""
    annotations = _project(_ann(10, 0, "img.jpg"))
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
    annotations = _project(_ann(10, 0, "a.jpg"))
    s3_data = {"test-bucket/images/a.jpg": b"full-data"}
    downloader = ImageDownloader(tmp_path / "images")
    _patch_boto(monkeypatch, FakeS3Client(s3_data))
    target = tmp_path / "images"

    with monkeypatch.context() as patched:
        patched.setattr(
            "cveta2.adapters.files.shared.write_shared_bytes", _raise_no_space
        )
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


# ======================================================================
# S3 sync tests
# ======================================================================


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
    target = tmp_path / "deep" / "sync-dir"
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
    annotations = _project(_ann(10, 0, "2026-01/a.jpg"), _ann(10, 1, "b.jpg"))
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
    annotations = _project(
        make_bbox(image_name="one.jpg", frame_path="2026-01/one.jpg", task_id=10),
        make_bbox(image_name="two.jpg", frame_path="stale/two.jpg", task_id=10),
    )
    _patch_boto(monkeypatch, FakeS3Client(s3_data))

    target = tmp_path / "images"
    stats = ImageDownloader(target).download(
        annotations, project_cloud_storage=_project_cs()
    )

    assert stats.downloaded == 2
    assert stats.failed == 0
    assert (target / "2026-01" / "one.jpg").read_bytes() == b"nested-one"
    assert (target / "2026-02" / "two.jpg").read_bytes() == b"wanted-two"

    # Nested frames mirror the S3 layout and are cache hits on a rerun.
    rerun = ImageDownloader(target).download(
        annotations, project_cloud_storage=_project_cs()
    )
    assert (rerun.cached, rerun.downloaded) == (2, 0)


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
    factory = patch_recording_s3(monkeypatch, "cveta2.adapters.s3.download", client)
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


def test_absolute_frame_path_is_made_relative_to_storage_root(tmp_path: Path) -> None:
    downloader = ImageDownloader(tmp_path / "cache")

    destination = downloader._dest_path(
        "/images/nested/a.jpg", make_cs_info(prefix="images")
    )

    assert destination == tmp_path / "cache" / "nested" / "a.jpg"


@pytest.mark.parametrize(
    ("prefix", "frame_ref", "expected"),
    [
        ("images/", "/images/nested/a.jpg", "images/nested/a.jpg"),
        ("images/", "/images", "images"),
        ("", "/nested/a.jpg", "nested/a.jpg"),
        ("images", "nested/a.jpg", "images/nested/a.jpg"),
    ],
)
def test_frame_keys_are_canonical(prefix: str, frame_ref: str, expected: str) -> None:
    assert _canonical_frame_key(prefix, frame_ref) == expected


@pytest.mark.parametrize("value", ["", ".", "..", "a//b", "a/./b", "a/../b"])
def test_relative_key_rejects_empty_and_dot_segments(value: str) -> None:
    with pytest.raises(Cveta2Error):
        _validate_relative_key(value, original=value)


def test_relative_key_and_local_name_preserve_nested_segments() -> None:
    assert _validate_relative_key("a/b.jpg", original="a/b.jpg") == "a/b.jpg"
    assert (
        _local_name_from_key("images/a/b.jpg", "images/", original="a/b.jpg")
        == "a/b.jpg"
    )


def test_storage_name_map_forwards_bucket_and_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[object, str, str]] = []
    client = FakeS3Client({}, keyed_by_bucket=False)

    def record_listing(
        received_client: object, bucket: str, prefix: str
    ) -> list[tuple[str, str]]:
        calls.append((received_client, bucket, prefix))
        return [("images/a.jpg", "a.jpg")]

    monkeypatch.setattr("cveta2.adapters.s3.download.list_s3_objects", record_listing)

    result = ImageDownloader(tmp_path)._build_project_storage_name_map(
        client, "bucket", "images"
    )

    assert calls == [(client, "bucket", "images")]
    assert result["a.jpg"] == "images/a.jpg"


def test_listing_fallback_still_validates_absolute_frame_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    downloader = ImageDownloader(tmp_path)
    storage = make_cs_info(prefix="images")
    listed_prefixes: list[str] = []

    def storage_map(_client: object, _bucket: str, prefix: str) -> dict[str, str]:
        listed_prefixes.append(prefix)
        return {"a.jpg": "images/a.jpg"}

    monkeypatch.setattr(downloader, "_build_project_storage_name_map", storage_map)

    with pytest.raises(Cveta2Error, match="вне"):
        downloader._resolve_s3_keys(
            FakeS3Client({}), storage, {"a.jpg": "/outside/a.jpg"}
        )
    assert listed_prefixes == ["images"]


@pytest.mark.parametrize("frame_ref", ["/outside/a.jpg", "../escape.jpg"])
def test_frame_path_cannot_escape_storage_root(tmp_path: Path, frame_ref: str) -> None:
    downloader = ImageDownloader(tmp_path / "cache")

    with pytest.raises(Cveta2Error, match=r"путь|корня"):
        downloader._dest_path(frame_ref, make_cs_info(prefix="images"))


def test_frame_path_cannot_escape_through_cache_symlink(tmp_path: Path) -> None:
    target = tmp_path / "cache"
    target.mkdir()
    (target / "linked").symlink_to(tmp_path)

    with pytest.raises(Cveta2Error, match="вне локального кэша"):
        ImageDownloader(target)._dest_path(
            "linked/escape.jpg", make_cs_info(prefix="images")
        )


def test_s3_sync_rejects_traversal_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_boto(
        monkeypatch,
        FakeS3Client({"images/../../escape.jpg": b"bad"}, keyed_by_bucket=False),
    )

    with pytest.raises(Cveta2Error, match="Небезопасный путь"):
        S3Syncer(tmp_path / "cache").sync(make_cs_info(prefix="images"))

    assert not (tmp_path / "escape.jpg").exists()


# ---------------------------------------------------------------------------
# S3 key resolution: download the expected key before walking the whole prefix
# ---------------------------------------------------------------------------


def test_expected_keys_skip_the_whole_prefix_listing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Images sitting at their expected key are found without a listing.

    The prefix holds every task's images, so listing it to place a couple
    of them is what made a one-task fetch cost as much as a whole-project
    one.  The key CVAT's frame name implies is checked first instead, over
    the storage's own endpoint.
    """
    annotations = _project(_ann(10, 0, "a.jpg"), _ann(10, 1, "b.jpg"))
    fake_s3 = FakeS3Client(
        {
            "test-bucket/images/a.jpg": b"data-a",
            "test-bucket/images/b.jpg": b"data-b",
            "test-bucket/images/someone-elses.jpg": b"data-other",
        }
    )
    factory = patch_recording_s3(monkeypatch, "cveta2.adapters.s3.download", fake_s3)

    target = tmp_path / "images"
    stats = ImageDownloader(target).download(
        annotations, project_cloud_storage=_project_cs()
    )

    assert factory.endpoints == [_project_cs().endpoint_url]
    assert (stats.total, stats.downloaded, stats.cached) == (2, 2, 0)
    assert sorted(f.name for f in target.iterdir()) == ["a.jpg", "b.jpg"]
    assert [record.s3_image_path for record in annotations.annotations] == [
        "images/a.jpg",
        "images/b.jpg",
    ]
    assert fake_s3.list_requests == []
    assert fake_s3.head_calls == []
    assert fake_s3.get_calls == [
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

    Only the listing carries the basename fallback, so a GET that comes
    back empty must hand the name over to it rather than report the image
    as missing from S3.  The listing stays scoped to the project prefix:
    the decoy sorts before the real key, so a listing widened to the whole
    bucket would claim the basename first and hand back the wrong bytes.
    """
    annotations = _project(_ann(10, 0, "flat.jpg"), _ann(10, 1, "nested.jpg"))
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
    assert (target / "2026-02" / "nested.jpg").read_bytes() == b"data-nested"


@pytest.mark.parametrize(
    ("limit", "lists"),
    [
        pytest.param(2, False, id="at-limit-probes"),
        pytest.param(1, True, id="past-limit-lists"),
    ],
)
def test_the_probe_limit_is_inclusive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    limit: int,
    lists: bool,
) -> None:
    """A batch exactly at the limit downloads directly; one past it lists."""
    fake_s3 = FakeS3Client(
        {
            "test-bucket/images/a.jpg": b"data-a",
            "test-bucket/images/b.jpg": b"data-b",
        }
    )
    _patch_boto(monkeypatch, fake_s3)
    monkeypatch.setattr("cveta2.adapters.s3.download._DIRECT_KEY_PROBE_LIMIT", limit)

    stats = ImageDownloader(tmp_path / "images").download(
        _project(_ann(10, 0, "a.jpg"), _ann(10, 1, "b.jpg")),
        project_cloud_storage=_project_cs(),
    )

    assert stats.downloaded == 2
    assert fake_s3.head_calls == []
    assert bool(fake_s3.list_requests) is lists
    if not lists:
        assert len(fake_s3.get_calls) == 2


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
    monkeypatch.setattr("cveta2.adapters.s3.download._DIRECT_KEY_PROBE_LIMIT", 0)

    target = tmp_path / "images"
    stats = ImageDownloader(target).download(
        _project(annotation),
        project_cloud_storage=_project_cs(),
    )

    assert stats.downloaded == 1
    assert fake_s3.head_calls == []
    assert (target / "2026-02" / "x.jpg").read_bytes() == b"data-february"


def test_nested_cache_hits_need_no_s3_requests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Storage-aware cache lookup must work while S3 is unavailable."""
    target = tmp_path / "images"
    cached = target / "project" / "nested" / "a.jpg"
    cached.parent.mkdir(parents=True)
    cached.write_bytes(b"cached")
    storage = make_cs_info(bucket="test-bucket", prefix="data/project")
    annotations = _project(_ann(10, 0, "nested/a.jpg"))
    fake_s3 = FakeS3Client({"test-bucket/data/project/nested/a.jpg": b"remote"})
    _patch_boto(monkeypatch, fake_s3)

    stats = ImageDownloader(target, ignored_prefix="data").download(
        annotations, project_cloud_storage=storage
    )

    assert stats.cached == stats.total == 1
    assert stats.downloaded == stats.failed == 0
    assert not fake_s3.head_calls
    assert not fake_s3.list_requests
    assert not fake_s3.get_calls
    assert cached.read_bytes() == b"cached"


def test_fallback_cache_hits_accumulate_and_do_not_stop_later_images(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A mixed batch counts both cache paths, downloads, and missing images."""
    target = tmp_path / "images"
    (target / "month").mkdir(parents=True)
    (target / "direct.jpg").write_bytes(b"direct-cache")
    (target / "month" / "a.jpg").write_bytes(b"cache-a")
    (target / "month" / "b.jpg").write_bytes(b"cache-b")
    names = ["direct.jpg", "a.jpg", "b.jpg", "new.jpg", "missing.jpg"]
    annotations = _project(*(_ann(10, index, name) for index, name in enumerate(names)))
    fake_s3 = FakeS3Client(
        {
            "test-bucket/images/month/a.jpg": b"remote-a",
            "test-bucket/images/month/b.jpg": b"remote-b",
            "test-bucket/images/new.jpg": b"new-image",
        }
    )
    _patch_boto(monkeypatch, fake_s3)

    stats = ImageDownloader(target).download(
        annotations, project_cloud_storage=_project_cs()
    )

    assert stats.total == 5
    assert stats.cached == 3
    assert stats.downloaded == stats.failed == 1
    assert fake_s3.get_calls == [
        "test-bucket/images/a.jpg",
        "test-bucket/images/b.jpg",
        "test-bucket/images/new.jpg",
        "test-bucket/images/missing.jpg",
    ]
    assert fake_s3.head_calls == []
    assert (target / "new.jpg").read_bytes() == b"new-image"
    assert (target / "month" / "a.jpg").read_bytes() == b"cache-a"
    assert (target / "month" / "b.jpg").read_bytes() == b"cache-b"


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
