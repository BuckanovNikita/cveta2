"""Live-test session and helpers: the session's services, its client and project.

The live tests are part of the normal pytest run. ``tests/conftest.py`` marks
every test here ``integration`` and puts it in the ``live`` xdist group, so one
worker runs them serially while unit tests stay parallel. The autouse session
fixture ``live_run`` starts one session through ``tests/integration/lifecycle.py``
before the first live test - its own namespace with CVAT, MinIO and ClearML,
after one bounded preflight in Task runs (``CVETA2_TASK_VERIFICATION=1``) and
otherwise waiting, with a notice, while the cluster is unavailable - and deletes it after
the last unless ``INTEGRATION_KEEP_DATA=1``. Everything else reads the
``CVAT_INTEGRATION_*``, ``MINIO_*`` and ``CLEARML_*`` variables it exports.
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
def live_run(request: pytest.FixtureRequest) -> Iterator[lifecycle.Session]:
    """Start this pytest session's live session, then delete or keep it.

    The session's variables stay in this worker's environment until the session
    ends; ``tests/conftest.py`` hides the names listed in
    ``CVETA2_LIVE_EXPORTED`` from unit tests, and teardown restores the
    environment.
    """
    saved = dict(os.environ)
    # SIGTERM becomes SystemExit while the session exists, so the cleanup in
    # prepare and below runs on termination as well as on Ctrl-C.
    with lifecycle.sigterm_as_exit():
        yield from _live_session(request, saved)


def _live_session(request: pytest.FixtureRequest, saved: dict[str, str]) -> Iterator[lifecycle.Session]:
    try:
        run = lifecycle.prepare(REPO_ROOT, notify=lambda m: _notify(request, m))
    except lifecycle.LifecycleError as error:
        refusal = "\n".join(error.lines)
    else:
        refusal = ""
    if refusal:
        pytest.fail(refusal, pytrace=False)
    os.environ[LIVE_EXPORTED_VARIABLE] = json.dumps(sorted(set(os.environ) - set(saved) | set(run.exported)))
    _notify(request, f"live session {run.namespace} is ready")
    try:
        yield run
    finally:
        try:
            failed = lifecycle.finish(run)
            kept = "kept" if lifecycle.keep_data() else "deleted"
            _notify(request, f"live session {run.namespace}: {'cleanup incomplete' if failed else kept}")
            if failed:
                pytest.fail(
                    f"session namespace '{run.namespace}' is not fully removed; retry with "
                    f"{lifecycle.MODULE} stop {run.namespace}; see the output above.",
                    pytrace=False,
                )
        finally:
            os.environ.clear()
            os.environ.update(saved)


def _env(key: str, default: str) -> str:
    return os.environ.get(key, default).strip()


def session_cvat_host() -> str:
    """Return the session's own CVAT host; there is no default to fall back to."""
    host = _env("CVAT_INTEGRATION_HOST", "")
    if not host:
        pytest.fail(
            "CVAT_INTEGRATION_HOST is not set; live tests run through pytest, whose "
            "live_run fixture starts the session, or after "
            f'eval "$({lifecycle.MODULE} env)"',
            pytrace=False,
        )
    return host


def make_integration_config() -> CvatConfig:
    """CvatConfig for the session's CVAT, scoped to the integration organization."""
    return CvatConfig(
        host=session_cvat_host(),
        username=_env("CVAT_INTEGRATION_USER", ""),
        password=_env("CVAT_INTEGRATION_PASSWORD", ""),
        organization=_env("CVAT_INTEGRATION_ORG", "") or None,
    )


def _make_sdk_client() -> CvatSdkClient:
    """Create and return an opened cvat_sdk client scoped to the organization.

    Skips the SDK's server-version check: the locked SDK is newer than the
    pinned server, and that check would be a second request per open, next to
    the login itself.
    """
    from cvat_sdk.api_client.exceptions import ApiException
    from cvat_sdk.core.client import Client
    from urllib3.exceptions import HTTPError as Urllib3Error

    cfg = make_integration_config()
    client = Client(cfg.host, check_server_version=False)
    try:
        client.login((cfg.username, cfg.password))
    except (OSError, ApiException, Urllib3Error):
        client.close()
        raise
    if cfg.organization:
        client.organization_slug = cfg.organization
    return client


def seeded_project_name() -> str:
    """Full name of this session's seeded project, ``"<namespace> coco8-dev"``."""
    return _env("CVAT_INTEGRATION_PROJECT", "coco8-dev")


def find_seeded_project(adapter: CvatApiPort) -> ProjectInfo:
    """Return the seeded project by full name; skip if absent, fail if ambiguous.

    CVAT does not enforce unique project names, and the session seeds exactly
    one - a duplicate is never silently the first match.
    """
    name = seeded_project_name()
    matches = [p for p in adapter.list_projects() if p.name == name]
    if not matches:
        pytest.skip(f"project '{name}' not found (run `uv run python -m tests.integration.lifecycle up` first)")
    if len(matches) > 1:
        ids = ", ".join(str(p.id) for p in matches)
        pytest.fail(f"{len(matches)} projects named '{name}' (ids {ids}); the session seeds one, start a new session")
    return matches[0]
