"""Tests for the persistent task-annotation cache (local + S3)."""

from __future__ import annotations

import argparse
import json
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pandas as pd
import pytest
from botocore.exceptions import EndpointConnectionError

from cveta2.client import CvatClient
from cveta2.commands.fetch import run_fetch, run_fetch_task
from cveta2.config import CvatConfig, IgnoreConfig
from cveta2.image_downloader import CloudStorageInfo
from cveta2.models import (
    BBoxAnnotation,
    DeletedImage,
    ImageWithoutAnnotations,
    TaskAnnotations,
    TaskInfo,
)
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
from tests.helpers import CFG, build_fake, make_bbox, make_fetch_args, make_task

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
        task_status="completed",
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

    def test_get_miss_on_empty_dir(self, tmp_path: Path) -> None:
        cache = TaskAnnotationCache(tmp_path / "cache")

        assert cache.get(make_task(updated=_UPDATED)) is None

    def test_stale_updated_date_miss_and_deletes_file(self, tmp_path: Path) -> None:
        cache = TaskAnnotationCache(tmp_path / "cache")
        cache.put(make_task(updated="2026-01-01T00:00:00"), _payload())
        newer_task = make_task(updated="2026-02-02T00:00:00")

        assert cache.get(newer_task) is None
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
        cache_dir = tmp_path / "cache"
        cache = TaskAnnotationCache(cache_dir)
        for task_id in (1, 2, 3):
            cache.put(make_task(task_id, updated=_UPDATED), _payload(task_id))

        removed = cache.prune({1, 3})

        assert removed == 1
        assert (cache_dir / "task_1.json").exists()
        assert not (cache_dir / "task_2.json").exists()
        assert (cache_dir / "task_3.json").exists()

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

        invalidate_local_entry(5, 1)

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

    def put_object(self, *, Bucket: str, Key: str, Body: bytes) -> None:  # noqa: N803
        del Bucket, Key, Body
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


class TestS3Backend:
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

    def test_stale_s3_entry_ignored_without_remote_delete(self, tmp_path: Path) -> None:
        stale_task = make_task(updated="2025-01-01T00:00:00")
        key = f"bkt/{_s3_key(1)}"
        fake_s3 = FakeS3Client({key: _envelope_bytes(stale_task, _payload())})
        cache = TaskAnnotationCache(
            tmp_path / "local", s3=S3CacheBackend(fake_s3, "bkt", "pfx")
        )

        assert cache.get(make_task(updated="2026-06-06T00:00:00")) is None
        assert key in fake_s3.objects
        assert not (tmp_path / "local" / "task_1.json").exists()

    def test_missing_key_is_plain_miss_not_disable(self, tmp_path: Path) -> None:
        fake_s3 = FakeS3Client()
        backend = S3CacheBackend(fake_s3, "bkt", "pfx")
        cache = TaskAnnotationCache(tmp_path / "local", s3=backend)

        assert cache.get(make_task(1, updated=_UPDATED)) is None
        assert cache.get(make_task(2, updated=_UPDATED)) is None
        assert len(fake_s3.get_calls) == 2

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

_MODULE = "cveta2.commands.fetch"


def _run_fetch_task_cached(
    fake_api: FakeCvatApi,
    args: argparse.Namespace,
    *,
    cs_info: CloudStorageInfo | None = None,
) -> None:
    """Drive ``run_fetch_task`` with a fake API and a local-only cache."""

    def make_client(cfg: CvatConfig, **_kw: object) -> CvatClient:
        return CvatClient(cfg, api=fake_api)

    with (
        patch("cveta2.commands._bootstrap.CvatConfig.load", return_value=CFG),
        patch("cveta2.commands._bootstrap.require_host"),
        patch("cveta2.commands._helpers.load_projects_cache", return_value=[]),
        patch(f"{_MODULE}.load_ignore_config", return_value=IgnoreConfig()),
        patch("cveta2.commands._bootstrap.CvatClient", side_effect=make_client),
        patch(
            "cveta2.client.CvatClient.detect_project_cloud_storage",
            return_value=cs_info,
        ),
        patch(f"{_MODULE}.S3CacheBackend.from_cloud_storage", return_value=None),
    ):
        run_fetch_task(args)


class TestFetchWithCache:
    def test_second_fetch_skips_completed_tasks(
        self, coco8_fixtures: LoadedFixtures, tmp_path: Path
    ) -> None:
        fake = build_fake(coco8_fixtures, ["normal"], statuses=["completed"])
        api = FakeCvatApi(fake)
        task_name = fake.tasks[0].name

        _run_fetch_task_cached(
            api,
            make_fetch_args(
                project=str(fake.project.id),
                task=[task_name],
                output_dir=str(tmp_path / "out1"),
                no_cache=False,
            ),
        )
        assert len(api.annotation_calls) == 1

        _run_fetch_task_cached(
            api,
            make_fetch_args(
                project=str(fake.project.id),
                task=[task_name],
                output_dir=str(tmp_path / "out2"),
                save_tasks=True,
                no_cache=False,
            ),
        )

        assert len(api.annotation_calls) == 1
        df1 = pd.read_csv(tmp_path / "out1" / "dataset.csv")
        df2 = pd.read_csv(tmp_path / "out2" / "dataset.csv")
        pd.testing.assert_frame_equal(df1, df2)
        task_csv = tmp_path / "out2" / ".tasks" / f"task_{fake.tasks[0].id}.csv"
        assert task_csv.exists()

    def test_force_refetches_and_no_cache_disables(
        self, coco8_fixtures: LoadedFixtures, tmp_path: Path
    ) -> None:
        fake = build_fake(coco8_fixtures, ["normal"], statuses=["completed"])
        api = FakeCvatApi(fake)
        task_name = fake.tasks[0].name

        def fetch(out: str, *, no_cache: bool = False, force: bool = False) -> None:
            _run_fetch_task_cached(
                api,
                make_fetch_args(
                    project=str(fake.project.id),
                    task=[task_name],
                    output_dir=str(tmp_path / out),
                    no_cache=no_cache,
                    force=force,
                ),
            )

        fetch("out1")
        fetch("out2", force=True)
        assert len(api.annotation_calls) == 2

        fetch("out3", no_cache=True)
        assert len(api.annotation_calls) == 3

        fetch("out4")
        assert len(api.annotation_calls) == 3

    def test_non_completed_tasks_always_refetched(
        self, coco8_fixtures: LoadedFixtures, tmp_path: Path
    ) -> None:
        fake = build_fake(coco8_fixtures, ["normal"], statuses=["annotation"])
        api = FakeCvatApi(fake)
        task_name = fake.tasks[0].name

        for out in ("out1", "out2"):
            _run_fetch_task_cached(
                api,
                make_fetch_args(
                    project=str(fake.project.id),
                    task=[task_name],
                    output_dir=str(tmp_path / out),
                    no_cache=False,
                ),
            )

        assert len(api.annotation_calls) == 2

    def test_cached_payload_is_machine_independent(
        self, coco8_fixtures: LoadedFixtures, tmp_path: Path
    ) -> None:
        fake = build_fake(coco8_fixtures, ["normal"], statuses=["completed"])
        api = FakeCvatApi(fake)
        cs_info = CloudStorageInfo(id=1, bucket="bkt", prefix="pfx", endpoint_url="")

        _run_fetch_task_cached(
            api,
            make_fetch_args(
                project=str(fake.project.id),
                task=[fake.tasks[0].name],
                output_dir=str(tmp_path / "out"),
                no_cache=False,
            ),
            cs_info=cs_info,
        )

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
        self, coco8_fixtures: LoadedFixtures, tmp_path: Path
    ) -> None:
        fake = build_fake(coco8_fixtures, ["normal"], statuses=["completed"])
        api = FakeCvatApi(fake)
        cache_dir = get_task_cache_dir(fake.project.id)
        TaskAnnotationCache(cache_dir).put(
            make_task(999, updated=_UPDATED), _payload(999)
        )
        args = argparse.Namespace(
            project=str(fake.project.id),
            output_dir=str(tmp_path / "out"),
            raw=False,
            completed_only=False,
            no_images=True,
            images_dir=None,
            save_tasks=False,
            no_cache=False,
            force=False,
        )

        def make_client(cfg: CvatConfig, **_kw: object) -> CvatClient:
            return CvatClient(cfg, api=api)

        with (
            patch("cveta2.commands._bootstrap.CvatConfig.load", return_value=CFG),
            patch("cveta2.commands._bootstrap.require_host"),
            patch("cveta2.commands._helpers.load_projects_cache", return_value=[]),
            patch(f"{_MODULE}.load_ignore_config", return_value=IgnoreConfig()),
            patch("cveta2.commands._bootstrap.CvatClient", side_effect=make_client),
            patch(
                "cveta2.client.CvatClient.detect_project_cloud_storage",
                return_value=None,
            ),
            patch(f"{_MODULE}.S3CacheBackend.from_cloud_storage", return_value=None),
            patch("cveta2._clearml.maybe_publish_clearml"),
        ):
            run_fetch(args)

        assert not (cache_dir / "task_999.json").exists()
        assert (cache_dir / f"task_{fake.tasks[0].id}.json").exists()
