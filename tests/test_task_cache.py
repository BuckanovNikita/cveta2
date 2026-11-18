"""Tests for the persistent per-job annotation cache (local + S3)."""

from __future__ import annotations

import os
import stat
from dataclasses import asdict, replace
from datetime import datetime, timezone
from importlib import import_module
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pandas as pd
import pytest
from botocore.exceptions import ClientError, EndpointConnectionError, ProfileNotFound

import cveta2
from cveta2.adapters.execution.retry import RetryPolicy, configure_retries
from cveta2.adapters.s3.task_cache import (
    CachedAnnotationsEntry,
    S3CacheBackend,
    TaskAnnotationCache,
    get_task_cache_dir,
)
from cveta2.application.ports.cache import AnnotationScope
from cveta2.application.ports.dtos import (
    RawAnnotations,
    RawDataMeta,
    RawFrame,
    RawIssue,
    RawJob,
)
from cveta2.application.use_cases.fetch import FetchOptions, FetchTarget
from cveta2.application.use_cases.upload import UploadOutcome, UploadRequest
from cveta2.composition.client import CvatClient
from cveta2.composition.workflows import (
    fetch_project,
    fetch_selected_tasks,
    invalidate_local_entry,
    resolved_task,
    upload_dependencies,
)
from cveta2.domain.cache import CACHE_SCHEMA_VERSION, CachedJob
from cveta2.domain.errors import CvatApiError, Cveta2Error
from cveta2.domain.models import ProjectInfo, TaskInfo
from cveta2.domain.storage import CloudStorageInfo
from tests.api_helpers import _scoped
from tests.fixtures.fake_cvat_api import FakeCvatApi
from tests.fixtures.fake_cvat_project import LoadedFixtures
from tests.fixtures.fake_s3 import FakeS3Client
from tests.helpers import CFG, build_fake, csv_row, make_raw_shape, make_task, write_split_config_yaml

if TYPE_CHECKING:
    from collections.abc import Callable, Generator
    from pathlib import Path


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
_JOB_UPDATED = "2026-01-02T00:00:00"


def _job(  # noqa: PLR0913 - every job field a test varies
    job_id: int = 1,
    *,
    start: int = 0,
    stop: int = 9,
    stage: str = "acceptance",
    state: str = "completed",
    job_type: str = "annotation",
    updated_date: str = _JOB_UPDATED,
) -> RawJob:
    """Build a job, finished unless *stage* or *state* say otherwise."""
    return RawJob(job_id, start, stop, stage, state, job_type, updated_date)


def _scope(job_id: int = 1, *, job: RawJob | None = None) -> AnnotationScope:
    return AnnotationScope(jobs=(job or _job(job_id),))


def _shapes(shape_id: int = 7) -> RawAnnotations:
    return RawAnnotations(shapes=[make_raw_shape(id=shape_id, frame=0)])


def _entry(cache_dir: Path, task_id: int = 1, job_id: int | None = None) -> Path:
    """Path of the job entry; the fake's single job shares the task's id."""
    return cache_dir / f"task_{task_id}" / f"job_{task_id if job_id is None else job_id}.json"


def _entry_bytes(
    task: TaskInfo,
    scope: AnnotationScope | None = None,
    shapes: RawAnnotations | None = None,
    *,
    schema_version: int = CACHE_SCHEMA_VERSION,
) -> bytes:
    scope = scope or _scope(task.id)
    entry = CachedAnnotationsEntry(
        schema_version=schema_version,
        task_id=task.id,
        task_updated_date=task.updated_date,
        jobs=[CachedJob.model_validate(asdict(job)) for job in scope.jobs],
        cached_at="2026-01-01T00:00:00+00:00",
        shapes=list((shapes or _shapes()).shapes),
    )
    return entry.model_dump_json().encode("utf-8")


def _s3_key(task_id: int, prefix: str = "pfx", job_id: int | None = None) -> str:
    job = task_id if job_id is None else job_id
    return f"{prefix}/.cveta2_cache/task_annotations/task_{task_id}/job_{job}.json"


def _legacy_s3_key(task_id: int, prefix: str = "pfx") -> str:
    return f"{prefix}/.cveta2_cache/task_annotations/task_{task_id}.json"


# ---------------------------------------------------------------------------
# TaskAnnotationCache: local behavior
# ---------------------------------------------------------------------------


class TestLocalCache:
    @pytest.mark.parametrize(
        "corrupt",
        [
            # Schema five held finished records per task, not raw job shapes.
            lambda entry, task: entry.write_bytes(_entry_bytes(task, schema_version=5)),
            lambda entry, task: entry.write_bytes(_entry_bytes(task, schema_version=CACHE_SCHEMA_VERSION + 1)),
            lambda entry, _task: entry.write_bytes(b"{not json!!"),
            # A changed task revision (label edit) must not serve stale shapes.
            lambda entry, task: entry.write_bytes(_entry_bytes(task.model_copy(update={"updated_date": "2025-12-31"}))),
            # A job moved in review or edited without touching the task.
            lambda entry, task: entry.write_bytes(_entry_bytes(task, _scope(job=_job(state="rejected")))),
            lambda entry, task: entry.write_bytes(_entry_bytes(task, _scope(job=_job(stage="validation")))),
            lambda entry, task: entry.write_bytes(_entry_bytes(task, _scope(job=_job(updated_date="2026-01-03")))),
            lambda entry, task: entry.write_bytes(_entry_bytes(task, _scope(job=_job(stop=8)))),
        ],
        ids=[
            "schema-5",
            "future-schema",
            "corrupt-json",
            "older-task-revision",
            "job-state",
            "job-stage",
            "job-updated",
            "job-range",
        ],
    )
    def test_invalid_entry_is_a_miss_and_is_deleted(
        self, tmp_path: Path, corrupt: Callable[[Path, TaskInfo], object]
    ) -> None:
        task = make_task(updated=_UPDATED)
        entry = _entry(tmp_path)
        entry.parent.mkdir()
        corrupt(entry, task)

        assert TaskAnnotationCache(tmp_path).get(task, _scope()) is None
        assert not entry.exists()

    def test_put_creates_group_writable_entry(self, tmp_path: Path) -> None:
        old_umask = os.umask(0o077)
        try:
            cache = TaskAnnotationCache(tmp_path / "cache")
            cache.put(make_task(updated=_UPDATED), _scope(), _shapes())
        finally:
            os.umask(old_umask)

        cache_dir = tmp_path / "cache"
        entry = _entry(cache_dir)
        assert stat.S_IMODE(cache_dir.stat().st_mode) == 0o775
        assert stat.S_IMODE(entry.parent.stat().st_mode) == 0o775
        assert stat.S_IMODE(entry.stat().st_mode) == 0o664

    def test_get_miss_on_empty_dir(self, tmp_path: Path) -> None:
        cache = TaskAnnotationCache(tmp_path / "cache")

        assert cache.get(make_task(updated=_UPDATED), _scope()) is None

    def test_unreadable_entry_is_miss_and_keeps_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """An unreadable entry is a miss, not a crash, and stays on disk.

        Only entries proven *invalid* are dropped; a permission error or a
        broken mount must not propagate out of the fetch.
        """
        cache_dir = tmp_path / "cache"
        cache = TaskAnnotationCache(cache_dir)
        task = make_task(updated=_UPDATED)
        cache.put(task, _scope(), _shapes())

        def _deny(self: Path) -> bytes:
            raise PermissionError(13, "Permission denied", str(self))

        monkeypatch.setattr("pathlib.Path.read_bytes", _deny)

        assert cache.get(task, _scope()) is None
        assert _entry(cache_dir).exists()

    def test_cached_at_is_utc(self, tmp_path: Path) -> None:
        """``cached_at`` carries an explicit UTC offset: the entry is read on other machines."""
        cache_dir = tmp_path / "cache"
        TaskAnnotationCache(cache_dir).put(make_task(updated=_UPDATED), _scope(), _shapes())

        entry = CachedAnnotationsEntry.model_validate_json(_entry(cache_dir).read_bytes())

        assert datetime.fromisoformat(entry.cached_at).tzinfo == timezone.utc

    def test_entry_records_the_job_it_was_cached_against(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / "cache"
        TaskAnnotationCache(cache_dir).put(make_task(updated=_UPDATED), _scope(), _shapes())

        entry = CachedAnnotationsEntry.model_validate_json(_entry(cache_dir).read_bytes())

        assert entry.task_updated_date == _UPDATED
        assert entry.jobs == [
            CachedJob(
                id=1,
                type="annotation",
                start_frame=0,
                stop_frame=9,
                stage="acceptance",
                state="completed",
                updated_date=_JOB_UPDATED,
            )
        ]

    def test_task_scope_entry_is_separate_from_job_entries(self, tmp_path: Path) -> None:
        cache = TaskAnnotationCache(tmp_path)
        task = make_task(updated=_UPDATED)
        whole = AnnotationScope(jobs=(_job(1), _job(2, job_type="ground_truth")), whole_task=True)

        cache.put(task, whole, _shapes(8))

        assert (tmp_path / "task_1" / "task.json").exists()
        assert cache.get(task, _scope()) is None
        assert cache.get(task, whole) == _shapes(8)
        # Any covered job changing invalidates the task-scope entry.
        moved = _job(2, job_type="ground_truth", state="in progress")
        changed = AnnotationScope(jobs=(_job(1), moved), whole_task=True)
        assert cache.get(task, changed) is None

    def test_prune_removes_only_orphans(self, tmp_path: Path) -> None:
        """Two orphans, so the returned count cannot be a constant."""
        cache_dir = tmp_path / "cache"
        cache = TaskAnnotationCache(cache_dir)
        for task_id in (1, 2, 3, 4):
            cache.put(make_task(task_id, updated=_UPDATED), _scope(task_id), _shapes())

        removed = cache.prune({1, 3})

        assert removed == 2
        assert _entry(cache_dir, 1).exists()
        assert not (cache_dir / "task_2").exists()
        assert _entry(cache_dir, 3).exists()
        assert not (cache_dir / "task_4").exists()

    def test_prune_on_missing_dir_returns_zero(self, tmp_path: Path) -> None:
        cache = TaskAnnotationCache(tmp_path / "nonexistent")

        assert cache.prune({1}) == 0

    def test_keep_only_drops_entries_of_vanished_jobs(self, tmp_path: Path) -> None:
        cache = TaskAnnotationCache(tmp_path)
        task = make_task(updated=_UPDATED)
        for job_id in (1, 2):
            cache.put(task, _scope(job_id), _shapes())
        cache.put(task, AnnotationScope(jobs=(_job(1),), whole_task=True), _shapes())

        cache.keep_only(1, [_scope(1)])

        assert sorted(path.name for path in (tmp_path / "task_1").iterdir()) == ["job_1.json"]

    def test_remove_legacy_entries_counts_only_old_task_files(self, tmp_path: Path) -> None:
        cache = TaskAnnotationCache(tmp_path)
        cache.put(make_task(updated=_UPDATED), _scope(), _shapes())
        for name in ("task_5.json", "task_6.json"):
            (tmp_path / name).write_text("{}", encoding="utf-8")
        (tmp_path / "task_x.json").write_text("{}", encoding="utf-8")

        assert cache.remove_legacy_entries() == 2
        assert sorted(path.name for path in tmp_path.iterdir()) == ["task_1", "task_x.json"]
        assert cache.remove_legacy_entries() == 0

    def test_atomic_write_leaves_no_tmp_files(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / "cache"
        cache = TaskAnnotationCache(cache_dir)

        cache.put(make_task(updated=_UPDATED), _scope(), _shapes())

        leftovers = [p.name for p in cache_dir.rglob("*") if ".tmp" in p.name]
        assert leftovers == []

    def test_invalidate_local_removes_every_entry_and_the_legacy_file(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / "cache"
        cache = TaskAnnotationCache(cache_dir)
        cache.put(make_task(updated=_UPDATED), _scope(1), _shapes())
        cache.put(make_task(updated=_UPDATED), _scope(2), _shapes())
        (cache_dir / "task_1.json").write_text("{}", encoding="utf-8")
        cache.put(make_task(12, updated=_UPDATED), _scope(3), _shapes())

        cache.invalidate_local(1)

        assert not (cache_dir / "task_1").exists()
        assert not (cache_dir / "task_1.json").exists()
        assert _entry(cache_dir, 12, 3).exists()
        cache.invalidate_local(1)

    def test_round_trip_preserves_shapes(self, tmp_path: Path) -> None:
        cache = TaskAnnotationCache(tmp_path / "cache")
        task = make_task(updated=_UPDATED)
        shapes = RawAnnotations(shapes=[make_raw_shape(id=3, frame=2), make_raw_shape(id=4, frame=5, type="polygon")])
        cache.put(task, _scope(), shapes)

        assert cache.get(task, _scope()) == shapes


# ---------------------------------------------------------------------------
# get_task_cache_dir / invalidate_local_entry
# ---------------------------------------------------------------------------


class TestCacheDir:
    def test_uses_xdg_cache_home(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))

        result = get_task_cache_dir(5)

        assert result == tmp_path / "xdg" / "cveta2" / "task_annotations" / "project_5"

    def test_falls_back_to_home_cache(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path))

        result = get_task_cache_dir(7)

        expected = tmp_path / ".cache" / "cveta2" / "task_annotations" / "project_7"
        assert result == expected

    def test_invalidate_local_entry_helper(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
        cache = TaskAnnotationCache(get_task_cache_dir(5))
        cache.put(make_task(updated=_UPDATED), _scope(), _shapes())
        entry = _entry(get_task_cache_dir(5))
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

    The body is typed loosely on purpose: the point is to feed the backend
    shapes botocore's own stubs forbid.
    """

    def __init__(self, error_response: Any) -> None:
        """Fail every read with *error_response* as the ClientError body."""
        super().__init__()
        self._error_response = error_response

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:  # noqa: N803
        self.get_calls.append(f"{Bucket}/{Key}")
        raise ClientError(self._error_response, "GetObject")


class TestS3Backend:
    def test_schema_five_entry_is_rejected_without_local_backfill(self, tmp_path: Path) -> None:
        task = make_task(updated=_UPDATED)
        key = f"bkt/{_s3_key(task.id)}"
        fake_s3 = FakeS3Client({key: _entry_bytes(task, schema_version=5)})
        cache = TaskAnnotationCache(tmp_path / "local", s3=S3CacheBackend(fake_s3, "bkt", "pfx"))

        assert cache.get(task, _scope()) is None
        assert fake_s3.get_calls == [key]
        assert not _entry(tmp_path / "local").exists()

    def test_an_old_per_task_object_is_never_read(self, tmp_path: Path) -> None:
        task = make_task(updated=_UPDATED)
        fake_s3 = FakeS3Client({f"bkt/{_legacy_s3_key(1)}": _entry_bytes(task)})
        cache = TaskAnnotationCache(tmp_path / "local", s3=S3CacheBackend(fake_s3, "bkt", "pfx"))

        assert cache.get(task, _scope()) is None
        assert fake_s3.get_calls == [f"bkt/{_s3_key(1)}"]

    @pytest.fixture(autouse=True)
    def _single_attempt(self) -> Generator[None, None, None]:
        """``_FailingS3Client`` raises a retryable fault; one attempt is enough."""
        previous = (RetryPolicy.attempts, RetryPolicy.max_wait)
        configure_retries(1, 0.01)
        yield
        configure_retries(*previous)

    def test_s3_hit_backfills_local(self, tmp_path: Path) -> None:
        task = make_task(updated=_UPDATED)
        fake_s3 = FakeS3Client({f"bkt/{_s3_key(1)}": _entry_bytes(task)})
        cache = TaskAnnotationCache(tmp_path / "local", s3=S3CacheBackend(fake_s3, "bkt", "pfx"))

        assert cache.get(task, _scope()) == _shapes()
        assert _entry(tmp_path / "local").exists()

    def test_local_hit_never_touches_s3(self, tmp_path: Path) -> None:
        task = make_task(updated=_UPDATED)
        local_dir = tmp_path / "local"
        TaskAnnotationCache(local_dir).put(task, _scope(), _shapes())
        fake_s3 = FakeS3Client()
        cache = TaskAnnotationCache(local_dir, s3=S3CacheBackend(fake_s3, "bkt", "pfx"))

        assert cache.get(task, _scope()) == _shapes()
        assert fake_s3.get_calls == []

    def test_put_writes_local_and_s3_and_drops_the_old_object_once(self, tmp_path: Path) -> None:
        legacy = f"bkt/{_legacy_s3_key(1)}"
        fake_s3 = FakeS3Client({legacy: b"old format", f"bkt/{_legacy_s3_key(10)}": b"other task"})
        cache = TaskAnnotationCache(tmp_path / "local", s3=S3CacheBackend(fake_s3, "bkt", "pfx"))

        cache.put(make_task(updated=_UPDATED), _scope(1), _shapes())
        cache.put(make_task(updated=_UPDATED), _scope(2), _shapes())

        assert _entry(tmp_path / "local").exists()
        assert fake_s3.put_calls == [f"bkt/{_s3_key(1)}", f"bkt/{_s3_key(1, job_id=2)}"]
        assert fake_s3.delete_calls == [legacy]
        assert legacy not in fake_s3.objects
        assert f"bkt/{_legacy_s3_key(10)}" in fake_s3.objects

    def test_invalidate_drops_every_s3_entry_of_the_task_only(self, tmp_path: Path) -> None:
        """A task mutation must not be undone by the S3 mirror, nor touch task 12's neighbour 123."""
        task = make_task(12, updated=_UPDATED)
        fake_s3 = FakeS3Client()
        cache = TaskAnnotationCache(tmp_path / "local", s3=S3CacheBackend(fake_s3, "bkt", "pfx"))
        cache.put(task, _scope(1), _shapes())
        cache.put(task, _scope(2), _shapes())
        cache.put(make_task(123, updated=_UPDATED), _scope(3), _shapes())
        fake_s3.delete_calls.clear()

        cache.invalidate(12)

        assert cache.get(task, _scope(1)) is None
        assert sorted(fake_s3.delete_calls) == sorted(
            [f"bkt/{_s3_key(12, job_id=1)}", f"bkt/{_s3_key(12, job_id=2)}", f"bkt/{_legacy_s3_key(12)}"]
        )
        assert list(fake_s3.objects) == [f"bkt/{_s3_key(123, job_id=3)}"]
        assert fake_s3.list_requests[-1]["Prefix"] == "pfx/.cveta2_cache/task_annotations/task_12/"
        assert not (tmp_path / "local" / "task_12").exists()

    def test_invalidate_without_s3_only_removes_locally(self, tmp_path: Path) -> None:
        task = make_task(updated=_UPDATED)
        cache = TaskAnnotationCache(tmp_path / "local")
        cache.put(task, _scope(), _shapes())

        cache.invalidate(1)

        assert cache.get(task, _scope()) is None
        assert not (tmp_path / "local" / "task_1").exists()

    def test_deleting_a_task_without_entries_only_drops_the_old_key(self) -> None:
        fake_s3 = FakeS3Client()
        backend = S3CacheBackend(fake_s3, "bkt", "pfx")

        backend.delete_task(1)
        backend.put("task_1/job_1.json", b"data")

        assert fake_s3.delete_calls == [f"bkt/{_legacy_s3_key(1)}"]
        assert fake_s3.objects[f"bkt/{_s3_key(1)}"] == b"data"

    def test_failing_listing_disables_s3_and_still_removes_locally(
        self, tmp_path: Path, capture_logs: list[str]
    ) -> None:
        task = make_task(updated=_UPDATED)
        local_dir = tmp_path / "local"
        TaskAnnotationCache(local_dir).put(task, _scope(), _shapes())
        failing = _FailingS3Client()
        backend = S3CacheBackend(failing, "bkt", "pfx")
        cache = TaskAnnotationCache(local_dir, s3=backend)

        cache.invalidate(1)
        backend.delete_task(1)
        backend.put("task_1/job_1.json", b"data")

        assert not (local_dir / "task_1").exists()
        assert failing.calls == 1
        warnings = [m for m in capture_logs if "S3-кэш" in m]
        assert len(warnings) == 1
        assert "s3.invalid" in warnings[0]

    def test_stale_s3_entry_ignored_without_remote_delete(self, tmp_path: Path) -> None:
        task = make_task(updated=_UPDATED)
        key = f"bkt/{_s3_key(1)}"
        fake_s3 = FakeS3Client({key: _entry_bytes(task, schema_version=CACHE_SCHEMA_VERSION + 1)})
        cache = TaskAnnotationCache(tmp_path / "local", s3=S3CacheBackend(fake_s3, "bkt", "pfx"))

        assert cache.get(task, _scope()) is None
        assert key in fake_s3.objects
        assert not _entry(tmp_path / "local").exists()

    @pytest.mark.parametrize(
        ("cached_task", "cached_scope"),
        [
            (make_task(updated="2025-01-01T00:00:00"), _scope()),
            (make_task(updated=_UPDATED), _scope(job=_job(state="in progress"))),
        ],
        ids=["bumped-task-date", "job-moved-back"],
    )
    def test_a_stale_s3_entry_is_rejected_without_backfill(
        self, tmp_path: Path, cached_task: TaskInfo, cached_scope: AnnotationScope
    ) -> None:
        key = f"bkt/{_s3_key(1)}"
        fake_s3 = FakeS3Client({key: _entry_bytes(cached_task, cached_scope)})
        cache = TaskAnnotationCache(tmp_path / "local", s3=S3CacheBackend(fake_s3, "bkt", "pfx"))

        assert cache.get(make_task(updated=_UPDATED), _scope()) is None
        assert not _entry(tmp_path / "local").exists()

    def test_missing_key_is_plain_miss_not_disable(self, tmp_path: Path) -> None:
        fake_s3 = FakeS3Client()
        backend = S3CacheBackend(fake_s3, "bkt", "pfx")
        cache = TaskAnnotationCache(tmp_path / "local", s3=backend)

        assert cache.get(make_task(1, updated=_UPDATED), _scope(1)) is None
        assert cache.get(make_task(2, updated=_UPDATED), _scope(2)) is None
        assert len(fake_s3.get_calls) == 2

    @pytest.mark.parametrize("code", ["404", "NoSuchBucket"])
    def test_every_missing_key_code_is_a_plain_miss(self, code: str, tmp_path: Path, capture_logs: list[str]) -> None:
        """``404`` and ``NoSuchBucket`` behave exactly like ``NoSuchKey``."""
        s3 = _ClientErrorS3Client({"Error": {"Code": code}})
        cache = TaskAnnotationCache(tmp_path / "local", s3=S3CacheBackend(s3, "bkt", "pfx"))

        assert cache.get(make_task(1, updated=_UPDATED), _scope(1)) is None
        assert cache.get(make_task(2, updated=_UPDATED), _scope(2)) is None

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
        """Anything that is not a known missing-key code is fatal for the run, never raised."""
        s3 = _ClientErrorS3Client(error_response)
        cache = TaskAnnotationCache(tmp_path / "local", s3=S3CacheBackend(s3, "bkt", "pfx"))

        assert cache.get(make_task(1, updated=_UPDATED), _scope(1)) is None
        assert cache.get(make_task(2, updated=_UPDATED), _scope(2)) is None

        assert len(s3.get_calls) == 1
        assert sum("S3-кэш" in m for m in capture_logs) == 1

    def test_put_mirrors_a_readable_entry_to_s3(self, tmp_path: Path) -> None:
        """Another machine's cache can read what ``put`` mirrored."""
        fake_s3 = FakeS3Client()
        task = make_task(updated=_UPDATED)
        writer = TaskAnnotationCache(tmp_path / "writer", s3=S3CacheBackend(fake_s3, "bkt", "pfx"))
        writer.put(task, _scope(), _shapes())

        reader = TaskAnnotationCache(tmp_path / "reader", s3=S3CacheBackend(fake_s3, "bkt", "pfx"))

        assert reader.get(task, _scope()) == _shapes()

    def test_get_failure_warns_once_and_disables(self, tmp_path: Path, capture_logs: list[str]) -> None:
        failing = _FailingS3Client()
        cache = TaskAnnotationCache(tmp_path / "local", s3=S3CacheBackend(failing, "bkt", "pfx"))

        assert cache.get(make_task(1, updated=_UPDATED), _scope(1)) is None
        assert cache.get(make_task(2, updated=_UPDATED), _scope(2)) is None
        cache.put(make_task(3, updated=_UPDATED), _scope(3), _shapes())

        assert failing.calls == 1
        assert sum("S3-кэш" in m for m in capture_logs) == 1

    def test_put_failure_keeps_local_entry(self, tmp_path: Path, capture_logs: list[str]) -> None:
        failing = _FailingS3Client()
        cache = TaskAnnotationCache(tmp_path / "local", s3=S3CacheBackend(failing, "bkt", "pfx"))
        task = make_task(updated=_UPDATED)

        cache.put(task, _scope(), _shapes())

        assert cache.get(task, _scope()) == _shapes()
        assert failing.calls == 1
        assert sum("S3-кэш" in m for m in capture_logs) == 1

    def test_a_denied_old_object_delete_keeps_the_mirror(self, tmp_path: Path, capture_logs: list[str]) -> None:
        """A bucket that allows Get/Put but not Delete keeps serving the shared cache."""

        class _NoDelete(FakeS3Client):
            def delete_object(self, *, Bucket: str, Key: str) -> None:  # noqa: N803
                self.delete_calls.append(f"{Bucket}/{Key}")
                raise ClientError({"Error": {"Code": "AccessDenied"}}, "DeleteObject")

        fake_s3 = _NoDelete()
        cache = TaskAnnotationCache(tmp_path / "local", s3=S3CacheBackend(fake_s3, "bkt", "pfx"))
        for task_id in (1, 2):
            cache.put(make_task(task_id, updated=_UPDATED), _scope(task_id), _shapes())

        reader = TaskAnnotationCache(tmp_path / "reader", s3=cache._s3)
        assert reader.get(make_task(2, updated=_UPDATED), _scope(2)) == _shapes()
        assert fake_s3.put_calls == [f"bkt/{_s3_key(1)}", f"bkt/{_s3_key(2)}"]
        assert fake_s3.delete_calls == [f"bkt/{_legacy_s3_key(1)}"]
        assert sum("старого формата" in m for m in capture_logs) == 1
        assert not any("недоступен" in m for m in capture_logs)

    def test_from_cloud_storage_none(self) -> None:
        assert S3CacheBackend.from_cloud_storage(None) is None

    def test_from_cloud_storage_builds_backend(self) -> None:
        cs_info = CloudStorageInfo(id=1, bucket="bkt", prefix="pfx", endpoint_url="http://minio:9000")
        fake_s3 = FakeS3Client()

        with patch("cveta2.adapters.s3.task_cache.make_s3_client", return_value=fake_s3) as make_client:
            backend = S3CacheBackend.from_cloud_storage(cs_info)

        assert backend is not None
        make_client.assert_called_once_with("http://minio:9000")
        backend.put("task_1/job_1.json", b"data")
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
) -> pd.DataFrame:
    """Drive ``fetch_selected_tasks`` with a fake API and return its dataset.csv.

    ``FakeCvatApi.get_project_cloud_storage`` returns None, so the S3
    backend is never built — the cache stays local-only.  The task
    selector always targets the fixture's first task.
    """
    fetch_selected_tasks(
        CvatClient(CFG, api=fake_api),
        FetchTarget(fake.project.id, fake.project.name, output_dir, cs_info),
        replace(options, task_selector=[fake.tasks[0].name]),
    )
    return pd.read_csv(output_dir / "dataset.csv")


class TestFetchWithCache:
    def test_second_fetch_reads_no_annotations_of_finished_jobs(
        self, normal_fake: LoadedFixtures, tmp_path: Path
    ) -> None:
        fake = normal_fake
        api = FakeCvatApi(fake)

        df1 = _fetch_task_cached(api, fake, tmp_path / "out1", FetchOptions())
        assert len(api.annotation_calls) == 1

        df2 = _fetch_task_cached(api, fake, tmp_path / "out2", FetchOptions(save_tasks=True))

        assert len(api.annotation_calls) == 1
        assert api.job_annotation_calls == []
        # Completion and job positions are rebuilt from a fresh jobs list every time.
        assert api.call_counts["get_task_jobs"] == 2
        pd.testing.assert_frame_equal(df1, df2)
        task_csv = tmp_path / "out2" / ".tasks" / f"task_{fake.tasks[0].id}.csv"
        assert task_csv.exists()

    def test_force_refetches_and_no_cache_disables(self, normal_fake: LoadedFixtures, tmp_path: Path) -> None:
        fake = normal_fake
        api = FakeCvatApi(fake)

        _fetch_task_cached(api, fake, tmp_path / "out1", FetchOptions())
        _fetch_task_cached(api, fake, tmp_path / "out2", FetchOptions(force=True))
        assert len(api.annotation_calls) == 2

        _fetch_task_cached(api, fake, tmp_path / "out3", FetchOptions(use_cache=False))
        assert len(api.annotation_calls) == 3

        _fetch_task_cached(api, fake, tmp_path / "out4", FetchOptions())
        assert len(api.annotation_calls) == 3

    def test_unfinished_jobs_are_never_cached(self, coco8_fixtures: LoadedFixtures, tmp_path: Path) -> None:
        fake = build_fake(coco8_fixtures, ["normal"], statuses=["annotation"])
        api = FakeCvatApi(fake)

        for out in ("out1", "out2"):
            _fetch_task_cached(api, fake, tmp_path / out, FetchOptions())

        assert len(api.annotation_calls) == 2
        assert not (get_task_cache_dir(fake.project.id) / f"task_{fake.tasks[0].id}").exists()

    def test_cached_entry_holds_no_machine_paths(self, normal_fake: LoadedFixtures, tmp_path: Path) -> None:
        fake = normal_fake
        api = FakeCvatApi(fake)
        cs_info = CloudStorageInfo(id=1, bucket="bkt", prefix="pfx", endpoint_url="")

        df = _fetch_task_cached(api, fake, tmp_path / "out", FetchOptions(), cs_info)

        assert df["s3_image_path"].str.startswith("pfx/").all()
        raw = _entry(get_task_cache_dir(fake.project.id), fake.tasks[0].id).read_bytes()
        assert b"image_path" not in raw
        assert b"pfx/" not in raw

    def test_shapes_without_frame_metadata_warn_on_every_fetch(self, tmp_path: Path, capture_logs: list[str]) -> None:
        """The missing-frame summary is a consistency signal, so a cache hit repeats it."""
        task = make_task()
        api = FakeCvatApi(
            LoadedFixtures(
                project=ProjectInfo(id=1, name="audit-project"),
                tasks=[task],
                labels=[],
                task_data={
                    task.id: (
                        RawDataMeta([RawFrame("a.jpg", 20, 20)]),
                        RawAnnotations(shapes=[make_raw_shape(id=1, frame=0), make_raw_shape(id=2, frame=5)]),
                    )
                },
            )
        )
        fake = LoadedFixtures(project=ProjectInfo(id=1, name="audit-project"), tasks=[task], labels=[], task_data={})
        api.jobs[task.id] = [_job(task.id, start=0, stop=9)]

        for out in ("first", "second"):
            capture_logs.clear()
            _fetch_task_cached(api, fake, tmp_path / out, FetchOptions())
            assert sum("без метаданных кадра: 1" in message for message in capture_logs) == 1, out
        assert api.annotation_calls == [task.id]

    def test_issues_are_read_live_on_every_fetch(self, tmp_path: Path) -> None:
        """Issues are not cached: a failed read neither blocks caching nor sticks."""
        task = make_task()
        api = FakeCvatApi(
            LoadedFixtures(
                project=ProjectInfo(id=1, name="audit-project"),
                tasks=[task],
                labels=[],
                task_data={
                    task.id: (
                        RawDataMeta([RawFrame("a.jpg", 20, 20)]),
                        RawAnnotations(),
                    )
                },
            )
        )
        config = tmp_path / "config.yaml"
        config.write_text(f"cache:\n  tasks_root: {tmp_path / 'cache'}\n", encoding="utf-8")
        connection = cveta2.Connection(client=CvatClient(CFG, api=api), config_path=config)

        def fetch(out: str) -> pd.DataFrame:
            return cveta2.fetch(
                "audit-project",
                tmp_path / out,
                connection=connection,
                download_images=False,
            ).dataset

        review = [RawIssue(id=1, frame=0, resolved=False, comments=["review this"])]
        with patch.object(
            api,
            "get_task_issues",
            side_effect=[CvatApiError("temporary", status_code=500), review, []],
        ) as issues:
            assert fetch("first").loc[0, "issue_text"] == ""
            assert list((tmp_path / "cache").rglob("job_*.json"))
            second, third = fetch("second"), fetch("third")
        assert second.loc[0, "issue_text"] == "review this"
        assert third.loc[0, "issue_text"] == ""
        assert issues.call_count == 3
        assert api.annotation_calls == [task.id]


# ---------------------------------------------------------------------------
# Job freshness: the per-job entries against changing jobs
# ---------------------------------------------------------------------------

_HALF = 3  # The coco8 "normal" task has eight frames: jobs 0-3 and 4-7.


def _two_jobs(api: FakeCvatApi, task_id: int, **second: str) -> None:
    """Split the task into two finished jobs; *second* overrides the later one."""
    api.jobs[task_id] = [
        _job(501, start=0, stop=_HALF),
        _job(502, start=_HALF + 1, stop=7, **second),
    ]


class TestJobFreshness:
    def test_a_job_moved_without_touching_the_task_is_noticed(
        self, normal_fake: LoadedFixtures, tmp_path: Path
    ) -> None:
        """The case the old per-task cache served stale: same task date, job sent back."""
        fake = normal_fake
        task_id = fake.tasks[0].id
        api = FakeCvatApi(fake)
        _two_jobs(api, task_id)
        first = _fetch_task_cached(api, fake, tmp_path / "out1", FetchOptions())
        assert first["task_completed"].all()

        _two_jobs(api, task_id, stage="annotation", state="in progress", updated_date="2026-01-05T00:00:00")
        second = _fetch_task_cached(api, fake, tmp_path / "out2", FetchOptions())

        assert not second["task_completed"].any()
        moved = second[second["frame_id"] > _HALF]
        assert set(moved["job_stage"]) == {"annotation"}
        assert set(second[second["frame_id"] <= _HALF]["job_stage"]) == {"acceptance"}
        # Only the moved job's shapes were read again, from its own endpoint.
        assert api.annotation_calls == [task_id]
        assert api.job_annotation_calls == [502]
        cache_dir = get_task_cache_dir(fake.project.id)
        assert _entry(cache_dir, task_id, 501).exists()
        assert not _entry(cache_dir, task_id, 502).exists()

    def test_only_the_changed_job_is_read_again(self, normal_fake: LoadedFixtures, tmp_path: Path) -> None:
        fake = normal_fake
        task_id = fake.tasks[0].id
        api = FakeCvatApi(fake)
        _two_jobs(api, task_id)
        cold = _fetch_task_cached(api, fake, tmp_path / "cold", FetchOptions())
        cache_dir = get_task_cache_dir(fake.project.id)
        assert {path.name for path in (cache_dir / f"task_{task_id}").iterdir()} == {"job_501.json", "job_502.json"}

        warm = _fetch_task_cached(api, fake, tmp_path / "warm", FetchOptions())
        _two_jobs(api, task_id, updated_date="2026-01-06T00:00:00")
        partial = _fetch_task_cached(api, fake, tmp_path / "partial", FetchOptions())

        assert api.annotation_calls == [task_id]
        assert api.job_annotation_calls == [502]
        pd.testing.assert_frame_equal(cold, warm)
        pd.testing.assert_frame_equal(cold, partial)

    def test_a_task_date_change_rereads_every_job(self, normal_fake: LoadedFixtures, tmp_path: Path) -> None:
        """A label edit moves only the task date; every entry depends on it."""
        fake = normal_fake
        task = fake.tasks[0]
        api = FakeCvatApi(fake)
        _two_jobs(api, task.id)
        _fetch_task_cached(api, fake, tmp_path / "out1", FetchOptions())

        relabelled = fake._replace(tasks=[task.model_copy(update={"updated_date": "2026-02-02T00:00:00+00:00"})])
        api2 = FakeCvatApi(relabelled)
        _two_jobs(api2, task.id)
        _fetch_task_cached(api2, relabelled, tmp_path / "out2", FetchOptions())

        assert api2.annotation_calls == [task.id]
        assert api2.job_annotation_calls == []

    @pytest.mark.parametrize(
        "jobs",
        [
            pytest.param(
                [_job(501, start=0, stop=_HALF), _job(502, start=_HALF + 1, stop=7)],
                id="separable",
            ),
            pytest.param(
                [_job(501, start=0, stop=7), _job(509, start=0, stop=7, job_type="ground_truth")],
                id="ground-truth",
            ),
            pytest.param(
                [_job(501, start=0, stop=4), _job(502, start=4, stop=7)],
                id="overlap",
            ),
            pytest.param(
                [_job(501, start=0, stop=_HALF), _job(502, start=_HALF + 1, stop=7, state="in progress")],
                id="one-unfinished",
            ),
            # Frames 3 and 4 belong to no job: the task response cannot be split.
            pytest.param(
                [_job(501, start=0, stop=2), _job(502, start=5, stop=7)],
                id="gap",
            ),
        ],
    )
    def test_cached_reads_reassemble_the_uncached_result(
        self, normal_fake: LoadedFixtures, tmp_path: Path, jobs: list[RawJob]
    ) -> None:
        """Cold, warm and cache-off fetches give the same rows in the same order."""
        fake = normal_fake
        task_id = fake.tasks[0].id
        api = FakeCvatApi(fake)
        api.jobs[task_id] = jobs

        off = _fetch_task_cached(api, fake, tmp_path / "off", FetchOptions(use_cache=False))
        cold = _fetch_task_cached(api, fake, tmp_path / "cold", FetchOptions())
        warm = _fetch_task_cached(api, fake, tmp_path / "warm", FetchOptions())

        assert len(off) > 0
        pd.testing.assert_frame_equal(off, cold)
        pd.testing.assert_frame_equal(off, warm)

    @pytest.mark.parametrize(
        ("second_type", "second_start"),
        [("ground_truth", 0), ("consensus_replica", 0), ("ground_truth", 6)],
        ids=["ground-truth", "consensus", "ground-truth-own-range"],
    )
    def test_inseparable_jobs_share_one_task_entry(
        self, normal_fake: LoadedFixtures, tmp_path: Path, second_type: str, second_start: int
    ) -> None:
        """Any non-annotation job makes the task one entry, even on frames of its own."""
        fake = normal_fake
        task_id = fake.tasks[0].id
        api = FakeCvatApi(fake)
        first_stop = 7 if second_start == 0 else second_start - 1
        api.jobs[task_id] = [
            _job(501, start=0, stop=first_stop),
            _job(509, start=second_start, stop=7, job_type=second_type),
        ]
        _fetch_task_cached(api, fake, tmp_path / "out1", FetchOptions())
        cache_dir = get_task_cache_dir(fake.project.id)
        assert [path.name for path in (cache_dir / f"task_{task_id}").iterdir()] == ["task.json"]

        _fetch_task_cached(api, fake, tmp_path / "out2", FetchOptions())
        rejected = _job(509, start=second_start, stop=7, job_type=second_type, state="rejected")
        api.jobs[task_id] = [_job(501, start=0, stop=first_stop), rejected]
        _fetch_task_cached(api, fake, tmp_path / "out3", FetchOptions())

        assert api.annotation_calls == [task_id, task_id]
        assert api.job_annotation_calls == []

    def test_a_job_without_an_update_time_is_never_cached(self, normal_fake: LoadedFixtures, tmp_path: Path) -> None:
        """An empty time always matches, so such a job's edits could not be noticed."""
        fake = normal_fake
        task_id = fake.tasks[0].id
        api = FakeCvatApi(fake)
        api.jobs[task_id] = [_job(501, start=0, stop=_HALF), _job(502, start=_HALF + 1, stop=7, updated_date="")]

        for out in ("out1", "out2"):
            _fetch_task_cached(api, fake, tmp_path / out, FetchOptions())

        cache_dir = get_task_cache_dir(fake.project.id)
        assert [path.name for path in (cache_dir / f"task_{task_id}").glob("job_*.json")] == ["job_501.json"]
        assert api.job_annotation_calls == [502]

    def test_a_vanished_job_loses_its_entry(self, normal_fake: LoadedFixtures, tmp_path: Path) -> None:
        fake = normal_fake
        task_id = fake.tasks[0].id
        api = FakeCvatApi(fake)
        _two_jobs(api, task_id)
        _fetch_task_cached(api, fake, tmp_path / "out1", FetchOptions())

        api.jobs[task_id] = [_job(501, start=0, stop=7)]
        _fetch_task_cached(api, fake, tmp_path / "out2", FetchOptions())

        cache_dir = get_task_cache_dir(fake.project.id)
        assert [path.name for path in (cache_dir / f"task_{task_id}").iterdir()] == ["job_501.json"]


class TestLegacyEntries:
    def test_first_fetch_removes_old_local_entries_and_reports_them(
        self, normal_fake: LoadedFixtures, tmp_path: Path, capture_info_logs: list[str]
    ) -> None:
        fake = normal_fake
        cache_dir = get_task_cache_dir(fake.project.id)
        cache_dir.mkdir(parents=True)
        old = [cache_dir / f"task_{fake.tasks[0].id}.json", cache_dir / "task_999.json"]
        for path in old:
            path.write_text('{"schema_version": 5}', encoding="utf-8")
        api = FakeCvatApi(fake)

        _fetch_task_cached(api, fake, tmp_path / "out1", FetchOptions())
        assert not any(path.exists() for path in old)
        assert api.annotation_calls == [fake.tasks[0].id]
        assert any("записей старого формата: 2" in message for message in capture_info_logs)

        capture_info_logs.clear()
        _fetch_task_cached(api, fake, tmp_path / "out2", FetchOptions())
        assert not any("старого формата" in message for message in capture_info_logs)

    def test_the_old_s3_object_goes_when_the_task_is_written(self, normal_fake: LoadedFixtures, tmp_path: Path) -> None:
        fake = normal_fake
        task_id = fake.tasks[0].id
        legacy = f"bkt/{_legacy_s3_key(task_id)}"
        untouched = f"bkt/{_legacy_s3_key(999)}"
        foreign = "bkt/pfx/images/task_1.json"
        fake_s3 = FakeS3Client({legacy: b"old", untouched: b"old", foreign: b"image"})

        with patch("cveta2.adapters.s3.task_cache.make_s3_client", return_value=fake_s3):
            fetch_selected_tasks(
                CvatClient(CFG, api=FakeCvatApi(fake, cloud_storage=_PROJECT_STORAGE)),
                FetchTarget(fake.project.id, fake.project.name, tmp_path / "out", None),
                FetchOptions(task_selector=[fake.tasks[0].name]),
            )

        assert legacy not in fake_s3.objects
        assert untouched in fake_s3.objects
        assert foreign in fake_s3.objects
        assert fake_s3.delete_calls == [legacy]


class TestFullFetchPrunesCache:
    def test_full_fetch_prunes_orphaned_entries(self, normal_fake: LoadedFixtures, tmp_path: Path) -> None:
        fake = normal_fake
        api = FakeCvatApi(fake)
        cache_dir = get_task_cache_dir(fake.project.id)
        TaskAnnotationCache(cache_dir).put(make_task(999, updated=_UPDATED), _scope(999), _shapes())

        fetch_project(
            CvatClient(CFG, api=api),
            FetchTarget(fake.project.id, fake.project.name, tmp_path / "out", None),
            FetchOptions(use_cache=True),
        )

        assert not (cache_dir / "task_999").exists()
        assert _entry(cache_dir, fake.tasks[0].id).exists()


# ---------------------------------------------------------------------------
# Cache settings (tasks_root / task_cache_s3)
# ---------------------------------------------------------------------------


class TestCacheSettings:
    def test_cache_dir_with_custom_root(self, tmp_path: Path) -> None:
        result = get_task_cache_dir(5, root=tmp_path / "tasks")

        assert result == tmp_path / "tasks" / "project_5"

    def test_invalidate_local_entry_honors_tasks_root(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text(f"cache:\n  tasks_root: {tmp_path / 'tasks'}\n", encoding="utf-8")
        monkeypatch.setenv("CVETA2_CONFIG", str(cfg_path))
        cache_dir = get_task_cache_dir(5, root=tmp_path / "tasks")
        TaskAnnotationCache(cache_dir).put(make_task(updated=_UPDATED), _scope(), _shapes())
        entry = _entry(cache_dir)
        assert entry.exists()

        invalidate_local_entry(5, 1, "")

        assert not entry.exists()

    def test_invalidate_local_entry_prefers_project_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A per-project ``tasks_root`` wins over the global one."""
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
        TaskAnnotationCache(cache_dir).put(make_task(updated=_UPDATED), _scope(), _shapes())

        invalidate_local_entry(5, 1, "proj")

        assert not _entry(cache_dir).exists()

    def test_invalidate_local_entry_drops_the_default_s3_entry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
        cache_dir = get_task_cache_dir(5)
        TaskAnnotationCache(cache_dir).put(make_task(updated=_UPDATED), _scope(), _shapes())
        key = f"bkt/{_s3_key(1)}"
        fake_s3 = FakeS3Client({key: b"stale"})

        with patch("cveta2.adapters.s3.task_cache.make_s3_client", return_value=fake_s3):
            invalidate_local_entry(5, 1, "", _PROJECT_STORAGE)

        assert not _entry(cache_dir).exists()
        assert fake_s3.delete_calls == [key, f"bkt/{_legacy_s3_key(1)}"]
        assert key not in fake_s3.objects

    def test_invalidate_local_entry_honors_task_cache_s3(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """The explicit-location keys are the ones dropped, not the default ones."""
        config_path = write_split_config_yaml(
            tmp_path / "cfg.yaml",
            project_ids={"proj": 5},
            cache={"projects": {"proj": {"task_cache_s3": "s3://ml-cache/proj"}}},
        )
        monkeypatch.setenv("CVETA2_CONFIG", str(config_path))
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
        explicit_key = "ml-cache/proj/task_annotations/task_1/job_1.json"
        default_key = f"bkt/{_s3_key(1)}"
        fake_s3 = FakeS3Client({explicit_key: b"stale", default_key: b"other"})

        with patch("cveta2.adapters.s3.task_cache.make_s3_client", return_value=fake_s3):
            invalidate_local_entry(5, 1, "proj", _PROJECT_STORAGE)

        assert fake_s3.delete_calls == [explicit_key, "ml-cache/proj/task_annotations/task_1.json"]
        assert explicit_key not in fake_s3.objects
        assert default_key in fake_s3.objects

    def test_invalidate_local_entry_leaves_s3_alone_when_cache_disabled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``CVETA2_DISABLE_CACHE`` means no S3 traffic at all, deletes included."""
        monkeypatch.setenv("CVETA2_DISABLE_CACHE", "true")
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
        cache_dir = get_task_cache_dir(5)
        TaskAnnotationCache(cache_dir).put(make_task(updated=_UPDATED), _scope(), _shapes())
        key = f"bkt/{_s3_key(1)}"
        fake_s3 = FakeS3Client({key: b"stale"})

        with patch("cveta2.adapters.s3.task_cache.make_s3_client", return_value=fake_s3) as make_client:
            invalidate_local_entry(5, 1, "", _PROJECT_STORAGE)

        make_client.assert_not_called()
        assert fake_s3.delete_calls == []
        assert key in fake_s3.objects
        assert not _entry(cache_dir).exists()

    def test_explicit_location_uses_plain_task_annotations_key(self, tmp_path: Path) -> None:
        fake_s3 = FakeS3Client()
        backend = S3CacheBackend(fake_s3, "ml-cache", "proj", explicit_location=True)
        cache = TaskAnnotationCache(tmp_path / "local", s3=backend)

        cache.put(make_task(updated=_UPDATED), _scope(), _shapes())

        assert fake_s3.put_calls == ["ml-cache/proj/task_annotations/task_1/job_1.json"]

    @pytest.mark.parametrize(
        ("task_cache_s3", "expected_key"),
        [
            (None, "bkt/pfx/.cveta2_cache/task_annotations/task_1/job_1.json"),
            ("s3://ml-cache/proj", "ml-cache/proj/task_annotations/task_1/job_1.json"),
            ("_cveta2_cache", "bkt/_cveta2_cache/task_annotations/task_1/job_1.json"),
        ],
        ids=["default-layout", "full-url-other-bucket", "bare-prefix-same-bucket"],
    )
    def test_from_cloud_storage_key_layout(self, tmp_path: Path, task_cache_s3: str | None, expected_key: str) -> None:
        fake_s3 = FakeS3Client()
        cs_info = CloudStorageInfo(id=1, bucket="bkt", prefix="pfx", endpoint_url="")
        with patch("cveta2.adapters.s3.task_cache.make_s3_client", return_value=fake_s3):
            backend = S3CacheBackend.from_cloud_storage(cs_info, task_cache_s3=task_cache_s3)
        assert backend is not None
        cache = TaskAnnotationCache(tmp_path / "local", s3=backend)

        cache.put(make_task(updated=_UPDATED), _scope(), _shapes())

        assert fake_s3.put_calls == [expected_key]

    def test_bare_prefix_without_project_storage_builds_nothing(self) -> None:
        """A bare prefix names no bucket, so without storage there is none."""
        assert S3CacheBackend.from_cloud_storage(None, task_cache_s3="_cache") is None

    def test_full_url_works_without_project_storage(self, tmp_path: Path) -> None:
        """``s3://`` carries its own bucket; the client is built with ``None``, not ``""``."""
        fake_s3 = FakeS3Client()
        with patch("cveta2.adapters.s3.task_cache.make_s3_client", return_value=fake_s3) as make_client:
            backend = S3CacheBackend.from_cloud_storage(None, task_cache_s3="s3://ml-cache/proj")
        assert backend is not None
        make_client.assert_called_once_with(None)
        cache = TaskAnnotationCache(tmp_path / "local", s3=backend)

        cache.put(make_task(updated=_UPDATED), _scope(), _shapes())

        assert fake_s3.put_calls == ["ml-cache/proj/task_annotations/task_1/job_1.json"]

    def test_explicit_location_inherits_the_storage_endpoint(self) -> None:
        """The override moves the cache, it does not change how S3 is reached."""
        cs_info = CloudStorageInfo(id=1, bucket="bkt", prefix="pfx", endpoint_url="http://minio:9000")
        with patch("cveta2.adapters.s3.task_cache.make_s3_client", return_value=FakeS3Client()) as make_client:
            S3CacheBackend.from_cloud_storage(cs_info, task_cache_s3="s3://ml-cache/p")

        make_client.assert_called_once_with("http://minio:9000")


# ---------------------------------------------------------------------------
# _build_task_cache: what the fetch pipeline wires the cache up to
# ---------------------------------------------------------------------------


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
        with patch("cveta2.adapters.s3.task_cache.make_s3_client", return_value=fake_s3):
            fetch_selected_tasks(
                CvatClient(CFG, api=api),
                FetchTarget(fake.project.id, fake.project.name, output_dir, None),
                FetchOptions(
                    task_selector=[fake.tasks[0].name],
                    config_path=config_path,
                ),
            )

    def test_an_s3_entry_spares_the_annotation_download(self, normal_fake: LoadedFixtures, tmp_path: Path) -> None:
        """A teammate's cached entry spares this machine the annotation download.

        Frame metadata, jobs and issues are still read live.
        """
        fake = normal_fake
        api = FakeCvatApi(fake, cloud_storage=_PROJECT_STORAGE)
        task = fake.tasks[0]
        job = api.get_task_jobs(task.id)[0]
        shapes = api.get_task_annotations(task.id)
        api.annotation_calls.clear()
        fake_s3 = FakeS3Client({f"bkt/{_s3_key(task.id)}": _entry_bytes(task, AnnotationScope(jobs=(job,)), shapes)})

        self._fetch(api, fake, tmp_path / "out", fake_s3)

        assert api.annotation_calls == []
        assert api.job_annotation_calls == []
        assert _entry(get_task_cache_dir(fake.project.id), task.id).exists()

    def test_a_fresh_fetch_is_published_to_s3(self, normal_fake: LoadedFixtures, tmp_path: Path) -> None:
        """A local-only write would leave every other machine re-fetching."""
        fake = normal_fake
        fake_s3 = FakeS3Client()

        self._fetch(
            FakeCvatApi(fake, cloud_storage=_PROJECT_STORAGE),
            fake,
            tmp_path / "out",
            fake_s3,
        )

        assert fake_s3.put_calls == [f"bkt/{_s3_key(fake.tasks[0].id)}"]

    def test_the_configured_override_moves_the_s3_location(self, normal_fake: LoadedFixtures, tmp_path: Path) -> None:
        """``task_cache_s3`` must survive the trip from config to backend."""
        fake = normal_fake
        fake_s3 = FakeS3Client()
        config_path = write_split_config_yaml(
            tmp_path / "cfg.yaml",
            project_ids={fake.project.name: fake.project.id},
            cache={"projects": {fake.project.name: {"task_cache_s3": "s3://ml-cache/proj"}}},
        )

        self._fetch(
            FakeCvatApi(fake, cloud_storage=_PROJECT_STORAGE),
            fake,
            tmp_path / "out",
            fake_s3,
            config_path,
        )

        task_id = fake.tasks[0].id
        assert fake_s3.put_calls == [f"ml-cache/proj/task_annotations/task_{task_id}/job_{task_id}.json"]


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
        client = CvatClient(CFG, api=FakeCvatApi(fake, cloud_storage=_PROJECT_STORAGE))

        with (
            patch("cveta2.adapters.s3.task_cache.make_s3_client", return_value=fake_s3),
            client,
            resolved_task(client, fake.project.id, fake.project.name, task.id),
        ):
            assert key in fake_s3.objects

        assert fake_s3.delete_calls == [key, f"bkt/{_legacy_s3_key(task.id)}"]
        assert key not in fake_s3.objects


class TestSelectedFetchDoesNotPrune:
    def test_a_selected_fetch_keeps_entries_for_the_tasks_it_skipped(
        self, normal_fake: LoadedFixtures, tmp_path: Path
    ) -> None:
        """Pruning on a partial fetch would delete every unselected task."""
        fake = normal_fake
        cache_dir = get_task_cache_dir(fake.project.id)
        TaskAnnotationCache(cache_dir).put(make_task(999, updated=_UPDATED), _scope(999), _shapes())

        _fetch_task_cached(FakeCvatApi(fake), fake, tmp_path / "out", FetchOptions())

        assert _entry(cache_dir, 999).exists()


@pytest.mark.parametrize("disabled_first", [False, True])
def test_strict_invalidation_reports_s3_failure_and_can_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, disabled_first: bool
) -> None:
    """Mutation preflight must not silently accept a failed S3 deletion or listing."""
    s3 = FakeS3Client()
    backend = S3CacheBackend(s3, "bucket", "prefix")
    cache = TaskAnnotationCache(tmp_path, s3=backend)
    task = make_task(1)
    cache.put(task, _scope(), _shapes())
    assert _entry(tmp_path).exists()
    key = "bucket/prefix/.cveta2_cache/task_annotations/task_1/job_1.json"
    assert key in s3.objects

    with monkeypatch.context() as failures:

        def fail_delete(**_kwargs: str) -> None:
            raise ClientError({"Error": {"Code": "AccessDenied"}}, "DeleteObject")

        failures.setattr(s3, "delete_object", fail_delete)
        if disabled_first:
            backend.delete_task(1)
        with pytest.raises(Cveta2Error):
            cache.invalidate(1, strict=True)
    assert not (tmp_path / "task_1").exists()
    assert key in s3.objects

    cache.invalidate(1, strict=True)
    assert key not in s3.objects


class TestInvalidationFollowsTheSelectedConfig:
    """``Connection(config_path=...)`` selects one cache state for every step."""

    def _custom_config(self, tmp_path: Path) -> tuple[Path, Path]:
        root = tmp_path / "custom_tasks_root"
        config_path = tmp_path / "custom.yaml"
        config_path.write_text(f"cache:\n  tasks_root: {root}\n", encoding="utf-8")
        return config_path, root

    def test_api_task_mutation_drops_the_entry_under_the_selected_tasks_root(
        self, normal_fake: LoadedFixtures, tmp_path: Path
    ) -> None:
        """Fetch caches under the custom root, so the mutation must clear it there."""
        config_path, root = self._custom_config(tmp_path)
        api, connection = _scoped(normal_fake, config_path=config_path)
        task = normal_fake.tasks[0]
        cveta2.fetch(normal_fake.project.id, tmp_path / "out", download_images=False, connection=connection)
        entry = _entry(get_task_cache_dir(normal_fake.project.id, root=root), task.id)
        assert entry.exists()

        cveta2.task_set_status(normal_fake.project.id, task.id, state="in progress", connection=connection)

        assert not entry.exists()
        api.annotation_calls.clear()
        cveta2.fetch(normal_fake.project.id, tmp_path / "out2", download_images=False, connection=connection)
        assert task.id in api.annotation_calls

    def test_upload_invalidates_under_the_selected_tasks_root(self, tmp_path: Path) -> None:
        config_path, root = self._custom_config(tmp_path)
        cache_dir = get_task_cache_dir(5, root=root)
        TaskAnnotationCache(cache_dir).put(make_task(updated=_UPDATED), _scope(), _shapes())

        upload_dependencies(config_path=config_path).invalidate(5, 1, "")

        assert not (cache_dir / "task_1").exists()

    def test_api_upload_forwards_the_selected_config(
        self, normal_fake: LoadedFixtures, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_path, _root = self._custom_config(tmp_path)
        seen: list[Path | None] = []

        def record(_client: object, request: UploadRequest, *, config_path: Path | None = None) -> UploadOutcome:
            seen.append(config_path)
            return UploadOutcome(
                task_id=1, task_name=request.task_name, images=0, deleted=0, annotations=0, issues=0, jobs=0
            )

        monkeypatch.setattr(import_module("cveta2.interfaces.api.upload"), "upload_cvat_dataset", record)
        dataset = pd.DataFrame([csv_row("a.jpg", label="cat")])
        _api, connection = _scoped(normal_fake, config_path=config_path)

        cveta2.upload(dataset, project=normal_fake.project.id, name="t", connection=connection)

        assert seen == [config_path]


_MALFORMED_TASK_CACHE_S3 = ["s3://", "s3:///x", "/", "  "]


def _write_task_cache_s3_config(tmp_path: Path, project_name: str, project_id: int, task_cache_s3: str) -> Path:
    return write_split_config_yaml(
        tmp_path / "mirror.yaml",
        project_ids={project_name: project_id},
        cache={"projects": {project_name: {"task_cache_s3": task_cache_s3}}},
    )


def _missing_profile(_endpoint: str | None) -> None:
    raise ProfileNotFound(profile="absent")


class TestUnusableS3Mirror:
    """A mirror that cannot be configured or reached never escapes as a raw error."""

    @pytest.mark.parametrize("task_cache_s3", _MALFORMED_TASK_CACHE_S3)
    def test_a_malformed_location_is_a_typed_error(self, task_cache_s3: str) -> None:
        with (
            patch("cveta2.adapters.s3.task_cache.make_s3_client", return_value=FakeS3Client()),
            pytest.raises(Cveta2Error, match="task_cache_s3"),
        ):
            S3CacheBackend.from_cloud_storage(_PROJECT_STORAGE, task_cache_s3=task_cache_s3)

    def test_fetch_without_an_s3_client_warns_and_uses_the_local_cache(
        self, normal_fake: LoadedFixtures, tmp_path: Path, capture_logs: list[str]
    ) -> None:
        fake = normal_fake
        task = fake.tasks[0]
        api = FakeCvatApi(fake, cloud_storage=_PROJECT_STORAGE)

        with patch("cveta2.adapters.s3.task_cache.make_s3_client", side_effect=_missing_profile):
            fetch_selected_tasks(
                CvatClient(CFG, api=api),
                FetchTarget(fake.project.id, fake.project.name, tmp_path / "out", None),
                FetchOptions(task_selector=[task.name]),
            )

        assert api.annotation_calls == [task.id]
        assert _entry(get_task_cache_dir(fake.project.id), task.id).exists()
        assert any("S3-кэш аннотаций недоступен" in message for message in capture_logs)

    @pytest.mark.parametrize("task_cache_s3", _MALFORMED_TASK_CACHE_S3)
    def test_api_mutation_refuses_malformed_shared_cache_settings_before_writing(
        self, normal_fake: LoadedFixtures, tmp_path: Path, task_cache_s3: str
    ) -> None:
        config_path = _write_task_cache_s3_config(
            tmp_path, normal_fake.project.name, normal_fake.project.id, task_cache_s3
        )
        api, connection = _scoped(normal_fake, cloud_storage=_PROJECT_STORAGE, config_path=config_path)
        task = normal_fake.tasks[0]

        with pytest.raises(Cveta2Error, match="task_cache_s3"):
            cveta2.task_set_status(normal_fake.project.id, task.id, state="in progress", connection=connection)

        assert api.writes.job_updates == []

    @pytest.mark.parametrize("task_cache_s3", _MALFORMED_TASK_CACHE_S3)
    def test_api_mutation_succeeds_when_cache_settings_become_invalid_after_writing(
        self,
        normal_fake: LoadedFixtures,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capture_logs: list[str],
        task_cache_s3: str,
    ) -> None:
        config_path = _write_task_cache_s3_config(
            tmp_path, normal_fake.project.name, normal_fake.project.id, "s3://cache/tasks"
        )
        api, connection = _scoped(normal_fake, cloud_storage=_PROJECT_STORAGE, config_path=config_path)
        task = normal_fake.tasks[0]
        update_job = api.update_job

        def update_then_damage_config(job_id: int, *, stage: str | None = None, state: str | None = None) -> None:
            update_job(job_id, stage=stage, state=state)
            _write_task_cache_s3_config(tmp_path, normal_fake.project.name, normal_fake.project.id, task_cache_s3)

        monkeypatch.setattr(api, "update_job", update_then_damage_config)

        updated = cveta2.task_set_status(normal_fake.project.id, task.id, state="in progress", connection=connection)

        assert updated > 0
        assert len(api.writes.job_updates) == updated
        assert any("не удалось прочитать настройки кэша" in message for message in capture_logs)

    def test_invalidation_warns_when_the_cache_settings_cannot_load(
        self, tmp_path: Path, capture_logs: list[str]
    ) -> None:
        """The CVAT write already happened, so an unreadable config only warns."""
        config_path = tmp_path / "broken.yaml"
        config_path.write_text("cache: [unclosed\n", encoding="utf-8")

        upload_dependencies(config_path=config_path).invalidate(5, 1, "proj", _PROJECT_STORAGE)

        assert capture_logs

    def test_api_mutation_without_an_s3_client_still_drops_the_local_entry(
        self, normal_fake: LoadedFixtures, capture_logs: list[str]
    ) -> None:
        api, connection = _scoped(normal_fake, cloud_storage=_PROJECT_STORAGE)
        task = normal_fake.tasks[0]
        cache_dir = get_task_cache_dir(normal_fake.project.id)
        TaskAnnotationCache(cache_dir).put(make_task(task.id, updated=_UPDATED), _scope(task.id), _shapes())

        with patch("cveta2.adapters.s3.task_cache.make_s3_client", side_effect=_missing_profile):
            cveta2.task_delete(normal_fake.project.id, task.id, connection=connection)

        assert api.writes.deleted_tasks == [task.id]
        assert not (cache_dir / f"task_{task.id}").exists()
        assert capture_logs

    def test_a_failed_invalidation_never_masks_the_mutation_error(
        self, normal_fake: LoadedFixtures, tmp_path: Path, capture_logs: list[str]
    ) -> None:
        config_path = _write_task_cache_s3_config(tmp_path, normal_fake.project.name, normal_fake.project.id, "s3://")
        client = CvatClient(CFG, api=FakeCvatApi(normal_fake, cloud_storage=_PROJECT_STORAGE))
        task = normal_fake.tasks[0]

        with (
            pytest.raises(CvatApiError, match="mutation refused"),
            client,
            resolved_task(client, normal_fake.project.id, normal_fake.project.name, task.id, config_path=config_path),
        ):
            raise CvatApiError("mutation refused", status_code=403)
        assert capture_logs

    def test_upload_invalidation_warns_instead_of_raising(self, tmp_path: Path, capture_logs: list[str]) -> None:
        config_path = _write_task_cache_s3_config(tmp_path, "proj", 5, "s3://")

        upload_dependencies(config_path=config_path).invalidate(5, 1, "proj", _PROJECT_STORAGE)

        assert capture_logs

    def test_upload_invalidation_without_an_s3_client_drops_the_local_entry(self, capture_logs: list[str]) -> None:
        cache_dir = get_task_cache_dir(5)
        TaskAnnotationCache(cache_dir).put(make_task(updated=_UPDATED), _scope(), _shapes())

        with patch("cveta2.adapters.s3.task_cache.make_s3_client", side_effect=_missing_profile):
            upload_dependencies().invalidate(5, 1, "proj", _PROJECT_STORAGE)

        assert not (cache_dir / "task_1").exists()
        assert capture_logs
