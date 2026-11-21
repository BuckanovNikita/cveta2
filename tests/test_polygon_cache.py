"""Polygon payloads refresh old caches and survive local/shared cache hits."""

from pathlib import Path
from typing import override
from unittest.mock import patch

import pandas as pd
import pytest

from cveta2.adapters.s3.task_cache import (
    CachedAnnotationsEntry,
    TaskAnnotationCache,
    get_task_cache_dir,
)
from cveta2.application.ports.dtos import RawAnnotations, RawDataMeta, RawFrame
from cveta2.application.use_cases.fetch import FetchOptions, FetchTarget
from cveta2.composition.client import CvatClient
from cveta2.composition.workflows import fetch_selected_tasks
from cveta2.domain.models import (
    BBoxAnnotation,
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

    @override
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
def test_old_polygon_cache_is_removed_refetched_and_round_trips_without_warning_replay(
    old_layer: str, tmp_path: Path, capture_logs: list[str]
) -> None:
    fake = _polygon_fixture()
    task = fake.tasks[0]
    api = _PolygonApi(fake)
    local_dir = get_task_cache_dir(fake.project.id)
    old_entry = local_dir / f"task_{task.id}.json"
    old_key = f"bkt/pfx/.cveta2_cache/task_annotations/task_{task.id}.json"
    entry = local_dir / f"task_{task.id}" / f"job_{task.id}.json"
    key = f"bkt/pfx/.cveta2_cache/task_annotations/task_{task.id}/job_{task.id}.json"
    old_bytes = b'{"schema_version": 5, "task_id": 100, "payload": {}}'
    fake_s3 = FakeS3Client({old_key: old_bytes} if old_layer == "s3" else {})
    if old_layer == "local":
        local_dir.mkdir(parents=True)
        old_entry.write_bytes(old_bytes)

    def fetch(output: str) -> pd.DataFrame:
        fetch_selected_tasks(
            CvatClient(CFG, api=api),
            FetchTarget(fake.project.id, fake.project.name, tmp_path / output),
            FetchOptions(task_selector=[task.id]),
        )
        return pd.read_csv(tmp_path / output / "dataset.csv")

    with patch("cveta2.adapters.s3.task_cache.make_s3_client", return_value=fake_s3):
        fresh = fetch("fresh")
        assert not old_entry.exists()
        assert old_key not in fake_s3.objects
        assert api.annotation_calls == [task.id]
        assert fresh["instance_shape"].tolist() == ["box"]
        columns = ["bbox_x_tl", "bbox_y_tl", "bbox_x_br", "bbox_y_br"]
        assert tuple(fresh[columns].iloc[0]) == _BOUNDS
        assert any("42" in warning and "100" in warning and "приближение" in warning for warning in capture_logs)
        local = CachedAnnotationsEntry.model_validate_json(entry.read_bytes())
        shared = CachedAnnotationsEntry.model_validate_json(fake_s3.objects[key])
        assert [shape.id for shape in local.shapes] == [42]
        assert local == shared
        meta_key = key.replace(f"job_{task.id}.json", "meta.json")
        assert fake_s3.put_calls == [key, meta_key]

        capture_logs.clear()
        get_count = len(fake_s3.get_calls)
        cached_local = fetch("local-hit")
        pd.testing.assert_frame_equal(fresh, cached_local)
        assert api.annotation_calls == [task.id]
        assert len(fake_s3.get_calls) == get_count
        assert capture_logs == []

        # Simulate a second machine with no local entry; its shared hit must
        # backfill the same shapes and replay no approximation warning.
        TaskAnnotationCache(local_dir).invalidate_local(task.id)
        cached_s3 = fetch("s3-hit")
        pd.testing.assert_frame_equal(fresh, cached_s3)
        assert api.annotation_calls == [task.id]
        assert len(fake_s3.get_calls) == get_count + 2  # the job's shapes and the task's metadata
        assert capture_logs == []
        assert CachedAnnotationsEntry.model_validate_json(entry.read_bytes()) == local


def test_an_uncached_fetch_warns_about_every_approximation(tmp_path: Path, capture_logs: list[str]) -> None:
    """Without a cache every shape is downloaded, so its parsing warning is shown each run."""
    fake = _polygon_fixture()
    task = fake.tasks[0]
    api = _PolygonApi(fake)

    for output in ("first", "second"):
        capture_logs.clear()
        fetch_selected_tasks(
            CvatClient(CFG, api=api),
            FetchTarget(fake.project.id, fake.project.name, tmp_path / output),
            FetchOptions(task_selector=[task.id], use_cache=False),
        )
        assert any("42" in warning and "приближение" in warning for warning in capture_logs), output
