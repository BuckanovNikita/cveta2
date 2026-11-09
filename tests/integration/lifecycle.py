"""Integration-run lifecycle on the shared docker-desktop stands.

The live tests in ``tests/integration`` are part of the normal pytest run: the
session fixture in ``tests/integration/conftest.py`` calls ``prepare`` before the
first live test and ``finish`` after the last one. The same steps by hand:

    uv run python -m tests.integration.lifecycle up      # wait, claim a tag, seed
    uv run python -m tests.integration.lifecycle stop    # remove it, release the tag
    eval "$(uv run python -m tests.integration.lifecycle env)"  # this run's variables

The run acts as project ``cveta2`` of the shared stands (k8s-infra skill,
``references/run-contract.md``): the tag is minted by the skill, the credentials
come from the project's Secrets, and every object a run creates is named by the
tag. Nothing runs on this host, so there are no ports and no Compose stack.

The run tag, in order of precedence:

1. ``INFRA_RUN_TAG`` when exported (the contract's own variable; also how a
   shell adopts an active run);
2. on the ``main`` branch the durable slot ``cveta2-main``, which the next main
   run replaces;
3. ``tests/integration/.run-tag``, the gitignored file ``up`` writes when it
   mints a tag and ``stop`` deletes;
4. nothing: ``up`` mints one; ``stop`` refuses.

Exported for the run (and printed by ``env``): ``INTEGRATION_RUN_TAG``;
``CVAT_INTEGRATION_HOST/USER/PASSWORD/ORG`` from Secret
``cvat/cvat-cveta2-access``; ``CVAT_INTEGRATION_PROJECT`` = ``"<tag> coco8-dev"``;
``MINIO_ENDPOINT`` (as the host sees it), ``MINIO_ENDPOINT_FOR_CVAT`` (as the CVAT
pods see it), ``MINIO_ACCESS_KEY/SECRET_KEY/REGION/CONSOLE`` and ``MINIO_BUCKET``
= ``<tag>``; the ``CLEARML_*`` identity as the helper exports it; and the CA
trust variables (``SSL_CERT_FILE`` and friends) the helpers add. A failed
handshake is reported as a TLS problem, never as a stand that is down.

``check`` performs a read-only preflight within ``CVETA2_INFRA_CHECK_TIMEOUT``
(60 seconds by default). Task-driven ``prepare`` repeats this bounded check;
an outage blocks setup without minting a tag. Direct operator ``up`` retains
the explicit stand-wait workflow, bounded by ``CVETA2_STAND_WAIT_TIMEOUT`` when
set. Missing prerequisites, credentials, TLS trust and refused identities are
errors rather than temporary outages.

The module stays standard-library only. Inside pytest, ``tests.env_isolation``
replaces HOME; it records the real environment in ``CVETA2_REAL_ENV`` and this
module restores it for the skill lookup and for every child (kubectl, uv and
the k8s-infra helpers need the real HOME and caches).
"""

import argparse
import io
import json
import math
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import tomllib
import urllib.request
import zipfile
from collections.abc import Callable, Sequence
from contextlib import suppress
from http import HTTPStatus
from pathlib import Path
from types import FrameType
from typing import NoReturn

PROJECT = "cveta2"
MAIN_TAG = "cveta2-main"
TAG_SLUG = "integration"
TAG_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
MODULE = "uv run python -m tests.integration.lifecycle"
COCO8_URL = "https://github.com/ultralytics/assets/releases/download/v0.0.0/coco8.zip"
# curl exit statuses that mean the TLS handshake or certificate check failed:
# the stand answered, this machine does not trust it.
TLS_CURL_STATUSES = frozenset({35, 51, 53, 54, 58, 59, 60, 64, 66, 77, 80, 82, 83, 90, 91})
TLS_REMEDY = (
    "This is a certificate-trust problem, not a stand that is down: the stands serve",
    "https://<name>.k8s.docker.internal with a certificate from the k8s-infra CA.",
    "Check that /usr/local/share/ca-certificates/k8s-infra-local-ca.crt is installed",
    "(update-ca-certificates) and that the k8s-infra helpers export SSL_CERT_FILE.",
)
REQUIRED_KEYS = {
    "cvat": ("CVAT_URL", "CVAT_USERNAME", "CVAT_PASSWORD", "CVAT_ORG"),
    "minio": (
        "S3_ENDPOINT",
        "S3_ENDPOINT_IN_CLUSTER",
        "S3_ACCESS_KEY",
        "S3_SECRET_KEY",
        "S3_REGION",
    ),
    "clearml": ("CLEARML_API_HOST", "CLEARML_API_ACCESS_KEY", "CLEARML_API_SECRET_KEY"),
}


class LifecycleError(Exception):
    """A refusal or failure, reported as ``ERROR:`` plus indented detail lines."""

    def __init__(self, *lines: str) -> None:
        """Keep every line; the first is the headline."""
        super().__init__(lines[0])
        self.lines = lines


class StandUnavailableError(LifecycleError):
    """Temporary infrastructure unavailability; live verification is deferred."""


def _probe_call(command: Sequence[str], deadline: float) -> subprocess.CompletedProcess[str]:
    """Bound a read-only probe and kill only its owned process group on timeout."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise StandUnavailableError("infrastructure preflight deadline expired")
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
                    raise StandUnavailableError(
                        f"infrastructure preflight timed out during {Path(command[0]).name}"
                    ) from error
                raise
    except FileNotFoundError:
        fail(f"{command[0]} is not installed or not on PATH; the live tests need it.")
    return subprocess.CompletedProcess(list(command), child.returncode, stdout, stderr)


def _probe_failure(result: subprocess.CompletedProcess[str], description: str) -> NoReturn:
    """Classify helper transport errors without exposing captured credentials."""
    detail = (result.stderr or "").lower()
    permanent = ("unauthorized", "forbidden", "certificate", "tls", "credential", "not found", "401", "403")
    temporary = (
        "connection refused",
        "connection reset",
        "remote end closed",
        "timed out",
        "timeout",
        "no such host",
        "name or service not known",
        "unreachable",
        "503",
        "502",
        "504",
    )
    if not any(term in detail for term in permanent) and any(term in detail for term in temporary):
        raise StandUnavailableError(f"{description}: service connectivity was lost")
    fail(f"{description} failed (exit {result.returncode}); check prerequisites, credentials, TLS and service access.")


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


def call(command: Sequence[str], *, cwd: Path | None = None, capture: bool = False) -> subprocess.CompletedProcess[str]:
    """Run a child and, if this process is interrupted, let the child finish first.

    ``subprocess.run`` kills its child on any exception, so Ctrl-C or SIGTERM
    would orphan pytest's own session cleanup and race the gate's teardown.
    Like a shell's foreground job, the child is waited for: Ctrl-C already
    reached it through the terminal's process group, SIGTERM is forwarded.
    A second Ctrl-C while waiting kills it.
    """
    with subprocess.Popen(  # noqa: S603 - fixed tool commands
        list(command),
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        env=child_env(),
    ) as child:
        try:
            stdout, _ = child.communicate()
        except BaseException as interrupt:
            if isinstance(interrupt, SystemExit) and child.poll() is None:
                child.send_signal(signal.SIGTERM)
            try:
                child.wait()
            except KeyboardInterrupt:
                child.kill()
                child.wait()
            raise
    return subprocess.CompletedProcess(list(command), child.returncode, stdout)


def valid_tag(tag: str) -> bool:
    return bool(TAG_PATTERN.match(tag))


def parse_exports(text: str, source: str) -> dict[str, str]:
    """Parse ``export KEY=<shell-quoted value>`` lines, as the helpers print them."""
    values: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        try:
            words = shlex.split(line)
        except ValueError:
            words = []
        key, _, value = words[-1].partition("=") if words else ("", "", "")
        if len(words) != 2 or words[0] != "export" or not NAME_PATTERN.match(key):
            fail(f"{source} printed an unexpected line: {line!r}")
        values[key] = value
    return values


def find_skill_dir() -> Path | None:
    """Return the installed k8s-infra skill; its presence arms the machine.

    An explicit ``K8S_INFRA_SKILL_DIR`` that does not hold the skill is an
    error rather than "not armed": somebody meant to arm this machine.
    """
    explicit = os.environ.get("K8S_INFRA_SKILL_DIR", "")
    if explicit:
        if not (Path(explicit) / "scripts" / "infra.py").is_file():
            fail(
                f"K8S_INFRA_SKILL_DIR={explicit} has no scripts/infra.py;",
                "point it at k8s-infra/skills/k8s-infra of a checkout that carries the run contract.",
            )
        return Path(explicit)
    home = Path(child_env().get("HOME", "~")).expanduser()
    for candidate in (
        home / ".agents" / "skills" / "k8s-infra",
        home / ".claude" / "skills" / "k8s-infra",
    ):
        if (candidate / "scripts" / "infra.py").is_file():
            return candidate
    return None


class Run:
    """One integration run: its tag, its credentials and the steps on it."""

    def __init__(self, root: Path, *, deadline: float | None = None) -> None:
        """Resolve everything a run owns, as sourcing the old env script did."""
        self.root = root
        self.deadline = deadline
        self.tag_file = root / "tests" / "integration" / ".run-tag"
        self.exported: dict[str, str] = {}
        skill_dir = find_skill_dir()
        if skill_dir is None:
            fail(
                "the k8s-infra skill was not found under ~/.agents/skills or ~/.claude/skills,",
                "or the installed one predates the run contract (no scripts/infra.py).",
                "Install or update it, or export K8S_INFRA_SKILL_DIR=<k8s-infra>/skills/k8s-infra.",
            )
        self.skill_dir = skill_dir
        self.tag = ""
        self._resolve_run_tag()

        cvat = self._stand_env("cvat")
        self._export(
            CVAT_INTEGRATION_HOST=cvat["CVAT_URL"].rstrip("/"),
            CVAT_INTEGRATION_USER=cvat["CVAT_USERNAME"],
            CVAT_INTEGRATION_PASSWORD=cvat["CVAT_PASSWORD"],
            CVAT_INTEGRATION_ORG=cvat["CVAT_ORG"],
        )
        minio = self._stand_env("minio")
        self._export(
            MINIO_ENDPOINT=minio["S3_ENDPOINT"].rstrip("/"),
            MINIO_ENDPOINT_FOR_CVAT=minio["S3_ENDPOINT_IN_CLUSTER"].rstrip("/"),
            MINIO_ACCESS_KEY=minio["S3_ACCESS_KEY"],
            MINIO_SECRET_KEY=minio["S3_SECRET_KEY"],
            MINIO_REGION=minio["S3_REGION"],
            MINIO_CONSOLE=minio.get("S3_CONSOLE", ""),
        )
        self._stand_env("clearml")
        self._export(INTEGRATION_SKILL_DIR=str(self.skill_dir), INTEGRATION_PROJECT=PROJECT)

    # -- environment ------------------------------------------------------

    def _export(self, **values: str) -> None:
        os.environ.update(values)
        self.exported.update(values)

    def helper(self, stand: str, *args: str, capture: bool = False) -> subprocess.CompletedProcess[str]:
        """Run a k8s-infra helper as project cveta2."""
        script = self.skill_dir / "scripts" / f"{stand}.py"
        command = [sys.executable, str(script), "--project", PROJECT, *args]
        if self.deadline is not None:
            return _probe_call(command, self.deadline)
        return call(command, capture=capture)

    def _stand_env(self, stand: str) -> dict[str, str]:
        completed = self.helper(stand, "env", capture=True)
        if completed.returncode != 0:
            if self.deadline is not None:
                _probe_failure(completed, f"{stand} credential lookup")
            fail(
                f"{stand}.py --project {PROJECT} env failed (see above);",
                f"the cveta2 {stand} Secret is missing or the cluster is not reachable.",
            )
        values = parse_exports(completed.stdout, f"{stand}.py env")
        for key in REQUIRED_KEYS[stand]:
            if not values.get(key):
                fail(
                    f"the cveta2 {stand} Secret carries no {key};",
                    f"re-run the {stand} stand deploy from the k8s-infra repository.",
                )
        self._export(**values)
        return values

    # -- run tag ----------------------------------------------------------

    def on_main(self) -> bool:
        command = ["git", "-C", str(self.root), "symbolic-ref", "--quiet", "--short", "HEAD"]
        if self.deadline is not None:
            branch = _probe_call(command, self.deadline)
        else:
            branch = subprocess.run(command, check=False, capture_output=True, text=True)  # noqa: S603
        return branch.stdout.strip() == "main"

    def _read_tag_file(self) -> str:
        lines = self.tag_file.read_text(encoding="utf-8").splitlines()
        tag = lines[0] if lines else ""
        if not valid_tag(tag):
            fail(
                f"{self.tag_file} does not hold a run tag;",
                "remove it if the run it named is gone.",
            )
        return tag

    def _set_tag(self, tag: str) -> None:
        self.tag = tag
        self._export(
            INTEGRATION_RUN_TAG=tag,
            CVAT_INTEGRATION_PROJECT=f"{tag} coco8-dev" if tag else "",
            MINIO_BUCKET=tag,
        )

    def _resolve_run_tag(self) -> None:
        tag = ""
        if os.environ.get("INFRA_RUN_TAG"):
            tag = os.environ["INFRA_RUN_TAG"]
        elif self.on_main():
            tag = MAIN_TAG
        elif self.tag_file.is_file():
            tag = self._read_tag_file()
        if tag and not valid_tag(tag):
            fail(f"run tag '{tag}' is not lowercase [a-z0-9-]; mint it with infra.py newtag.")
        preset = os.environ.get("INTEGRATION_RUN_TAG", "")
        if preset and tag and preset != tag:
            fail(
                f"INTEGRATION_RUN_TAG={preset} is set in the shell but the tag is derived now;",
                "unset it and export INFRA_RUN_TAG=<tag> to run under an explicit tag.",
            )
        self._set_tag(tag)

    def require_tag(self) -> None:
        if not self.tag:
            fail(
                f"no run is active: run {MODULE} up first,",
                "or export INFRA_RUN_TAG=<tag> to act on a run started elsewhere.",
            )

    def would_mint(self) -> bool:
        """Whether ``up`` must mint: an exported tag and the main slot need none."""
        return not os.environ.get("INFRA_RUN_TAG") and not self.on_main()

    def refuse_active_run(self) -> None:
        """Refuse to mint while a tag file names another active run."""
        if self.would_mint() and self.tag_file.is_file():
            try:
                active = self._read_tag_file()
            except LifecycleError:
                active = "?"
            fail(
                "a run is active; stop it or export INFRA_RUN_TAG to adopt it",
                f"    ({self.tag_file} names '{active}').",
            )

    def claim_run_tag(self) -> None:
        """Mint when needed; assign, then record, so a refusal leaves nothing."""
        if not self.would_mint():
            return
        self.refuse_active_run()
        minted = call(
            [
                "python3",
                str(self.skill_dir / "scripts" / "infra.py"),
                "newtag",
                "--project",
                PROJECT,
                "--slug",
                TAG_SLUG,
            ],
            capture=True,
        )
        tag = minted.stdout.strip()
        if minted.returncode != 0 or not valid_tag(tag):
            fail(f"infra.py newtag --project {PROJECT} --slug {TAG_SLUG} did not mint a tag (see above).")
        self.tag_file.write_text(f"{tag}\n", encoding="utf-8")
        self._set_tag(tag)

    def release_run_tag(self) -> None:
        """Forget the tag, but only the file that names this run."""
        if not self.tag_file.is_file():
            return
        try:
            recorded = self._read_tag_file()
        except LifecycleError:
            recorded = ""
        if recorded in {self.tag, ""}:
            self.tag_file.unlink(missing_ok=True)

    # -- steps ------------------------------------------------------------

    def uv_python(self, *args: str) -> int:
        return call(["uv", "run", "python", *args], cwd=self.root).returncode

    def _require(self, status: int, command: str) -> None:
        if status != 0:
            fail(f"{command} failed with exit status {status} (see above).")

    def up(self) -> None:
        """Claim the tag, verify the identity, clear the tag's leftovers, seed."""
        self.claim_run_tag()
        host = os.environ["CVAT_INTEGRATION_HOST"]
        user = os.environ["CVAT_INTEGRATION_USER"]
        org = os.environ["CVAT_INTEGRATION_ORG"]
        log(f"Run tag '{self.tag}': verifying user {user} on the CVAT stand at {host}")
        self._require(
            self.uv_python("tests/integration/cvat_stand.py", "verify"),
            "cvat_stand.py verify",
        )
        # A freshly minted tag owns nothing yet; an adopted tag and the main
        # slot do. The cloud storage points at the bucket, so CVAT goes first.
        log(f"Removing the previous '{self.tag}' run from organization {org}")
        self._require(
            self.uv_python("tests/integration/cvat_stand.py", "cleanup", "--tag", self.tag),
            "cvat_stand.py cleanup",
        )
        log(
            f"Removing bucket '{self.tag}' of the previous '{self.tag}' run from "
            f"MinIO at {os.environ['MINIO_ENDPOINT']}"
        )
        self._require(
            self.helper("minio", "cleanup", "--prefix", self.tag).returncode,
            "minio.py cleanup",
        )
        self._ensure_coco8_images()
        log(f"Seeding bucket '{self.tag}' and project '{os.environ['CVAT_INTEGRATION_PROJECT']}'")
        self._require(self.uv_python("tests/integration/seed_cvat.py"), "seed_cvat.py")
        log("Done.")
        log(f"CVAT:          {host}  (organization {org}, project '{os.environ['CVAT_INTEGRATION_PROJECT']}')")
        log(
            f"MinIO bucket:  {self.tag} at {os.environ['MINIO_ENDPOINT']}  "
            f"(for CVAT: {os.environ['MINIO_ENDPOINT_FOR_CVAT']})"
        )
        log(f"MinIO console: {os.environ.get('MINIO_CONSOLE') or 'not published by the Secret'}")
        log(f"ClearML:       {os.environ['CLEARML_API_HOST']}  (the shared stand)")
        log("Run live tests:         uv run pytest tests/integration")
        log(f"Tear down:              {MODULE} stop")

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
                shutil.copytree(
                    Path(scratch) / "coco8" / "images" / split,
                    images / split,
                    dirs_exist_ok=True,
                )
        log(f"coco8 images extracted to {images}")

    def stop(self) -> int:
        """Remove this tag's objects: CVAT, then the bucket, then ClearML."""
        self.require_tag()
        tag, failed = self.tag, False
        log(
            f"Removing '{tag}' data from CVAT organization "
            f"{os.environ['CVAT_INTEGRATION_ORG']} (project "
            f"'{os.environ['CVAT_INTEGRATION_PROJECT']}')"
        )
        if self.uv_python("tests/integration/cvat_stand.py", "cleanup", "--tag", tag):
            warn(f"WARNING: the CVAT data of tag '{tag}' could not be removed.")
            warn("         Retry once the stand is reachable:")
            warn(f"         uv run python tests/integration/cvat_stand.py cleanup --tag '{tag}'")
            failed = True
        log(f"Removing bucket '{tag}' of '{tag}' from MinIO at {os.environ['MINIO_ENDPOINT']}")
        if self.helper("minio", "cleanup", "--prefix", tag).returncode:
            warn(f"WARNING: bucket '{tag}' could not be removed.")
            warn("         Retry once the stand is reachable:")
            warn(f"         python3 \"{self.skill_dir}/scripts/minio.py\" --project {PROJECT} cleanup --prefix '{tag}'")
            failed = True
        log(f"Removing '{tag}' projects from ClearML at {os.environ['CLEARML_API_HOST']}")
        if self.helper("clearml", "cleanup", "--prefix", tag).returncode:
            warn(f"WARNING: the ClearML projects of tag '{tag}' could not be removed.")
            warn("         Retry once the stand is reachable:")
            warn(
                f"         python3 \"{self.skill_dir}/scripts/clearml.py\" --project {PROJECT} cleanup --prefix '{tag}'"
            )
            failed = True
        for stand in REQUIRED_KEYS:
            listing = self.helper(stand, "ls", "--prefix", tag, capture=True)
            rows = [
                line
                for line in listing.stdout.splitlines()
                if line.split() and line.split()[0] in {"project", "task", "storage", "bucket"}
            ]
            if listing.returncode or rows:
                warn(f"WARNING: {stand} exact-tag cleanup proof failed for '{tag}': {len(rows)} object row(s).")
                failed = True
            else:
                log(f"{stand}: no objects remain for exact tag '{tag}'")
        if failed:
            warn(f"ERROR: run '{tag}' is not fully torn down; the .run-tag file stays for the retry.")
            return 1
        self.release_run_tag()
        log("Done")
        return 0


# -- stand availability ----------------------------------------------------

ROOM_WAIT = 3
FIRST_DELAY_SECONDS = 15.0
MAX_DELAY_SECONDS = 60.0
HEARTBEAT_SECONDS = 300.0
PROBE_TIMEOUT_SECONDS = 20
WAIT_TIMEOUT_VARIABLE = "CVETA2_STAND_WAIT_TIMEOUT"
CHECK_TIMEOUT_VARIABLE = "CVETA2_INFRA_CHECK_TIMEOUT"
DEFAULT_CHECK_TIMEOUT_SECONDS = 60.0


# curl exit statuses of an endpoint that is not there right now: host not
# resolved, connection refused, timeout, empty reply, connection reset.
DOWN_CURL_STATUSES = frozenset({6, 7, 28, 52, 56, -1})
HTTP_SERVER_ERROR = 500


def _quiet(command: Sequence[str], deadline: float | None = None) -> tuple[int, str]:
    """Exit status and stdout of a probe command; its stderr is noise."""
    try:
        if deadline is not None:
            result = _probe_call(command, deadline)
            return result.returncode, result.stdout
        completed = subprocess.run(  # noqa: S603 - fixed tool commands and stand URLs
            list(command),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            env=child_env(),
            timeout=PROBE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return -1, ""
    except FileNotFoundError:
        fail(f"{command[0]} is not installed or not on PATH; the live tests need it.")
    return completed.returncode, completed.stdout


def _curl(name: str, url: str, deadline: float | None = None) -> str | None:
    """None when the endpoint answers; a reason when it is down; else fail.

    Down means no connection or an HTTP 5xx (an ingress whose backend is scaled
    to zero answers 503). A TLS failure or another HTTP error (404, 401) is a
    problem waiting cannot fix.
    """
    status, out = _quiet(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", "10", url], deadline)
    if status in TLS_CURL_STATUSES:
        fail(
            f"TLS verification of the {name} stand at {url} failed (curl exit {status}).",
            *TLS_REMEDY,
        )
    if status in DOWN_CURL_STATUSES:
        return f"the {name} stand at {url} does not answer (curl exit {status})"
    if status != 0:
        fail(f"curl could not check the {name} stand at {url} (exit {status}).")
    try:
        code = int(out.strip() or "0")
    except ValueError:
        fail(f"curl returned an invalid HTTP status for the {name} stand")
    if code >= HTTP_SERVER_ERROR or code == HTTPStatus.TOO_MANY_REQUESTS:
        return f"the {name} stand at {url} answers HTTP {code}"
    if code >= HTTPStatus.BAD_REQUEST or code == 0:
        fail(
            f"the {name} stand at {url} answers HTTP {code}; that is not a stopped "
            "stand. Diagnose it with the k8s-infra skill."
        )
    return None


def _cluster_available(deadline: float) -> str | None:
    """Separate Kubernetes access errors from temporary connectivity failures."""
    try:
        result = _probe_call(["kubectl", "--context", "docker-desktop", "get", "--raw=/readyz"], deadline)
    except StandUnavailableError as error:
        return str(error)
    if result.returncode == 0:
        return None
    detail = result.stderr.lower()
    if any(term in detail for term in ("unauthorized", "forbidden", "certificate", "tls", "context", "credentials")):
        fail("Kubernetes access, context, credentials or TLS configuration failed; check kubectl access.")
    if any(
        term in detail
        for term in (
            "connection refused",
            "connection reset",
            "timed out",
            "timeout",
            "no such host",
            "unreachable",
            "eof",
            "serviceunavailable",
            "unable to handle the request",
        )
    ):
        return "the docker-desktop cluster does not answer"
    fail(f"Kubernetes readiness probe failed unexpectedly (exit {result.returncode}); check kubectl access.")


def _run_capacity(run: Run) -> str | None:
    """Apply the installed registry's limit without claiming or creating a run."""
    override = os.environ.get("INFRA_REGISTRY")
    candidates = (
        [Path(override)] if override else [run.skill_dir / "projects.toml", run.skill_dir / "scripts" / "projects.toml"]
    )
    try:
        registry = next(path for path in candidates if path.is_file())
        values = tomllib.loads(registry.read_text(encoding="utf-8"))
        limit = values["capacity"]["cveta2_integration_runs"]
        pattern = re.compile(values["contract"]["tag_regex"])
    except (StopIteration, OSError, KeyError, TypeError, tomllib.TOMLDecodeError, re.PatternError) as error:
        fail(f"cannot read integration capacity from the k8s-infra registry: {error}")
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        fail("registry capacity.cveta2_integration_runs must be a positive integer")
    if "project" not in pattern.groupindex:
        fail("registry contract.tag_regex must identify the owning project")
    listing = run.helper("cvat", "ls", capture=True)
    if listing.returncode:
        _probe_failure(listing, "CVAT run-capacity listing")
    tags: set[str] = set()
    for line in listing.stdout.splitlines():
        fields = line.split(maxsplit=4)
        if not fields or fields[0] not in {"project", "task", "storage"}:
            continue
        if len(fields) != 5:
            fail("CVAT run-capacity listing has an unexpected row format")
        tag = fields[4].split()[0]
        match = pattern.fullmatch(tag)
        if tag == MAIN_TAG or (match is not None and match.groupdict().get("project") == PROJECT):
            tags.add(tag)
    # An explicitly adopted run already occupies its slot.
    tags.discard(run.tag)
    if len(tags) >= limit:
        return f"capacity.cveta2_integration_runs is full ({len(tags)}/{limit})"
    return None


def probe(root: Path, *, deadline: float | None = None) -> "Run | str":
    """Return a ready run, or the reason the stands are down.

    "Down" is what the owner causes by stopping the stands (cluster or stand
    unreachable or answering 5xx, capacity WAIT) and is waited for. Everything
    else - a missing tool, skill or Secret, an untrusted certificate, a failing
    room check, another HTTP error, a refused identity - is raised as a
    LifecycleError, because waiting would not fix it.
    """
    skill_dir = find_skill_dir()
    if skill_dir is not None:
        reason = _cluster_available(deadline or (time.monotonic() + PROBE_TIMEOUT_SECONDS))
        if reason is not None:
            return reason
    run = Run(root, deadline=deadline)
    room, _ = _quiet([sys.executable, str(run.skill_dir / "scripts" / "infra.py"), "room"], deadline)
    if room == ROOM_WAIT:
        return "infra.py room answers WAIT: the stands are at capacity"
    if room != 0:
        fail(f"infra.py room failed (exit {room}); run it by hand to see why.")
    for name, url in (
        ("CVAT", f"{os.environ['CVAT_INTEGRATION_HOST']}/api/server/about"),
        ("MinIO", f"{os.environ['MINIO_ENDPOINT']}/minio/health/live"),
        ("ClearML", f"{os.environ['CLEARML_API_HOST']}/debug.ping"),
    ):
        reason = _curl(name, url, deadline)
        if reason is not None:
            return reason
    for stand in REQUIRED_KEYS:
        identity = run.helper(stand, "whoami", capture=True)
        if identity.returncode:
            _probe_failure(identity, f"{stand} identity probe")
    reason = _run_capacity(run)
    if reason is not None:
        return reason
    run.deadline = None
    return run


def check_timeout() -> float:
    raw = os.environ.get(CHECK_TIMEOUT_VARIABLE, str(DEFAULT_CHECK_TIMEOUT_SECONDS))
    try:
        timeout = float(raw)
    except ValueError:
        fail(f"{CHECK_TIMEOUT_VARIABLE} must be a positive finite number of seconds")
    if not math.isfinite(timeout) or timeout <= 0:
        fail(f"{CHECK_TIMEOUT_VARIABLE} must be a positive finite number of seconds")
    return timeout


def check_stands(root: Path) -> Run:
    """One read-only preflight, with one overall deadline and no polling."""
    result = probe(root, deadline=time.monotonic() + check_timeout())
    if isinstance(result, str):
        raise StandUnavailableError(result)
    return result


def _minutes(seconds: float) -> str:
    return f"{int(seconds // 60)} мин {int(seconds % 60)} с"


def wait_for_stands(
    check: Callable[[], "Run | str"],
    *,
    notify: Callable[[str], None],
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
    timeout: float | None = None,
) -> "Run":
    """Poll until the stands are ready; say once that we wait, then heartbeat.

    The wait is unbounded unless a timeout is given; Ctrl-C ends it, and
    nothing has been minted or created at that point.
    """
    started = now()
    delay = FIRST_DELAY_SECONDS
    last_notice: float | None = None
    while True:
        result = check()
        if not isinstance(result, str):
            if last_notice is not None:
                notify(f"Стенды снова доступны (ожидание {_minutes(now() - started)}); продолжаю.")
            return result
        elapsed = now() - started
        if timeout is not None and elapsed >= timeout:
            fail(f"Стенды не восстановились за {int(timeout)} с ({WAIT_TIMEOUT_VARIABLE}): {result}.")
        if last_notice is None:
            notify(
                f"Стенды недоступны: {result}. Похоже, они остановлены; жду "
                "восстановления (Ctrl-C - прервать). Пока идёт коммит, не "
                "редактируйте рабочую копию."
            )
            last_notice = now()
        elif now() - last_notice >= HEARTBEAT_SECONDS:
            notify(f"Всё ещё жду стенды ({_minutes(elapsed)}): {result}.")
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


def prepare(root: Path, *, notify: Callable[[str], None]) -> "Run":
    """Wait for the stands, refuse a foreign active run, then claim and seed.

    The teardown is armed before seeding: a failed or interrupted ``up`` keeps
    or stops whatever its tag already created, exactly as ``finish`` would.
    """
    if os.environ.get("CVETA2_TASK_VERIFICATION") == "1":
        try:
            run = check_stands(root)
        except StandUnavailableError as error:
            raise StandUnavailableError(f"UNAVAILABLE: live setup blocked: {error}") from error
    else:
        run = wait_for_stands(lambda: probe(root), notify=notify, timeout=wait_timeout())
    run.refuse_active_run()
    try:
        run.up()
    except BaseException as setup_error:
        unavailable: StandUnavailableError | None = None
        if os.environ.get("CVETA2_TASK_VERIFICATION") == "1" and isinstance(setup_error, LifecycleError):
            try:
                check_stands(root)
            except StandUnavailableError as error:
                unavailable = error
            except LifecycleError as error:
                # Preserve the original setup failure while exposing a second
                # permanent preflight error, without treating it as an outage.
                report(error)
        if run.tag:
            try:
                finish(run)
            except LifecycleError as error:
                report(error)
        if unavailable is not None:
            raise StandUnavailableError(
                f"UNAVAILABLE: live setup blocked: {unavailable}; original setup failure: {setup_error}"
            ) from setup_error
        raise
    return run


def keep_data(run: "Run") -> bool:
    choice = os.environ.get("INTEGRATION_KEEP_DATA", "")
    if choice == "1":
        return True
    if choice == "0":
        return False
    return run.on_main()


def finish(run: "Run") -> int:
    """Keep the main slot or an explicitly kept run; stop everything else."""
    if not keep_data(run):
        return run.stop()
    reason = f"it is the durable slot '{run.tag}' (main)" if run.on_main() else "INTEGRATION_KEEP_DATA=1"
    log(f"keeping run '{run.tag}' for inspection: {reason}")
    log(f"    remove everything with {MODULE} stop")
    return 0


# -- command line ----------------------------------------------------------


def _terminate(signum: int, _frame: FrameType | None) -> NoReturn:
    """Turn SIGTERM into an exit so an interrupted child is waited for."""
    raise SystemExit(128 + signum)


def _print_env(run: "Run") -> None:
    if sys.stdout.isatty():
        fail(
            "env prints the run's credentials; evaluate it instead of reading it:",
            f'eval "$({MODULE} env)"',
        )
    for key, value in run.exported.items():
        sys.stdout.write(f"export {key}={shlex.quote(value)}\n")


def _dispatch(command: str, root: Path) -> int:
    if command == "check":
        check_stands(root)
        log("AVAILABLE: infrastructure preflight passed; no resources created")
        return 0
    if command == "up":
        prepare(root, notify=warn)
        return 0
    run = Run(root)
    if command == "env":
        _print_env(run)
        return 0
    return run.stop()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=MODULE, description="Integration-run lifecycle on the shared stands.")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help=argparse.SUPPRESS,
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check", help="read-only bounded availability check (0 available, 3 unavailable, 1 error)")
    commands.add_parser("env", help="print this run's variables as shell exports")
    commands.add_parser("up", help="wait for the stands, claim a tag, seed the run")
    commands.add_parser("stop", help="remove the run and release its tag")
    args = parser.parse_args(argv)

    if isinstance(sys.stdout, io.TextIOWrapper):
        # Our lines must interleave with the children's in captured output.
        sys.stdout.reconfigure(line_buffering=True)
    signal.signal(signal.SIGTERM, _terminate)
    root: Path = args.repo_root.resolve()
    try:
        return _dispatch(args.command, root)
    except StandUnavailableError as error:
        warn(f"UNAVAILABLE: {error}; live verification is deferred")
        return ROOM_WAIT
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
