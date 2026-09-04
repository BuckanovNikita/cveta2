"""Integration test helpers: the stand client, the seeded project, live fixtures.

Everything here reads ``CVAT_INTEGRATION_*`` (exported by
``scripts/integration_env.sh``): host, credentials, the organization every
call is scoped to, and the full name of this run's seeded project.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

from cveta2._client.sdk_adapter import SdkCvatApiAdapter
from cveta2.config import CvatConfig
from tests.fixtures.fake_cvat_project import LoadedFixtures

if TYPE_CHECKING:
    from cvat_sdk import Client as CvatSdkClient

    from cveta2._client.dtos import RawAnnotations, RawDataMeta
    from cveta2._client.ports import CvatApiPort
    from cveta2.models import LabelInfo, ProjectInfo, TaskInfo

pytestmark = pytest.mark.integration


def _env(key: str, default: str) -> str:
    return os.environ.get(key, default).strip()


def make_integration_config() -> CvatConfig:
    """CvatConfig for the stand, scoped to the integration organization."""
    return CvatConfig(
        host=_env("CVAT_INTEGRATION_HOST", "http://cvat.k8s.localhost"),
        username=_env("CVAT_INTEGRATION_USER", "cveta2"),
        password=_env("CVAT_INTEGRATION_PASSWORD", ""),
        organization=_env("CVAT_INTEGRATION_ORG", "") or None,
    )


def _make_sdk_client() -> CvatSdkClient:
    """Create and return an opened cvat_sdk client scoped to the organization."""
    from cvat_sdk import make_client

    cfg = make_integration_config()
    client = make_client(host=cfg.host, credentials=(cfg.username, cfg.password))
    if cfg.organization:
        client.organization_slug = cfg.organization
    return client


def seeded_project_name() -> str:
    """Full name of this run's seeded project, ``"<run-tag> coco8-dev"``."""
    return _env("CVAT_INTEGRATION_PROJECT", "coco8-dev")


def find_seeded_project(adapter: CvatApiPort) -> ProjectInfo:
    """Return the seeded project by full name; skip if absent, fail if ambiguous.

    CVAT does not enforce unique project names, and two copies mean a run's
    cleanup did not happen - a duplicate is never silently the first match.
    """
    name = seeded_project_name()
    matches = [p for p in adapter.list_projects() if p.name == name]
    if not matches:
        pytest.skip(f"project '{name}' not found (run scripts/integration_up.sh first)")
    if len(matches) > 1:
        ids = ", ".join(str(p.id) for p in matches)
        pytest.fail(
            f"{len(matches)} projects named '{name}' (ids {ids}); "
            "run cvat_stand.py cleanup --tag and seed again"
        )
    return matches[0]


def fetch_live_fixtures() -> LoadedFixtures:
    """Connect to live CVAT and fetch the seeded project as LoadedFixtures.

    Called by the parameterized ``coco8_fixtures`` fixture in
    ``tests/conftest.py`` when ``request.param == "live"``.
    Skips the test session if CVAT is unreachable.
    """
    host = _env("CVAT_INTEGRATION_HOST", "http://cvat.k8s.localhost")
    try:
        client = _make_sdk_client()
    except OSError as exc:
        pytest.skip(f"CVAT not reachable at {host}: {exc}")

    try:
        adapter = SdkCvatApiAdapter(client)
        project = find_seeded_project(adapter)
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
