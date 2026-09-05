"""Fetch regressions crossing the SDK records, cache, and output boundaries."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pandas as pd
import pytest

import cveta2
from cveta2._client.dtos import RawAnnotations, RawDataMeta, RawFrame, RawIssue, RawJob
from cveta2.client import CvatClient
from cveta2.config import CvatConfig
from cveta2.dataset_partition import completed_task_ids, partition_annotations_df
from cveta2.exceptions import CvatApiError
from cveta2.models import ProjectInfo
from tests.fixtures.fake_cvat_api import FakeCvatApi
from tests.fixtures.fake_cvat_project import LoadedFixtures
from tests.fixtures.fake_s3 import FakeS3Client
from tests.helpers import make_cs_info, make_raw_shape, make_task

if TYPE_CHECKING:
    from pathlib import Path

    from cveta2.models import TaskInfo


def _connection(
    tmp_path: Path, task: TaskInfo, frame_name: str = "a.jpg"
) -> tuple[cveta2.Connection, FakeCvatApi]:
    api = FakeCvatApi(
        LoadedFixtures(
            project=ProjectInfo(id=1, name="audit-project"),
            tasks=[task],
            labels=[],
            task_data={
                task.id: (RawDataMeta([RawFrame(frame_name, 20, 20)]), RawAnnotations())
            },
        )
    )
    config = tmp_path / "config.yaml"
    config.write_text(f"cache:\n  tasks_root: {tmp_path / 'cache'}\n", encoding="utf-8")
    return cveta2.Connection(
        client=CvatClient(CvatConfig(), api=api), config_path=config
    ), api


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("unfinished_type", ["annotation", "ground_truth"])
def test_overlapping_jobs_never_promote_unfinished_task(
    tmp_path: Path, unfinished_type: str, *, reverse: bool
) -> None:
    connection, api = _connection(tmp_path, make_task(status="annotation"))
    jobs = [
        RawJob(1, 0, 0, "annotation", "new", type=unfinished_type),
        RawJob(
            2,
            0,
            0,
            "acceptance",
            "completed",
            type="ground_truth" if unfinished_type == "annotation" else "annotation",
        ),
    ]
    if reverse:
        jobs.reverse()
    with patch.object(api, "get_task_jobs", return_value=jobs):
        result = cveta2.fetch(
            "audit-project",
            tmp_path / "output",
            connection=connection,
            download_images=False,
            publish_clearml=False,
            cache="off",
        )
    assert result.dataset.empty
    assert list(result.in_progress["image_name"]) == ["a.jpg"]
    saved = pd.read_csv(tmp_path / "output" / "in_progress.csv")
    assert not bool(saved.loc[0, "task_completed"])
    assert partition_annotations_df(saved, []).dataset.empty


def test_job_without_exported_frames_still_prevents_completion(tmp_path: Path) -> None:
    connection, api = _connection(tmp_path, make_task(status="annotation"))
    jobs = [
        RawJob(1, 0, 0, "acceptance", "completed"),
        RawJob(2, 10, 10, "annotation", "new", type="ground_truth"),
    ]
    with patch.object(api, "get_task_jobs", return_value=jobs):
        result = cveta2.fetch(
            "audit-project",
            tmp_path / "output",
            connection=connection,
            download_images=False,
            publish_clearml=False,
            cache="off",
        )
    assert result.dataset.empty
    assert result.in_progress.loc[0, "job_state"] == "completed"
    assert not bool(result.in_progress.loc[0, "task_completed"])


def test_annotated_frames_preserve_unfinished_ground_truth_job(tmp_path: Path) -> None:
    """A bbox must carry task-wide completion independently of its own job."""
    connection, api = _connection(tmp_path, make_task(status="annotation"))
    jobs = [
        RawJob(1, 0, 0, "acceptance", "completed"),
        RawJob(2, 0, 0, "annotation", "new", type="ground_truth"),
    ]
    with (
        patch.object(api, "get_task_jobs", return_value=jobs),
        patch.object(
            api,
            "get_task_annotations",
            return_value=RawAnnotations([make_raw_shape(frame=0)]),
        ),
    ):
        result = cveta2.fetch(
            "audit-project",
            tmp_path / "output",
            connection=connection,
            download_images=False,
            publish_clearml=False,
            cache="off",
        )
    assert result.dataset.empty
    assert result.in_progress["instance_shape"].tolist() == ["box"]
    assert result.in_progress["task_completed"].tolist() == [False]


def test_deleted_frames_preserve_unfinished_ground_truth_job(tmp_path: Path) -> None:
    """Deleting every frame does not make an unfinished job disappear."""
    connection, api = _connection(tmp_path, make_task(status="annotation"))
    jobs = [
        RawJob(1, 0, 0, "acceptance", "completed"),
        RawJob(2, 0, 0, "annotation", "new", type="ground_truth"),
    ]
    with (
        patch.object(api, "get_task_jobs", return_value=jobs),
        patch.object(
            api,
            "get_task_data_meta",
            return_value=RawDataMeta([RawFrame("a.jpg", 20, 20)], deleted_frames=[0]),
        ),
    ):
        result = cveta2.fetch(
            "audit-project",
            tmp_path / "output",
            connection=connection,
            download_images=False,
            publish_clearml=False,
            cache="off",
        )
    assert len(result.deleted_images) == 1
    assert completed_task_ids(result.dataset, result.deleted_images) == set()
    saved = pd.read_csv(tmp_path / "output" / "deleted.csv")
    assert saved["task_completed"].tolist() == [False]


@pytest.mark.parametrize("legacy_value", [None, float("nan")])
def test_missing_completion_values_use_legacy_jobs_but_false_excludes_task(
    legacy_value: float | None,
) -> None:
    rows = pd.DataFrame(
        [
            {
                "image_name": "legacy.jpg",
                "task_id": 1,
                "job_stage": "acceptance",
                "job_state": "completed",
                "task_completed": legacy_value,
            },
            {
                "image_name": "explicit.jpg",
                "task_id": 2,
                "job_stage": "acceptance",
                "job_state": "completed",
                "task_completed": False,
            },
            {
                "image_name": "other.jpg",
                "task_id": 2,
                "job_stage": "acceptance",
                "job_state": "completed",
                "task_completed": legacy_value,
            },
        ]
    )
    result = partition_annotations_df(rows, [])
    assert list(result.dataset["image_name"]) == ["legacy.jpg"]
    assert set(result.in_progress["image_name"]) == {"explicit.jpg", "other.jpg"}


def test_issue_failure_is_retried_next_fetch_before_caching(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CVETA2_DISABLE_CACHE", raising=False)
    connection, api = _connection(tmp_path, make_task())
    with patch.object(
        api,
        "get_task_issues",
        side_effect=[
            CvatApiError("temporary", status_code=500),
            [RawIssue(id=1, frame=0, resolved=False, comments=["review this"])],
        ],
    ) as issues:
        first = cveta2.fetch(
            "audit-project",
            tmp_path / "first",
            connection=connection,
            download_images=False,
            publish_clearml=False,
        )
        assert first.dataset.loc[0, "issue_text"] == ""
        assert not list((tmp_path / "cache").rglob("task_*.json"))
        second = cveta2.fetch(
            "audit-project",
            tmp_path / "second",
            connection=connection,
            download_images=False,
            publish_clearml=False,
        )
        third = cveta2.fetch(
            "audit-project",
            tmp_path / "third",
            connection=connection,
            download_images=False,
            publish_clearml=False,
        )
    assert (
        second.dataset.loc[0, "issue_text"]
        == third.dataset.loc[0, "issue_text"]
        == "review this"
    )
    assert issues.call_count == 2


@pytest.mark.parametrize(
    "frame_name",
    ["/images/nested/a.jpg", "images/nested/a.jpg", "a.jpg", "stale/a.jpg"],
)
def test_downloaded_paths_survive_csv_and_cache_hit(
    tmp_path: Path, frame_name: str
) -> None:
    connection, api = _connection(tmp_path, make_task(), frame_name)
    storage = make_cs_info(bucket="bucket", prefix="images")
    s3 = FakeS3Client({"bucket/images/nested/a.jpg": b"image"})
    with (
        patch.object(api, "get_project_cloud_storage", return_value=storage),
        patch("cveta2.image_downloader.make_s3_client", return_value=s3),
    ):
        for run in range(2):
            result = cveta2.fetch(
                "audit-project",
                tmp_path / f"out-{run}",
                connection=connection,
                images_dir=tmp_path / "images",
                publish_clearml=False,
                cache="off",
            )
            row = result.dataset.iloc[0]
            assert row["s3_image_path"] == "images/nested/a.jpg"
            assert row["image_path"] == str(tmp_path / "images" / "nested" / "a.jpg")
    assert s3.get_calls == ["bucket/images/nested/a.jpg"]
