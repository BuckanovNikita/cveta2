"""Name-based consistency tests for CVAT fixtures (coco8-dev).

Load fixtures from tests/fixtures/cvat/coco8-dev and assert each task
satisfies the invariant implied by its name. No CvatClient used.
"""

from collections.abc import Callable
from pathlib import Path

import pytest

from cveta2.application.ports.dtos import RawAnnotations, RawDataMeta
from tests.fixtures.fake_cvat_project import LoadedFixtures
from tests.fixtures.load_cvat_fixtures import load_cvat_fixtures

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "cvat" / "coco8-dev"


def _kept(meta: RawDataMeta) -> set[int]:
    return set(range(len(meta.frames))) - set(meta.deleted_frames)


def _shape_frames(annotations: RawAnnotations) -> set[int]:
    return {shape.frame for shape in annotations.shapes}


# Task name -> invariant its name implies, over (data meta, annotations).
TASK_INVARIANTS: dict[str, Callable[[RawDataMeta, RawAnnotations], bool]] = {
    "normal": lambda meta, _: bool(_kept(meta)),
    "all-empty": lambda meta, ann: not ann.shapes and bool(_kept(meta)),
    "all-removed": lambda meta, _: bool(meta.deleted_frames) and not _kept(meta),
    "zero-frame-empty-last-removed": lambda meta, ann: (
        0 not in _shape_frames(ann) and len(meta.frames) - 1 in meta.deleted_frames
    ),
    "all-bboxes-moved": lambda _, ann: bool(ann.shapes),
    "all-except-first-empty": lambda _, ann: _shape_frames(ann) <= {0},
    "frames-1-2-removed": lambda meta, _: {1, 2} <= set(meta.deleted_frames) and bool(_kept(meta)),
}


@pytest.fixture(scope="module")
def loaded_fixtures() -> LoadedFixtures:
    return load_cvat_fixtures(FIXTURES_DIR)


def test_fixtures_load(loaded_fixtures: LoadedFixtures) -> None:
    assert loaded_fixtures.project.name == "coco8-dev"
    assert loaded_fixtures.labels
    assert {task.id for task in loaded_fixtures.tasks} == set(loaded_fixtures.task_data)


@pytest.mark.parametrize("name", list(TASK_INVARIANTS))
def test_each_task_satisfies_its_name(loaded_fixtures: LoadedFixtures, name: str) -> None:
    (task,) = [t for t in loaded_fixtures.tasks if t.name.strip().lower() == name]
    meta, annotations = loaded_fixtures.task_data[task.id]
    assert TASK_INVARIANTS[name](meta, annotations)
