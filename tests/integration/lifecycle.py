"""Integration-run lifecycle on the shared docker-desktop stands.

    uv run python -m tests.integration.lifecycle up      # claim a tag, seed the run
    uv run python -m tests.integration.lifecycle test [pytest args]
    uv run python -m tests.integration.lifecycle stop    # remove it, release the tag
    uv run python -m tests.integration.lifecycle gate [--keep-stack] [pytest args]
    eval "$(uv run python -m tests.integration.lifecycle env)"  # this run's variables

The run acts as project ``cveta2`` of the shared stands (k8s-infra skill,
``references/run-contract.md``): the tag is minted by the skill, the credentials
come from the project's Secrets, and every object a run creates is named by the
tag. Nothing runs on this host, so there are no ports and no Compose stack.

The run tag, in order of precedence:

1. ``INFRA_RUN_TAG`` when exported (the contract's own variable; also how a
   shell adopts an active run);
2. on main (or when pre-commit pushes ``refs/heads/main``) the durable slot
   ``cveta2-main``, which the next main run replaces;
3. ``tests/integration/.run-tag``, the gitignored file ``up`` writes when it
   mints a tag and ``stop`` deletes;
4. nothing: ``up`` mints one; ``test`` and ``stop`` refuse.

Exported for the run (and printed by ``env``): ``INTEGRATION_RUN_TAG``;
``CVAT_INTEGRATION_HOST/USER/PASSWORD/ORG`` from Secret
``cvat/cvat-cveta2-access``; ``CVAT_INTEGRATION_PROJECT`` = ``"<tag> coco8-dev"``;
``MINIO_ENDPOINT`` (as the host sees it), ``MINIO_ENDPOINT_FOR_CVAT`` (as the CVAT
pods see it), ``MINIO_ACCESS_KEY/SECRET_KEY/REGION/CONSOLE`` and ``MINIO_BUCKET``
= ``<tag>``; the ``CLEARML_*`` identity as the helper exports it; and the CA
trust variables (``SSL_CERT_FILE`` and friends) the helpers add, which is what
makes curl, the CVAT SDK, boto3 and the ClearML SDK trust the stands'
``https://<name>.k8s.docker.internal`` names. A failed handshake is reported as
a TLS problem, never as a stand that is down.

``tests/integration/.env`` must exist: its presence arms the machine for
integration tests and the pre-push gate. It holds optional overrides only (see
``.env.example``); a value in the file wins over the shell. A missing Secret key
is an error, never a default: a defaulted credential would silently act as
somebody else on a shared stand.

This is a standard-library CLI rather than a pytest fixture on purpose: it must
resolve the installed k8s-infra skill under the real HOME, which
``tests.env_isolation`` replaces once pytest starts, and the gate's preflight and
keep-or-stop decision belong outside the test session.
"""

import argparse
import io
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from collections.abc import Sequence
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
TLS_CURL_STATUSES = frozenset(
    {35, 51, 53, 54, 58, 59, 60, 64, 66, 77, 80, 82, 83, 90, 91}
)
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


def valid_tag(tag: str) -> bool:
    return bool(TAG_PATTERN.match(tag))


def parse_exports(text: str, source: str) -> dict[str, str]:
    """Parse ``export KEY=<shell-quoted value>`` lines, as the helpers print them."""
    values: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        words = shlex.split(line)
        key, _, value = words[-1].partition("=") if words else ("", "", "")
        if len(words) != 2 or words[0] != "export" or not NAME_PATTERN.match(key):
            fail(f"{source} printed an unexpected line: {line!r}")
        values[key] = value
    return values


def parse_env_file(path: Path) -> dict[str, str]:
    """Read ``KEY=value`` overrides (an optional ``export`` prefix, comments)."""
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        words = shlex.split(stripped)
        if words and words[0] == "export":
            words = words[1:]
        key, _, value = words[0].partition("=") if words else ("", "", "")
        if len(words) != 1 or "=" not in words[0] or not NAME_PATTERN.match(key):
            fail(f"{path} has a line that is not KEY=value: {line!r}")
        values[key] = value
    return values


class Run:
    """One integration run: its tag, its credentials and the steps on it."""

    def __init__(self, root: Path) -> None:
        """Resolve everything a run owns, as sourcing the old env script did."""
        self.root = root
        self.env_file = root / "tests" / "integration" / ".env"
        self.tag_file = root / "tests" / "integration" / ".run-tag"
        self.exported: dict[str, str] = {}
        if not self.env_file.is_file():
            fail(
                f"{self.env_file} is missing.",
                "cp tests/integration/.env.example tests/integration/.env  arms "
                "this machine.",
            )
        os.environ.update(parse_env_file(self.env_file))
        self.skill_dir = self._find_skill_dir()
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
        self._export(
            INTEGRATION_SKILL_DIR=str(self.skill_dir), INTEGRATION_PROJECT=PROJECT
        )

    # -- environment ------------------------------------------------------

    def _export(self, **values: str) -> None:
        os.environ.update(values)
        self.exported.update(values)

    def _find_skill_dir(self) -> Path:
        explicit = os.environ.get("K8S_INFRA_SKILL_DIR", "")
        if explicit:
            if not (Path(explicit) / "scripts" / "infra.py").is_file():
                fail(
                    f"K8S_INFRA_SKILL_DIR={explicit} has no scripts/infra.py;",
                    "point it at k8s-infra/skills/k8s-infra of a checkout that "
                    "carries the run contract.",
                )
            return Path(explicit)
        home = Path(os.environ.get("HOME", "~")).expanduser()
        for candidate in (
            home / ".agents" / "skills" / "k8s-infra",
            home / ".claude" / "skills" / "k8s-infra",
        ):
            if (candidate / "scripts" / "infra.py").is_file():
                return candidate
        fail(
            "the k8s-infra skill was not found under ~/.agents/skills or "
            "~/.claude/skills,",
            "or the installed one predates the run contract (no scripts/infra.py).",
            "Install or update it, or export "
            "K8S_INFRA_SKILL_DIR=<k8s-infra>/skills/k8s-infra.",
        )

    def helper(
        self, stand: str, *args: str, capture: bool = False
    ) -> subprocess.CompletedProcess[str]:
        """Run a k8s-infra helper as project cveta2."""
        script = self.skill_dir / "scripts" / f"{stand}.py"
        return subprocess.run(  # noqa: S603 - the installed skill's own helper
            ["python3", str(script), "--project", PROJECT, *args],  # noqa: S607
            check=False,
            text=True,
            stdout=subprocess.PIPE if capture else None,
        )

    def _stand_env(self, stand: str) -> dict[str, str]:
        completed = self.helper(stand, "env", capture=True)
        if completed.returncode != 0:
            fail(
                f"{stand}.py --project {PROJECT} env failed (see above);",
                f"the cveta2 {stand} Secret is missing or the cluster is not "
                "reachable.",
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
        remote_branch = os.environ.get("PRE_COMMIT_REMOTE_BRANCH", "")
        if remote_branch:
            return remote_branch == "refs/heads/main"
        branch = subprocess.run(  # noqa: S603 - fixed git arguments
            ["git", "-C", str(self.root), "symbolic-ref", "--quiet", "--short", "HEAD"],  # noqa: S607
            check=False,
            capture_output=True,
            text=True,
        )
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
            fail(
                f"run tag '{tag}' is not lowercase [a-z0-9-]; "
                "mint it with infra.py newtag."
            )
        preset = os.environ.get("INTEGRATION_RUN_TAG", "")
        if preset and tag and preset != tag:
            fail(
                f"INTEGRATION_RUN_TAG={preset} is set in the shell but the tag is "
                "derived now;",
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
        minted = subprocess.run(  # noqa: S603 - the installed skill's own helper
            [  # noqa: S607
                "python3",
                str(self.skill_dir / "scripts" / "infra.py"),
                "newtag",
                "--project",
                PROJECT,
                "--slug",
                TAG_SLUG,
            ],
            check=False,
            stdout=subprocess.PIPE,
            text=True,
        )
        tag = minted.stdout.strip()
        if minted.returncode != 0 or not valid_tag(tag):
            fail(
                f"infra.py newtag --project {PROJECT} --slug {TAG_SLUG} did not "
                "mint a tag (see above)."
            )
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
        return subprocess.run(  # noqa: S603 - repository scripts
            ["uv", "run", "python", *args],  # noqa: S607
            check=False,
            cwd=self.root,
        ).returncode

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
            self.uv_python(
                "tests/integration/cvat_stand.py", "cleanup", "--tag", self.tag
            ),
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
        log(
            f"Seeding bucket '{self.tag}' and project "
            f"'{os.environ['CVAT_INTEGRATION_PROJECT']}'"
        )
        self._require(self.uv_python("tests/integration/seed_cvat.py"), "seed_cvat.py")
        log("Done.")
        log(
            f"CVAT:          {host}  (organization {org}, project "
            f"'{os.environ['CVAT_INTEGRATION_PROJECT']}')"
        )
        log(
            f"MinIO bucket:  {self.tag} at {os.environ['MINIO_ENDPOINT']}  "
            f"(for CVAT: {os.environ['MINIO_ENDPOINT_FOR_CVAT']})"
        )
        log(
            "MinIO console: "
            f"{os.environ.get('MINIO_CONSOLE') or 'not published by the Secret'}"
        )
        log(f"ClearML:       {os.environ['CLEARML_API_HOST']}  (the shared stand)")
        log(f"Run integration tests:  {MODULE} test")
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

    def whoami_clearml(self) -> bool:
        return self.helper("clearml", "whoami").returncode == 0

    def test(self, pytest_args: Sequence[str]) -> int:
        """Check the ClearML identity, then run pytest serially with the SDK extra."""
        self.require_tag()
        log(f"ClearML: {os.environ['CLEARML_API_HOST']}  (the shared stand)")
        if not self.whoami_clearml():
            fail(
                "the ClearML stand does not authenticate the cveta2 identity",
                f"(clearml.py --project {PROJECT} whoami failed, see above).",
                "A certificate or SSL error in that output is a trust problem, "
                "not a refused identity:",
                *TLS_REMEDY,
                "Diagnose the stand and the Secret with the k8s-infra skill;",
                "the ClearML tests are never skipped on an armed machine.",
            )
        log(
            f"CVAT:    {os.environ['CVAT_INTEGRATION_HOST']}  (org "
            f"{os.environ['CVAT_INTEGRATION_ORG']}, project "
            f"'{os.environ['CVAT_INTEGRATION_PROJECT']}')"
        )
        log(f"MinIO:   {os.environ['MINIO_ENDPOINT']}  (bucket {self.tag})")
        log("Running pytest (xdist disabled for CVAT rate limits)")
        return subprocess.run(  # noqa: S603 - pytest with caller arguments
            [  # noqa: S607
                "uv",
                "run",
                "--extra",
                "clearml",
                "pytest",
                "-o",
                "addopts=-v --tb=short -p tests.env_isolation",
                *pytest_args,
            ],
            check=False,
            cwd=self.root,
        ).returncode

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
            warn(
                "         uv run python tests/integration/cvat_stand.py cleanup "
                f"--tag '{tag}'"
            )
            failed = True
        log(
            f"Removing bucket '{tag}' of '{tag}' from MinIO at "
            f"{os.environ['MINIO_ENDPOINT']}"
        )
        if self.helper("minio", "cleanup", "--prefix", tag).returncode:
            warn(f"WARNING: bucket '{tag}' could not be removed.")
            warn("         Retry once the stand is reachable:")
            warn(
                f'         python3 "{self.skill_dir}/scripts/minio.py" --project '
                f"{PROJECT} cleanup --prefix '{tag}'"
            )
            failed = True
        log(
            f"Removing '{tag}' projects from ClearML at "
            f"{os.environ['CLEARML_API_HOST']}"
        )
        if self.helper("clearml", "cleanup", "--prefix", tag).returncode:
            warn(f"WARNING: the ClearML projects of tag '{tag}' could not be removed.")
            warn("         Retry once the stand is reachable:")
            warn(
                f'         python3 "{self.skill_dir}/scripts/clearml.py" --project '
                f"{PROJECT} cleanup --prefix '{tag}'"
            )
            failed = True
        if failed:
            warn(
                f"ERROR: run '{tag}' is not fully torn down; the .run-tag file "
                "stays for the retry."
            )
            return 1
        self.release_run_tag()
        log("Done")
        return 0


# -- the pre-push gate -----------------------------------------------------


def _armed_but_down(*lines: str) -> NoReturn:
    fail(
        "the integration gate is armed (tests/integration/.env exists)",
        *lines,
        "Diagnose the stand with the k8s-infra skill, or push without this gate:",
        "    SKIP=integration-tests git push",
    )


def _keep_data(run: Run) -> bool:
    choice = os.environ.get("INTEGRATION_KEEP_DATA", "")
    if choice == "1":
        return True
    if choice == "0":
        return False
    return run.on_main()


def _teardown(run: Run, *, passed: bool, keep_stack: bool) -> None:
    """Keep the main slot or an explicitly kept run; stop everything else."""
    if _keep_data(run):
        if run.on_main():
            log(
                "keeping the run for inspection: it is the durable slot "
                f"'{run.tag}' (main)"
            )
        else:
            log("keeping the run for inspection (INTEGRATION_KEEP_DATA=1):")
            log(
                "    tests/integration/.run-tag still names it; the next gate "
                "refuses to start until it is stopped"
            )
        log(
            f"    CVAT:    {os.environ['CVAT_INTEGRATION_HOST']}  organization "
            f"{os.environ['CVAT_INTEGRATION_ORG']}, project "
            f"'{os.environ['CVAT_INTEGRATION_PROJECT']}'"
        )
        log(f"    MinIO:   bucket {run.tag} at {os.environ['MINIO_ENDPOINT']}")
        log(
            "    ClearML: nothing is kept - the tests remove their "
            f"'{run.tag} ...' projects at session end"
        )
        log(f"    remove everything with {MODULE} stop")
        return
    if not passed and keep_stack:
        log("leaving the run's data for triage (--keep-stack);")
        log(f"    remove it with {MODULE} stop")
        return
    log("tearing down the run")
    try:
        run.stop()
    except LifecycleError as error:
        report(error)


def gate(root: Path, pytest_args: Sequence[str], *, keep_stack: bool) -> int:
    """Pre-push gate: preflight, then up, test and keep-or-stop.

    A missing ``.env`` is the only silent skip: once armed, the gate passes,
    fails or is skipped on purpose (``SKIP=integration-tests``). A stand that is
    down fails it, because a gate that quietly passes teaches everyone to
    ignore it. The teardown is armed only after the preflight and the
    active-run check, so a run that never prepared anything cannot tear another
    one down.
    """
    if not (root / "tests" / "integration" / ".env").is_file():
        log("integration gate skipped: no tests/integration/.env on this machine")
        log("    arm it with: cp tests/integration/.env.example tests/integration/.env")
        return 0
    run = Run(root)
    host = os.environ["CVAT_INTEGRATION_HOST"]
    curl = subprocess.run(  # noqa: S603 - the stand URL from the Secret
        ["curl", "-sf", f"{host}/api/server/about"],  # noqa: S607
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode
    if curl in TLS_CURL_STATUSES:
        _armed_but_down(
            f"but TLS verification of the CVAT stand at {host} failed "
            f"(curl exit {curl}).",
            *TLS_REMEDY,
        )
    if curl != 0:
        _armed_but_down(
            f"but the CVAT stand at {host} does not answer (curl exit {curl})."
        )
    if not run.whoami_clearml():
        _armed_but_down(
            "but the ClearML stand at "
            f"{os.environ['CLEARML_API_HOST']} does not authenticate the cveta2 "
            "identity",
            f"(clearml.py --project {PROJECT} whoami failed, see above).",
            "A certificate or SSL error in that output is a trust problem, not a "
            "refused identity:",
            *TLS_REMEDY,
        )
    run.refuse_active_run()

    passed = False
    try:
        log("integration gate: preparing the run")
        run.up()
        log(f"integration gate: run tag '{run.tag}'")
        # Scoped to tests/integration: CVAT_INTEGRATION_HOST also adds a
        # live-cvat parameter to the coco8_fixtures session fixture, which
        # re-runs a slice of the unit tests against live CVAT, serially. That
        # re-run is worth doing by hand, not on every push.
        log("integration gate: running tests/integration")
        passed = run.test(["tests/integration", *pytest_args]) == 0
    finally:
        _teardown(run, passed=passed, keep_stack=keep_stack)
    if passed:
        log("integration gate: passed")
        return 0
    warn("")
    warn("==> integration gate FAILED. Reproduce and triage with:")
    warn(f"      {MODULE} up")
    warn(f"      {MODULE} test tests/integration -x --tb=long")
    warn(f"      {MODULE} stop")
    warn(
        "==> A stand that misbehaves is diagnosed with the k8s-infra skill; this "
        "tool never deploys one."
    )
    warn("==> To push without this gate (mutmut-full still runs):")
    warn("      SKIP=integration-tests git push")
    return 1


# -- command line ----------------------------------------------------------


def _terminate(signum: int, _frame: FrameType | None) -> NoReturn:
    """Turn SIGTERM into an exit so the gate's teardown still runs."""
    raise SystemExit(128 + signum)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog=MODULE, description="Integration-run lifecycle on the shared stands."
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help=argparse.SUPPRESS,
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("env", help="print this run's variables as shell exports")
    commands.add_parser("up", help="claim a tag and seed the run")
    commands.add_parser(
        "test", help="run pytest against the run (extra args go to pytest)"
    )
    commands.add_parser("stop", help="remove the run and release its tag")
    gate_parser = commands.add_parser(
        "gate", help="pre-push gate: up, test, keep-or-stop (extra args go to pytest)"
    )
    gate_parser.add_argument(
        "--keep-stack", action="store_true", help="keep a failed run for triage"
    )
    args, extra = parser.parse_known_args(argv)
    if extra and args.command not in {"test", "gate"}:
        parser.error(f"unrecognized arguments: {' '.join(extra)}")

    if isinstance(sys.stdout, io.TextIOWrapper):
        # Our lines must interleave with the children's in captured output.
        sys.stdout.reconfigure(line_buffering=True)
    signal.signal(signal.SIGTERM, _terminate)
    root: Path = args.repo_root.resolve()
    try:
        if args.command == "gate":
            return gate(root, extra, keep_stack=args.keep_stack)
        run = Run(root)
        if args.command == "env":
            for key, value in run.exported.items():
                sys.stdout.write(f"export {key}={shlex.quote(value)}\n")
            return 0
        if args.command == "up":
            run.up()
            return 0
        if args.command == "test":
            return run.test(extra)
        return run.stop()
    except LifecycleError as error:
        report(error)
        return 1


if __name__ == "__main__":
    sys.exit(main())
