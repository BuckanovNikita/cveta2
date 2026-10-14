"""Polygon payloads refresh old caches and survive local/shared cache hits."""

from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from cveta2.adapters.s3.task_cache import (
    S3CacheBackend,
    TaskAnnotationCache,
    get_task_cache_dir,
)
from cveta2.application.ports.dtos import RawAnnotations, RawDataMeta, RawFrame
from cveta2.application.use_cases.fetch import FetchOptions, FetchTarget
from cveta2.composition.client import CvatClient
from cveta2.composition.workflows import fetch_selected_tasks
from cveta2.domain.cache import CachedTaskEnvelope
from cveta2.domain.models import (
    BBoxAnnotation,
    ImageWithoutAnnotations,
    LabelInfo,
    ProjectInfo,
    TaskAnnotations,
)
from cveta2.domain.storage import CloudStorageInfo
from tests.fixtures.fake_cvat_api import FakeCvatApi
from tests.fixtures.fake_cvat_project import LoadedFixtures
from tests.fixtures.fake_s3 import FakeS3Client
from tests.helpers import CFG, make_raw_shape, make_task

_STORAGE = CloudStorageInfo(id=1, bucket="bkt", prefix="pfx", endpoint_url="")
_BOUNDS = (12.0, 10.25, 90.75, 80.0)


@pytest.fixture(autouse=True)
def _enable_cache(_disable_task_cache: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CVETA2_DISABLE_CACHE", raising=False)


class _PolygonApi(FakeCvatApi):
    """Expose project storage so real fetch orchestration builds the S3 cache."""

    def get_project_cloud_storage(self, _project_id: int) -> CloudStorageInfo:
        return _STORAGE


def _polygon_fixture() -> LoadedFixtures:
    task = make_task(100, name="polygon-task", subset="train")
    return LoadedFixtures(
        project=ProjectInfo(id=1, name="polygon-project"),
        tasks=[task],
        labels=[LabelInfo(id=1, name="car")],
        task_data={
            task.id: (
                RawDataMeta(frames=[RawFrame("polygon.jpg", 640, 480)]),
                RawAnnotations(
                    shapes=[
                        make_raw_shape(
                            id=42,
                            type="polygon",
                            points=[12.0, 30.5, 90.75, 10.25, 40.5, 80.0],
                            rotation=25.0,
                        )
                    ]
                ),
            )
        },
    )


def _assert_polygon(payload: TaskAnnotations) -> None:
    assert len(payload.annotations) == 1
    box = payload.annotations[0]
    assert isinstance(box, BBoxAnnotation)
    assert (box.bbox_x_tl, box.bbox_y_tl, box.bbox_x_br, box.bbox_y_br) == _BOUNDS
    assert box.instance_label == "car"
    assert box.annotation_id == 42
    assert box.rotation == 0.0
    assert box.task_id == 100
    assert box.frame_id == 0


@pytest.mark.parametrize("old_layer", ["local", "s3"])
def test_old_polygon_cache_refetches_and_round_trips_without_warning_replay(
    old_layer: str, tmp_path: Path, capture_logs: list[str]
) -> None:
    fake = _polygon_fixture()
    task = fake.tasks[0]
    api = _PolygonApi(fake)
    local_dir = get_task_cache_dir(fake.project.id)
    entry = local_dir / f"task_{task.id}.json"
    key = f"bkt/pfx/.cveta2_cache/task_annotations/task_{task.id}.json"
    old_payload = TaskAnnotations(
        task_id=task.id,
        task_name=task.name,
        deleted_images=[],
        annotations=[
            ImageWithoutAnnotations(
                image_name="polygon.jpg",
                image_width=640,
                image_height=480,
                task_id=task.id,
                task_name=task.name,
                task_updated_date=task.updated_date,
                task_completed=True,
                job_stage="acceptance",
                job_state="completed",
                frame_id=0,
            )
        ],
    )
    old_bytes = (
        CachedTaskEnvelope(
            schema_version=4,
            task_id=task.id,
            task_updated_date=task.updated_date,
            cached_at="2026-01-01T00:00:00+00:00",
            payload=old_payload,
        )
        .model_dump_json()
        .encode()
    )
    fake_s3 = FakeS3Client({key: old_bytes} if old_layer == "s3" else {})
    if old_layer == "local":
        local_dir.mkdir(parents=True)
        entry.write_bytes(old_bytes)

    def fetch(output: str) -> pd.DataFrame:
        fetch_selected_tasks(
            CvatClient(CFG, api=api),
            FetchTarget(fake.project.id, fake.project.name, tmp_path / output),
            FetchOptions(task_selector=[task.id], publish_clearml=False),
        )
        return pd.read_csv(tmp_path / output / "dataset.csv")

    with patch("cveta2.adapters.s3.task_cache.make_s3_client", return_value=fake_s3):
        fresh = fetch("fresh")
        assert api.annotation_calls == [task.id]
        assert fresh["instance_shape"].tolist() == ["box"]
        columns = ["bbox_x_tl", "bbox_y_tl", "bbox_x_br", "bbox_y_br"]
        assert tuple(fresh[columns].iloc[0]) == _BOUNDS
        assert any(
            "42" in warning and "100" in warning and "приближение" in warning
            for warning in capture_logs
        )
        local = CachedTaskEnvelope.model_validate_json(entry.read_bytes()).payload
        shared = CachedTaskEnvelope.model_validate_json(fake_s3.objects[key]).payload
        _assert_polygon(local)
        _assert_polygon(shared)
        assert local == shared
        assert fake_s3.put_calls == [key]

        capture_logs.clear()
        get_count = len(fake_s3.get_calls)
        cached_local = fetch("local-hit")
        pd.testing.assert_frame_equal(fresh, cached_local)
        assert api.annotation_calls == [task.id]
        assert len(fake_s3.get_calls) == get_count
        assert capture_logs == []

        # Simulate a second machine with no local entry; its shared hit must
        # backfill the same polygon payload without parsing it again.
        TaskAnnotationCache(local_dir).invalidate_local(task.id)
        cached_s3 = fetch("s3-hit")
        pd.testing.assert_frame_equal(fresh, cached_s3)
        assert api.annotation_calls == [task.id]
        assert len(fake_s3.get_calls) == get_count + 1
        assert capture_logs == []
        restored = TaskAnnotationCache(
            local_dir, s3=S3CacheBackend(fake_s3, "bkt", "pfx")
        ).get(task)
        assert restored == local
