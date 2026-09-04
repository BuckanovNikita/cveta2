"""Tests for the persistent task-annotation cache (local + S3)."""

from __future__ import annotations

import json
import os
import stat
from dataclasses import replace
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pandas as pd
import pytest
from botocore.exceptions import ClientError, EndpointConnectionError

from cveta2._retry import RetryPolicy
from cveta2.client import CvatClient
from cveta2.image_downloader import CloudStorageInfo
from cveta2.models import (
    BBoxAnnotation,
    DeletedImage,
    ImageWithoutAnnotations,
    TaskAnnotations,
    TaskInfo,
)
from cveta2.services.fetch import (
    FetchOptions,
    FetchTarget,
    fetch_project,
    fetch_selected_tasks,
)
from cveta2.services.task_ops import resolved_task
from cveta2.task_cache import (
    CACHE_SCHEMA_VERSION,
    CachedTaskEnvelope,
    S3CacheBackend,
    TaskAnnotationCache,
    get_task_cache_dir,
    invalidate_local_entry,
)
from tests.fixtures.fake_cvat_api import FakeCvatApi
from tests.fixtures.fake_s3 import FakeS3Client
from tests.helpers import CFG, build_fake, make_bbox, make_task, write_config_yaml

if TYPE_CHECKING:
    from pathlib import Path

    from tests.fixtures.fake_cvat_project import LoadedFixtures


@pytest.fixture(autouse=True)
def _enable_task_cache(
    _disable_task_cache: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Re-enable the task cache disabled globally by conftest."""
    monkeypatch.delenv("CVETA2_DISABLE_CACHE", raising=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_UPDATED = "2026-01-01T00:00:00"


def _payload(task_id: int = 1) -> TaskAnnotations:
    bbox = make_bbox(
        task_id=task_id,
        issue_text="плохая рамка",
        issue_state="открыт",
    )
    empty = ImageWithoutAnnotations(
        image_name="empty.jpg",
        image_width=640,
        image_height=480,
        task_id=task_id,
        task_name=f"task-{task_id}",
        task_updated_date=_UPDATED,
        frame_id=1,
    )
    deleted = DeletedImage(
        image_name="gone.jpg",
        task_id=task_id,
        task_name=f"task-{task_id}",
        task_updated_date=_UPDATED,
        frame_id=2,
    )
    return TaskAnnotations(
        task_id=task_id,
        task_name=f"task-{task_id}",
        annotations=[bbox, empty],
        deleted_images=[deleted],
    )


def _envelope_bytes(
    task: TaskInfo,
    payload: TaskAnnotations,
    *,
    schema_version: int = CACHE_SCHEMA_VERSION,
) -> bytes:
    envelope = CachedTaskEnvelope(
        schema_version=schema_version,
        task_id=task.id,
        task_updated_date=task.updated_date,
        cached_at="2026-01-01T00:00:00+00:00",
        payload=payload,
    )
    return envelope.model_dump_json().encode("utf-8")


def _s3_key(task_id: int, prefix: str = "pfx") -> str:
    return f"{prefix}/.cveta2_cache/task_annotations/task_{task_id}.json"


# ---------------------------------------------------------------------------
# TaskAnnotationCache: local behavior
# ---------------------------------------------------------------------------


class TestLocalCache:
    def test_put_then_get_hit(self, tmp_path: Path) -> None:
        cache = TaskAnnotationCache(tmp_path / "cache")
        task = make_task(updated=_UPDATED)
        payload = _payload()

        cache.put(task, payload)

        assert cache.get(task) == payload

    def test_put_creates_group_writable_entry(self, tmp_path: Path) -> None:
        old_umask = os.umask(0o077)
        try:
            cache = TaskAnnotationCache(tmp_path / "cache")
            cache.put(make_task(updated=_UPDATED), _payload())
        finally:
            os.umask(old_umask)

        cache_dir = tmp_path / "cache"
        entry = cache_dir / "task_1.json"
        assert stat.S_IMODE(cache_dir.stat().st_mode) == 0o775
        assert stat.S_IMODE(entry.stat().st_mode) == 0o664

    def test_get_miss_on_empty_dir(self, tmp_path: Path) -> None:
        cache = TaskAnnotationCache(tmp_path / "cache")

        assert cache.get(make_task(updated=_UPDATED)) is None

    def test_bumped_updated_date_invalidates_local_entry(self, tmp_path: Path) -> None:
        """A changed task revision must not serve rendered stale annotations."""
        cache = TaskAnnotationCache(tmp_path / "cache")
        payload = _payload()
        cache.put(make_task(updated="2026-01-01T00:00:00"), payload)
        relabelled_task = make_task(updated="2026-02-02T00:00:00")

        assert cache.get(relabelled_task) is None
        assert not (tmp_path / "cache" / "task_1.json").exists()

    def test_wrong_schema_version_miss_and_deletes_file(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / "cache"
        cache = TaskAnnotationCache(cache_dir)
        task = make_task(updated=_UPDATED)
        cache.put(task, _payload())
        entry_path = cache_dir / "task_1.json"
        data = json.loads(entry_path.read_text(encoding="utf-8"))
        data["schema_version"] = CACHE_SCHEMA_VERSION + 1
        entry_path.write_text(json.dumps(data), encoding="utf-8")

        assert cache.get(task) is None
        assert not entry_path.exists()

    def test_unreadable_entry_is_miss_and_keeps_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An unreadable entry is a miss, not a crash, and stays on disk.

        Only ``FileNotFoundError`` was ever exercised, so the ``OSError``
        branch was untested: a permission error or a broken mount would
        have propagated out of the fetch.  The file must survive — only
        entries proven *invalid* are dropped.
        """
        cache_dir = tmp_path / "cache"
        cache = TaskAnnotationCache(cache_dir)
        task = make_task(updated=_UPDATED)
        cache.put(task, _payload())

        def _deny(self: Path) -> bytes:
            raise PermissionError(13, "Permission denied", str(self))

        monkeypatch.setattr("pathlib.Path.read_bytes", _deny)

        assert cache.get(task) is None
        assert (cache_dir / "task_1.json").exists()

    def test_cached_at_is_utc(self, tmp_path: Path) -> None:
        """``cached_at`` carries an explicit UTC offset.

        The entry is mirrored to S3 and read back on other machines, so a
        naive local timestamp is ambiguous.  Nothing parsed the field
        before, which left the timezone argument free.
        """
        cache_dir = tmp_path / "cache"
        TaskAnnotationCache(cache_dir).put(make_task(updated=_UPDATED), _payload())

        raw = (cache_dir / "task_1.json").read_bytes()
        envelope = CachedTaskEnvelope.model_validate_json(raw)

        assert datetime.fromisoformat(envelope.cached_at).tzinfo == timezone.utc

    def test_corrupt_json_miss_and_deletes_file(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        (cache_dir / "task_1.json").write_bytes(b"{not json!!")
        cache = TaskAnnotationCache(cache_dir)

        assert cache.get(make_task(updated=_UPDATED)) is None
        assert not (cache_dir / "task_1.json").exists()

    def test_non_completed_task_get_none_put_noop(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / "cache"
        cache = TaskAnnotationCache(cache_dir)
        task = make_task(status="annotation", updated=_UPDATED)

        cache.put(task, _payload())

        assert cache.get(task) is None
        assert not cache_dir.exists()

    def test_prune_removes_only_orphans(self, tmp_path: Path) -> None:
        """Two orphans, so the returned count cannot be a constant.

        With a single orphan an accumulator that assigns instead of adding
        returns the same 1, which said nothing about counting.
        """
        cache_dir = tmp_path / "cache"
        cache = TaskAnnotationCache(cache_dir)
        for task_id in (1, 2, 3, 4):
            cache.put(make_task(task_id, updated=_UPDATED), _payload(task_id))

        removed = cache.prune({1, 3})

        assert removed == 2
        assert (cache_dir / "task_1.json").exists()
        assert not (cache_dir / "task_2.json").exists()
        assert (cache_dir / "task_3.json").exists()
        assert not (cache_dir / "task_4.json").exists()

    def test_prune_on_missing_dir_returns_zero(self, tmp_path: Path) -> None:
        cache = TaskAnnotationCache(tmp_path / "nonexistent")

        assert cache.prune({1}) == 0

    def test_atomic_write_leaves_no_tmp_files(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / "cache"
        cache = TaskAnnotationCache(cache_dir)

        cache.put(make_task(updated=_UPDATED), _payload())

        leftovers = [p.name for p in cache_dir.iterdir() if ".tmp" in p.name]
        assert leftovers == []

    def test_invalidate_local_removes_entry(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / "cache"
        cache = TaskAnnotationCache(cache_dir)
        cache.put(make_task(updated=_UPDATED), _payload())

        cache.invalidate_local(1)

        assert not (cache_dir / "task_1.json").exists()
        cache.invalidate_local(1)

    def test_envelope_round_trip_preserves_record_types(self, tmp_path: Path) -> None:
        cache = TaskAnnotationCache(tmp_path / "cache")
        task = make_task(updated=_UPDATED)
        payload = _payload()
        cache.put(task, payload)

        restored = cache.get(task)

        assert restored is not None
        assert isinstance(restored.annotations[0], BBoxAnnotation)
        assert restored.annotations[0].issue_text == "плохая рамка"
        assert restored.annotations[0].issue_state == "открыт"
        assert isinstance(restored.annotations[1], ImageWithoutAnnotations)
        assert isinstance(restored.deleted_images[0], DeletedImage)
        assert restored == payload


# ---------------------------------------------------------------------------
# get_task_cache_dir / invalidate_local_entry
# ---------------------------------------------------------------------------


class TestCacheDir:
    def test_uses_xdg_cache_home(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))

        result = get_task_cache_dir(5)

        assert result == tmp_path / "xdg" / "cveta2" / "task_annotations" / "project_5"

    def test_falls_back_to_home_cache(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path))

        result = get_task_cache_dir(7)

        expected = tmp_path / ".cache" / "cveta2" / "task_annotations" / "project_7"
        assert result == expected

    def test_invalidate_local_entry_helper(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
        cache = TaskAnnotationCache(get_task_cache_dir(5))
        cache.put(make_task(updated=_UPDATED), _payload())
        entry = get_task_cache_dir(5) / "task_1.json"
        assert entry.exists()

        invalidate_local_entry(5, 1, "")

        assert not entry.exists()


# ---------------------------------------------------------------------------
# S3 backend
# ---------------------------------------------------------------------------


class _FailingS3Client:
    """S3 client whose every operation raises EndpointConnectionError."""

    def __init__(self) -> None:
        self.calls = 0

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:  # noqa: N803
        del Bucket, Key
        self.calls += 1
        raise EndpointConnectionError(endpoint_url="http://s3.invalid")

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:  # noqa: N803
        del Bucket, Key
        self.calls += 1
        raise EndpointConnectionError(endpoint_url="http://s3.invalid")

    def put_object(self, *, Bucket: str, Key: str, Body: bytes) -> None:  # noqa: N803
        del Bucket, Key, Body
        self.calls += 1
        raise EndpointConnectionError(endpoint_url="http://s3.invalid")

    def delete_object(self, *, Bucket: str, Key: str) -> None:  # noqa: N803
        del Bucket, Key
        self.calls += 1
        raise EndpointConnectionError(endpoint_url="http://s3.invalid")

    def list_objects_v2(self, **kwargs: str) -> dict[str, Any]:
        del kwargs
        self.calls += 1
        raise EndpointConnectionError(endpoint_url="http://s3.invalid")

    def upload_file(self, filename: str, bucket: str, key: str) -> None:
        del filename, bucket, key
        self.calls += 1
        raise EndpointConnectionError(endpoint_url="http://s3.invalid")


class _ClientErrorS3Client(FakeS3Client):
    """Fake S3 whose ``get_object`` raises a caller-supplied error body.

    :class:`FakeS3Client` can only ever raise a well-formed ``NoSuchKey``,
    so neither the other missing-key codes nor a malformed response could
    reach the backend.  The body is typed loosely on purpose: the point is
    to feed the backend shapes botocore's own stubs forbid.
    """

    def __init__(self, error_response: Any) -> None:
        """Fail every read with *error_response* as the ClientError body."""
        super().__init__()
        self._error_response = error_response

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:  # noqa: N803
        self.get_calls.append(f"{Bucket}/{Key}")
        raise ClientError(self._error_response, "GetObject")


class TestS3Backend:
    @pytest.fixture(autouse=True)
    def _single_attempt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``_FailingS3Client`` raises a retryable fault; one attempt is enough."""
        monkeypatch.setattr(RetryPolicy, "attempts", 1)
        monkeypatch.setattr(RetryPolicy, "max_wait", 0.01)

    def test_s3_hit_backfills_local(self, tmp_path: Path) -> None:
        task = make_task(updated=_UPDATED)
        payload = _payload()
        fake_s3 = FakeS3Client({f"bkt/{_s3_key(1)}": _envelope_bytes(task, payload)})
        cache = TaskAnnotationCache(
            tmp_path / "local", s3=S3CacheBackend(fake_s3, "bkt", "pfx")
        )

        assert cache.get(task) == payload
        assert (tmp_path / "local" / "task_1.json").exists()

    def test_local_hit_never_touches_s3(self, tmp_path: Path) -> None:
        task = make_task(updated=_UPDATED)
        payload = _payload()
        local_dir = tmp_path / "local"
        TaskAnnotationCache(local_dir).put(task, payload)
        fake_s3 = FakeS3Client()
        cache = TaskAnnotationCache(local_dir, s3=S3CacheBackend(fake_s3, "bkt", "pfx"))

        assert cache.get(task) == payload
        assert fake_s3.get_calls == []

    def test_put_writes_local_and_s3(self, tmp_path: Path) -> None:
        fake_s3 = FakeS3Client()
        cache = TaskAnnotationCache(
            tmp_path / "local", s3=S3CacheBackend(fake_s3, "bkt", "pfx")
        )

        cache.put(make_task(updated=_UPDATED), _payload())

        assert (tmp_path / "local" / "task_1.json").exists()
        assert fake_s3.put_calls == [f"bkt/{_s3_key(1)}"]

    def test_invalidate_drops_the_s3_entry_so_get_misses(self, tmp_path: Path) -> None:
        """A task mutation must not be undone by the S3 mirror.

        ``invalidate_local`` alone left the S3 copy in place, and the next
        ``get`` backfilled the pre-mutation payload from it.
        """
        task = make_task(updated=_UPDATED)
        fake_s3 = FakeS3Client()
        cache = TaskAnnotationCache(
            tmp_path / "local", s3=S3CacheBackend(fake_s3, "bkt", "pfx")
        )
        cache.put(task, _payload())
        key = f"bkt/{_s3_key(1)}"
        assert key in fake_s3.objects

        cache.invalidate(1)

        assert cache.get(task) is None
        assert key not in fake_s3.objects
        assert fake_s3.delete_calls == [key]
        assert not (tmp_path / "local" / "task_1.json").exists()

    def test_invalidate_without_s3_only_unlinks_locally(self, tmp_path: Path) -> None:
        task = make_task(updated=_UPDATED)
        cache = TaskAnnotationCache(tmp_path / "local")
        cache.put(task, _payload())

        cache.invalidate(1)

        assert cache.get(task) is None
        assert not (tmp_path / "local" / "task_1.json").exists()

    def test_delete_of_a_missing_key_is_a_noop(self) -> None:
        fake_s3 = FakeS3Client()
        backend = S3CacheBackend(fake_s3, "bkt", "pfx")

        backend.delete(1)
        backend.put(1, b"data")

        assert fake_s3.delete_calls == [f"bkt/{_s3_key(1)}"]
        assert fake_s3.objects[f"bkt/{_s3_key(1)}"] == b"data"

    def test_failing_delete_disables_s3_and_still_unlinks_locally(
        self, tmp_path: Path, capture_logs: list[str]
    ) -> None:
        task = make_task(updated=_UPDATED)
        local_dir = tmp_path / "local"
        TaskAnnotationCache(local_dir).put(task, _payload())
        failing = _FailingS3Client()
        backend = S3CacheBackend(failing, "bkt", "pfx")
        cache = TaskAnnotationCache(local_dir, s3=backend)

        cache.invalidate(1)
        backend.delete(1)
        backend.put(1, b"data")

        assert not (local_dir / "task_1.json").exists()
        assert failing.calls == 1
        warnings = [m for m in capture_logs if "S3-кэш" in m]
        assert len(warnings) == 1
        assert "s3.invalid" in warnings[0]

    def test_stale_s3_entry_ignored_without_remote_delete(self, tmp_path: Path) -> None:
        task = make_task(updated=_UPDATED)
        key = f"bkt/{_s3_key(1)}"
        fake_s3 = FakeS3Client(
            {
                key: _envelope_bytes(
                    task, _payload(), schema_version=CACHE_SCHEMA_VERSION + 1
                )
            }
        )
        cache = TaskAnnotationCache(
            tmp_path / "local", s3=S3CacheBackend(fake_s3, "bkt", "pfx")
        )

        assert cache.get(task) is None
        assert key in fake_s3.objects
        assert not (tmp_path / "local" / "task_1.json").exists()

    def test_s3_entry_with_a_bumped_date_is_rejected_without_backfill(
        self, tmp_path: Path
    ) -> None:
        payload = _payload()
        key = f"bkt/{_s3_key(1)}"
        fake_s3 = FakeS3Client(
            {key: _envelope_bytes(make_task(updated="2025-01-01T00:00:00"), payload)}
        )
        cache = TaskAnnotationCache(
            tmp_path / "local", s3=S3CacheBackend(fake_s3, "bkt", "pfx")
        )

        assert cache.get(make_task(updated="2026-06-06T00:00:00")) is None
        assert not (tmp_path / "local" / "task_1.json").exists()

    def test_missing_key_is_plain_miss_not_disable(self, tmp_path: Path) -> None:
        fake_s3 = FakeS3Client()
        backend = S3CacheBackend(fake_s3, "bkt", "pfx")
        cache = TaskAnnotationCache(tmp_path / "local", s3=backend)

        assert cache.get(make_task(1, updated=_UPDATED)) is None
        assert cache.get(make_task(2, updated=_UPDATED)) is None
        assert len(fake_s3.get_calls) == 2

    @pytest.mark.parametrize("code", ["404", "NoSuchBucket"])
    def test_every_missing_key_code_is_a_plain_miss(
        self, code: str, tmp_path: Path, capture_logs: list[str]
    ) -> None:
        """``404`` and ``NoSuchBucket`` behave exactly like ``NoSuchKey``.

        Only ``NoSuchKey`` was exercised, so the rest of the missing-key
        set was decoration.  A plain miss keeps the backend enabled (the
        second task still reaches S3) and warns about nothing.
        """
        s3 = _ClientErrorS3Client({"Error": {"Code": code}})
        cache = TaskAnnotationCache(
            tmp_path / "local", s3=S3CacheBackend(s3, "bkt", "pfx")
        )

        assert cache.get(make_task(1, updated=_UPDATED)) is None
        assert cache.get(make_task(2, updated=_UPDATED)) is None

        assert len(s3.get_calls) == 2
        assert [m for m in capture_logs if "S3-кэш" in m] == []

    @pytest.mark.parametrize(
        "error_response",
        [{"Error": {"Code": "AccessDenied"}}, {"Error": {}}, {}],
        ids=["unknown-code", "no-code", "no-error-body"],
    )
    def test_unclassifiable_error_disables_backend(
        self, error_response: Any, tmp_path: Path, capture_logs: list[str]
    ) -> None:
        """Anything that is not a known missing-key code is fatal for the run.

        The ``ClientError`` disable branch had no test at all — only the
        ``BotoCoreError`` one did — so nothing checked that an unexpected
        code stops the backend instead of reading as a miss.  The two
        malformed bodies matter just as much: a cache problem must never
        raise out of the fetch, and reading the code out of a response
        that has no ``Error`` mapping is the one way it could.
        """
        s3 = _ClientErrorS3Client(error_response)
        cache = TaskAnnotationCache(
            tmp_path / "local", s3=S3CacheBackend(s3, "bkt", "pfx")
        )

        assert cache.get(make_task(1, updated=_UPDATED)) is None
        assert cache.get(make_task(2, updated=_UPDATED)) is None

        assert len(s3.get_calls) == 1
        assert sum("S3-кэш" in m for m in capture_logs) == 1

    def test_put_mirrors_a_readable_payload_to_s3(self, tmp_path: Path) -> None:
        """Another machine's cache can read what ``put`` mirrored.

        The S3 copy was only ever asserted by key, so a mirror written
        with the wrong body — or no body — still passed.
        """
        fake_s3 = FakeS3Client()
        task = make_task(updated=_UPDATED)
        payload = _payload()
        TaskAnnotationCache(
            tmp_path / "writer", s3=S3CacheBackend(fake_s3, "bkt", "pfx")
        ).put(task, payload)

        reader = TaskAnnotationCache(
            tmp_path / "reader", s3=S3CacheBackend(fake_s3, "bkt", "pfx")
        )

        assert reader.get(task) == payload

    def test_get_failure_warns_once_and_disables(
        self, tmp_path: Path, capture_logs: list[str]
    ) -> None:
        failing = _FailingS3Client()
        cache = TaskAnnotationCache(
            tmp_path / "local", s3=S3CacheBackend(failing, "bkt", "pfx")
        )

        assert cache.get(make_task(1, updated=_UPDATED)) is None
        assert cache.get(make_task(2, updated=_UPDATED)) is None
        cache.put(make_task(3, updated=_UPDATED), _payload(3))

        assert failing.calls == 1
        assert sum("S3-кэш" in m for m in capture_logs) == 1

    def test_put_failure_keeps_local_entry(
        self, tmp_path: Path, capture_logs: list[str]
    ) -> None:
        failing = _FailingS3Client()
        cache = TaskAnnotationCache(
            tmp_path / "local", s3=S3CacheBackend(failing, "bkt", "pfx")
        )
        task = make_task(updated=_UPDATED)
        payload = _payload()

        cache.put(task, payload)

        assert cache.get(task) == payload
        assert failing.calls == 1
        assert sum("S3-кэш" in m for m in capture_logs) == 1

    def test_from_cloud_storage_none(self) -> None:
        assert S3CacheBackend.from_cloud_storage(None) is None

    def test_from_cloud_storage_builds_backend(self) -> None:
        cs_info = CloudStorageInfo(
            id=1, bucket="bkt", prefix="pfx", endpoint_url="http://minio:9000"
        )
        fake_s3 = FakeS3Client()

        with patch(
            "cveta2.task_cache.make_s3_client", return_value=fake_s3
        ) as make_client:
            backend = S3CacheBackend.from_cloud_storage(cs_info)

        assert backend is not None
        make_client.assert_called_once_with("http://minio:9000")
        backend.put(1, b"data")
        assert fake_s3.objects[f"bkt/{_s3_key(1)}"] == b"data"


# ---------------------------------------------------------------------------
# Fetch flow integration (fake CVAT API)
# ---------------------------------------------------------------------------


def _fetch_task_cached(
    fake_api: FakeCvatApi,
    fake: LoadedFixtures,
    output_dir: Path,
    options: FetchOptions,
    cs_info: CloudStorageInfo | None = None,
) -> None:
    """Drive ``fetch_selected_tasks`` with a fake API and a local-only cache.

    ``FakeCvatApi.get_project_cloud_storage`` returns None, so the S3
    backend is never built — the cache stays local-only.  The task
    selector always targets the fixture's first task.
    """
    fetch_selected_tasks(
        CvatClient(CFG, api=fake_api),
        FetchTarget(fake.project.id, fake.project.name, output_dir, cs_info),
        replace(options, task_selector=[fake.tasks[0].name]),
    )


class TestFetchWithCache:
    def test_second_fetch_skips_completed_tasks(
        self, normal_fake: LoadedFixtures, tmp_path: Path
    ) -> None:
        fake = normal_fake
        api = FakeCvatApi(fake)

        _fetch_task_cached(api, fake, tmp_path / "out1", FetchOptions())
        assert len(api.annotation_calls) == 1

        _fetch_task_cached(api, fake, tmp_path / "out2", FetchOptions(save_tasks=True))

        assert len(api.annotation_calls) == 1
        df1 = pd.read_csv(tmp_path / "out1" / "dataset.csv")
        df2 = pd.read_csv(tmp_path / "out2" / "dataset.csv")
        pd.testing.assert_frame_equal(df1, df2)
        task_csv = tmp_path / "out2" / ".tasks" / f"task_{fake.tasks[0].id}.csv"
        assert task_csv.exists()

    def test_force_refetches_and_no_cache_disables(
        self, normal_fake: LoadedFixtures, tmp_path: Path
    ) -> None:
        fake = normal_fake
        api = FakeCvatApi(fake)

        _fetch_task_cached(api, fake, tmp_path / "out1", FetchOptions())
        _fetch_task_cached(api, fake, tmp_path / "out2", FetchOptions(force=True))
        assert len(api.annotation_calls) == 2

        _fetch_task_cached(api, fake, tmp_path / "out3", FetchOptions(use_cache=False))
        assert len(api.annotation_calls) == 3

        _fetch_task_cached(api, fake, tmp_path / "out4", FetchOptions())
        assert len(api.annotation_calls) == 3

    def test_non_completed_tasks_always_refetched(
        self, coco8_fixtures: LoadedFixtures, tmp_path: Path
    ) -> None:
        fake = build_fake(coco8_fixtures, ["normal"], statuses=["annotation"])
        api = FakeCvatApi(fake)

        for out in ("out1", "out2"):
            _fetch_task_cached(api, fake, tmp_path / out, FetchOptions())

        assert len(api.annotation_calls) == 2

    def test_cached_payload_is_machine_independent(
        self, normal_fake: LoadedFixtures, tmp_path: Path
    ) -> None:
        fake = normal_fake
        api = FakeCvatApi(fake)
        cs_info = CloudStorageInfo(id=1, bucket="bkt", prefix="pfx", endpoint_url="")

        _fetch_task_cached(api, fake, tmp_path / "out", FetchOptions(), cs_info)

        df = pd.read_csv(tmp_path / "out" / "dataset.csv")
        assert df["s3_image_path"].str.startswith("pfx/").all()

        entry = get_task_cache_dir(fake.project.id) / f"task_{fake.tasks[0].id}.json"
        envelope = CachedTaskEnvelope.model_validate_json(entry.read_bytes())
        for record in envelope.payload.annotations:
            assert record.s3_image_path is None
            assert record.image_path is None
        for deleted in envelope.payload.deleted_images:
            assert deleted.s3_image_path is None
            assert deleted.image_path is None


class TestFullFetchPrunesCache:
    def test_full_fetch_prunes_orphaned_entries(
        self, normal_fake: LoadedFixtures, tmp_path: Path
    ) -> None:
        fake = normal_fake
        api = FakeCvatApi(fake)
        cache_dir = get_task_cache_dir(fake.project.id)
        TaskAnnotationCache(cache_dir).put(
            make_task(999, updated=_UPDATED), _payload(999)
        )

        fetch_project(
            CvatClient(CFG, api=api),
            FetchTarget(fake.project.id, fake.project.name, tmp_path / "out", None),
            FetchOptions(use_cache=True, publish_clearml=False),
        )

        assert not (cache_dir / "task_999.json").exists()
        assert (cache_dir / f"task_{fake.tasks[0].id}.json").exists()


# ---------------------------------------------------------------------------
# Cache settings (tasks_root / task_cache_s3)
# ---------------------------------------------------------------------------


class TestCacheSettings:
    def test_cache_dir_with_custom_root(self, tmp_path: Path) -> None:
        result = get_task_cache_dir(5, root=tmp_path / "tasks")

        assert result == tmp_path / "tasks" / "project_5"

    def test_invalidate_local_entry_honors_tasks_root(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text(
            f"cache:\n  tasks_root: {tmp_path / 'tasks'}\n", encoding="utf-8"
        )
        monkeypatch.setenv("CVETA2_CONFIG", str(cfg_path))
        cache_dir = get_task_cache_dir(5, root=tmp_path / "tasks")
        TaskAnnotationCache(cache_dir).put(make_task(updated=_UPDATED), _payload())
        entry = cache_dir / "task_1.json"
        assert entry.exists()

        invalidate_local_entry(5, 1, "")

        assert not entry.exists()

    def test_invalidate_local_entry_prefers_project_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A per-project ``tasks_root`` wins over the global one.

        Every earlier call resolved to the same directory whether or not
        the project name was taken into account, so dropping the name on
        the way to ``CacheConfig.for_project`` was invisible.
        """
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text(
            "cache:\n"
            f"  tasks_root: {tmp_path / 'global'}\n"
            "  projects:\n"
            "    proj:\n"
            f"      tasks_root: {tmp_path / 'proj'}\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("CVETA2_CONFIG", str(cfg_path))
        cache_dir = get_task_cache_dir(5, root=tmp_path / "proj")
        TaskAnnotationCache(cache_dir).put(make_task(updated=_UPDATED), _payload())

        invalidate_local_entry(5, 1, "proj")

        assert not (cache_dir / "task_1.json").exists()

    def test_invalidate_local_entry_drops_the_default_s3_entry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
        cache_dir = get_task_cache_dir(5)
        TaskAnnotationCache(cache_dir).put(make_task(updated=_UPDATED), _payload())
        key = f"bkt/{_s3_key(1)}"
        fake_s3 = FakeS3Client({key: b"stale"})

        with patch("cveta2.task_cache.make_s3_client", return_value=fake_s3):
            invalidate_local_entry(5, 1, "", _PROJECT_STORAGE)

        assert not (cache_dir / "task_1.json").exists()
        assert fake_s3.delete_calls == [key]
        assert key not in fake_s3.objects

    def test_invalidate_local_entry_honors_task_cache_s3(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The explicit-location key is the one dropped, not the default one.

        Losing the ``task_cache_s3`` pass-through would delete a key nobody
        wrote and leave the team's shared entry to be served again.
        """
        config_path = write_config_yaml(
            tmp_path / "cfg.yaml",
            cache={"projects": {"proj": {"task_cache_s3": "s3://ml-cache/proj"}}},
        )
        monkeypatch.setenv("CVETA2_CONFIG", str(config_path))
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
        explicit_key = "ml-cache/proj/task_annotations/task_1.json"
        default_key = f"bkt/{_s3_key(1)}"
        fake_s3 = FakeS3Client({explicit_key: b"stale", default_key: b"other"})

        with patch("cveta2.task_cache.make_s3_client", return_value=fake_s3):
            invalidate_local_entry(5, 1, "proj", _PROJECT_STORAGE)

        assert fake_s3.delete_calls == [explicit_key]
        assert explicit_key not in fake_s3.objects
        assert default_key in fake_s3.objects

    def test_invalidate_local_entry_leaves_s3_alone_when_cache_disabled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``CVETA2_DISABLE_CACHE`` means no S3 traffic at all, deletes included."""
        monkeypatch.setenv("CVETA2_DISABLE_CACHE", "true")
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
        cache_dir = get_task_cache_dir(5)
        TaskAnnotationCache(cache_dir).put(make_task(updated=_UPDATED), _payload())
        key = f"bkt/{_s3_key(1)}"
        fake_s3 = FakeS3Client({key: b"stale"})

        with patch(
            "cveta2.task_cache.make_s3_client", return_value=fake_s3
        ) as make_client:
            invalidate_local_entry(5, 1, "", _PROJECT_STORAGE)

        make_client.assert_not_called()
        assert fake_s3.delete_calls == []
        assert key in fake_s3.objects
        assert not (cache_dir / "task_1.json").exists()

    def test_explicit_location_uses_plain_task_annotations_key(
        self, tmp_path: Path
    ) -> None:
        fake_s3 = FakeS3Client()
        backend = S3CacheBackend(fake_s3, "ml-cache", "proj", explicit_location=True)
        cache = TaskAnnotationCache(tmp_path / "local", s3=backend)

        cache.put(make_task(updated=_UPDATED), _payload())

        assert fake_s3.put_calls == ["ml-cache/proj/task_annotations/task_1.json"]

    def test_from_cloud_storage_with_full_url_targets_other_bucket(
        self, tmp_path: Path
    ) -> None:
        fake_s3 = FakeS3Client()
        cs_info = CloudStorageInfo(id=1, bucket="bkt", prefix="pfx", endpoint_url="")
        with patch("cveta2.task_cache.make_s3_client", return_value=fake_s3):
            backend = S3CacheBackend.from_cloud_storage(
                cs_info, task_cache_s3="s3://ml-cache/proj"
            )
        assert backend is not None
        cache = TaskAnnotationCache(tmp_path / "local", s3=backend)

        cache.put(make_task(updated=_UPDATED), _payload())

        assert fake_s3.put_calls == ["ml-cache/proj/task_annotations/task_1.json"]

    def test_from_cloud_storage_with_bare_prefix_stays_in_project_bucket(
        self, tmp_path: Path
    ) -> None:
        fake_s3 = FakeS3Client()
        cs_info = CloudStorageInfo(id=1, bucket="bkt", prefix="pfx", endpoint_url="")
        with patch("cveta2.task_cache.make_s3_client", return_value=fake_s3):
            backend = S3CacheBackend.from_cloud_storage(
                cs_info, task_cache_s3="_cveta2_cache"
            )
        assert backend is not None
        cache = TaskAnnotationCache(tmp_path / "local", s3=backend)

        cache.put(make_task(updated=_UPDATED), _payload())

        assert fake_s3.put_calls == ["bkt/_cveta2_cache/task_annotations/task_1.json"]

    def test_bare_prefix_without_project_storage_builds_nothing(self) -> None:
        """A bare prefix names no bucket, so without storage there is none.

        Both override forms were only ever tried with a project storage
        attached, which left the "no bucket anywhere" guard free.
        """
        assert S3CacheBackend.from_cloud_storage(None, task_cache_s3="_cache") is None

    def test_full_url_works_without_project_storage(self, tmp_path: Path) -> None:
        """``s3://`` carries its own bucket, so it needs no project storage.

        With no storage there is also no endpoint to inherit, and the
        client must be built with ``None`` rather than an empty string.
        """
        fake_s3 = FakeS3Client()
        with patch(
            "cveta2.task_cache.make_s3_client", return_value=fake_s3
        ) as make_client:
            backend = S3CacheBackend.from_cloud_storage(
                None, task_cache_s3="s3://ml-cache/proj"
            )
        assert backend is not None
        make_client.assert_called_once_with(None)
        cache = TaskAnnotationCache(tmp_path / "local", s3=backend)

        cache.put(make_task(updated=_UPDATED), _payload())

        assert fake_s3.put_calls == ["ml-cache/proj/task_annotations/task_1.json"]

    def test_explicit_location_inherits_the_storage_endpoint(self) -> None:
        """The override moves the cache, it does not change how S3 is reached.

        Every other override test used an empty ``endpoint_url``, where
        passing the project endpoint and passing ``None`` are the same
        call.
        """
        cs_info = CloudStorageInfo(
            id=1, bucket="bkt", prefix="pfx", endpoint_url="http://minio:9000"
        )
        with patch(
            "cveta2.task_cache.make_s3_client", return_value=FakeS3Client()
        ) as make_client:
            S3CacheBackend.from_cloud_storage(cs_info, task_cache_s3="s3://ml-cache/p")

        make_client.assert_called_once_with("http://minio:9000")

    def test_from_cloud_storage_default_keeps_cveta2_cache_layout(
        self, tmp_path: Path
    ) -> None:
        fake_s3 = FakeS3Client()
        cs_info = CloudStorageInfo(id=1, bucket="bkt", prefix="pfx", endpoint_url="")
        with patch("cveta2.task_cache.make_s3_client", return_value=fake_s3):
            backend = S3CacheBackend.from_cloud_storage(cs_info)
        assert backend is not None
        cache = TaskAnnotationCache(tmp_path / "local", s3=backend)

        cache.put(make_task(updated=_UPDATED), _payload())

        assert fake_s3.put_calls == [
            "bkt/pfx/.cveta2_cache/task_annotations/task_1.json"
        ]


# ---------------------------------------------------------------------------
# _build_task_cache: what the fetch pipeline wires the cache up to
# ---------------------------------------------------------------------------


class _FakeApiWithStorage(FakeCvatApi):
    """``FakeCvatApi`` whose project reports a cloud storage.

    The base fake answers ``None``, so no service-level test ever reached
    the S3 half of the cache: every one of them ran local-only.
    """

    def __init__(self, fake: LoadedFixtures, storage: CloudStorageInfo) -> None:
        super().__init__(fake)
        self._storage = storage

    def get_project_cloud_storage(self, _project_id: int) -> CloudStorageInfo | None:
        return self._storage


_PROJECT_STORAGE = CloudStorageInfo(id=1, bucket="bkt", prefix="pfx", endpoint_url="")


class TestFetchBuildsTheS3CacheBackend:
    """The shared S3 cache only exists if the pipeline wires it up."""

    def _fetch(
        self,
        api: FakeCvatApi,
        fake: LoadedFixtures,
        output_dir: Path,
        fake_s3: FakeS3Client,
        config_path: Path | None = None,
    ) -> None:
        with patch("cveta2.task_cache.make_s3_client", return_value=fake_s3):
            fetch_selected_tasks(
                CvatClient(CFG, api=api),
                FetchTarget(fake.project.id, fake.project.name, output_dir, None),
                FetchOptions(
                    task_selector=[fake.tasks[0].name],
                    config_path=config_path,
                ),
            )

    def test_an_s3_entry_is_served_without_asking_cvat(
        self, normal_fake: LoadedFixtures, tmp_path: Path
    ) -> None:
        """A teammate's cached entry must spare this machine the fetch.

        Every earlier fetch test ran against the storage-less fake, so the
        S3 backend was never built and the whole shared half of the cache
        was reachable only through direct ``S3CacheBackend`` unit tests.
        """
        fake = normal_fake
        api = _FakeApiWithStorage(fake, _PROJECT_STORAGE)
        task = fake.tasks[0]
        fake_s3 = FakeS3Client(
            {f"bkt/{_s3_key(task.id)}": _envelope_bytes(task, _payload(task.id))}
        )

        self._fetch(api, fake, tmp_path / "out", fake_s3)

        assert api.annotation_calls == []
        assert (get_task_cache_dir(fake.project.id) / f"task_{task.id}.json").exists()

    def test_a_fresh_fetch_is_published_to_s3(
        self, normal_fake: LoadedFixtures, tmp_path: Path
    ) -> None:
        """A local-only write would leave every other machine re-fetching."""
        fake = normal_fake
        fake_s3 = FakeS3Client()

        self._fetch(
            _FakeApiWithStorage(fake, _PROJECT_STORAGE), fake, tmp_path / "out", fake_s3
        )

        assert fake_s3.put_calls == [f"bkt/{_s3_key(fake.tasks[0].id)}"]

    def test_the_configured_override_moves_the_s3_location(
        self, normal_fake: LoadedFixtures, tmp_path: Path
    ) -> None:
        """``task_cache_s3`` must survive the trip from config to backend.

        Dropping it silently relocates a team's shared cache back to the
        project bucket's ``.cveta2_cache/``, where nobody is looking.
        """
        fake = normal_fake
        fake_s3 = FakeS3Client()
        config_path = write_config_yaml(
            tmp_path / "cfg.yaml",
            cache={
                "projects": {fake.project.name: {"task_cache_s3": "s3://ml-cache/proj"}}
            },
        )

        self._fetch(
            _FakeApiWithStorage(fake, _PROJECT_STORAGE),
            fake,
            tmp_path / "out",
            fake_s3,
            config_path,
        )

        assert fake_s3.put_calls == [
            f"ml-cache/proj/task_annotations/task_{fake.tasks[0].id}.json"
        ]


class TestTaskMutationDropsTheS3Entry:
    """``resolved_task`` hands the project's storage to the invalidation."""

    def test_resolved_task_drops_the_s3_entry_on_exit(
        self,
        normal_fake: LoadedFixtures,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
        fake = normal_fake
        task = fake.tasks[0]
        key = f"bkt/{_s3_key(task.id)}"
        fake_s3 = FakeS3Client({key: b"stale"})
        client = CvatClient(CFG, api=_FakeApiWithStorage(fake, _PROJECT_STORAGE))

        with (
            patch("cveta2.task_cache.make_s3_client", return_value=fake_s3),
            client,
            resolved_task(client, fake.project.id, fake.project.name, task.id),
        ):
            assert key in fake_s3.objects

        assert fake_s3.delete_calls == [key]
        assert key not in fake_s3.objects


class TestSelectedFetchDoesNotPrune:
    def test_a_selected_fetch_keeps_entries_for_the_tasks_it_skipped(
        self, normal_fake: LoadedFixtures, tmp_path: Path
    ) -> None:
        """Pruning on a partial fetch would delete every unselected task.

        ``fetch_project`` prunes because it has just seen the whole project;
        ``fetch_selected_tasks`` has seen one task and must not conclude the
        rest are gone.
        """
        fake = normal_fake
        cache_dir = get_task_cache_dir(fake.project.id)
        TaskAnnotationCache(cache_dir).put(
            make_task(999, updated=_UPDATED), _payload(999)
        )

        _fetch_task_cached(FakeCvatApi(fake), fake, tmp_path / "out", FetchOptions())

        assert (cache_dir / "task_999.json").exists()
