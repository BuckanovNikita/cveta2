"""Tests for fake CVAT project builder (order, count, names, statuses, repetition)."""

from __future__ import annotations

from pathlib import Path

import pytest

from cveta2.models import LabelInfo, ProjectInfo
from tests.fixtures.fake_cvat_project import (
    FakeProjectConfig,
    LoadedFixtures,
    build_fake_project,
    task_indices_by_names,
)
from tests.fixtures.load_cvat_fixtures import load_cvat_fixtures

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "cvat" / "coco8-dev"


@pytest.fixture(scope="module")
def base_fixtures() -> LoadedFixtures:
    return load_cvat_fixtures(FIXTURES_DIR)


def test_task_indices_by_names(base_fixtures: LoadedFixtures) -> None:
    tasks = base_fixtures.tasks
    indices = task_indices_by_names(tasks, ["normal", "all-removed", "normal"])
    assert len(indices) == 3
    assert tasks[indices[0]].name.lower() == "normal"
    assert tasks[indices[1]].name.lower() == "all-removed"
    assert tasks[indices[2]].name.lower() == "normal"

    with pytest.raises(ValueError, match="No base task with name"):
        task_indices_by_names(tasks, ["nonexistent"])


def test_build_fake_keep_names_and_statuses(base_fixtures: LoadedFixtures) -> None:
    config = FakeProjectConfig(
        task_indices=[0, 1],
        task_id_start=200,
        project_name="two-tasks",
    )
    result = build_fake_project(base_fixtures, config)
    assert result.project.id == 1
    assert result.project.name == "two-tasks"
    assert len(result.tasks) == 2
    assert len(result.labels) == len(base_fixtures.labels)
    assert result.tasks[0].id == 200
    assert result.tasks[1].id == 201
    assert result.tasks[0].name == base_fixtures.tasks[0].name
    assert result.tasks[1].name == base_fixtures.tasks[1].name
    assert result.tasks[0].status == base_fixtures.tasks[0].status
    assert 200 in result.task_data
    assert 201 in result.task_data


def test_build_fake_repeated_tasks(base_fixtures: LoadedFixtures) -> None:
    config = FakeProjectConfig(
        task_indices=[0, 0, 0],
        task_id_start=300,
    )
    result = build_fake_project(base_fixtures, config)
    assert len(result.tasks) == 3
    assert result.tasks[0].id == 300
    assert result.tasks[1].id == 301
    assert result.tasks[2].id == 302
    assert result.tasks[0].name == result.tasks[1].name == result.tasks[2].name
    assert len(result.task_data) == 3


def test_build_fake_random_order_and_count(base_fixtures: LoadedFixtures) -> None:
    config = FakeProjectConfig(
        count=5,
        seed=42,
        task_id_order="asc",
        task_id_start=100,
    )
    result = build_fake_project(base_fixtures, config)
    assert len(result.tasks) == 5
    assert [t.id for t in result.tasks] == [100, 101, 102, 103, 104]
    assert len(result.task_data) == 5

    # Same seed gives same task indices (same base tasks chosen)
    config2 = FakeProjectConfig(count=5, seed=42, task_id_start=100)
    result2 = build_fake_project(base_fixtures, config2)
    assert [t.id for t in result2.tasks] == [100, 101, 102, 103, 104]


def test_build_fake_task_id_order_random(base_fixtures: LoadedFixtures) -> None:
    config = FakeProjectConfig(
        task_indices=[0, 1],
        task_id_order="random",
        task_id_start=400,
        seed=123,
    )
    result = build_fake_project(base_fixtures, config)
    assert len(result.tasks) == 2
    ids = {t.id for t in result.tasks}
    assert ids == {400, 401}


def test_build_fake_enumerated_names(base_fixtures: LoadedFixtures) -> None:
    config = FakeProjectConfig(
        task_indices=[0, 1, 2],
        task_names="enumerated",
    )
    result = build_fake_project(base_fixtures, config)
    assert [t.name for t in result.tasks] == ["task-0", "task-1", "task-2"]


def test_build_fake_custom_names_list(base_fixtures: LoadedFixtures) -> None:
    config = FakeProjectConfig(
        task_indices=[0, 1, 0],
        task_names=["a", "b"],
    )
    result = build_fake_project(base_fixtures, config)
    assert [t.name for t in result.tasks] == ["a", "b", "a"]


def test_build_fake_random_names(base_fixtures: LoadedFixtures) -> None:
    config = FakeProjectConfig(
        task_indices=[0, 0],
        task_names="random",
        seed=99,
    )
    result = build_fake_project(base_fixtures, config)
    assert len(result.tasks) == 2
    assert result.tasks[0].name != result.tasks[1].name
    assert result.tasks[0].name.startswith(base_fixtures.tasks[0].name + "_")
    assert result.tasks[1].name.startswith(base_fixtures.tasks[0].name + "_")


def test_build_fake_random_statuses(base_fixtures: LoadedFixtures) -> None:
    config = FakeProjectConfig(
        task_indices=[0, 1, 2],
        task_statuses="random",
        seed=7,
    )
    result = build_fake_project(base_fixtures, config)
    statuses = {t.status for t in result.tasks}
    assert len(statuses) >= 1
    allowed = {"backlog", "annotation", "validation", "completed"}
    for s in statuses:
        assert s in allowed


def test_build_fake_custom_statuses_list(base_fixtures: LoadedFixtures) -> None:
    config = FakeProjectConfig(
        task_indices=[0, 1, 0],
        task_statuses=["completed", "annotation"],
    )
    result = build_fake_project(base_fixtures, config)
    assert [t.status for t in result.tasks] == ["completed", "annotation", "completed"]


def test_build_fake_invalid_task_index(base_fixtures: LoadedFixtures) -> None:
    config = FakeProjectConfig(task_indices=[0, 999])
    with pytest.raises(ValueError, match="task_indices contains 999"):
        build_fake_project(base_fixtures, config)


def test_build_fake_empty_base_tasks() -> None:
    empty = LoadedFixtures(
        project=ProjectInfo(id=0, name="empty"),
        tasks=[],
        labels=[LabelInfo(id=1, name="x", attributes=[])],
        task_data={},
    )
    config = FakeProjectConfig(count=2, seed=1)
    with pytest.raises(ValueError, match="no tasks"):
        build_fake_project(empty, config)
