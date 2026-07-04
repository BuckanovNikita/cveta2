"""Shared pytest fixtures for cveta2 tests (builders live in tests/helpers.py)."""

from __future__ import annotations

import os
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from loguru import logger

from cveta2._client.mapping import _build_label_maps
from tests.fixtures.load_cvat_fixtures import load_cvat_fixtures
from tests.helpers import build_fake, write_test_config

if TYPE_CHECKING:
    from collections.abc import Generator

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


@pytest.fixture
def normal_fake(coco8_fixtures: LoadedFixtures) -> LoadedFixtures:
    """Build a single completed ``normal`` task — the most-used fetch scenario."""
    return build_fake(coco8_fixtures, ["normal"], statuses=["completed"])


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


@pytest.fixture(autouse=True)
def _isolate_task_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point XDG_CACHE_HOME at tmp_path so tests never touch the real ~/.cache."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))


@pytest.fixture(autouse=True)
def _disable_task_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disable the task-annotation cache for all tests; cache tests opt back in."""
    monkeypatch.setenv("CVETA2_DISABLE_CACHE", "true")


@pytest.fixture
def test_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Write a minimal test config and isolate env from real CVAT vars."""
    cfg_path = tmp_path / "config.yaml"
    write_test_config(cfg_path)
    monkeypatch.setenv("CVETA2_CONFIG", str(cfg_path))
    for var in ("CVAT_HOST", "CVAT_ORGANIZATION", "CVAT_USERNAME", "CVAT_PASSWORD"):
        monkeypatch.delenv(var, raising=False)
    return cfg_path


@pytest.fixture
def capture_logs() -> Generator[list[str], None, None]:
    """Capture loguru messages at WARNING+ level into a list of strings."""
    messages: list[str] = []
    handler_id = logger.add(
        lambda msg: messages.append(msg.record["message"]), level="WARNING"
    )
    try:
        yield messages
    finally:
        logger.remove(handler_id)
