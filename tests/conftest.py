"""Shared pytest fixtures for cveta2 tests."""

from __future__ import annotations

import os
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import yaml

from cveta2._client.mapping import _build_label_maps
from cveta2.client import CvatClient
from cveta2.config import CvatConfig
from cveta2.models import BBoxAnnotation
from tests.fixtures.fake_cvat_api import FakeCvatApi
from tests.fixtures.fake_cvat_project import (
    FakeProjectConfig,
    build_fake_project,
    task_indices_by_names,
)
from tests.fixtures.load_cvat_fixtures import load_cvat_fixtures

if TYPE_CHECKING:
    from _pytest.mark.structures import ParameterSet

    from cveta2._client.dtos import RawAnnotations, RawDataMeta
    from cveta2.models import TaskInfo
    from tests.fixtures.fake_cvat_project import LoadedFixtures

COCO8_DIR = Path(__file__).resolve().parent / "fixtures" / "cvat" / "coco8-dev"

# Gate tests/integration/ collection on CVAT_INTEGRATION_HOST env var.
collect_ignore_glob: list[str] = (
    [] if os.environ.get("CVAT_INTEGRATION_HOST") else ["integration/*"]
)


def _coco8_params() -> list[ParameterSet]:
    """Build parameterization list for coco8_fixtures."""
    params: list[ParameterSet] = [pytest.param("json", id="fixtures")]
    if os.environ.get("CVAT_INTEGRATION_HOST"):
        params.append(
            pytest.param("live", id="live-cvat", marks=pytest.mark.integration)
        )
    return params


@pytest.fixture(scope="session", params=_coco8_params())
def coco8_fixtures(request: pytest.FixtureRequest) -> LoadedFixtures:
    """Load coco8-dev fixtures from JSON files or live CVAT."""
    if request.param == "json":
        return load_cvat_fixtures(COCO8_DIR)
    # Lazy import to avoid failures when integration deps aren't needed
    from tests.integration.conftest import fetch_live_fixtures

    return fetch_live_fixtures()


@pytest.fixture(scope="session")
def coco8_label_maps(
    coco8_fixtures: LoadedFixtures,
) -> tuple[dict[int, str], dict[int, str]]:
    """Pre-built (label_names, attr_names) dicts from coco8-dev labels."""
    return _build_label_maps(coco8_fixtures.labels)


@pytest.fixture(scope="session")
def coco8_tasks_by_name(
    coco8_fixtures: LoadedFixtures,
) -> dict[str, tuple[TaskInfo, RawDataMeta, RawAnnotations]]:
    """Map task slug -> (TaskInfo, RawDataMeta, RawAnnotations)."""
    result: dict[str, tuple[TaskInfo, RawDataMeta, RawAnnotations]] = {}
    for task in coco8_fixtures.tasks:
        key = task.name.strip().lower()
        data_meta, annotations = coco8_fixtures.task_data[task.id]
        result[key] = (task, data_meta, annotations)
    return result


def pytest_report_header() -> list[str]:
    """Warn when CVAT is running but CVAT_INTEGRATION_HOST is not set."""
    if os.environ.get("CVAT_INTEGRATION_HOST"):
        return []
    try:
        urllib.request.urlopen("http://localhost:8080/api/server/about", timeout=1)
    except OSError:
        return []
    return [
        "WARNING: CVAT detected at localhost:8080 but"
        " CVAT_INTEGRATION_HOST is not set.",
        "  Integration tests will NOT run. To include them:",
        "  CVAT_INTEGRATION_HOST=http://localhost:8080 uv run pytest",
    ]


# ---------------------------------------------------------------------------
# Shared test helpers
# ---------------------------------------------------------------------------


def build_fake(
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


def make_fake_client(fixtures: LoadedFixtures) -> CvatClient:
    """Create a CvatClient backed by fake API data."""
    return CvatClient(CvatConfig(), api=FakeCvatApi(fixtures))


def write_test_config(
    path: Path,
    *,
    image_cache: dict[str, str] | None = None,
) -> None:
    """Write a minimal config YAML for testing."""
    data: dict[str, object] = {
        "cvat": {
            "host": "http://localhost:8080",
            "username": "test-user",
            "password": "test-password",
        },
    }
    if image_cache:
        data["image_cache"] = image_cache
    path.write_text(yaml.safe_dump(data), encoding="utf-8")


def make_bbox(**overrides: object) -> BBoxAnnotation:
    """Create a BBoxAnnotation with sensible defaults."""
    defaults: dict[str, object] = {
        "image_name": "img.jpg",
        "image_width": 640,
        "image_height": 480,
        "instance_label": "car",
        "bbox_x_tl": 10.0,
        "bbox_y_tl": 20.0,
        "bbox_x_br": 100.0,
        "bbox_y_br": 200.0,
        "task_id": 1,
        "task_name": "task-1",
        "task_status": "completed",
        "task_updated_date": "2026-01-01T00:00:00",
        "created_by_username": "tester",
        "frame_id": 0,
        "subset": "train",
        "occluded": False,
        "z_order": 0,
        "rotation": 0.0,
        "source": "manual",
        "annotation_id": 42,
        "attributes": {"color": "red"},
    }
    defaults.update(overrides)
    return BBoxAnnotation(**defaults)  # type: ignore[arg-type]
