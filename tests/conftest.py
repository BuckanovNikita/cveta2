"""Shared pytest fixtures for cveta2 tests (builders live in tests/helpers.py)."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from hypothesis import HealthCheck, settings
from loguru import logger
from tqdm import tqdm

from cveta2.adapters.execution.concurrency import configure_workers
from cveta2.application.client.mapping import _build_label_maps
from tests.fixtures.load_cvat_fixtures import load_cvat_fixtures
from tests.helpers import build_fake, write_test_config

if TYPE_CHECKING:
    from collections.abc import Generator

    from cveta2.application.ports.dtos import RawAnnotations, RawDataMeta
    from cveta2.domain.models import TaskInfo
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

# Property tests stay deterministic and deadline-free by default: commits run
# them under xdist load, where wall-clock deadlines turn into flakes, and a
# fixed seed keeps a commit's verdict reproducible. That also means every run
# checks the same examples, so explore with random inputs from time to time:
#   HYPOTHESIS_PROFILE=explore uv run pytest -m "not integration" -p no:randomly
# A failure found there is stored in .hypothesis/ and replayed by later runs.
settings.register_profile(
    "cveta2",
    deadline=None,
    derandomize=True,
    max_examples=50,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.register_profile(
    "explore",
    deadline=None,
    derandomize=False,
    max_examples=1000,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "cveta2"))

INTEGRATION_DIR = Path(__file__).resolve().parent / "integration"
_COLLECTION_ORDER = pytest.StashKey[int]()
_collected = 0


def pytest_itemcollected(item: pytest.Item) -> None:
    """Mark live tests and put them in one xdist group.

    Every test under ``tests/integration`` is marked ``integration`` and joins
    the ``live`` xdist group: with ``--dist loadgroup`` one worker runs them
    serially, so the run's session fixture prepares the stands once. This runs
    per item during collection, before xdist reads the groups. Exclude them
    with ``-m "not integration"``.
    """
    global _collected  # noqa: PLW0603 - a per-process collection counter
    item.stash[_COLLECTION_ORDER] = _collected
    _collected += 1
    if item.path.resolve().is_relative_to(INTEGRATION_DIR):
        item.add_marker(pytest.mark.integration)
        item.add_marker(pytest.mark.xdist_group("live"))


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Keep the live tests in file order, then order the invariant guards first.

    pytest-randomly shuffles everything; the live tests share one seeded
    project and some add tasks to it, so they run in their collection order
    (in the slots the shuffle gave them) while unit tests stay shuffled.

    Invalid worker floors break the sequential-transfer fixture. The bounded
    stream rejects CSV scanning beyond EOF. Check both before dependent tests,
    even when a runner (or pytest-randomly, hence ``trylast``) supplies the
    selected tests in arbitrary order.
    """
    slots = [i for i, it in enumerate(items) if it.get_closest_marker("integration")]
    live = sorted((items[i] for i in slots), key=lambda it: it.stash[_COLLECTION_ORDER])
    for slot, item in zip(slots, live, strict=True):
        items[slot] = item

    guards = {
        "test_counts_below_one_are_floored": 0,
        "test_csv_reader_stops_after_first_eof": 1,
    }
    items.sort(key=lambda item: guards.get(item.name, len(guards)))


@pytest.fixture(scope="session")
def coco8_fixtures() -> LoadedFixtures:
    """Load the coco8-dev fixtures from their recorded JSON files."""
    return load_cvat_fixtures(COCO8_DIR)


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
def _hide_live_run_variables(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep a live run's credentials and endpoints away from unit tests.

    The live session fixture exports the run's variables into its worker and
    lists their names in ``CVETA2_LIVE_EXPORTED``; a unit test scheduled on the
    same worker after the live group must not see them.
    """
    if request.node.get_closest_marker("integration"):
        return
    for name in json.loads(os.environ.get("CVETA2_LIVE_EXPORTED", "[]")):
        monkeypatch.delenv(name, raising=False)


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

    Worker counts persist in the current runtime context and ``open_client``
    installs the configured ones, so a single CLI test would otherwise leave
    every later test in that worker running its transfers concurrently — and a fan-out
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
    handler_id = logger.add(lambda msg: messages.append(msg.record["message"]), level="WARNING")
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
    handler_id = logger.add(lambda msg: messages.append(msg.record["message"]), level="INFO")
    try:
        yield messages
    finally:
        logger.remove(handler_id)
