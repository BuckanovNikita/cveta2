"""Integration tests: full pipeline through FakeCvatApi + CvatClient."""

from __future__ import annotations

import argparse
import os
from typing import TYPE_CHECKING

import pandas as pd
import pytest
from cvat_sdk.api_client.exceptions import ApiException

from cveta2.client import CvatClient
from cveta2.config import CvatConfig
from cveta2.dataset_partition import PartitionResult, partition_annotations_df
from cveta2.models import (
    CSV_COLUMNS,
    BBoxAnnotation,
    DeletedImage,
    ImageWithoutAnnotations,
    ProjectAnnotations,
    TaskInfo,
)
from tests.conftest import build_fake, make_fake_client
from tests.fixtures.fake_cvat_api import FakeCvatApi

if TYPE_CHECKING:
    from pathlib import Path

    from cveta2._client.dtos import RawAnnotations, RawDataMeta
    from cveta2.models import LabelInfo, ProjectInfo
    from tests.fixtures.fake_cvat_project import LoadedFixtures

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CFG = CvatConfig()

_IMAGE_NAMES = [
    "000000000009.jpg",
    "000000000025.jpg",
    "000000000030.jpg",
    "000000000034.jpg",
    "000000000036.jpg",
    "000000000042.jpg",
    "000000000049.jpg",
    "000000000061.jpg",
]


class _FailingTaskApi:
    """CvatApiPort wrapper that raises ApiException(500) for a given task id."""

    def __init__(self, delegate: FakeCvatApi, failing_task_id: int) -> None:
        self._delegate = delegate
        self._failing_task_id = failing_task_id

    def list_projects(self) -> list[ProjectInfo]:
        return self._delegate.list_projects()

    def get_project_tasks(self, project_id: int) -> list[TaskInfo]:
        return self._delegate.get_project_tasks(project_id)

    def get_project_labels(self, project_id: int) -> list[LabelInfo]:
        return self._delegate.get_project_labels(project_id)

    def get_task_data_meta(self, task_id: int) -> RawDataMeta:
        if task_id == self._failing_task_id:
            raise ApiException(status=500, reason="Internal Server Error")
        return self._delegate.get_task_data_meta(task_id)

    def get_task_annotations(self, task_id: int) -> RawAnnotations:
        if task_id == self._failing_task_id:
            raise ApiException(status=500, reason="Internal Server Error")
        return self._delegate.get_task_annotations(task_id)


def _with_dates(
    fixtures: LoadedFixtures,
    dates: dict[int, str],
) -> LoadedFixtures:
    """Return fixtures with updated_date overrides by task position."""
    new_tasks = [
        task.model_copy(update={"updated_date": dates[i]}) if i in dates else task
        for i, task in enumerate(fixtures.tasks)
    ]
    new_data: dict[int, tuple[RawDataMeta, RawAnnotations]] = {
        t.id: fixtures.task_data[fixtures.tasks[i].id] for i, t in enumerate(new_tasks)
    }
    return fixtures._replace(tasks=new_tasks, task_data=new_data)


def _fetch_and_partition(
    fake: LoadedFixtures,
) -> tuple[ProjectAnnotations, PartitionResult]:
    """Fetch annotations and partition them."""
    result = make_fake_client(fake).fetch_annotations(fake.project.id)
    rows = result.to_csv_rows()
    df = pd.DataFrame(rows)
    partition = partition_annotations_df(df, result.deleted_images)
    return result, partition


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_normal_project_annotations(coco8_fixtures: LoadedFixtures) -> None:
    """Normal task produces the expected number of annotations."""
    fake = build_fake(coco8_fixtures, ["normal"], statuses=["completed"])
    result = make_fake_client(fake).fetch_annotations(fake.project.id)

    bbox_records = [a for a in result.annotations if isinstance(a, BBoxAnnotation)]
    without_records = [
        a for a in result.annotations if isinstance(a, ImageWithoutAnnotations)
    ]
    assert len(bbox_records) == 30
    assert len(result.deleted_images) == 0
    annotated_frames = {a.frame_id for a in bbox_records}
    without_frames = {w.frame_id for w in without_records}
    assert annotated_frames | without_frames == set(range(8))


def test_all_empty_images_without_annotations(
    coco8_fixtures: LoadedFixtures,
) -> None:
    """all-empty task: no annotations, all frames without."""
    fake = build_fake(coco8_fixtures, ["all-empty"], statuses=["completed"])
    result = make_fake_client(fake).fetch_annotations(fake.project.id)

    without_records = [
        a for a in result.annotations if isinstance(a, ImageWithoutAnnotations)
    ]
    assert len(result.annotations) == 8
    assert len(result.deleted_images) == 0
    assert len(without_records) == 8
    without_names = {w.image_name for w in without_records}
    assert without_names == set(_IMAGE_NAMES)


def test_all_removed_only_deleted(coco8_fixtures: LoadedFixtures) -> None:
    """all-removed task: all 8 frames in deleted_images."""
    fake = build_fake(coco8_fixtures, ["all-removed"], statuses=["completed"])
    result = make_fake_client(fake).fetch_annotations(fake.project.id)

    assert len(result.deleted_images) == 8
    assert {d.image_name for d in result.deleted_images} == set(_IMAGE_NAMES)
    # Shapes exist but reference deleted frames -- still extracted
    bbox_records = [a for a in result.annotations if isinstance(a, BBoxAnnotation)]
    without_records = [
        a for a in result.annotations if isinstance(a, ImageWithoutAnnotations)
    ]
    assert len(bbox_records) == 30
    assert len(without_records) == 0


def test_frames_1_2_removed(coco8_fixtures: LoadedFixtures) -> None:
    """frames-1-2-removed: frames 1,2 deleted; others have annotations or not."""
    fake = build_fake(coco8_fixtures, ["frames-1-2-removed"], statuses=["completed"])
    result = make_fake_client(fake).fetch_annotations(fake.project.id)

    deleted_frame_ids = {d.frame_id for d in result.deleted_images}
    assert deleted_frame_ids == {1, 2}

    bbox_records = [a for a in result.annotations if isinstance(a, BBoxAnnotation)]
    without_records = [
        a for a in result.annotations if isinstance(a, ImageWithoutAnnotations)
    ]
    annotated_frames = {a.frame_id for a in bbox_records}
    without_frames = {w.frame_id for w in without_records}
    # Together they cover all 8 frames
    assert (annotated_frames | without_frames | deleted_frame_ids) == set(range(8))
    # without_annotations has no overlap with deleted or annotated
    assert without_frames.isdisjoint(deleted_frame_ids | annotated_frames)


def test_zero_frame_empty_last_removed(
    coco8_fixtures: LoadedFixtures,
) -> None:
    """zero-frame-empty-last-removed: frame 0 unannotated, frame 7 deleted."""
    fake = build_fake(
        coco8_fixtures,
        ["zero-frame-empty-last-removed"],
        statuses=["completed"],
    )
    result = make_fake_client(fake).fetch_annotations(fake.project.id)

    assert result.deleted_images[0].frame_id == 7
    without_records = [
        a for a in result.annotations if isinstance(a, ImageWithoutAnnotations)
    ]
    without_frame_ids = {w.frame_id for w in without_records}
    assert 0 in without_frame_ids
    bbox_records = [a for a in result.annotations if isinstance(a, BBoxAnnotation)]
    assert 0 not in {a.frame_id for a in bbox_records}
    assert len(bbox_records) == 17


def test_mixed_tasks_aggregation(coco8_fixtures: LoadedFixtures) -> None:
    """Three tasks aggregated: normal + all-empty + all-removed."""
    fake = build_fake(
        coco8_fixtures,
        ["normal", "all-empty", "all-removed"],
        statuses=["completed", "completed", "completed"],
    )
    result = make_fake_client(fake).fetch_annotations(fake.project.id)

    bbox_records = [a for a in result.annotations if isinstance(a, BBoxAnnotation)]
    without_records = [
        a for a in result.annotations if isinstance(a, ImageWithoutAnnotations)
    ]
    assert len(bbox_records) == 60  # 30 + 0 + 30
    assert len(result.deleted_images) == 8  # only from all-removed
    assert len(without_records) == 8  # only from all-empty


def test_deleted_then_restored(coco8_fixtures: LoadedFixtures) -> None:
    """Image deleted in older task, re-annotated in newer -- not deleted."""
    fake = build_fake(
        coco8_fixtures,
        ["all-removed", "normal"],
        statuses=["completed", "completed"],
    )
    fake = _with_dates(
        fake,
        {
            0: "2026-01-01T00:00:00+00:00",
            1: "2026-02-01T00:00:00+00:00",
        },
    )

    _result, partition = _fetch_and_partition(fake)

    assert partition.deleted_images == []
    assert len(partition.dataset) > 0
    assert fake.tasks[1].id in set(partition.dataset["task_id"].unique())
    assert len(partition.obsolete) > 0
    assert fake.tasks[0].id in set(partition.obsolete["task_id"].unique())
    assert len(partition.in_progress) == 0


def test_completed_only_filter(coco8_fixtures: LoadedFixtures) -> None:
    """completed_only=True skips non-completed tasks."""
    fake = build_fake(
        coco8_fixtures,
        ["normal", "all-empty"],
        statuses=["completed", "annotation"],
    )
    result = make_fake_client(fake).fetch_annotations(
        fake.project.id, completed_only=True
    )

    # Only the "normal" (completed) task processed; "all-empty" skipped entirely
    bbox_records = [a for a in result.annotations if isinstance(a, BBoxAnnotation)]
    without_records = [
        a for a in result.annotations if isinstance(a, ImageWithoutAnnotations)
    ]
    assert len(bbox_records) == 30
    # All 8 frames accounted for across annotations + without_annotations
    annotated_frames = {a.frame_id for a in bbox_records}
    without_frames = {w.frame_id for w in without_records}
    assert annotated_frames | without_frames == set(range(8))


def test_csv_rows_structure(coco8_fixtures: LoadedFixtures) -> None:
    """to_csv_rows() output has all CSV_COLUMNS keys."""
    fake = build_fake(coco8_fixtures, ["normal"], statuses=["completed"])
    result = make_fake_client(fake).fetch_annotations(fake.project.id)

    rows = result.to_csv_rows()
    assert len(rows) > 0

    expected_keys = set(CSV_COLUMNS)
    for row in rows:
        assert set(row.keys()) == expected_keys
        assert isinstance(row["attributes"], str)


def test_full_pipeline_fetch_to_partition(
    coco8_fixtures: LoadedFixtures,
) -> None:
    """Newer task's annotations go to dataset, older to obsolete."""
    fake = build_fake(
        coco8_fixtures,
        ["normal", "all-bboxes-moved"],
        statuses=["completed", "completed"],
    )
    fake = _with_dates(
        fake,
        {
            0: "2026-02-01T00:00:00+00:00",
            1: "2026-01-01T00:00:00+00:00",
        },
    )

    _result, partition = _fetch_and_partition(fake)

    assert fake.tasks[0].id in set(partition.dataset["task_id"].unique())
    assert fake.tasks[1].id in set(partition.obsolete["task_id"].unique())


def test_partition_with_deleted_and_in_progress(
    coco8_fixtures: LoadedFixtures,
) -> None:
    """Three-way partition: completed + in_progress + external deletion."""
    fake = build_fake(
        coco8_fixtures,
        ["normal", "all-empty"],
        statuses=["completed", "annotation"],
    )
    fake = _with_dates(
        fake,
        {
            0: "2026-01-01T00:00:00+00:00",
            1: "2026-01-15T00:00:00+00:00",
        },
    )

    result = make_fake_client(fake).fetch_annotations(fake.project.id)
    rows = result.to_csv_rows()
    df = pd.DataFrame(rows)

    # Inject synthetic deletions newer than both tasks
    deleted_extra = [
        DeletedImage(
            task_id=999,
            task_name="external-delete",
            task_status="completed",
            task_updated_date="2026-02-01T00:00:00+00:00",
            frame_id=i,
            image_name=_IMAGE_NAMES[i],
        )
        for i in range(2)
    ]
    all_deleted = list(result.deleted_images) + deleted_extra
    partition = partition_annotations_df(df, all_deleted)

    assert sorted(d.image_name for d in partition.deleted_images) == sorted(
        _IMAGE_NAMES[:2]
    )
    for name in _IMAGE_NAMES[:2]:
        assert name in set(partition.obsolete["image_name"])
    assert len(partition.dataset) > 0
    assert len(partition.in_progress) > 0


def test_5xx_task_skipped(coco8_fixtures: LoadedFixtures) -> None:
    """When one task returns 5xx, that task is skipped and others are processed."""
    fake = build_fake(
        coco8_fixtures,
        ["normal", "all-empty"],
        statuses=["completed", "completed"],
    )
    failing_task_id = fake.tasks[1].id
    api = _FailingTaskApi(FakeCvatApi(fake), failing_task_id=failing_task_id)
    client = CvatClient(_CFG, api=api)

    result = client.fetch_annotations(
        fake.project.id,
        project_name="test-project",
    )

    # Only first task (normal) data; second task (all-empty) was skipped due to 5xx
    bbox_records = [a for a in result.annotations if isinstance(a, BBoxAnnotation)]
    task_ids = {a.task_id for a in result.annotations}
    assert len(bbox_records) == 30
    assert task_ids == {fake.tasks[0].id}
    assert failing_task_id not in task_ids


def test_4xx_error_propagated(coco8_fixtures: LoadedFixtures) -> None:
    """Non-5xx ApiException (e.g. 404) is re-raised, not swallowed."""
    fake = build_fake(coco8_fixtures, ["normal"], statuses=["completed"])

    class _NotFoundApi(_FailingTaskApi):
        def get_task_data_meta(self, task_id: int) -> RawDataMeta:
            if task_id == self._failing_task_id:
                raise ApiException(status=404, reason="Not Found")
            return self._delegate.get_task_data_meta(task_id)

    api = _NotFoundApi(FakeCvatApi(fake), failing_task_id=fake.tasks[0].id)
    client = CvatClient(_CFG, api=api)

    with pytest.raises(ApiException) as exc_info:
        client.fetch_annotations(fake.project.id)
    assert exc_info.value.status == 404


def test_5xx_raise_on_failure(coco8_fixtures: LoadedFixtures) -> None:
    """When CVETA2_RAISE_ON_FAILURE=true, 5xx is re-raised immediately."""
    fake = build_fake(
        coco8_fixtures,
        ["normal", "all-empty"],
        statuses=["completed", "completed"],
    )
    failing_task_id = fake.tasks[1].id
    api = _FailingTaskApi(FakeCvatApi(fake), failing_task_id=failing_task_id)
    client = CvatClient(_CFG, api=api)

    prev = os.environ.get("CVETA2_RAISE_ON_FAILURE")
    try:
        os.environ["CVETA2_RAISE_ON_FAILURE"] = "true"
        with pytest.raises(ApiException) as exc_info:
            client.fetch_annotations(fake.project.id)
        assert exc_info.value.status == 500
    finally:
        if prev is None:
            os.environ.pop("CVETA2_RAISE_ON_FAILURE", None)
        else:
            os.environ["CVETA2_RAISE_ON_FAILURE"] = prev


# ---------------------------------------------------------------------------
# resolve_project_id
# ---------------------------------------------------------------------------


def test_resolve_project_id_digit_string(coco8_fixtures: LoadedFixtures) -> None:
    """Digit-string input returns the integer directly."""
    fake = build_fake(coco8_fixtures, ["normal"], statuses=["completed"])
    client = make_fake_client(fake)
    assert client.resolve_project_id("42") == 42


def test_resolve_project_id_casefold_name(coco8_fixtures: LoadedFixtures) -> None:
    """Name matching is case-insensitive."""
    fake = build_fake(coco8_fixtures, ["normal"], statuses=["completed"])
    client = make_fake_client(fake)
    name = fake.project.name
    # Use uppercased name — should still resolve
    result = client.resolve_project_id(name.upper(), cached=[fake.project])
    assert result == fake.project.id


def test_resolve_project_id_not_found(coco8_fixtures: LoadedFixtures) -> None:
    """Non-existent project name raises ProjectNotFoundError."""
    from cveta2.exceptions import ProjectNotFoundError

    fake = build_fake(coco8_fixtures, ["normal"], statuses=["completed"])
    client = make_fake_client(fake)

    with pytest.raises(ProjectNotFoundError):
        client.resolve_project_id("does-not-exist")


def test_raw_csv_includes_deleted_images(
    coco8_fixtures: LoadedFixtures,
    tmp_path: Path,
) -> None:
    """--raw produces raw.csv containing both annotation and deletion rows."""
    fake = build_fake(
        coco8_fixtures,
        ["normal", "all-removed"],
        statuses=["completed", "completed"],
    )
    result = make_fake_client(fake).fetch_annotations(fake.project.id)

    # Simulate args with raw=True
    args = argparse.Namespace(raw=True)
    from cveta2.commands.fetch import _write_output

    _write_output(args, result, tmp_path / "out")

    raw_csv = tmp_path / "out" / "raw.csv"
    assert raw_csv.exists()

    raw_df = pd.read_csv(raw_csv)
    shapes = set(raw_df["instance_shape"].dropna().unique())
    assert "deleted" in shapes, "raw.csv must include deletion rows"
    assert "box" in shapes, "raw.csv must include annotation rows"

    # Total rows = annotations + deleted
    annotation_rows = result.to_csv_rows()
    expected_total = len(annotation_rows) + len(result.deleted_images)
    assert len(raw_df) == expected_total


def test_task_to_records_unknown_deleted_frame_id() -> None:
    """Deleted frame_id not in frames produces '<unknown>' image_name."""
    from cveta2._client.dtos import RawAnnotations, RawDataMeta, RawFrame
    from cveta2.client import _task_to_records

    task = TaskInfo(
        id=99,
        name="test",
        status="completed",
        subset="",
        updated_date="2026-01-01T00:00:00",
    )
    data_meta = RawDataMeta(
        frames=[RawFrame(name="a.jpg", width=640, height=480)],
        deleted_frames=[999],  # frame 999 doesn't exist
    )
    annotations = RawAnnotations(shapes=[])

    _records, deleted = _task_to_records(task, data_meta, annotations, {}, {})

    assert len(deleted) == 1
    assert deleted[0].image_name == "<unknown>"
    assert deleted[0].frame_id == 999
