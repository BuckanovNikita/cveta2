"""Live-test session and helpers: the run on the stands, its client and project.

The live tests are part of the normal pytest run. ``tests/conftest.py`` marks
every test here ``integration`` and puts it in the ``live`` xdist group, so one
worker runs them serially (CVAT rate limits) while unit tests stay parallel.
The autouse session fixture ``live_run`` prepares one tagged run through
``tests/integration/lifecycle.py`` before the first live test - waiting, with a
notice, while the stands are stopped - and keeps or stops it after the last.
Everything else reads the ``CVAT_INTEGRATION_*`` variables that run exports.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from cveta2.adapters.config.settings import CvatConfig
from tests.integration import lifecycle
from tests.integration.stand_tls import StandTlsError, tls_failure_message

if TYPE_CHECKING:
    from collections.abc import Iterator

    from cvat_sdk import Client as CvatSdkClient

    from cveta2.application.ports.cvat import CvatApiPort
    from cveta2.domain.models import ProjectInfo

REPO_ROOT = Path(__file__).resolve().parents[2]


LIVE_EXPORTED_VARIABLE = "CVETA2_LIVE_EXPORTED"


def _notify(request: pytest.FixtureRequest, message: str) -> None:
    """Show *message* now, past output capture and a buffering hook runner.

    prek, like pre-commit, shows a hook's output only when the hook ends, so a
    terminal (``/dev/tty``) gets the notice directly; the stderr copy reaches
    the hook log and agent sessions without a terminal.
    """
    line = f"\n==> {message}\n"
    try:
        with Path("/dev/tty").open("w", encoding="utf-8") as tty:
            tty.write(line)
    except OSError:
        pass
    capture = request.config.pluginmanager.getplugin("capturemanager")
    if capture is None:
        sys.stderr.write(line)
        return
    with capture.global_and_fixture_disabled():
        sys.stderr.write(line)
        sys.stderr.flush()


@pytest.fixture(scope="session", autouse=True)
def live_run(request: pytest.FixtureRequest) -> Iterator[lifecycle.Run]:
    """Prepare this session's run on the stands, then keep or stop it.

    The run's variables stay in this worker's environment until the session
    ends; ``tests/conftest.py`` hides the names listed in
    ``CVETA2_LIVE_EXPORTED`` from unit tests, and teardown restores the
    environment.
    """
    saved = dict(os.environ)
    try:
        run = lifecycle.prepare(REPO_ROOT, notify=lambda m: _notify(request, m))
    except lifecycle.LifecycleError as error:
        refusal = "\n".join(error.lines)
    else:
        refusal = ""
    if refusal:
        pytest.fail(refusal, pytrace=False)
    os.environ[LIVE_EXPORTED_VARIABLE] = json.dumps(sorted(set(os.environ) - set(saved) | set(run.exported)))
    try:
        yield run
    finally:
        try:
            if lifecycle.finish(run):
                _notify(
                    request,
                    f"run '{run.tag}' is not fully torn down; see the output above.",
                )
        finally:
            os.environ.clear()
            os.environ.update(saved)


def _env(key: str, default: str) -> str:
    return os.environ.get(key, default).strip()


def make_integration_config() -> CvatConfig:
    """CvatConfig for the stand, scoped to the integration organization."""
    return CvatConfig(
        host=_env("CVAT_INTEGRATION_HOST", "https://cvat.k8s.docker.internal"),
        username=_env("CVAT_INTEGRATION_USER", "cveta2"),
        password=_env("CVAT_INTEGRATION_PASSWORD", ""),
        organization=_env("CVAT_INTEGRATION_ORG", "") or None,
    )


def _make_sdk_client() -> CvatSdkClient:
    """Create and return an opened cvat_sdk client scoped to the organization.

    Skips the SDK's server-version check: the stand throttles anonymous
    requests per client IP, and that check would be a second one per open,
    next to the login itself.
    """
    from cvat_sdk.api_client.exceptions import ApiException
    from cvat_sdk.core.client import Client
    from urllib3.exceptions import HTTPError as Urllib3Error

    cfg = make_integration_config()
    client = Client(cfg.host, check_server_version=False)
    try:
        client.login((cfg.username, cfg.password))
    except (OSError, ApiException, Urllib3Error) as exc:
        client.close()
        # A trust failure is an OSError too; callers skip on OSError as
        # "not reachable", so it is re-raised as a failure that names TLS.
        tls = tls_failure_message(exc, cfg.host)
        if tls is not None:
            raise StandTlsError(tls) from exc
        raise
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
        pytest.skip(f"project '{name}' not found (run `uv run python -m tests.integration.lifecycle up` first)")
    if len(matches) > 1:
        ids = ", ".join(str(p.id) for p in matches)
        pytest.fail(
            f"{len(matches)} projects named '{name}' (ids {ids}); run cvat_stand.py cleanup --tag and seed again"
        )
    return matches[0]
