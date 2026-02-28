"""Integration test helpers: fetch LoadedFixtures from a live CVAT instance."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

from cveta2._client.sdk_adapter import SdkCvatApiAdapter
from tests.fixtures.fake_cvat_project import LoadedFixtures

if TYPE_CHECKING:
    from cvat_sdk import Client as CvatSdkClient

    from cveta2._client.dtos import RawAnnotations, RawDataMeta
    from cveta2.models import LabelInfo, ProjectInfo, TaskInfo

pytestmark = pytest.mark.integration


def _env(key: str, default: str) -> str:
    return os.environ.get(key, default).strip()


def _make_sdk_client() -> CvatSdkClient:
    """Create and return an opened cvat_sdk client."""
    from cvat_sdk import make_client

    host = _env("CVAT_INTEGRATION_HOST", "http://localhost:8080")
    username = _env("CVAT_INTEGRATION_USER", "admin")
    password = _env("CVAT_INTEGRATION_PASSWORD", "admin")
    return make_client(host=host, credentials=(username, password))


def fetch_live_fixtures() -> LoadedFixtures:
    """Connect to live CVAT and fetch coco8-dev project as LoadedFixtures.

    Called by the parameterized ``coco8_fixtures`` fixture in
    ``tests/conftest.py`` when ``request.param == "live"``.
    Skips the test session if CVAT is unreachable.
    """
    host = _env("CVAT_INTEGRATION_HOST", "http://localhost:8080")
    try:
        client = _make_sdk_client()
    except OSError as exc:
        pytest.skip(f"CVAT not reachable at {host}: {exc}")

    try:
        adapter = SdkCvatApiAdapter(client)
        projects: list[ProjectInfo] = adapter.list_projects()
        project: ProjectInfo | None = None
        for p in projects:
            if p.name.strip().lower() == "coco8-dev":
                project = p
                break

        if project is None:
            pytest.skip("coco8-dev project not found in CVAT (run seed_cvat.py first)")

        tasks: list[TaskInfo] = adapter.get_project_tasks(project.id)
        labels: list[LabelInfo] = adapter.get_project_labels(project.id)
        task_data: dict[int, tuple[RawDataMeta, RawAnnotations]] = {}
        for task in tasks:
            data_meta = adapter.get_task_data_meta(task.id)
            annotations = adapter.get_task_annotations(task.id)
            task_data[task.id] = (data_meta, annotations)

        return LoadedFixtures(
            project=project,
            tasks=tasks,
            labels=labels,
            task_data=task_data,
        )
    finally:
        client.close()
