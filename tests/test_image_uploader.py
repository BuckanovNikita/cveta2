"""Tests for image_uploader module — server file mapping and image lookup."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, NamedTuple
from unittest.mock import MagicMock

import pytest

from cveta2.image_uploader import (
    S3Uploader,
    build_server_file_mapping,
    resolve_images,
)
from cveta2.s3_utils import build_s3_key
from tests.fixtures.fake_s3 import FakeS3Client
from tests.helpers import make_cs_info, patch_recording_s3

if TYPE_CHECKING:
    from pathlib import Path

    from cveta2.image_downloader import CloudStorageInfo

_MONTH_PREFIX_RE = re.compile(r"\d{4}-\d{2}/.+")

_FIXED_UTC_NOW = datetime(2026, 3, 1, 0, 30, tzinfo=timezone.utc)
_ONE_HOUR_WEST = timezone(timedelta(hours=-1))


class _FixedClock:
    """``datetime`` stand-in whose month depends on the requested timezone.

    ``now(tz=timezone.utc)`` lands in 2026-03 while any other timezone
    (including the naive ``tz=None`` a mutation produces) lands in
    2026-02, so the ``tz=`` argument becomes observable without freezing
    the real clock.
    """

    @staticmethod
    def now(tz: timezone | None = None) -> datetime:
        """Return the frozen instant, converted out of UTC unless asked for UTC."""
        if tz is timezone.utc:
            return _FIXED_UTC_NOW
        return _FIXED_UTC_NOW.astimezone(_ONE_HOUR_WEST)


class _UnwritableKeysS3Client(FakeS3Client):
    """Refuses ``upload_file`` for some keys, accepting everything else.

    ``KeyError`` is in ``s3_utils.S3_TRANSFER_ERRORS`` but not in the
    ``s3_retry`` set, so the failure is counted without paying the retry
    backoff.
    """

    def __init__(
        self,
        objects: dict[str, bytes] | None = None,
        *,
        unwritable: set[str],
    ) -> None:
        """Seed the store and mark *unwritable* keys as un-uploadable."""
        super().__init__(objects)
        self._unwritable = frozenset(unwritable)

    def upload_file(self, filename: str, bucket: str, key: str) -> None:
        """Store the file unless its key was marked unwritable."""
        if key in self._unwritable:
            raise KeyError(key)
        super().upload_file(filename, bucket, key)


def _make_cs_info() -> CloudStorageInfo:
    return make_cs_info(prefix="project/images")


def _mock_s3_client(objects: list[tuple[str, str]]) -> MagicMock:
    """Create a mock S3 client that returns *objects* from list_objects_v2.

    *objects* is a list of ``(key, name)`` pairs where *name* is the
    relative path under the prefix.
    """
    s3 = MagicMock()
    s3.list_objects_v2.return_value = {
        "Contents": [{"Key": key} for key, _ in objects],
        "IsTruncated": False,
    }
    return s3


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    return path


class TestResolveImages:
    """Tests for resolve_images() — direct and recursive lookup."""

    def test_flat_direct_match(self, tmp_path: Path) -> None:
        img = _touch(tmp_path / "a.jpg")
        found, missing = resolve_images(["a.jpg"], [tmp_path])
        assert found == {"a.jpg": img}
        assert missing == []

    def test_subpath_name_direct_match(self, tmp_path: Path) -> None:
        img = _touch(tmp_path / "sub" / "a.jpg")
        found, missing = resolve_images(["sub/a.jpg"], [tmp_path])
        assert found == {"sub/a.jpg": img}
        assert missing == []

    def test_recursive_basename_match_in_nested_subdir(self, tmp_path: Path) -> None:
        img = _touch(tmp_path / "deep" / "nested" / "a.jpg")
        found, missing = resolve_images(["a.jpg"], [tmp_path])
        assert found == {"a.jpg": img}
        assert missing == []

    def test_direct_match_wins_over_recursive_in_same_dir(self, tmp_path: Path) -> None:
        flat = _touch(tmp_path / "a.jpg")
        _touch(tmp_path / "nested" / "a.jpg")
        found, _ = resolve_images(["a.jpg"], [tmp_path])
        assert found["a.jpg"] == flat

    def test_earlier_search_dir_wins(self, tmp_path: Path) -> None:
        dir1 = tmp_path / "dir1"
        dir2 = tmp_path / "dir2"
        nested = _touch(dir1 / "sub" / "a.jpg")
        _touch(dir2 / "a.jpg")
        found, _ = resolve_images(["a.jpg"], [dir1, dir2])
        assert found["a.jpg"] == nested

    def test_duplicate_basenames_pick_lexicographic_max_and_warn(
        self, tmp_path: Path, capture_logs: list[str]
    ) -> None:
        """The warning must name the searched directory and the duplicate.

        Those two arguments of ``pick_latest_duplicate`` reach nothing but
        this message, so asserting only that *some* warning fired left the
        search directory and the file name free to be dropped.  The
        directory has to be matched together with the following word: the
        listed candidate paths all start with it, so a bare containment
        check passes even when the context argument is thrown away.
        """
        _touch(tmp_path / "2026-01" / "a.jpg")
        latest = _touch(tmp_path / "2026-02" / "a.jpg")
        found, _ = resolve_images(["a.jpg"], [tmp_path])
        assert found["a.jpg"] == latest
        warnings = [m for m in capture_logs if "Дубликаты" in m]
        assert len(warnings) == 1
        assert f"в {tmp_path} для 'a.jpg'" in warnings[0]

    def test_missing_names_sorted(self, tmp_path: Path) -> None:
        _, missing = resolve_images(["b.jpg", "a.jpg"], [tmp_path])
        assert missing == ["a.jpg", "b.jpg"]

    def test_nonexistent_search_dir_skipped(self, tmp_path: Path) -> None:
        img = _touch(tmp_path / "real" / "a.jpg")
        found, missing = resolve_images(
            ["a.jpg"], [tmp_path / "nope", tmp_path / "real"]
        )
        assert found == {"a.jpg": img}
        assert missing == []


class TestBuildServerFileMapping:
    """Tests for build_server_file_mapping()."""

    def test_existing_flat_image_keeps_path(self) -> None:
        cs_info = _make_cs_info()
        s3 = _mock_s3_client(
            [
                ("project/images/img1.jpg", "img1.jpg"),
                ("project/images/img2.jpg", "img2.jpg"),
            ]
        )

        mapping, existing_keys = build_server_file_mapping(
            cs_info,
            {"img1.jpg", "img2.jpg"},
            s3_client=s3,
        )

        assert mapping["img1.jpg"] == "img1.jpg"
        assert mapping["img2.jpg"] == "img2.jpg"
        assert existing_keys == {
            "project/images/img1.jpg",
            "project/images/img2.jpg",
        }

    def test_existing_subfolder_image_keeps_path(self) -> None:
        cs_info = _make_cs_info()
        s3 = _mock_s3_client(
            [
                ("project/images/2026-01/img1.jpg", "2026-01/img1.jpg"),
            ]
        )

        mapping, _ = build_server_file_mapping(
            cs_info,
            {"img1.jpg"},
            s3_client=s3,
        )

        assert mapping["img1.jpg"] == "2026-01/img1.jpg"

    def test_new_image_gets_month_prefix(self) -> None:
        cs_info = _make_cs_info()
        s3 = _mock_s3_client([])

        mapping, existing_keys = build_server_file_mapping(
            cs_info,
            {"new_img.jpg"},
            s3_client=s3,
        )

        assert _MONTH_PREFIX_RE.fullmatch(mapping["new_img.jpg"])
        assert mapping["new_img.jpg"].endswith("/new_img.jpg")
        assert existing_keys == set()

    def test_new_image_month_folder_is_the_utc_calendar_month(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The folder is the UTC *month*, not the local month nor the minute.

        The four-digits-dash-two-digits regex above matches ``%Y-%M``
        (minutes) just as happily as ``%Y-%m``, and with the real clock a
        naive ``datetime.now()`` agrees with UTC on this machine.  The
        frozen clock straddles a month boundary, so both mistakes change
        the answer.
        """
        monkeypatch.setattr("cveta2.image_uploader.datetime", _FixedClock)
        cs_info = _make_cs_info()

        mapping, _ = build_server_file_mapping(
            cs_info,
            {"new_img.jpg"},
            s3_client=_mock_s3_client([]),
        )

        assert mapping["new_img.jpg"] == "2026-03/new_img.jpg"

    def test_lists_own_bucket_over_the_storage_endpoint(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without an injected client, the storage's endpoint and bucket are used.

        Every other case passed ``s3_client=``, so the ``make_s3_client``
        branch never ran, and the mock listing ignored the bucket it was
        asked for.
        """
        cs_info = make_cs_info(
            bucket="own-bucket",
            prefix="project/images",
            endpoint_url="http://minio:9000",
        )
        client = FakeS3Client(
            {
                "own-bucket/project/images/mine.jpg": b"mine",
                "other-bucket/project/images/theirs.jpg": b"theirs",
            }
        )
        factory = patch_recording_s3(monkeypatch, "cveta2.image_uploader", client)

        mapping, existing_keys = build_server_file_mapping(
            cs_info, {"mine.jpg", "theirs.jpg"}
        )

        assert factory.endpoints == ["http://minio:9000"]
        assert existing_keys == {"project/images/mine.jpg"}
        assert mapping["mine.jpg"] == "mine.jpg"
        assert _MONTH_PREFIX_RE.fullmatch(mapping["theirs.jpg"])

    def test_mixed_existing_and_new(self) -> None:
        cs_info = _make_cs_info()
        s3 = _mock_s3_client(
            [
                ("project/images/old.jpg", "old.jpg"),
            ]
        )

        mapping, _ = build_server_file_mapping(
            cs_info,
            {"old.jpg", "brand_new.jpg"},
            s3_client=s3,
        )

        assert mapping["old.jpg"] == "old.jpg"
        assert _MONTH_PREFIX_RE.fullmatch(mapping["brand_new.jpg"])
        assert mapping["brand_new.jpg"].endswith("/brand_new.jpg")

    def test_duplicate_basenames_uses_latest(self, capture_logs: list[str]) -> None:
        """Latest month folder wins, and the warning names S3 and the file.

        The context and name handed to ``pick_latest_duplicate`` only ever
        reach this message, so nothing stopped them from being dropped.
        """
        cs_info = _make_cs_info()
        s3 = _mock_s3_client(
            [
                ("project/images/2026-01/img.jpg", "2026-01/img.jpg"),
                ("project/images/2026-02/img.jpg", "2026-02/img.jpg"),
            ]
        )

        mapping, _ = build_server_file_mapping(
            cs_info,
            {"img.jpg"},
            s3_client=s3,
        )

        # Lexicographic max = 2026-02
        assert mapping["img.jpg"] == "2026-02/img.jpg"
        warnings = [m for m in capture_logs if "Дубликаты" in m]
        assert len(warnings) == 1
        assert "S3" in warnings[0]
        assert "'img.jpg'" in warnings[0]

    def test_deep_nested_subfolder(self) -> None:
        cs_info = _make_cs_info()
        s3 = _mock_s3_client(
            [
                (
                    "project/images/subdir/another/img.jpg",
                    "subdir/another/img.jpg",
                ),
            ]
        )

        mapping, _ = build_server_file_mapping(
            cs_info,
            {"img.jpg"},
            s3_client=s3,
        )

        assert mapping["img.jpg"] == "subdir/another/img.jpg"
        assert (
            build_s3_key(cs_info.prefix, mapping["img.jpg"])
            == "project/images/subdir/another/img.jpg"
        )

    def test_mixed_depths_with_prefix(self) -> None:
        cs_info = _make_cs_info()
        s3 = _mock_s3_client(
            [
                ("project/images/flat.jpg", "flat.jpg"),
                ("project/images/2026-03/monthly.jpg", "2026-03/monthly.jpg"),
                ("project/images/a/b/c/deep.jpg", "a/b/c/deep.jpg"),
            ]
        )

        mapping, _ = build_server_file_mapping(
            cs_info,
            {"flat.jpg", "monthly.jpg", "deep.jpg"},
            s3_client=s3,
        )

        assert mapping["flat.jpg"] == "flat.jpg"
        assert mapping["monthly.jpg"] == "2026-03/monthly.jpg"
        assert mapping["deep.jpg"] == "a/b/c/deep.jpg"

        # All produce correct full S3 keys
        assert (
            build_s3_key(cs_info.prefix, mapping["flat.jpg"])
            == "project/images/flat.jpg"
        )
        assert (
            build_s3_key(cs_info.prefix, mapping["monthly.jpg"])
            == "project/images/2026-03/monthly.jpg"
        )
        assert (
            build_s3_key(cs_info.prefix, mapping["deep.jpg"])
            == "project/images/a/b/c/deep.jpg"
        )


def _upload_cs_info() -> CloudStorageInfo:
    return make_cs_info(
        bucket="upload-bucket",
        prefix="project/images",
        endpoint_url="http://minio:9000",
    )


class _ExistingKeysCase(NamedTuple):
    seeded: dict[str, bytes]
    existing_keys: set[str]
    expected_uploaded: int
    expected_skipped: int


_EXISTING_KEYS_CASES = [
    pytest.param(
        _ExistingKeysCase(
            {"upload-bucket/project/images/img.jpg": b"stale"}, set(), 1, 0
        ),
        id="empty-argument-beats-a-populated-bucket",
    ),
    pytest.param(
        _ExistingKeysCase({}, {"project/images/img.jpg"}, 0, 1),
        id="populated-argument-beats-an-empty-bucket",
    ),
]


class TestS3Uploader:
    """Tests for ``S3Uploader.upload``.

    The method was reachable only from ``tests/integration/``, which is
    skipped without a live CVAT: under unit tests not a single line of it
    ran.  :class:`FakeS3Client` implements both ``list_objects_v2`` and
    ``upload_file``, so the whole method works in memory.
    """

    def test_no_images_returns_zeroed_stats(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An empty batch short-circuits before any S3 client is built."""
        factory = patch_recording_s3(
            monkeypatch, "cveta2.image_uploader", FakeS3Client()
        )

        stats = S3Uploader().upload(_upload_cs_info(), {})

        assert stats.total == 0
        assert stats.uploaded == 0
        assert stats.skipped_existing == 0
        assert factory.endpoints == []

    def test_uploads_new_files_and_skips_existing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """New files land under prefix; ones already in the bucket are skipped.

        Without ``existing_keys`` the method lists the bucket itself, so
        this also pins the endpoint, the bucket and the prefix it lists.
        """
        client = FakeS3Client(
            {
                "upload-bucket/project/images/old.jpg": b"already-there",
                "upload-bucket/project/images/old2.jpg": b"already-there-too",
                "other-bucket/project/images/new.jpg": b"not-mine",
            }
        )
        factory = patch_recording_s3(monkeypatch, "cveta2.image_uploader", client)
        images = {
            "new.jpg": _touch(tmp_path / "new.jpg"),
            "old.jpg": _touch(tmp_path / "old.jpg"),
            "old2.jpg": _touch(tmp_path / "old2.jpg"),
        }

        stats = S3Uploader().upload(_upload_cs_info(), images)

        assert factory.endpoints == ["http://minio:9000"]
        assert stats.total == 3
        assert stats.uploaded == 1
        assert stats.skipped_existing == 2
        assert stats.failed == 0
        assert set(client.objects) == {
            "upload-bucket/project/images/old.jpg",
            "upload-bucket/project/images/old2.jpg",
            "upload-bucket/project/images/new.jpg",
            "other-bucket/project/images/new.jpg",
        }
        assert client.objects["upload-bucket/project/images/new.jpg"] == b"x"

    def test_server_file_mapping_decides_the_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A mapped name uses its server_file; an unmapped one uses the name.

        The mapping deliberately omits ``unmapped.jpg`` so the membership
        test in the conditional is load-bearing, not just the truthiness
        of the mapping itself.
        """
        client = FakeS3Client()
        patch_recording_s3(monkeypatch, "cveta2.image_uploader", client)
        images = {
            "mapped.jpg": _touch(tmp_path / "mapped.jpg"),
            "unmapped.jpg": _touch(tmp_path / "unmapped.jpg"),
        }

        stats = S3Uploader().upload(
            _upload_cs_info(),
            images,
            name_to_server_file={"mapped.jpg": "2026-01/mapped.jpg"},
            existing_keys=set(),
        )

        assert stats.uploaded == 2
        assert set(client.objects) == {
            "upload-bucket/project/images/2026-01/mapped.jpg",
            "upload-bucket/project/images/unmapped.jpg",
        }

    @pytest.mark.parametrize("case", _EXISTING_KEYS_CASES)
    def test_existing_keys_argument_replaces_the_listing(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        case: _ExistingKeysCase,
    ) -> None:
        """A supplied ``existing_keys`` is used *instead of* listing the bucket.

        Both cases make the argument disagree with the bucket, so a
        version that lists anyway — or ignores the argument — gets the
        opposite answer.
        """
        client = FakeS3Client(case.seeded)
        patch_recording_s3(monkeypatch, "cveta2.image_uploader", client)

        stats = S3Uploader().upload(
            _upload_cs_info(),
            {"img.jpg": _touch(tmp_path / "img.jpg")},
            existing_keys=case.existing_keys,
        )

        assert stats.uploaded == case.expected_uploaded
        assert stats.skipped_existing == case.expected_skipped

    def test_failed_upload_is_counted_and_named(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capture_logs: list[str],
    ) -> None:
        """A refused upload is counted as failed and identified in the log.

        Nothing else reads a ``Transfer``'s display name, so without a
        failing transfer the name and the describe callable were free.
        """
        client = _UnwritableKeysS3Client(unwritable={"project/images/bad.jpg"})
        patch_recording_s3(monkeypatch, "cveta2.image_uploader", client)
        images = {
            "good.jpg": _touch(tmp_path / "good.jpg"),
            "bad.jpg": _touch(tmp_path / "bad.jpg"),
        }

        stats = S3Uploader().upload(_upload_cs_info(), images, existing_keys=set())

        assert stats.total == 2
        assert stats.uploaded == 1
        assert stats.failed == 1
        assert set(client.objects) == {"upload-bucket/project/images/good.jpg"}
        assert "bad.jpg (key=project/images/bad.jpg)" in "\n".join(capture_logs)
