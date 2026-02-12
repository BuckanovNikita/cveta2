"""Build fake CVAT projects from base fixtures for tests.

Allows creating projects that contain any of the base tasks in arbitrary order,
with repeated tasks, custom/random task names, and variable task statuses.
"""

from __future__ import annotations

import random
from typing import Literal

from pydantic import BaseModel, Field

from cveta2._client.dtos import (
    RawAnnotations,
    RawDataMeta,
    RawLabel,
    RawProject,
    RawTask,
)

# Same tuple type as load_cvat_fixtures()
LoadedFixtures = tuple[
    RawProject,
    list[RawTask],
    list[RawLabel],
    dict[int, tuple[RawDataMeta, RawAnnotations]],
]

# CVAT task statuses for random choice
DEFAULT_TASK_STATUSES: tuple[str, ...] = (
    "backlog",
    "annotation",
    "validation",
    "completed",
)


class FakeProjectConfig(BaseModel):
    """Configuration for building a fake project from base fixtures."""

    # Which base tasks to include and in which order (indices into base tasks list).
    # Can repeat. If None, use count + random sampling.
    task_indices: list[int] | None = None

    # Number of tasks when task_indices is None (random sample with replacement).
    count: int = Field(
        default=1, ge=1, description="Number of tasks when task_indices not set"
    )

    # Order of assigned task ids: "asc" (100, 101, ...) or "random" (shuffle).
    task_id_order: Literal["asc", "random"] = "asc"

    project_id: int = 1
    project_name: str = "fake"
    task_id_start: int = 100

    # Task names: "keep" | "random" | "enumerated" (task-0, ...) | list (cycled).
    task_names: Literal["keep", "random", "enumerated"] | list[str] = "keep"

    # Task statuses: "keep" | "random" (from DEFAULT_TASK_STATUSES) | list (cycled).
    task_statuses: Literal["keep", "random"] | list[str] = "keep"

    # Reproducible random (indices/names/statuses/order). Not for crypto.
    seed: int | None = None

    model_config = {"frozen": True}


def _resolve_task_indices(
    base_tasks: list[RawTask],
    config: FakeProjectConfig,
) -> list[int]:
    if config.task_indices is not None:
        n = len(base_tasks)
        for i in config.task_indices:
            if i < 0 or i >= n:
                raise ValueError(f"task_indices contains {i}, base tasks count is {n}")
        return list(config.task_indices)
    rng = random.Random(config.seed)
    return rng.choices(range(len(base_tasks)), k=config.count)


def _resolve_task_ids(
    num_tasks: int,
    config: FakeProjectConfig,
) -> list[int]:
    ids = list(range(config.task_id_start, config.task_id_start + num_tasks))
    if config.task_id_order == "random":
        rng = random.Random(config.seed)
        rng.shuffle(ids)
    return ids


def _resolve_name(
    position: int,
    base_task: RawTask,
    config: FakeProjectConfig,
    rng: random.Random,
) -> str:
    if config.task_names == "keep":
        return base_task.name
    if config.task_names == "enumerated":
        return f"task-{position}"
    if config.task_names == "random":
        suffix = f"{rng.getrandbits(16):04x}"
        return f"{base_task.name}_{suffix}"
    # list[str] — cycle
    return config.task_names[position % len(config.task_names)]


def _resolve_status(
    position: int,
    base_task: RawTask,
    config: FakeProjectConfig,
    rng: random.Random,
) -> str:
    if config.task_statuses == "keep":
        return base_task.status
    if config.task_statuses == "random":
        return rng.choice(DEFAULT_TASK_STATUSES)
    # list[str] — cycle
    return config.task_statuses[position % len(config.task_statuses)]


def task_indices_by_names(
    base_tasks: list[RawTask],
    names: list[str],
) -> list[int]:
    """Resolve list of base task names to list of indices (for task_indices).

    names can repeat. Names are matched case-insensitively after strip.
    Raises ValueError if a name is not found or appears in multiple tasks.
    """
    name_to_index: dict[str, int] = {}
    for i, t in enumerate(base_tasks):
        key = (t.name or "").strip().lower()
        if key in name_to_index:
            raise ValueError(f"Duplicate base task name {t.name!r}")
        name_to_index[key] = i
    out: list[int] = []
    for n in names:
        key = (n or "").strip().lower()
        if key not in name_to_index:
            raise ValueError(
                f"No base task with name {n!r}; known: {list(name_to_index)}"
            )
        out.append(name_to_index[key])
    return out


def build_fake_project(
    base_fixtures: LoadedFixtures,
    config: FakeProjectConfig,
) -> LoadedFixtures:
    """Build a fake project from base fixtures.

    Base fixtures: (RawProject, list[RawTask], list[RawLabel],
    task_id -> (RawDataMeta, RawAnnotations)). Return has the same type:
    new project, new task list (optional reorder/repeat/names/statuses),
    same labels, task_data keyed by new task ids.

    - task_indices: which base tasks, in order (can repeat). If None:
      count + random (use seed for reproducibility).
    - task_id_order: "asc" (task_id_start, ...) or "random".
    - task_names: "keep" | "random" | "enumerated" | list (cycled).
    - task_statuses: "keep" | "random" | list (cycled).
    """
    _base_project, base_tasks, labels, task_data_map = base_fixtures
    if not base_tasks:
        raise ValueError("base_fixtures has no tasks")

    indices = _resolve_task_indices(base_tasks, config)
    task_ids = _resolve_task_ids(len(indices), config)
    rng = random.Random(config.seed)

    new_project = RawProject(id=config.project_id, name=config.project_name)
    new_tasks: list[RawTask] = []
    new_task_data: dict[int, tuple[RawDataMeta, RawAnnotations]] = {}

    for pos, (idx, new_id) in enumerate(zip(indices, task_ids, strict=True)):
        base_task = base_tasks[idx]
        data_meta, annotations = task_data_map[base_task.id]

        name = _resolve_name(pos, base_task, config, rng)
        status = _resolve_status(pos, base_task, config, rng)

        new_task = RawTask(
            id=new_id,
            name=name,
            status=status,
            subset=base_task.subset,
            updated_date=base_task.updated_date,
        )
        new_tasks.append(new_task)
        new_task_data[new_id] = (data_meta, annotations)

    return (new_project, new_tasks, labels, new_task_data)
