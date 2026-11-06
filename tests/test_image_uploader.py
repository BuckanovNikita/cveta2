"""Tests for image_uploader module — server file mapping and image lookup."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, NamedTuple

import pytest

from cveta2.adapters.files.image_search import resolve_images
from cveta2.adapters.s3.upload import S3Uploader, build_server_file_mapping
from tests.fixtures.fake_s3 import FakeS3Client
from tests.helpers import make_cs_info, patch_recording_s3

if TYPE_CHECKING:
    from pathlib import Path

    from cveta2.domain.storage import CloudStorageInfo

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


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    return path


def _bucket(*names: str) -> FakeS3Client:
    """Return a fake bucket holding *names* under the ``project/images`` prefix."""
    return FakeS3Client({f"test-bucket/project/images/{name}": b"x" for name in names})


class _ResolveCase(NamedTuple):
    files: list[str]
    names: list[str]
    search_dirs: list[str]
    expected: dict[str, str]


_RESOLVE_CASES = [
    pytest.param(
        _ResolveCase(["a.jpg"], ["a.jpg"], ["."], {"a.jpg": "a.jpg"}), id="flat"
    ),
    pytest.param(
        _ResolveCase(["sub/a.jpg"], ["sub/a.jpg"], ["."], {"sub/a.jpg": "sub/a.jpg"}),
        id="subpath-name",
    ),
    pytest.param(
        _ResolveCase(
            ["deep/nested/a.jpg"], ["a.jpg"], ["."], {"a.jpg": "deep/nested/a.jpg"}
        ),
        id="recursive-basename",
    ),
    pytest.param(
        _ResolveCase(["a.jpg", "nested/a.jpg"], ["a.jpg"], ["."], {"a.jpg": "a.jpg"}),
        id="direct-beats-recursive",
    ),
    pytest.param(
        _ResolveCase(
            ["dir1/sub/a.jpg", "dir2/a.jpg"],
            ["a.jpg"],
            ["dir1", "dir2"],
            {"a.jpg": "dir1/sub/a.jpg"},
        ),
        id="earlier-search-dir-wins",
    ),
    pytest.param(
        _ResolveCase(
            ["real/a.jpg"], ["a.jpg"], ["nope", "real"], {"a.jpg": "real/a.jpg"}
        ),
        id="nonexistent-search-dir-skipped",
    ),
]


class TestResolveImages:
    """Tests for resolve_images() — direct and recursive lookup."""

    @pytest.mark.parametrize("case", _RESOLVE_CASES)
    def test_finds_each_name(self, tmp_path: Path, case: _ResolveCase) -> None:
        for name in case.files:
            _touch(tmp_path / name)

        found, missing = resolve_images(
            case.names, [tmp_path / d for d in case.search_dirs]
        )

        assert found == {k: tmp_path / v for k, v in case.expected.items()}
        assert missing == []

    def test_duplicate_basenames_pick_lexicographic_max_and_warn(
        self, tmp_path: Path, capture_logs: list[str]
    ) -> None:
        """The warning must name the searched directory and the duplicate.

        The directory has to be matched together with the following word:
        the listed candidate paths all start with it, so a bare containment
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


_NEW = "<month>/"


class TestBuildServerFileMapping:
    """Tests for build_server_file_mapping()."""

    @pytest.mark.parametrize(
        ("listed", "names", "expected"),
        [
            pytest.param(
                ["flat.jpg", "2026-03/monthly.jpg", "a/b/c/deep.jpg"],
                {"flat.jpg", "monthly.jpg", "deep.jpg"},
                {
                    "flat.jpg": "flat.jpg",
                    "monthly.jpg": "2026-03/monthly.jpg",
                    "deep.jpg": "a/b/c/deep.jpg",
                },
                id="existing-images-keep-their-path-at-any-depth",
            ),
            pytest.param(
                [], {"new_img.jpg"}, {"new_img.jpg": _NEW}, id="new-image-month-prefix"
            ),
            pytest.param(
                ["old.jpg"],
                {"old.jpg", "brand_new.jpg"},
                {"old.jpg": "old.jpg", "brand_new.jpg": _NEW},
                id="mixed-existing-and-new",
            ),
        ],
    )
    def test_maps_each_name(
        self, listed: list[str], names: set[str], expected: dict[str, str]
    ) -> None:
        mapping, existing_keys = build_server_file_mapping(
            make_cs_info(prefix="project/images"), names, s3_client=_bucket(*listed)
        )

        assert mapping.keys() == expected.keys()
        for name, server_file in expected.items():
            if server_file == _NEW:
                assert _MONTH_PREFIX_RE.fullmatch(mapping[name])
                assert mapping[name].endswith(f"/{name}")
            else:
                assert mapping[name] == server_file
        assert existing_keys == {f"project/images/{key}" for key in listed}

    def test_new_image_month_folder_is_the_utc_calendar_month(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The folder is the UTC *month*, not the local month nor the minute.

        The month regex matches ``%Y-%M`` (minutes) just as happily as
        ``%Y-%m``, and with the real clock a naive ``datetime.now()`` agrees
        with UTC on this machine.  The frozen clock straddles a month
        boundary, so both mistakes change the answer.
        """
        monkeypatch.setattr("cveta2.adapters.s3.upload.datetime", _FixedClock)

        mapping, _ = build_server_file_mapping(
            make_cs_info(prefix="project/images"), {"new_img.jpg"}, s3_client=_bucket()
        )

        assert mapping["new_img.jpg"] == "2026-03/new_img.jpg"

    def test_lists_own_bucket_over_the_storage_endpoint(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without an injected client, the storage's endpoint and bucket are used."""
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
        factory = patch_recording_s3(monkeypatch, "cveta2.adapters.s3.upload", client)

        mapping, existing_keys = build_server_file_mapping(
            cs_info, {"mine.jpg", "theirs.jpg"}
        )

        assert factory.endpoints == ["http://minio:9000"]
        assert existing_keys == {"project/images/mine.jpg"}
        assert mapping["mine.jpg"] == "mine.jpg"
        assert _MONTH_PREFIX_RE.fullmatch(mapping["theirs.jpg"])

    def test_duplicate_basenames_uses_latest(self, capture_logs: list[str]) -> None:
        """Latest month folder wins, and the warning names S3 and the file."""
        mapping, _ = build_server_file_mapping(
            make_cs_info(prefix="project/images"),
            {"img.jpg"},
            s3_client=_bucket("2026-01/img.jpg", "2026-02/img.jpg"),
        )

        assert mapping["img.jpg"] == "2026-02/img.jpg"
        warnings = [m for m in capture_logs if "Дубликаты" in m]
        assert len(warnings) == 1
        assert "S3" in warnings[0]
        assert "'img.jpg'" in warnings[0]


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
    ran.  :class:`FakeS3Client` implements ``upload_file``, so the whole
    method works in memory.  The mapping and the existing keys are the
    caller's job (``build_server_file_mapping`` in production), so every
    test hands them over explicitly.
    """

    def test_no_images_returns_zeroed_stats(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An empty batch short-circuits before any S3 client is built."""
        factory = patch_recording_s3(
            monkeypatch, "cveta2.adapters.s3.upload", FakeS3Client()
        )

        stats = S3Uploader().upload(_upload_cs_info(), {}, {}, set())

        assert stats.total == 0
        assert stats.uploaded == 0
        assert stats.skipped_existing == 0
        assert factory.endpoints == []

    def test_uploads_new_files_and_skips_existing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """New files land under prefix; ones named in ``existing_keys`` are skipped.

        The seeded foreign-bucket copy of ``new.jpg`` and the recorded
        endpoint pin the bucket and the endpoint the upload targets.
        """
        client = FakeS3Client(
            {
                "upload-bucket/project/images/old.jpg": b"already-there",
                "upload-bucket/project/images/old2.jpg": b"already-there-too",
                "other-bucket/project/images/new.jpg": b"not-mine",
            }
        )
        factory = patch_recording_s3(monkeypatch, "cveta2.adapters.s3.upload", client)
        images = {
            "new.jpg": _touch(tmp_path / "new.jpg"),
            "old.jpg": _touch(tmp_path / "old.jpg"),
            "old2.jpg": _touch(tmp_path / "old2.jpg"),
        }

        stats = S3Uploader().upload(
            _upload_cs_info(),
            images,
            {name: name for name in images},
            {"project/images/old.jpg", "project/images/old2.jpg"},
        )

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
        """Each image lands at its server_file, not at its bare name.

        The two names map into different month folders, so a version that
        keys by name or by a single folder produces a different bucket.
        """
        client = FakeS3Client()
        patch_recording_s3(monkeypatch, "cveta2.adapters.s3.upload", client)
        images = {
            "january.jpg": _touch(tmp_path / "january.jpg"),
            "february.jpg": _touch(tmp_path / "february.jpg"),
        }

        stats = S3Uploader().upload(
            _upload_cs_info(),
            images,
            {
                "january.jpg": "2026-01/january.jpg",
                "february.jpg": "2026-02/february.jpg",
            },
            set(),
        )

        assert stats.uploaded == 2
        assert set(client.objects) == {
            "upload-bucket/project/images/2026-01/january.jpg",
            "upload-bucket/project/images/2026-02/february.jpg",
        }

    @pytest.mark.parametrize("case", _EXISTING_KEYS_CASES)
    def test_existing_keys_alone_decide_the_skip(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        case: _ExistingKeysCase,
    ) -> None:
        """``existing_keys`` decides the skip; the bucket is never consulted.

        Both cases make the argument disagree with the bucket, so a
        version that lists the bucket — or ignores the argument — gets
        the opposite answer.
        """
        client = FakeS3Client(case.seeded)
        patch_recording_s3(monkeypatch, "cveta2.adapters.s3.upload", client)

        stats = S3Uploader().upload(
            _upload_cs_info(),
            {"img.jpg": _touch(tmp_path / "img.jpg")},
            {"img.jpg": "img.jpg"},
            case.existing_keys,
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
        patch_recording_s3(monkeypatch, "cveta2.adapters.s3.upload", client)
        images = {
            "good.jpg": _touch(tmp_path / "good.jpg"),
            "bad.jpg": _touch(tmp_path / "bad.jpg"),
        }

        stats = S3Uploader().upload(
            _upload_cs_info(), images, {name: name for name in images}, set()
        )

        assert stats.total == 2
        assert stats.uploaded == 1
        assert stats.failed == 1
        assert set(client.objects) == {"upload-bucket/project/images/good.jpg"}
        assert "bad.jpg (key=project/images/bad.jpg)" in "\n".join(capture_logs)
