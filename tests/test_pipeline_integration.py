"""Integration tests: full pipeline through FakeCvatApi + CvatClient."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import pandas as pd

from cveta2.client import CvatClient
from cveta2.config import CvatConfig
from cveta2.dataset_partition import PartitionResult, partition_annotations_df
from cveta2.models import CSV_COLUMNS, DeletedImage, ProjectAnnotations
from tests.fixtures.fake_cvat_api import FakeCvatApi
from tests.fixtures.fake_cvat_project import (
    FakeProjectConfig,
    LoadedFixtures,
    build_fake_project,
    task_indices_by_names,
)

if TYPE_CHECKING:
    from cveta2._client.dtos import RawAnnotations, RawDataMeta

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


def _client(fixtures: LoadedFixtures) -> CvatClient:
    return CvatClient(_CFG, api=FakeCvatApi(fixtures))


def _build(
    base: LoadedFixtures,
    task_names: list[str],
    statuses: list[str] | None = None,
    **kwargs: object,
) -> LoadedFixtures:
    """Build a fake project from named base tasks with optional statuses."""
    indices = task_indices_by_names(base.tasks, task_names)
    config = FakeProjectConfig(
        task_indices=indices,
        task_statuses=statuses if statuses is not None else "keep",
        **kwargs,  # type: ignore[arg-type]
    )
    return build_fake_project(base, config)


def _with_dates(
    fixtures: LoadedFixtures,
    dates: dict[int, str],
) -> LoadedFixtures:
    """Return fixtures with updated_date overrides by task position."""
    new_tasks = [
        replace(task, updated_date=dates[i]) if i in dates else task
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
    result = _client(fake).fetch_annotations(fake.project.id)
    rows = result.to_csv_rows()
    df = pd.DataFrame(rows)
    partition = partition_annotations_df(df, result.deleted_images)
    return result, partition


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_normal_project_annotations(coco8_fixtures: LoadedFixtures) -> None:
    """Normal task produces the expected number of annotations."""
    fake = _build(coco8_fixtures, ["normal"], statuses=["completed"])
    result = _client(fake).fetch_annotations(fake.project.id)

    assert len(result.annotations) == 30
    assert len(result.deleted_images) == 0
    annotated_frames = {a.frame_id for a in result.annotations}
    without_frames = {w.frame_id for w in result.images_without_annotations}
    assert annotated_frames | without_frames == set(range(8))


def test_all_empty_images_without_annotations(
    coco8_fixtures: LoadedFixtures,
) -> None:
    """all-empty task: no annotations, all frames without."""
    fake = _build(coco8_fixtures, ["all-empty"], statuses=["completed"])
    result = _client(fake).fetch_annotations(fake.project.id)

    assert len(result.annotations) == 0
    assert len(result.deleted_images) == 0
    assert len(result.images_without_annotations) == 8
    without_names = {w.image_name for w in result.images_without_annotations}
    assert without_names == set(_IMAGE_NAMES)


def test_all_removed_only_deleted(coco8_fixtures: LoadedFixtures) -> None:
    """all-removed task: all 8 frames in deleted_images."""
    fake = _build(coco8_fixtures, ["all-removed"], statuses=["completed"])
    result = _client(fake).fetch_annotations(fake.project.id)

    assert len(result.deleted_images) == 8
    assert {d.image_name for d in result.deleted_images} == set(_IMAGE_NAMES)
    # Shapes exist but reference deleted frames -- still extracted
    assert len(result.annotations) == 30
    assert len(result.images_without_annotations) == 0


def test_frames_1_2_removed(coco8_fixtures: LoadedFixtures) -> None:
    """frames-1-2-removed: frames 1,2 deleted; others have annotations or not."""
    fake = _build(coco8_fixtures, ["frames-1-2-removed"], statuses=["completed"])
    result = _client(fake).fetch_annotations(fake.project.id)

    deleted_frame_ids = {d.frame_id for d in result.deleted_images}
    assert deleted_frame_ids == {1, 2}

    annotated_frames = {a.frame_id for a in result.annotations}
    without_frames = {w.frame_id for w in result.images_without_annotations}
    # Together they cover all 8 frames
    assert (annotated_frames | without_frames | deleted_frame_ids) == set(range(8))
    # without_annotations has no overlap with deleted or annotated
    assert without_frames.isdisjoint(deleted_frame_ids | annotated_frames)


def test_zero_frame_empty_last_removed(
    coco8_fixtures: LoadedFixtures,
) -> None:
    """zero-frame-empty-last-removed: frame 0 unannotated, frame 7 deleted."""
    fake = _build(
        coco8_fixtures,
        ["zero-frame-empty-last-removed"],
        statuses=["completed"],
    )
    result = _client(fake).fetch_annotations(fake.project.id)

    assert result.deleted_images[0].frame_id == 7
    without_frame_ids = {w.frame_id for w in result.images_without_annotations}
    assert 0 in without_frame_ids
    assert 0 not in {a.frame_id for a in result.annotations}
    assert len(result.annotations) == 17


def test_mixed_tasks_aggregation(coco8_fixtures: LoadedFixtures) -> None:
    """Three tasks aggregated: normal + all-empty + all-removed."""
    fake = _build(
        coco8_fixtures,
        ["normal", "all-empty", "all-removed"],
        statuses=["completed", "completed", "completed"],
    )
    result = _client(fake).fetch_annotations(fake.project.id)

    assert len(result.annotations) == 60  # 30 + 0 + 30
    assert len(result.deleted_images) == 8  # only from all-removed
    assert len(result.images_without_annotations) == 8  # only from all-empty


def test_deleted_then_restored(coco8_fixtures: LoadedFixtures) -> None:
    """Image deleted in older task, re-annotated in newer -- not deleted."""
    fake = _build(
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

    assert partition.deleted_names == []
    assert len(partition.dataset) > 0
    assert fake.tasks[1].id in set(partition.dataset["task_id"].unique())
    assert len(partition.obsolete) > 0
    assert fake.tasks[0].id in set(partition.obsolete["task_id"].unique())
    assert len(partition.in_progress) == 0


def test_completed_only_filter(coco8_fixtures: LoadedFixtures) -> None:
    """completed_only=True skips non-completed tasks."""
    fake = _build(
        coco8_fixtures,
        ["normal", "all-empty"],
        statuses=["completed", "annotation"],
    )
    result = _client(fake).fetch_annotations(fake.project.id, completed_only=True)

    # Only the "normal" (completed) task processed; "all-empty" skipped entirely
    assert len(result.annotations) == 30
    # All 8 frames accounted for across annotations + without_annotations
    annotated_frames = {a.frame_id for a in result.annotations}
    without_frames = {w.frame_id for w in result.images_without_annotations}
    assert annotated_frames | without_frames == set(range(8))


def test_csv_rows_structure(coco8_fixtures: LoadedFixtures) -> None:
    """to_csv_rows() output has all CSV_COLUMNS keys."""
    fake = _build(coco8_fixtures, ["normal"], statuses=["completed"])
    result = _client(fake).fetch_annotations(fake.project.id)

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
    fake = _build(
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
    fake = _build(
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

    result = _client(fake).fetch_annotations(fake.project.id)
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

    assert sorted(partition.deleted_names) == sorted(_IMAGE_NAMES[:2])
    for name in _IMAGE_NAMES[:2]:
        assert name in set(partition.obsolete["image_name"])
    assert len(partition.dataset) > 0
    assert len(partition.in_progress) > 0
