"""Name-based consistency tests for CVAT fixtures (coco8-dev).

Load fixtures from tests/fixtures/cvat/coco8-dev and assert each task
satisfies the invariant implied by its name. No CvatClient used.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from cveta2._client.dtos import (
    RawAnnotations,
    RawDataMeta,
    RawTask,
)
from tests.fixtures.load_cvat_fixtures import load_cvat_fixtures

if TYPE_CHECKING:
    from tests.fixtures.fake_cvat_project import LoadedFixtures

# Assertion: (task, data_meta, annotations) -> None
TaskAssertion = Callable[[RawTask, RawDataMeta, RawAnnotations], None]


FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "cvat" / "coco8-dev"


def _frame_indices(data_meta: RawDataMeta) -> set[int]:
    """Set of frame indices present in data_meta.frames (0..len-1)."""
    return set(range(len(data_meta.frames)))


def _deleted_set(data_meta: RawDataMeta) -> set[int]:
    return set(data_meta.deleted_frames)


def _shape_frames(annotations: RawAnnotations) -> set[int]:
    """Frame indices that have at least one shape."""
    return {s.frame for s in annotations.shapes}


def _track_frames(annotations: RawAnnotations) -> set[int]:
    """Frame indices that have at least one track segment."""
    out: set[int] = set()
    for track in annotations.tracks:
        for ts in track.shapes:
            out.add(ts.frame)
    return out


def _assert_normal(
    task: RawTask,
    data_meta: RawDataMeta,
    _annotations: RawAnnotations,
) -> None:
    """Baseline: at least one frame; at least one frame not in deleted_frames."""
    assert len(data_meta.frames) >= 1, f"task {task.name}: expected at least one frame"
    not_deleted = _frame_indices(data_meta) - _deleted_set(data_meta)
    assert len(not_deleted) >= 1, (
        f"task {task.name}: expected at least one frame not in deleted_frames"
    )


def _assert_all_empty(
    task: RawTask,
    data_meta: RawDataMeta,
    annotations: RawAnnotations,
) -> None:
    """No annotations; at least one frame not deleted."""
    assert len(annotations.shapes) == 0, f"task {task.name}: expected no shapes"
    assert len(annotations.tracks) == 0, f"task {task.name}: expected no tracks"
    not_deleted = _frame_indices(data_meta) - _deleted_set(data_meta)
    assert len(not_deleted) >= 1, (
        f"task {task.name}: expected at least one frame not in deleted_frames"
    )


def _assert_all_removed(
    task: RawTask,
    data_meta: RawDataMeta,
    _annotations: RawAnnotations,
) -> None:
    """All frame indices in deleted_frames, or frames empty and deleted non-empty."""
    indices = _frame_indices(data_meta)
    deleted = _deleted_set(data_meta)
    if len(data_meta.frames) == 0:
        assert len(data_meta.deleted_frames) >= 1, (
            f"task {task.name}: expected deleted_frames non-empty when frames empty"
        )
    else:
        for idx in indices:
            assert idx in deleted, (
                f"task {task.name}: frame index {idx} should be in deleted_frames"
            )


def _assert_zero_frame_empty_last_removed(
    task: RawTask,
    data_meta: RawDataMeta,
    annotations: RawAnnotations,
) -> None:
    """Frame 0 has no shapes/track segments; last frame index in deleted_frames."""
    shape_frames = _shape_frames(annotations)
    track_frames = _track_frames(annotations)
    assert 0 not in shape_frames, f"task {task.name}: frame 0 should have no shapes"
    assert 0 not in track_frames, (
        f"task {task.name}: frame 0 should have no track segments"
    )
    if len(data_meta.frames) >= 1:
        last_idx = len(data_meta.frames) - 1
        assert last_idx in _deleted_set(data_meta), (
            f"task {task.name}: last frame index {last_idx} should be in deleted_frames"
        )


def _assert_all_bboxes_moved(
    task: RawTask,
    _data_meta: RawDataMeta,
    annotations: RawAnnotations,
) -> None:
    """Has at least one shape or track."""
    assert len(annotations.shapes) >= 1 or len(annotations.tracks) >= 1, (
        f"task {task.name}: expected at least one shape or track"
    )


def _assert_all_except_first_empty(
    task: RawTask,
    data_meta: RawDataMeta,
    annotations: RawAnnotations,
) -> None:
    """No shape/track on frame index > 0; frame 0 may have annotations."""
    shape_frames = _shape_frames(annotations)
    track_frames = _track_frames(annotations)
    for idx in _frame_indices(data_meta):
        if idx > 0:
            assert idx not in shape_frames, (
                f"task {task.name}: frame {idx} should have no shapes"
            )
            assert idx not in track_frames, (
                f"task {task.name}: frame {idx} should have no track segments"
            )


def _assert_frames_1_2_removed(
    task: RawTask,
    data_meta: RawDataMeta,
    _annotations: RawAnnotations,
) -> None:
    """Frame indices 1 and 2 in deleted_frames; at least one other frame not deleted."""
    deleted = _deleted_set(data_meta)
    assert 1 in deleted, f"task {task.name}: frame 1 should be in deleted_frames"
    assert 2 in deleted, f"task {task.name}: frame 2 should be in deleted_frames"
    not_deleted = _frame_indices(data_meta) - deleted
    assert len(not_deleted) >= 1, (
        f"task {task.name}: expected at least one frame not in deleted_frames"
    )


# Task name (exact or normalized) -> assertion function
TASK_ASSERTIONS: dict[str, TaskAssertion] = {
    "normal": _assert_normal,
    "all-empty": _assert_all_empty,
    "all-removed": _assert_all_removed,
    "zero-frame-empty-last-removed": _assert_zero_frame_empty_last_removed,
    "all-bboxes-moved": _assert_all_bboxes_moved,
    "all-except-first-empty": _assert_all_except_first_empty,
    "frames-1-2-removed": _assert_frames_1_2_removed,
}


@pytest.fixture(scope="module")
def loaded_fixtures() -> LoadedFixtures:
    """Load coco8-dev fixtures once per test module."""
    return load_cvat_fixtures(FIXTURES_DIR)


def test_fixtures_load(loaded_fixtures: LoadedFixtures) -> None:
    """Fixtures directory loads and returns project, tasks, labels, task data."""
    assert loaded_fixtures.project.name == "coco8-dev"
    assert len(loaded_fixtures.tasks) >= 1
    assert len(loaded_fixtures.labels) >= 1
    for task in loaded_fixtures.tasks:
        assert task.id in loaded_fixtures.task_data


def test_task_name_consistency(loaded_fixtures: LoadedFixtures) -> None:
    """Each task with a known name satisfies its name-based assertion."""
    for task in loaded_fixtures.tasks:
        assert_func: TaskAssertion | None = TASK_ASSERTIONS.get(
            task.name.strip().lower()
        )
        if assert_func is None:
            continue
        data_meta, annotations = loaded_fixtures.task_data[task.id]
        assert_func(task, data_meta, annotations)
