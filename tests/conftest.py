"""Shared pytest fixtures for cveta2 tests (builders live in tests/helpers.py)."""

from __future__ import annotations

import os
import threading
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from loguru import logger
from tqdm import tqdm

from cveta2._client.mapping import _build_label_maps
from cveta2._concurrency import configure_workers
from tests.fixtures.load_cvat_fixtures import load_cvat_fixtures
from tests.helpers import build_fake, write_test_config

if TYPE_CHECKING:
    from collections.abc import Generator

    from _pytest.mark.structures import ParameterSet

    from cveta2._client.dtos import RawAnnotations, RawDataMeta
    from cveta2.models import TaskInfo
    from tests.fixtures.fake_cvat_project import LoadedFixtures

COCO8_DIR = Path(__file__).resolve().parent / "fixtures" / "cvat" / "coco8-dev"

# Cleared for every test so a developer's own CVAT credentials never leak in.
_CVAT_ENV_VARS = (
    "CVAT_HOST",
    "CVAT_ORGANIZATION",
    "CVAT_USERNAME",
    "CVAT_PASSWORD",
    "CVETA2_DATA_TIMEOUT",
    "CVETA2_CLEARML",
    "CVETA2_S3_WORKERS",
    "CVETA2_CVAT_WORKERS",
    "CVETA2_RETRY_ATTEMPTS",
)

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
        (
            "WARNING: CVAT detected at localhost:8080 but"
            " CVAT_INTEGRATION_HOST is not set."
        ),
        "  Integration tests will NOT run. To include them:",
        "  CVAT_INTEGRATION_HOST=http://localhost:8080 uv run pytest",
    ]


@pytest.fixture(scope="session", autouse=True)
def _fork_safe_tqdm() -> None:
    """Give tqdm no cross-process state, so a forked test session cannot hang.

    mutmut runs each mutant by forking the process that already ran the suite.
    Two pieces of tqdm's default global state do not survive that intact: the
    monitor ``Thread``, which the first bar a child closes tries to join even
    though it will never run there, and the write lock, whose
    ``multiprocessing.RLock`` half is one semaphore shared by every child, so a
    child killed while holding it wedges all the later ones. Either way the
    child hangs until mutmut's wall clock kills it and the gate reports a
    perfectly killable mutant as escaped. The monitor only auto-tunes the
    refresh rate and the lock only orders bars across processes, so no test
    behaviour depends on them.
    """
    tqdm.monitor_interval = 0
    tqdm.set_lock(threading.RLock())


@pytest.fixture(autouse=True)
def _isolate_task_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point XDG_CACHE_HOME at tmp_path so tests never touch the real ~/.cache."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))


@pytest.fixture(autouse=True)
def _disable_task_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disable the task-annotation cache for all tests; cache tests opt back in."""
    monkeypatch.setenv("CVETA2_DISABLE_CACHE", "true")


@pytest.fixture(autouse=True)
def _sequential_transfers() -> Generator[None, None, None]:
    """Run every test sequentially unless it asks for fan-out.

    Worker counts are process-wide and ``open_client`` installs the
    configured ones, so a single CLI test would otherwise leave every later
    test in that worker running its transfers concurrently — and a fan-out
    reorders S3 calls and adds a listing round-trip, which several tests
    legitimately assert on. Concurrency tests call ``configure_workers``
    themselves.
    """
    configure_workers(s3=1, cvat=1)
    yield
    configure_workers(s3=1, cvat=1)


@pytest.fixture(autouse=True)
def isolated_config_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point every config lookup at tmp_path so tests never read real config.

    Without this, ``CvatConfig.load()`` and ``get_projects_cache_path()`` fall
    back to the default location and test outcomes depend on the developer's own
    config. ``tests/env_isolation.py`` makes that fallback harmless; this fixture
    makes it unreachable, and gives each test its own config path. Named without
    a leading underscore because ``test_config`` requests its value.
    """
    cfg_path = tmp_path / "config.yaml"
    monkeypatch.setenv("CVETA2_CONFIG", str(cfg_path))
    for var in _CVAT_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    return cfg_path


@pytest.fixture
def test_config(isolated_config_path: Path) -> Path:
    """Write a minimal test config into the already-isolated config path."""
    write_test_config(isolated_config_path)
    return isolated_config_path


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


@pytest.fixture
def capture_info_logs() -> Generator[list[str], None, None]:
    """Capture loguru messages at INFO+ level into a list of strings.

    Separate from :func:`capture_logs` because a command whose entire
    output is INFO — `ignore --list`, `doctor` — has nothing to assert on
    at WARNING.
    """
    messages: list[str] = []
    handler_id = logger.add(
        lambda msg: messages.append(msg.record["message"]), level="INFO"
    )
    try:
        yield messages
    finally:
        logger.remove(handler_id)
