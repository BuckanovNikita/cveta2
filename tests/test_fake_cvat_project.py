"""Tests for fake CVAT project builder (order, count, names, statuses, repetition)."""

from pathlib import Path
from typing import Literal

import pytest

from cveta2.domain.models import LabelInfo, ProjectInfo
from tests.fixtures.fake_cvat_project import (
    FakeProjectConfig,
    LoadedFixtures,
    build_fake_project,
    task_indices_by_names,
)
from tests.fixtures.load_cvat_fixtures import load_cvat_fixtures

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "cvat" / "coco8-dev"
STATUSES = {"backlog", "annotation", "validation", "completed"}


@pytest.fixture(scope="module")
def base_fixtures() -> LoadedFixtures:
    return load_cvat_fixtures(FIXTURES_DIR)


def test_task_indices_by_names(base_fixtures: LoadedFixtures) -> None:
    tasks = base_fixtures.tasks
    indices = task_indices_by_names(tasks, ["normal", "all-removed", "normal"])
    assert [tasks[i].name.lower() for i in indices] == [
        "normal",
        "all-removed",
        "normal",
    ]
    with pytest.raises(ValueError, match="nonexistent"):
        task_indices_by_names(tasks, ["nonexistent"])


def test_build_keeps_names_and_statuses_and_numbers_repeats(
    base_fixtures: LoadedFixtures,
) -> None:
    config = FakeProjectConfig(
        task_indices=[0, 1, 0], task_id_start=200, project_name="three-tasks"
    )
    result = build_fake_project(base_fixtures, config)
    base = base_fixtures.tasks
    assert result.project.name == "three-tasks"
    assert len(result.labels) == len(base_fixtures.labels)
    assert [t.id for t in result.tasks] == [200, 201, 202]
    assert [t.name for t in result.tasks] == [base[0].name, base[1].name, base[0].name]
    assert [t.status for t in result.tasks] == [
        base[0].status,
        base[1].status,
        base[0].status,
    ]
    assert set(result.task_data) == {200, 201, 202}


def test_build_random_count_and_id_order(base_fixtures: LoadedFixtures) -> None:
    config = FakeProjectConfig(count=5, seed=42, task_id_start=100)
    result = build_fake_project(base_fixtures, config)
    assert [t.id for t in result.tasks] == [100, 101, 102, 103, 104]
    assert len(result.task_data) == 5
    shuffled = build_fake_project(
        base_fixtures,
        FakeProjectConfig(
            task_indices=[0, 1], task_id_order="random", task_id_start=400, seed=123
        ),
    )
    assert {t.id for t in shuffled.tasks} == {400, 401}


@pytest.mark.parametrize(
    ("task_names", "expected"),
    [("enumerated", ["task-0", "task-1", "task-2"]), (["a", "b"], ["a", "b", "a"])],
)
def test_build_names(
    base_fixtures: LoadedFixtures,
    task_names: Literal["enumerated"] | list[str],
    expected: list[str],
) -> None:
    config = FakeProjectConfig(task_indices=[0, 1, 0], task_names=task_names)
    result = build_fake_project(base_fixtures, config)
    assert [t.name for t in result.tasks] == expected


def test_build_random_names_keep_the_base_name(base_fixtures: LoadedFixtures) -> None:
    config = FakeProjectConfig(task_indices=[0, 0], task_names="random", seed=99)
    first, second = build_fake_project(base_fixtures, config).tasks
    assert first.name != second.name
    assert first.name.startswith(base_fixtures.tasks[0].name + "_")
    assert second.name.startswith(base_fixtures.tasks[0].name + "_")


@pytest.mark.parametrize(
    ("task_statuses", "expected"),
    [("random", None), (["completed", "annotation"], ["completed", "annotation"])],
)
def test_build_statuses(
    base_fixtures: LoadedFixtures,
    task_statuses: Literal["random"] | list[str],
    expected: list[str] | None,
) -> None:
    config = FakeProjectConfig(task_indices=[0, 1], task_statuses=task_statuses, seed=7)
    statuses = [t.status for t in build_fake_project(base_fixtures, config).tasks]
    assert set(statuses) <= STATUSES
    if expected is not None:
        assert statuses == expected


@pytest.mark.parametrize(
    ("base", "config", "message"),
    [
        (None, FakeProjectConfig(task_indices=[0, 999]), "999"),
        (
            LoadedFixtures(
                project=ProjectInfo(id=0, name="empty"),
                tasks=[],
                labels=[LabelInfo(id=1, name="x", attributes=[])],
                task_data={},
            ),
            FakeProjectConfig(count=2, seed=1),
            "no tasks",
        ),
    ],
    ids=["index-out-of-range", "no-base-tasks"],
)
def test_build_refuses_an_impossible_config(
    base_fixtures: LoadedFixtures,
    base: LoadedFixtures | None,
    config: FakeProjectConfig,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        build_fake_project(base or base_fixtures, config)
