"""Shared pytest fixtures for cveta2 tests."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from cveta2._client.mapping import _build_label_maps
from tests.fixtures.load_cvat_fixtures import load_cvat_fixtures

if TYPE_CHECKING:
    from cveta2._client.dtos import RawAnnotations, RawDataMeta, RawTask
    from tests.fixtures.fake_cvat_project import LoadedFixtures

COCO8_DIR = Path(__file__).resolve().parent / "fixtures" / "cvat" / "coco8-dev"


@pytest.fixture(scope="session")
def coco8_fixtures() -> LoadedFixtures:
    """Load coco8-dev fixtures once per test session."""
    return load_cvat_fixtures(COCO8_DIR)


@pytest.fixture(scope="session")
def coco8_label_maps(
    coco8_fixtures: LoadedFixtures,
) -> tuple[dict[int, str], dict[int, str]]:
    """Pre-built (label_names, attr_names) dicts from coco8-dev labels."""
    _project, _tasks, labels, _task_data = coco8_fixtures
    return _build_label_maps(labels)


@pytest.fixture(scope="session")
def coco8_tasks_by_name(
    coco8_fixtures: LoadedFixtures,
) -> dict[str, tuple[RawTask, RawDataMeta, RawAnnotations]]:
    """Map task slug -> (RawTask, RawDataMeta, RawAnnotations)."""
    _project, tasks, _labels, task_data_map = coco8_fixtures
    result: dict[str, tuple[RawTask, RawDataMeta, RawAnnotations]] = {}
    for task in tasks:
        key = task.name.strip().lower()
        data_meta, annotations = task_data_map[task.id]
        result[key] = (task, data_meta, annotations)
    return result
