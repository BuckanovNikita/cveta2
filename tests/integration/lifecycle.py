"""Live-test session lifecycle: one owned Kubernetes namespace per session.

The live tests in ``tests/integration`` are part of the normal pytest run: the
session fixture in ``tests/integration/conftest.py`` calls ``prepare`` before the
first live test and ``finish`` after the last one. The same steps by hand:

    uv run python -m tests.integration.lifecycle check   # bounded read-only preflight
    uv run python -m tests.integration.lifecycle up      # start and keep a session
    eval "$(uv run python -m tests.integration.lifecycle env)"  # its variables
    uv run python -m tests.integration.lifecycle stop [<namespace>]

A session creates the namespace ``cveta2-it-<UTC yyyymmdd-hhmmss>-<4 hex>`` in
the ``docker-desktop`` cluster, applies ``tests/integration/k8s/quota.yaml``
(quota and limit range) before any workload, generates its credentials into
the namespace's Secrets, applies the CVAT, MinIO and ClearML manifests next to
it, waits for them within a cold-start deadline (``CVETA2_SESSION_READY_TIMEOUT``,
300 seconds by default), reaches them through ``kubectl port-forward`` on
127.0.0.1, registers a regular CVAT user that owns one organization, and
seeds the run. The namespace name is also the run tag: the MinIO bucket and
the prefix of every CVAT and ClearML object. Teardown first requests deletion of
exactly that namespace, then stops the session's port-forwards and waits until
the namespace is gone; it runs on success, failure and interruption unless
``INTEGRATION_KEEP_DATA=1``.
A kept session (``up``, or the fixture with ``INTEGRATION_KEEP_DATA=1``) is
recorded with its local ports, never its credentials, in the gitignored
``tests/integration/.session``.

Exported for the session (and printed by ``env``): ``INTEGRATION_RUN_TAG``;
``CVAT_INTEGRATION_HOST/USER/PASSWORD/ORG/PROJECT``; ``MINIO_ENDPOINT`` (as the
host sees it), ``MINIO_ENDPOINT_FOR_CVAT`` (as the CVAT pods see it),
``MINIO_ACCESS_KEY/SECRET_KEY/REGION/BUCKET`` and the same MinIO as
``AWS_ACCESS_KEY_ID/SECRET_ACCESS_KEY/DEFAULT_REGION/ENDPOINT_URL``;
``CLEARML_API_HOST/FILES_HOST/WEB_HOST`` and ``CLEARML_API_ACCESS_KEY/SECRET_KEY``.

``check`` is read-only and bounded by ``CVETA2_INFRA_CHECK_TIMEOUT`` (60 seconds
by default): 0 AVAILABLE, 3 UNAVAILABLE (the cluster does not answer, or the
node cannot admit the session quota), 1 ERROR (a missing tool, or a context
that may not create or delete namespaces). Task-driven ``prepare`` repeats it;
direct operator ``up`` waits for an unavailable cluster instead, bounded by
``CVETA2_STAND_WAIT_TIMEOUT`` when set. Services that are not ready within the
cold-start deadline block setup (exit 3) and the namespace is deleted.

The module stays standard-library only. Inside pytest, ``tests.env_isolation``
replaces HOME; it records the real environment in ``CVETA2_REAL_ENV`` and this
module restores it for every child (kubectl and uv need the real HOME).
"""

import argparse
import base64
import io
import json
import math
import os
import re
import secrets
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import FrameType
from typing import Any, NoReturn

CONTEXT = "docker-desktop"
KUBECTL = ("kubectl", "--context", CONTEXT)
PREFIX = "cveta2-it-"
NAMESPACE_PATTERN = re.compile(r"^cveta2-it-[a-z0-9]([-a-z0-9]{0,51}[a-z0-9])?$")
PART_OF = ("app.kubernetes.io/part-of", "cveta2-integration")
MODULE = "uv run python -m tests.integration.lifecycle"
COCO8_URL = "https://github.com/ultralytics/assets/releases/download/v0.0.0/coco8.zip"
QUOTA_MANIFEST = "quota.yaml"
SERVICE_MANIFESTS = ("cvat.yaml", "minio.yaml", "clearml.yaml")
# Local name -> (Service, port) of every port-forward the host needs.
FORWARDS: dict[str, tuple[str, int]] = {
    "cvat": ("cvat-backend-service", 8080),
    "minio": ("minio", 9000),
    "clearml-api": ("clearml-apiserver", 8008),
    "clearml-files": ("clearml-fileserver", 8081),
}
CVAT_USER = "cveta2-it"
CVAT_ORG = "cveta2-it"
MINIO_REGION = "us-east-1"
READY_TIMEOUT_VARIABLE = "CVETA2_SESSION_READY_TIMEOUT"
DEFAULT_READY_TIMEOUT_SECONDS = 300.0
DELETE_TIMEOUT_SECONDS = 240.0
FORWARD_START_SECONDS = 30.0
BOOTSTRAP_SECONDS = 90.0
POLL_SECONDS = 3.0
KUBECTL_TIMEOUT_SECONDS = 120
# How long an interrupted or timed-out child may take to finish; execnet
# force-exits an interrupted xdist worker about 10 seconds after interrupting it.
CHILD_GRACE_SECONDS = 5.0
UNAVAILABLE_EXIT = 3


class LifecycleError(Exception):
    """A refusal or failure, reported as ``ERROR:`` plus indented detail lines."""

    def __init__(self, *lines: str) -> None:
        """Keep every line; the first is the headline."""
        super().__init__(lines[0])
        self.lines = lines


class InfrastructureUnavailableError(LifecycleError):
    """Temporary infrastructure unavailability; live verification is deferred."""


class SetupBlockedError(InfrastructureUnavailableError):
    """The session's services did not become ready within the cold-start deadline."""


def fail(*lines: str) -> NoReturn:
    raise LifecycleError(*lines)


def log(message: str) -> None:
    sys.stdout.write(f"==> {message}\n")


def warn(message: str) -> None:
    sys.stderr.write(f"{message}\n")


def report(error: LifecycleError) -> None:
    first, *rest = error.lines
    warn(f"ERROR: {first}")
    for line in rest:
        warn(f"       {line}")


REAL_ENV_VARIABLE = "CVETA2_REAL_ENV"


def child_env() -> dict[str, str]:
    """Return the environment with what env_isolation replaced restored.

    ``CVETA2_REAL_ENV`` maps each replaced name to its original value, or to
    null when it was unset; outside pytest it is absent and nothing changes.
    """
    environ = dict(os.environ)
    try:
        real = json.loads(environ.get(REAL_ENV_VARIABLE, "{}"))
    except json.JSONDecodeError:
        real = {}
    for name, value in real.items():
        if value is None:
            environ.pop(name, None)
        else:
            environ[name] = value
    return environ


def _probe_call(command: Sequence[str], deadline: float) -> subprocess.CompletedProcess[str]:
    """Bound a read-only probe and kill only its owned process group on timeout."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise InfrastructureUnavailableError("infrastructure preflight deadline expired")
    try:
        with subprocess.Popen(  # noqa: S603 - fixed read-only tool commands
            list(command),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=child_env(),
            start_new_session=True,
        ) as child:
            try:
                stdout, stderr = child.communicate(timeout=remaining)
            except (subprocess.TimeoutExpired, KeyboardInterrupt, SystemExit) as error:
                with suppress(ProcessLookupError):
                    os.killpg(child.pid, signal.SIGKILL)
                child.communicate()
                if isinstance(error, subprocess.TimeoutExpired):
                    raise InfrastructureUnavailableError(
                        f"infrastructure preflight timed out during {Path(command[0]).name}"
                    ) from error
                raise
    except FileNotFoundError:
        fail(f"{command[0]} is not installed or not on PATH; the live tests need it.")
    return subprocess.CompletedProcess(list(command), child.returncode, stdout, stderr)


def kubectl(
    *args: str,
    stdin: str | None = None,
    deadline: float | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run ``kubectl --context docker-desktop`` and return its result unchecked.

    Credentials only ever travel on stdin, never in the arguments, so neither a
    process listing nor an error message shows them.
    """
    command = [*KUBECTL, *args]
    if deadline is not None:
        return _probe_call(command, deadline)
    try:
        return subprocess.run(  # noqa: S603 - fixed tool commands
            command,
            input=stdin,
            check=False,
            capture_output=True,
            text=True,
            env=child_env(),
            timeout=KUBECTL_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        fail("kubectl is not installed or not on PATH; the live tests need it.")
    except subprocess.TimeoutExpired:
        fail(f"kubectl {' '.join(args[:3])} did not finish within {KUBECTL_TIMEOUT_SECONDS} s.")


def kubectl_ok(*args: str, stdin: str | None = None, what: str) -> str:
    """Run kubectl and return stdout; a non-zero exit is an error naming ``what``."""
    result = kubectl(*args, stdin=stdin)
    if result.returncode != 0:
        detail = (result.stderr or "").strip().splitlines()
        fail(f"{what} failed (kubectl exit {result.returncode}).", *(detail[-3:] or ["no detail"]))
    return result.stdout


def _stop_child(child: subprocess.Popen[str], signum: int) -> None:
    """Signal the child's process group, give it a grace period, then kill the group.

    A Ctrl-C while waiting kills it at once.
    """
    with suppress(ProcessLookupError, PermissionError):
        os.killpg(child.pid, signum)
    with suppress(subprocess.TimeoutExpired, KeyboardInterrupt):
        child.wait(timeout=CHILD_GRACE_SECONDS)
    if child.poll() is None:
        # The group leader is alive, so its group id cannot have been reused.
        with suppress(ProcessLookupError, PermissionError):
            os.killpg(child.pid, signal.SIGKILL)
        child.wait()


def call(command: Sequence[str], *, cwd: Path | None = None, timeout: float | None = None) -> int:
    """Run a child in its own process group and stop it together with this process.

    The child gets no terminal signals of its own: when this process is
    interrupted - Ctrl-C, or execnet interrupting an xdist worker, both a
    KeyboardInterrupt - the child's group gets SIGINT; on SIGTERM (SystemExit)
    or any other exception it gets SIGTERM. The child then has
    ``CHILD_GRACE_SECONDS`` to finish before the group is killed, so the
    session's teardown still runs before execnet force-exits the worker; a
    second Ctrl-C kills it at once. After ``timeout`` seconds the child is
    stopped the same way and ``subprocess.TimeoutExpired`` is raised.
    """
    with subprocess.Popen(  # noqa: S603 - fixed tool commands
        list(command), cwd=cwd, text=True, env=child_env(), stdin=subprocess.DEVNULL, start_new_session=True
    ) as child:
        try:
            return child.wait(timeout=timeout)
        except BaseException as interrupt:
            _stop_child(child, signal.SIGINT if isinstance(interrupt, KeyboardInterrupt) else signal.SIGTERM)
            raise


def require_session_name(namespace: str) -> str:
    """Accept only this tool's own namespace names; nothing else is ever deleted."""
    if not NAMESPACE_PATTERN.fullmatch(namespace):
        fail(
            f"'{namespace}' is not a live-test session namespace;",
            f"only names starting with '{PREFIX}' are created or deleted by this tool.",
        )
    return namespace


def new_session_name() -> str:
    stamp = datetime.now(tz=UTC).strftime("%Y%m%d-%H%M%S")
    return f"{PREFIX}{stamp}-{secrets.token_hex(2)}"


def namespace_exists(namespace: str) -> bool:
    result = kubectl("get", "namespace", namespace, "-o", "name")
    if result.returncode == 0:
        return True
    if "notfound" in (result.stderr or "").lower().replace(" ", ""):
        return False
    fail(f"cannot read namespace {namespace} (kubectl exit {result.returncode}); check kubectl access.")


# -- quantities and node admission -------------------------------------------

_QUANTITY = re.compile(r"^([0-9]+(?:\.[0-9]+)?(?:[eE][-+]?[0-9]+)?)([a-zA-Z]*)$")
_SUFFIXES = {
    "": 1.0,
    "n": 1e-9,
    "u": 1e-6,
    "m": 1e-3,
    "k": 1e3,
    "M": 1e6,
    "G": 1e9,
    "T": 1e12,
    "P": 1e15,
    "E": 1e18,
    "Ki": 2.0**10,
    "Mi": 2.0**20,
    "Gi": 2.0**30,
    "Ti": 2.0**40,
    "Pi": 2.0**50,
    "Ei": 2.0**60,
}


def quantity(text: str) -> float:
    """Value of a Kubernetes resource quantity such as ``250m`` or ``6Gi``."""
    match = _QUANTITY.match(str(text).strip())
    if match is None or match.group(2) not in _SUFFIXES:
        fail(f"unexpected resource quantity '{text}' in the cluster's answer")
    return float(match.group(1)) * _SUFFIXES[match.group(2)]


def _pod_requests(spec: dict[str, Any]) -> dict[str, float]:
    """Effective requests of one pod: its containers, or its largest init container."""
    total = {"cpu": 0.0, "memory": 0.0}
    for container in spec.get("containers", []):
        for name in total:
            total[name] += quantity(container.get("resources", {}).get("requests", {}).get(name, "0"))
    for container in spec.get("initContainers", []):
        requests = container.get("resources", {}).get("requests", {})
        for name, value in total.items():
            total[name] = max(value, quantity(requests.get(name, "0")))
    return total


def _json_output(result: subprocess.CompletedProcess[str], what: str) -> dict[str, Any]:
    if result.returncode != 0:
        fail(f"{what} failed (kubectl exit {result.returncode}); check kubectl access.")
    try:
        loaded = json.loads(result.stdout)
    except json.JSONDecodeError:
        fail(f"{what} returned something that is not JSON")
    if not isinstance(loaded, dict):
        fail(f"{what} returned an unexpected document")
    return loaded


def quota_requests(root: Path, deadline: float) -> dict[str, float]:
    """``requests.cpu`` and ``requests.memory`` of the session quota, read client-side."""
    manifest = root / "tests" / "integration" / "k8s" / QUOTA_MANIFEST
    result = kubectl("create", "--dry-run=client", "-o", "json", "-f", str(manifest), deadline=deadline)
    if _lost_connection(result):
        raise InfrastructureUnavailableError(f"the {CONTEXT} cluster stopped answering while reading the quota")
    if result.returncode != 0:
        fail(f"reading the session quota {manifest} failed (kubectl exit {result.returncode}).")
    # One JSON document per manifest document, concatenated.
    decoder, text, position, items = json.JSONDecoder(), result.stdout, 0, []
    while text[position:].strip():
        position += len(text[position:]) - len(text[position:].lstrip())
        try:
            item, position = decoder.raw_decode(text, position)
        except json.JSONDecodeError:
            fail(f"reading the session quota {manifest} returned something that is not JSON")
        items.append(item)
    for item in items:
        if item.get("kind") == "ResourceQuota":
            hard = item.get("spec", {}).get("hard", {})
            return {name: quantity(hard.get(f"requests.{name}", "0")) for name in ("cpu", "memory")}
    fail(f"{manifest} holds no ResourceQuota")


def _unschedulable(node: dict[str, Any]) -> list[str]:
    """Why the scheduler would place no session pod on *node*; empty when it may.

    The session's pods tolerate no taint, so any NoSchedule or NoExecute taint
    excludes the node, as do a cordon and a Ready condition that is not True.
    """
    reasons = []
    if node.get("spec", {}).get("unschedulable"):
        reasons.append("cordoned")
    conditions = node.get("status", {}).get("conditions", [])
    if not any(c.get("type") == "Ready" and c.get("status") == "True" for c in conditions):
        reasons.append("not Ready")
    reasons.extend(
        f"taint {taint.get('key', '?')}:{taint['effect']}"
        for taint in node.get("spec", {}).get("taints", []) or []
        if taint.get("effect") in {"NoSchedule", "NoExecute"}
    )
    return reasons


def node_admission(root: Path, deadline: float) -> str | None:
    """None when a schedulable node can admit the session quota's requests; else the reason."""
    need = quota_requests(root, deadline)
    nodes = _probe_json(kubectl("get", "nodes", "-o", "json", deadline=deadline), "listing nodes")
    pods = _probe_json(
        kubectl(
            "get",
            "pods",
            "--all-namespaces",
            "--field-selector=status.phase!=Succeeded,status.phase!=Failed",
            "-o",
            "json",
            deadline=deadline,
        ),
        "listing pods",
    )
    used: dict[str, dict[str, float]] = {}
    for pod in pods.get("items", []):
        node = pod.get("spec", {}).get("nodeName")
        if not node:
            continue
        requests = _pod_requests(pod.get("spec", {}))
        bucket = used.setdefault(node, {"cpu": 0.0, "memory": 0.0})
        for name, value in requests.items():
            bucket[name] += value
    shortfalls = []
    for node in nodes.get("items", []):
        name = node.get("metadata", {}).get("name", "?")
        ineligible = _unschedulable(node)
        if ineligible:
            shortfalls.append(f"{name} does not accept new pods ({', '.join(ineligible)})")
            continue
        allocatable = node.get("status", {}).get("allocatable", {})
        free = {
            resource: quantity(allocatable.get(resource, "0")) - used.get(name, {}).get(resource, 0.0)
            for resource in ("cpu", "memory")
        }
        if all(free[resource] >= need[resource] for resource in need):
            return None
        shortfalls.append(
            f"{name} has {free['cpu']:.2f} CPU and {free['memory'] / 2**30:.1f} GiB unrequested, "
            f"the session quota requests {need['cpu']:.2f} CPU and {need['memory'] / 2**30:.1f} GiB"
        )
    return "; ".join(shortfalls) or "the cluster reports no node"


# -- preflight ---------------------------------------------------------------

PROBE_TIMEOUT_SECONDS = 20
WAIT_TIMEOUT_VARIABLE = "CVETA2_STAND_WAIT_TIMEOUT"
CHECK_TIMEOUT_VARIABLE = "CVETA2_INFRA_CHECK_TIMEOUT"
DEFAULT_CHECK_TIMEOUT_SECONDS = 60.0
FIRST_DELAY_SECONDS = 15.0
MAX_DELAY_SECONDS = 60.0
HEARTBEAT_SECONDS = 300.0


def _cluster_available(deadline: float) -> str | None:
    """Separate Kubernetes access errors from temporary connectivity failures."""
    try:
        result = _probe_call([*KUBECTL, "get", "--raw=/readyz"], deadline)
    except InfrastructureUnavailableError as error:
        return str(error)
    if result.returncode == 0:
        return None
    detail = result.stderr.lower()
    if any(term in detail for term in ("unauthorized", "forbidden", "certificate", "x509", "invalid credentials")):
        fail("Kubernetes access, context, credentials or TLS configuration failed; check kubectl access.")
    if "context" in detail and ("does not exist" in detail or "not found" in detail):
        fail(f"kubectl has no context '{CONTEXT}'; the live tests run on Docker Desktop's Kubernetes.")
    if _lost_connection(result):
        return f"the {CONTEXT} cluster does not answer"
    fail(f"Kubernetes readiness probe failed unexpectedly (exit {result.returncode}); check kubectl access.")


_CONNECTIVITY_TERMS = (
    "connection refused",
    # kubectl's own wording when nothing listens on the API port, as
    # when Docker Desktop's Kubernetes is stopped.
    "was refused",
    "connection reset",
    "timed out",
    "timeout",
    "deadline exceeded",
    "no such host",
    "unreachable",
    "eof",
    "serviceunavailable",
    "unable to handle the request",
)


def _lost_connection(result: subprocess.CompletedProcess[str]) -> bool:
    """Whether a failed kubectl call reports a connectivity failure, not an answer."""
    detail = (result.stderr or "").lower()
    return result.returncode != 0 and any(term in detail for term in _CONNECTIVITY_TERMS)


def _probe_json(result: subprocess.CompletedProcess[str], what: str) -> dict[str, Any]:
    """Like ``_json_output`` for a preflight probe: lost connectivity is an outage."""
    if _lost_connection(result):
        raise InfrastructureUnavailableError(f"the {CONTEXT} cluster stopped answering while {what}")
    return _json_output(result, what)


def _namespace_rights(deadline: float) -> None:
    """Require the right to create and delete namespaces; a refusal is an error, not an outage."""
    for verb in ("create", "delete"):
        result = _probe_call([*KUBECTL, "auth", "can-i", verb, "namespaces"], deadline)
        answer = result.stdout.strip()
        if not answer and _lost_connection(result):
            raise InfrastructureUnavailableError(
                f"the {CONTEXT} cluster stopped answering while checking the right to {verb} namespaces"
            )
        if answer != "yes":
            fail(
                f"the {CONTEXT} context may not {verb} namespaces (kubectl auth can-i answered "
                f"'{result.stdout.strip() or result.stderr.strip()[:80]}');",
                "a live session creates and deletes its own namespace.",
            )


def probe(root: Path, *, deadline: float | None = None) -> str | None:
    """Read-only availability: None when a session can start, else why it cannot.

    "Unavailable" is what waiting can fix: a cluster that does not answer, or
    a node without room for the session quota. A missing tool, a missing
    context or a refused namespace permission is raised as a LifecycleError.
    """
    deadline = deadline if deadline is not None else time.monotonic() + PROBE_TIMEOUT_SECONDS
    reason = _cluster_available(deadline)
    if reason is not None:
        return reason
    try:
        _namespace_rights(deadline)
        return node_admission(root, deadline)
    except InfrastructureUnavailableError as error:
        return str(error)


def check_timeout() -> float:
    raw = os.environ.get(CHECK_TIMEOUT_VARIABLE, str(DEFAULT_CHECK_TIMEOUT_SECONDS))
    try:
        timeout = float(raw)
    except ValueError:
        fail(f"{CHECK_TIMEOUT_VARIABLE} must be a positive finite number of seconds")
    if not math.isfinite(timeout) or timeout <= 0:
        fail(f"{CHECK_TIMEOUT_VARIABLE} must be a positive finite number of seconds")
    return timeout


def check_infrastructure(root: Path) -> None:
    """One read-only preflight, with one overall deadline and no polling."""
    reason = probe(root, deadline=time.monotonic() + check_timeout())
    if reason is not None:
        raise InfrastructureUnavailableError(reason)


def _minutes(seconds: float) -> str:
    return f"{int(seconds // 60)} мин {int(seconds % 60)} с"


def wait_for_cluster(
    check: Callable[[], str | None],
    *,
    notify: Callable[[str], None],
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
    timeout: float | None = None,
) -> None:
    """Poll until a session can start; say once that we wait, then heartbeat.

    The wait is unbounded unless a timeout is given; Ctrl-C ends it, and
    nothing has been created at that point.
    """
    started = now()
    delay = FIRST_DELAY_SECONDS
    last_notice: float | None = None
    while True:
        reason = check()
        if reason is None:
            if last_notice is not None:
                notify(f"Кластер снова доступен (ожидание {_minutes(now() - started)}); продолжаю.")
            return
        elapsed = now() - started
        if timeout is not None and elapsed >= timeout:
            fail(f"Кластер не стал доступен за {int(timeout)} с ({WAIT_TIMEOUT_VARIABLE}): {reason}.")
        if last_notice is None:
            notify(
                f"Кластер недоступен: {reason}. Жду восстановления (Ctrl-C - прервать). "
                "Пока идёт коммит, не редактируйте рабочую копию."
            )
            last_notice = now()
        elif now() - last_notice >= HEARTBEAT_SECONDS:
            notify(f"Всё ещё жду кластер ({_minutes(elapsed)}): {reason}.")
            last_notice = now()
        sleep(delay if timeout is None else min(delay, timeout - elapsed))
        delay = min(delay * 2, MAX_DELAY_SECONDS)


def wait_timeout() -> float | None:
    raw = os.environ.get(WAIT_TIMEOUT_VARIABLE, "").strip()
    if not raw:
        return None
    try:
        return max(float(raw), 0.0)
    except ValueError:
        fail(f"{WAIT_TIMEOUT_VARIABLE}={raw} is not a number of seconds.")


def ready_timeout() -> float:
    raw = os.environ.get(READY_TIMEOUT_VARIABLE, "").strip()
    if not raw:
        return DEFAULT_READY_TIMEOUT_SECONDS
    try:
        timeout = float(raw)
    except ValueError:
        timeout = math.nan
    if not math.isfinite(timeout) or timeout <= 0:
        fail(f"{READY_TIMEOUT_VARIABLE} must be a positive finite number of seconds")
    return timeout


# -- port-forwards -----------------------------------------------------------


def forward_log_dir() -> Path:
    directory = Path(tempfile.gettempdir()) / "cveta2-it-port-forwards"
    directory.mkdir(mode=0o700, exist_ok=True)
    return directory


def port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe_socket:
        try:
            probe_socket.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def forward_command(namespace: str) -> list[str]:
    """Return the exact argv prefix of every port-forward a session starts."""
    return [*KUBECTL, "-n", namespace, "port-forward"]


def session_forward_pids(namespace: str) -> list[int]:
    """Find the processes whose command line is exactly this session's port-forward."""
    prefix = forward_command(namespace)
    found: list[int] = []
    proc = Path("/proc")
    if not proc.is_dir():
        return found
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            argv = (entry / "cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        words = [Path(argv[0].decode(errors="replace")).name] + [w.decode(errors="replace") for w in argv[1:]]
        if words[: len(prefix)] == prefix:
            found.append(int(entry.name))
    return found


@dataclass
class Forward:
    """One running ``kubectl port-forward`` to a session Service."""

    name: str
    port: int
    process: subprocess.Popen[bytes]
    log_path: Path

    def alive(self) -> bool:
        return self.process.poll() is None

    def stop(self) -> None:
        if self.alive():
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self.log_path.unlink(missing_ok=True)


_FORWARDING = re.compile(r"Forwarding from 127\.0\.0\.1:(\d+) ->")


def start_forward(namespace: str, name: str, local_port: int | None) -> Forward:
    """Forward a loopback port to one session Service and wait until it listens.

    kubectl writes a line per connection, so its output goes to a file rather
    than a pipe nobody drains; the first line names the port it bound.
    """
    service, target = FORWARDS[name]
    log_path = forward_log_dir() / f"{namespace}-{name}.log"
    with log_path.open("wb") as output:
        process = subprocess.Popen(  # noqa: S603 - fixed tool command
            [
                *forward_command(namespace),
                "--address",
                "127.0.0.1",
                f"svc/{service}",
                f"{local_port or ''}:{target}",
            ],
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            env=child_env(),
            start_new_session=True,
        )
    forward_deadline = time.monotonic() + FORWARD_START_SECONDS
    while time.monotonic() < forward_deadline:
        text = log_path.read_text(encoding="utf-8", errors="replace")
        match = _FORWARDING.search(text)
        if match:
            return Forward(name, int(match.group(1)), process, log_path)
        if process.poll() is not None:
            break
        time.sleep(0.2)
    forward = Forward(name, 0, process, log_path)
    detail = log_path.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-2:]
    forward.stop()
    fail(f"the port-forward to {service} in {namespace} did not start.", *detail)


def stop_session_forwards(namespace: str) -> None:
    """Stop every port-forward of exactly this namespace, wherever it was started."""
    pids = session_forward_pids(namespace)
    for pid in pids:
        with suppress(ProcessLookupError, PermissionError):
            os.kill(pid, signal.SIGTERM)
    # Wait until they have released their ports, so env can bind them again.
    stop_deadline = time.monotonic() + 10
    while pids and time.monotonic() < stop_deadline:
        pids = [pid for pid in pids if Path(f"/proc/{pid}").exists()]
        time.sleep(0.1)
    for log_path in forward_log_dir().glob(f"{namespace}-*.log"):
        log_path.unlink(missing_ok=True)


# -- credentials -------------------------------------------------------------


def _secret(name: str, data: dict[str, str]) -> dict[str, Any]:
    return {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {"name": name, "labels": {PART_OF[0]: PART_OF[1]}},
        "type": "Opaque",
        "stringData": data,
    }


def generated_secrets() -> list[dict[str, Any]]:
    """Fresh credentials for every service of one session; never stored elsewhere."""
    return [
        _secret(
            "cvat-postgres-secret",
            {"username": "cvat", "database": "cvat", "password": secrets.token_hex(16)},
        ),
        _secret("cvat-redis-secret", {"password": secrets.token_hex(16)}),
        _secret("cvat-kvrocks-secret", {"password": secrets.token_hex(16)}),
        _secret(
            "cvat-user",
            {"username": CVAT_USER, "password": secrets.token_urlsafe(24), "organization": CVAT_ORG},
        ),
        _secret(
            "minio-credentials",
            {"access-key": secrets.token_hex(10), "secret-key": secrets.token_hex(20), "region": MINIO_REGION},
        ),
        _secret(
            "clearml-credentials",
            {
                "apiserver-key": secrets.token_hex(12).upper(),
                "apiserver-secret": secrets.token_urlsafe(32),
                "tests-key": secrets.token_hex(12).upper(),
                "tests-secret": secrets.token_urlsafe(32),
                "token-secret": secrets.token_urlsafe(32),
            },
        ),
    ]


def read_secret(namespace: str, name: str) -> dict[str, str]:
    """Decode one session Secret without ever printing it."""
    document = _json_output(
        kubectl("-n", namespace, "get", "secret", name, "-o", "json"), f"reading Secret {name} of {namespace}"
    )
    data = document.get("data") or {}
    return {key: base64.b64decode(value).decode() for key, value in data.items()}


# -- CVAT bootstrap ----------------------------------------------------------

_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _http_json(method: str, url: str, body: dict[str, Any], token: str | None = None) -> tuple[int, Any]:
    """One JSON request to the session CVAT over loopback; no proxy, no logging."""
    # CVAT negotiates its API version on this media type; plain JSON gets HTTP 406.
    headers = {"Content-Type": "application/json", "Accept": "application/vnd.cvat+json"}
    if token:
        headers["Authorization"] = f"Token {token}"
    request = urllib.request.Request(  # noqa: S310 - loopback http URL built by this module
        url, data=json.dumps(body).encode(), headers=headers, method=method
    )
    try:
        with _DIRECT.open(request, timeout=30) as response:
            raw = response.read()
            status = response.status
    except urllib.error.HTTPError as error:
        raw = error.read()
        status = error.code
    try:
        return status, json.loads(raw or b"null")
    except json.JSONDecodeError:
        return status, None


def bootstrap_cvat(host: str, user: dict[str, str]) -> None:
    """Register the session's regular user and the organization it owns.

    Retries while CVAT still warms up (no answer or 5xx); any other refusal is
    an error. The response bodies are never shown: they may echo credentials.
    """
    bootstrap_deadline = time.monotonic() + BOOTSTRAP_SECONDS
    steps: list[tuple[str, str, dict[str, Any], set[int]]] = [
        (
            "registering the CVAT user",
            "/api/auth/register",
            {
                "username": user["username"],
                "email": f"{user['username']}@example.com",
                "password1": user["password"],
                "password2": user["password"],
                "first_name": "cveta2",
                "last_name": "integration",
                "confirmations": [],
            },
            {201},
        ),
        ("logging in to CVAT", "/api/auth/login", {"username": user["username"], "password": user["password"]}, {200}),
    ]
    token = ""
    for what, path, body, expected in steps:
        while True:
            try:
                status, answer = _http_json("POST", f"{host}{path}", body)
            except (OSError, urllib.error.URLError):
                status, answer = 0, None
            if status in expected:
                if isinstance(answer, dict) and answer.get("key"):
                    token = str(answer["key"])
                break
            if (status == 0 or status >= 500) and time.monotonic() < bootstrap_deadline:
                time.sleep(POLL_SECONDS)
                continue
            fail(f"{what} at {host} failed (HTTP {status or 'no answer'}).")
    if not token:
        fail(f"logging in to CVAT at {host} returned no token.")
    status, _ = _http_json(
        "POST", f"{host}/api/organizations", {"slug": user["organization"], "name": "cveta2 integration"}, token
    )
    if status != 201:
        fail(f"creating CVAT organization {user['organization']} at {host} failed (HTTP {status}).")


# -- the session -------------------------------------------------------------


def manifest_dir(root: Path) -> Path:
    return root / "tests" / "integration" / "k8s"


def session_file(root: Path) -> Path:
    return root / "tests" / "integration" / ".session"


def read_session_record(root: Path) -> tuple[str, dict[str, int]] | None:
    """Return the kept session of this checkout (namespace and local ports), or None."""
    path = session_file(root)
    if not path.is_file():
        return None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        namespace = require_session_name(str(record["namespace"]))
        ports = {str(k): int(v) for k, v in dict(record.get("ports", {})).items()}
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, LifecycleError):
        fail(f"{path} does not describe a kept session; delete it if that session is gone.")
    return namespace, ports


def write_session_record(root: Path, namespace: str, ports: dict[str, int]) -> None:
    session_file(root).write_text(json.dumps({"namespace": namespace, "ports": ports}) + "\n", encoding="utf-8")


def forget_session_record(root: Path, namespace: str) -> None:
    record = None
    with suppress(LifecycleError):
        record = read_session_record(root)
    if record is not None and record[0] == namespace:
        session_file(root).unlink(missing_ok=True)


@dataclass
class Session:
    """One live session: its namespace, its port-forwards and what it exports."""

    root: Path
    namespace: str
    exported: dict[str, str] = field(default_factory=dict)
    forwards: dict[str, Forward] = field(default_factory=dict)
    # Teardown deletes the namespace only once this session created it, so a
    # failed create can never remove a namespace somebody else owns.
    created: bool = False

    # -- environment ------------------------------------------------------

    def _export(self, **values: str) -> None:
        os.environ.update(values)
        self.exported.update(values)

    def ports(self) -> dict[str, int]:
        return {name: forward.port for name, forward in self.forwards.items()}

    def start_forwards(self, wanted: dict[str, int] | None = None) -> None:
        """Start the four port-forwards, on the wanted ports when they are free."""
        wanted = wanted or {}
        moved = []
        for name in FORWARDS:
            port = wanted.get(name)
            if port is not None and not port_is_free(port):
                moved.append(f"{name} (was {port})")
                port = None
            self.forwards[name] = start_forward(self.namespace, name, port)
        if moved and wanted:
            warn(
                f"WARNING: recorded local ports are taken, new ones were chosen for {', '.join(moved)}; "
                "ClearML file URLs stored by this session may point at the old port."
            )

    def stop_forwards(self) -> list[str]:
        """Stop this process's forwards; return the ones that had already died."""
        dead = [name for name, forward in self.forwards.items() if not forward.alive()]
        for forward in self.forwards.values():
            forward.stop()
        self.forwards.clear()
        return dead

    def export_environment(self) -> None:
        """Export the names the tests read, from the Secrets and the forwards."""
        user = read_secret(self.namespace, "cvat-user")
        minio = read_secret(self.namespace, "minio-credentials")
        clearml = read_secret(self.namespace, "clearml-credentials")
        url = {name: f"http://127.0.0.1:{forward.port}" for name, forward in self.forwards.items()}
        self._export(
            INTEGRATION_RUN_TAG=self.namespace,
            CVAT_INTEGRATION_HOST=url["cvat"],
            CVAT_INTEGRATION_USER=user["username"],
            CVAT_INTEGRATION_PASSWORD=user["password"],
            CVAT_INTEGRATION_ORG=user["organization"],
            CVAT_INTEGRATION_PROJECT=f"{self.namespace} coco8-dev",
            MINIO_ENDPOINT=url["minio"],
            MINIO_ENDPOINT_FOR_CVAT=f"http://minio.{self.namespace}.svc.cluster.local:9000",
            MINIO_ACCESS_KEY=minio["access-key"],
            MINIO_SECRET_KEY=minio["secret-key"],
            MINIO_REGION=minio["region"],
            MINIO_BUCKET=self.namespace,
            AWS_ACCESS_KEY_ID=minio["access-key"],
            AWS_SECRET_ACCESS_KEY=minio["secret-key"],
            AWS_DEFAULT_REGION=minio["region"],
            AWS_ENDPOINT_URL=url["minio"],
            CLEARML_API_HOST=url["clearml-api"],
            CLEARML_FILES_HOST=url["clearml-files"],
            CLEARML_WEB_HOST=url["clearml-api"],
            CLEARML_API_ACCESS_KEY=clearml["tests-key"],
            CLEARML_API_SECRET_KEY=clearml["tests-secret"],
        )

    # -- setup ------------------------------------------------------------

    def create(self) -> None:
        """Create the namespace, then its quota, then its Secrets: before any workload."""
        namespace = {
            "apiVersion": "v1",
            "kind": "Namespace",
            "metadata": {"name": require_session_name(self.namespace), "labels": {PART_OF[0]: PART_OF[1]}},
        }
        kubectl_ok("create", "-f", "-", stdin=json.dumps(namespace), what=f"creating namespace {self.namespace}")
        self.created = True
        log(f"Session namespace {self.namespace} created")
        kubectl_ok(
            "-n",
            self.namespace,
            "apply",
            "-f",
            str(manifest_dir(self.root) / QUOTA_MANIFEST),
            what="applying the session quota and limit range",
        )
        kubectl_ok(
            "-n",
            self.namespace,
            "apply",
            "-f",
            "-",
            stdin=json.dumps({"apiVersion": "v1", "kind": "List", "items": generated_secrets()}),
            what="storing the session credentials",
        )

    def deploy(self) -> None:
        files = [arg for name in SERVICE_MANIFESTS for arg in ("-f", str(manifest_dir(self.root) / name))]
        kubectl_ok("-n", self.namespace, "apply", *files, what="applying the CVAT, MinIO and ClearML manifests")
        log("CVAT, MinIO and ClearML applied; waiting until they are ready")

    def _not_ready(self) -> list[str]:
        """Components that are not ready yet; fails when the session cannot become ready."""
        document = _json_output(
            kubectl("-n", self.namespace, "get", "deployments,jobs", "-o", "json"),
            f"reading the workloads of {self.namespace}",
        )
        items = document.get("items", [])
        if not items:
            if not namespace_exists(self.namespace):
                fail(f"namespace {self.namespace} disappeared during setup.")
            return ["workloads not created yet"]
        pending = []
        for item in items:
            name = item["metadata"]["name"]
            status = item.get("status", {})
            if item["kind"] == "Job":
                if any(c.get("type") == "Failed" and c.get("status") == "True" for c in status.get("conditions", [])):
                    fail(f"job {name} in {self.namespace} failed; see kubectl -n {self.namespace} logs job/{name}.")
                if not status.get("succeeded"):
                    pending.append(f"job/{name}")
            elif (status.get("availableReplicas") or 0) < item.get("spec", {}).get("replicas", 1):
                pending.append(f"deployment/{name}")
        return pending

    def _waiting_reasons(self) -> list[str]:
        pods = _json_output(
            kubectl("-n", self.namespace, "get", "pods", "-o", "json"), f"reading the pods of {self.namespace}"
        )
        reasons = []
        for pod in pods.get("items", []):
            statuses = pod.get("status", {}).get("initContainerStatuses", []) + pod.get("status", {}).get(
                "containerStatuses", []
            )
            for status in statuses:
                waiting = status.get("state", {}).get("waiting")
                if waiting:
                    reasons.append(f"{pod['metadata']['name']}/{status['name']}: {waiting.get('reason', 'waiting')}")
        return reasons

    def wait_ready(self) -> None:
        timeout = ready_timeout()
        started = time.monotonic()
        while True:
            pending = self._not_ready()
            if not pending:
                log(f"Every service is ready ({time.monotonic() - started:.0f} s)")
                return
            if time.monotonic() - started >= timeout:
                reasons = self._waiting_reasons()
                raise SetupBlockedError(
                    f"session {self.namespace} was not ready within {timeout:.0f} s ({READY_TIMEOUT_VARIABLE})",
                    f"not ready: {', '.join(pending)}",
                    *(f"waiting: {reason}" for reason in reasons[:6]),
                )
            time.sleep(POLL_SECONDS)

    def uv_python(self, *args: str) -> int:
        return call(["uv", "run", "python", *args], cwd=self.root)

    def _require(self, status: int, command: str) -> None:
        if status != 0:
            fail(f"{command} failed with exit status {status} (see above).")

    def up(self) -> None:
        """Create, deploy, wait, reach, bootstrap, verify and seed this session."""
        self.create()
        self.deploy()
        self.wait_ready()
        self.start_forwards()
        user = read_secret(self.namespace, "cvat-user")
        host = f"http://127.0.0.1:{self.forwards['cvat'].port}"
        log(f"Registering CVAT user {user['username']} and organization {user['organization']}")
        bootstrap_cvat(host, user)
        self.export_environment()
        self._require(self.uv_python("tests/integration/cvat_stand.py", "verify"), "cvat_stand.py verify")
        self._ensure_coco8_images()
        log(f"Seeding bucket '{self.namespace}' and project '{os.environ['CVAT_INTEGRATION_PROJECT']}'")
        self._require(self.uv_python("tests/integration/seed_cvat.py"), "seed_cvat.py")
        log(f"Session {self.namespace} is ready:")
        log(f"CVAT:     {host}  (organization {user['organization']})")
        log(f"MinIO:    {os.environ['MINIO_ENDPOINT']}  (for CVAT: {os.environ['MINIO_ENDPOINT_FOR_CVAT']})")
        log(f"ClearML:  {os.environ['CLEARML_API_HOST']}  (files {os.environ['CLEARML_FILES_HOST']})")

    def _ensure_coco8_images(self) -> None:
        images = self.root / "tests" / "fixtures" / "data" / "coco8" / "images"
        if (images / "train").is_dir() and (images / "val").is_dir():
            log("coco8 images already present")
            return
        log("Downloading coco8 dataset images")
        with tempfile.TemporaryDirectory(prefix="coco8-") as scratch:
            archive = Path(scratch) / "coco8.zip"
            urllib.request.urlretrieve(COCO8_URL, archive)
            with zipfile.ZipFile(archive) as bundle:
                bundle.extractall(scratch)
            images.mkdir(parents=True, exist_ok=True)
            for split in ("train", "val"):
                shutil.copytree(Path(scratch) / "coco8" / "images" / split, images / split, dirs_exist_ok=True)
        log(f"coco8 images extracted to {images}")

    # -- teardown ---------------------------------------------------------

    def stop(self) -> int:
        """Delete exactly this namespace and stop its port-forwards.

        The delete request goes out first: an interrupted pytest worker may be
        force-exited before the rest of teardown finishes.
        """
        dead = [name for name, forward in self.forwards.items() if not forward.alive()]
        requested = request_deletion(self.namespace) if self.created else True
        self.stop_forwards()
        for name in dead:
            warn(f"WARNING: the port-forward to {FORWARDS[name][0]} had stopped before teardown;")
            warn("         tests after that point lost their connection to that service.")
        if not self.created:
            return 0
        stop_session_forwards(self.namespace)
        if not requested:
            return 1
        return await_deletion(self.root, self.namespace)


def request_deletion(namespace: str) -> bool:
    """Ask the API server to delete one session namespace by exact name; do not wait."""
    require_session_name(namespace)
    log(f"Deleting session namespace {namespace}")
    try:
        result = kubectl("delete", "namespace", namespace, "--ignore-not-found", "--wait=false")
    except LifecycleError as error:
        report(error)
        result = None
    if result is None or result.returncode != 0:
        status = "no answer" if result is None else f"kubectl exit {result.returncode}"
        warn(f"ERROR: deleting namespace {namespace} failed ({status}).")
        warn(f"       Retry: {MODULE} stop {namespace}")
        return False
    return True


def await_deletion(root: Path, namespace: str) -> int:
    """Wait, bounded, until a session namespace whose deletion was requested is gone."""
    started = time.monotonic()
    while namespace_exists(namespace):
        if time.monotonic() - started >= DELETE_TIMEOUT_SECONDS:
            warn(f"ERROR: namespace {namespace} is still terminating after {DELETE_TIMEOUT_SECONDS:.0f} s;")
            warn("       cleanup is incomplete.")
            warn(f"       Retry: {MODULE} stop {namespace}")
            return 1
        time.sleep(POLL_SECONDS)
    forget_session_record(root, namespace)
    log(f"Session namespace {namespace} is gone ({time.monotonic() - started:.0f} s)")
    return 0


def delete_session(root: Path, namespace: str) -> int:
    """Delete one session namespace by exact name, stop its port-forwards, wait until it is gone."""
    requested = request_deletion(namespace)
    stop_session_forwards(namespace)
    if not requested:
        return 1
    return await_deletion(root, namespace)


def keep_data() -> bool:
    return os.environ.get("INTEGRATION_KEEP_DATA", "") == "1"


def _outage_after(root: Path) -> InfrastructureUnavailableError | None:
    """Recheck availability after a failed setup: an outage turns it into deferral."""
    try:
        check_infrastructure(root)
    except InfrastructureUnavailableError as error:
        return error
    except LifecycleError as error:
        # Preserve the original setup failure while exposing a second
        # permanent preflight error, without treating it as an outage.
        report(error)
    return None


def _teardown_after(session: Session, *, delete: bool) -> None:
    """Delete or keep a session whose setup failed, without masking that failure."""
    try:
        if delete:
            session.stop()
        else:
            finish(session)
    except LifecycleError as error:
        report(error)
        warn(f"       Retry: {MODULE} stop {session.namespace}")


def prepare(root: Path, *, notify: Callable[[str], None]) -> Session:
    """Check or wait for the cluster, then create, deploy and seed a new session.

    Teardown is armed from the first created object: a failed or interrupted
    setup deletes the namespace unless ``INTEGRATION_KEEP_DATA=1``, and a
    session that is not ready in time is always deleted.
    """
    task_driven = os.environ.get("CVETA2_TASK_VERIFICATION") == "1"
    if task_driven:
        try:
            check_infrastructure(root)
        except InfrastructureUnavailableError as error:
            raise InfrastructureUnavailableError(f"UNAVAILABLE: live setup blocked: {error}") from error
    else:
        wait_for_cluster(lambda: probe(root), notify=notify, timeout=wait_timeout())
    session = Session(root, new_session_name())
    try:
        session.up()
    except BaseException as setup_error:
        unavailable: InfrastructureUnavailableError | None = None
        if task_driven and not isinstance(setup_error, SetupBlockedError) and isinstance(setup_error, LifecycleError):
            unavailable = _outage_after(root)
        _teardown_after(session, delete=isinstance(setup_error, SetupBlockedError) or not keep_data())
        if isinstance(setup_error, SetupBlockedError):
            first, *rest = setup_error.lines
            raise SetupBlockedError(f"UNAVAILABLE: live setup blocked: {first}", *rest) from setup_error
        if unavailable is not None:
            raise InfrastructureUnavailableError(
                f"UNAVAILABLE: live setup blocked: {unavailable}; original setup failure: {setup_error}"
            ) from setup_error
        raise
    return session


def keep(session: Session) -> None:
    """Record a kept session and release this process's port-forwards."""
    ports = session.ports()
    session.stop_forwards()
    write_session_record(session.root, session.namespace, ports)
    log(f"Keeping session {session.namespace} for inspection; its credentials stay in its Secrets.")
    log(f'    variables and port-forwards: eval "$({MODULE} env)"')
    log(f"    remove it:                   {MODULE} stop {session.namespace}")


def finish(session: Session) -> int:
    """Keep the session when asked to; otherwise delete its namespace."""
    if keep_data():
        keep(session)
        return 0
    return session.stop()


# -- command line ----------------------------------------------------------


def _terminate(signum: int, _frame: FrameType | None) -> NoReturn:
    """Turn SIGTERM into an exit so an interrupted child is waited for."""
    raise SystemExit(128 + signum)


@contextmanager
def sigterm_as_exit() -> Iterator[None]:
    """Run teardown on SIGTERM too: raise SystemExit instead of dying at once.

    Only the main thread may install a handler; elsewhere nothing changes.
    """
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    previous = signal.signal(signal.SIGTERM, _terminate)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


def _recorded_or_given(root: Path, given: str | None) -> tuple[str, dict[str, int]]:
    if given:
        namespace = require_session_name(given)
        # A damaged record must not block acting on a namespace named explicitly.
        record = None
        with suppress(LifecycleError):
            record = read_session_record(root)
        return namespace, record[1] if record and record[0] == namespace else {}
    record = read_session_record(root)
    if record is None:
        fail(f"no kept session in this checkout; start one with {MODULE} up or name the namespace.")
    return record


def command_up(root: Path) -> int:
    record = read_session_record(root)
    if record is not None:
        if namespace_exists(record[0]):
            fail(
                f"session {record[0]} is kept in this checkout ({session_file(root)});",
                f"stop it first: {MODULE} stop {record[0]}",
            )
        warn(f"Kept session {record[0]} no longer exists; forgetting it.")
        session_file(root).unlink(missing_ok=True)
    session = prepare(root, notify=warn)
    keep(session)
    return 0


def command_env(root: Path, given: str | None) -> int:
    if sys.stdout.isatty():
        fail(
            "env prints the session's credentials; evaluate it instead of reading it:",
            f'eval "$({MODULE} env)"',
        )
    namespace, ports = _recorded_or_given(root, given)
    if not namespace_exists(namespace):
        fail(f"session namespace {namespace} no longer exists; start a new session with {MODULE} up.")
    stop_session_forwards(namespace)
    session = Session(root, namespace)
    session.start_forwards(ports)
    session.export_environment()
    record = read_session_record(root)
    if record is not None and record[0] == namespace:
        write_session_record(root, namespace, session.ports())
    for key, value in session.exported.items():
        sys.stdout.write(f"export {key}={shlex.quote(value)}\n")
    # The forwards outlive this process on purpose: the shell uses them until stop.
    return 0


def command_stop(root: Path, given: str | None) -> int:
    if not given and read_session_record(root) is None:
        log("No kept session in this checkout; nothing to stop")
        return 0
    namespace, _ = _recorded_or_given(root, given)
    if not namespace_exists(namespace):
        stop_session_forwards(namespace)
        forget_session_record(root, namespace)
        log(f"Session namespace {namespace} is already gone")
        return 0
    return delete_session(root, namespace)


def _dispatch(args: argparse.Namespace, root: Path) -> int:
    if args.command == "check":
        check_infrastructure(root)
        log("AVAILABLE: infrastructure preflight passed; no resources created")
        return 0
    if args.command == "up":
        return command_up(root)
    if args.command == "env":
        return command_env(root, args.namespace)
    return command_stop(root, args.namespace)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=MODULE, description="Live-test sessions in their own namespaces.")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help=argparse.SUPPRESS,
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check", help="read-only bounded availability check (0 available, 3 unavailable, 1 error)")
    commands.add_parser("up", help="start, seed and keep a session")
    for name, text in (
        ("env", "start port-forwards and print a kept session's variables as shell exports"),
        ("stop", "delete exactly one session namespace and stop its port-forwards"),
    ):
        sub = commands.add_parser(name, help=text)
        sub.add_argument("namespace", nargs="?", help="session namespace (default: the one kept in this checkout)")
    args = parser.parse_args(argv)

    if isinstance(sys.stdout, io.TextIOWrapper):
        # Our lines must interleave with the children's in captured output.
        sys.stdout.reconfigure(line_buffering=True)
    root: Path = args.repo_root.resolve()
    try:
        with sigterm_as_exit():
            return _dispatch(args, root)
    except InfrastructureUnavailableError as error:
        first, *rest = error.lines
        first = first.removeprefix("UNAVAILABLE: ")
        warn(f"UNAVAILABLE: {first}; live verification is deferred")
        for line in rest:
            warn(f"       {line}")
        return UNAVAILABLE_EXIT
    except LifecycleError as error:
        report(error)
        return 1
    except OSError as error:
        warn(f"ERROR: lifecycle operation could not access a required tool or file ({type(error).__name__})")
        return 1
    except KeyboardInterrupt:
        warn("interrupted")
        return 130


if __name__ == "__main__":
    sys.exit(main())
