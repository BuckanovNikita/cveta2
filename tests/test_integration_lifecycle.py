"""tests/integration/lifecycle.py against a fake k8s-infra skill and a fake ``uv``.

The lifecycle runs as a subprocess with ``--repo-root`` pointing at a temporary
tree, so it reads and writes only there. The k8s-infra helpers are stand-ins
that print the exports a Secret would give and record every other call; ``uv``
and ``curl`` are recording stubs. The tree is an empty git repository whose
``HEAD`` names the branch, which is how the lifecycle decides "main".
"""

import os
import pty
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import ClassVar

import pytest
from pydantic import BaseModel

from tests.integration import lifecycle

REPO_ROOT = Path(__file__).resolve().parent.parent
LIFECYCLE = REPO_ROOT / "tests" / "integration" / "lifecycle.py"
FEATURE_BRANCH = "refs/heads/feature"
MAIN_BRANCH = "refs/heads/main"
MINTED_TAG = "cveta2-claude-20260905-integration-k3x9"
ACTIVE_TAG = "cveta2-claude-20260901-integration-a1b2"

# A helper answers `env` with the Secret's exports; every other subcommand is
# recorded in FAKE_TOOL_CALLS as "<stand> <args>" and succeeds, unless
# FAKE_FAIL_COMMAND names it ("clearml whoami", "clearml cleanup").
FAKE_HELPER = '''#!/usr/bin/env python3
import os, shlex, sys
if sys.argv[1:3] != ["--project", "cveta2"] or not sys.argv[3:]:
    sys.exit(f"unexpected arguments {sys.argv[1:]}")
command = sys.argv[3:]
if command != ["env"]:
    with open(os.environ["FAKE_TOOL_CALLS"], "a") as record:
        print("@STAND@", *command, file=record)
    if os.environ.get("FAKE_FAIL_COMMAND") == f"@STAND@ {command[0]}":
        print(f"@STAND@.py: {command[0]} refused by the stand", file=sys.stderr)
        sys.exit(1)
    print(f"@STAND@ {command[0]} ok")
    sys.exit(0)
if os.environ.get("FAKE_FAIL_STAND") == "@STAND@":
    print("@STAND@.py: cannot read the Secret", file=sys.stderr)
    sys.exit(1)
for line in filter(None, """@EXPORTS@""".splitlines()):
    key, _, value = line.partition("=")
    if key in os.environ.get("FAKE_DROP_KEYS", "").split(","):
        continue
    print(f"export {key}={shlex.quote(value)}")
'''

FAKE_INFRA = """#!/usr/bin/env python3
import os, sys
if sys.argv[1:] == ["room"]:
    with open(os.environ["FAKE_TOOL_CALLS"] + ".room", "a") as record:
        print("room", file=record)
    status = int(os.environ.get("FAKE_ROOM_STATUS", "0"))
    print("room: WAIT" if status == 3 else "room: GO")
    sys.exit(status)
expected = ["newtag", "--project", "cveta2", "--slug", "integration"]
if sys.argv[1:] != expected:
    sys.exit(f"unexpected arguments {sys.argv[1:]}")
if os.environ.get("FAKE_FAIL_NEWTAG"):
    print("infra.py: tag is already in use", file=sys.stderr)
    sys.exit(1)
print(os.environ["FAKE_TAG"])
"""

# `uv ...`: recorded, never executed. FAKE_FAIL_COMMAND=uv fails every call;
# FAKE_FAIL_TESTS fails only the pytest run.
FAKE_UV = """#!/usr/bin/env bash
echo "uv $*" >> "$FAKE_TOOL_CALLS"
[[ "${FAKE_FAIL_COMMAND:-}" != "uv" ]] || exit 1
if [[ "$*" == *" pytest "* && -n "${FAKE_FAIL_TESTS:-}" ]]; then exit 1; fi
exit 0
"""
# The availability probe: for URLs containing FAKE_CURL_URL (every URL when
# unset) curl exits FAKE_CURL_STATUS (60 is "peer certificate cannot be
# authenticated", 7 "connection refused") or prints FAKE_CURL_CODE as the HTTP
# status; anything else answers 200.
FAKE_CURL = """#!/usr/bin/env bash
if [[ -z "${FAKE_CURL_URL:-}" || "$*" == *"$FAKE_CURL_URL"* ]]; then
    [[ "${FAKE_CURL_STATUS:-0}" == 0 ]] || exit "$FAKE_CURL_STATUS"
    printf '%s' "${FAKE_CURL_CODE:-200}"
    exit 0
fi
printf 200
"""
FAKE_KUBECTL = '#!/usr/bin/env bash\nexit "${FAKE_KUBECTL_STATUS:-0}"\n'

# What every k8s-infra helper's `env` adds next to the Secret keys once the
# local CA is installed; the stands' https names are trusted through them.
CA_EXPORTS = """
SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
AWS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
NODE_EXTRA_CA_CERTS=/usr/local/share/ca-certificates/k8s-infra-local-ca.crt
"""
SECRET_EXPORTS = {
    "cvat": """
CVAT_URL=https://cvat.k8s.docker.internal/
CVAT_ORG=agents
CVAT_USERNAME=cveta2
CVAT_TOKEN=tok
CVAT_PASSWORD=pw with 'quotes'
""",
    "minio": """
S3_ENDPOINT=https://s3.k8s.docker.internal/
S3_ENDPOINT_IN_CLUSTER=http://minio.minio.svc:9000
S3_CONSOLE=https://minio.k8s.docker.internal
S3_ACCESS_KEY=ak
S3_SECRET_KEY=sk
S3_REGION=us-east-1
AWS_ACCESS_KEY_ID=ak
AWS_SECRET_ACCESS_KEY=sk
""",
    "clearml": """
CLEARML_API_HOST=https://api.clearml.k8s.docker.internal
CLEARML_WEB_HOST=https://clearml.k8s.docker.internal
CLEARML_FILES_HOST=https://files.clearml.k8s.docker.internal
CLEARML_API_ACCESS_KEY=cak
CLEARML_API_SECRET_KEY=csk
CLEARML_QUEUE=agents
""",
}
SECRET_EXPORTS = {
    stand: exports + CA_EXPORTS for stand, exports in SECRET_EXPORTS.items()
}


def cvat(command: str) -> str:
    return f"uv run python tests/integration/cvat_stand.py {command}"


def up_calls(tag: str) -> list[str]:
    return [
        "clearml whoami",
        cvat("verify"),
        cvat(f"cleanup --tag {tag}"),
        f"minio cleanup --prefix {tag}",
        "uv run python tests/integration/seed_cvat.py",
    ]


def stop_calls(tag: str) -> list[str]:
    return [
        cvat(f"cleanup --tag {tag}"),
        f"minio cleanup --prefix {tag}",
        f"clearml cleanup --prefix {tag}",
    ]


class Outcome(BaseModel):
    returncode: int
    stdout: str
    stderr: str


class Tree(BaseModel):
    """A temporary repository root with a fake skill and fake tools beside it."""

    root: Path
    skill_dir: Path

    @property
    def run_tag_file(self) -> Path:
        return self.root / "tests" / "integration" / ".run-tag"

    def run(
        self,
        *args: str,
        branch: str = FEATURE_BRANCH,
        env: dict[str, str] | None = None,
    ) -> Outcome:
        subprocess.run(  # noqa: S603 - fixed git arguments
            ["git", "-C", str(self.root), "symbolic-ref", "HEAD", branch],  # noqa: S607
            check=True,
        )
        run_env = {
            "PATH": f"{self.root / 'bin'}:/usr/bin:/bin",
            "HOME": str(self.root / "home"),
            "K8S_INFRA_SKILL_DIR": str(self.skill_dir),
            "FAKE_TAG": MINTED_TAG,
            "FAKE_TOOL_CALLS": str(self.root / "tool-calls"),
            **(env or {}),
        }
        completed = subprocess.run(  # noqa: S603 - the module under test
            [
                sys.executable,
                "-m",
                "tests.integration.lifecycle",
                "--repo-root",
                str(self.root),
                *args,
            ],
            check=False,
            capture_output=True,
            text=True,
            env=run_env,
            cwd=REPO_ROOT,
            timeout=60,
        )
        return Outcome(
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )

    def env(
        self,
        *,
        branch: str = FEATURE_BRANCH,
        env: dict[str, str] | None = None,
    ) -> tuple[Outcome, dict[str, str]]:
        """Run ``env`` and parse its exports the way a shell ``eval`` would."""
        outcome = self.run("env", branch=branch, env=env)
        values: dict[str, str] = {}
        if outcome.returncode == 0:
            for line in outcome.stdout.splitlines():
                key, _, value = shlex.split(line)[1].partition("=")
                values[key] = value
        return outcome, values

    def recorded_tag(self) -> str | None:
        if not self.run_tag_file.exists():
            return None
        return self.run_tag_file.read_text(encoding="utf-8")

    def tool_calls(self) -> list[str]:
        """Return what the helpers (beyond `env`) and `uv` were asked to do."""
        record = self.root / "tool-calls"
        if not record.exists():
            return []
        return record.read_text(encoding="utf-8").splitlines()


def _write_executable(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


@pytest.fixture
def tree(tmp_path: Path) -> Tree:
    (tmp_path / "tests" / "integration").mkdir(parents=True)
    for split in ("train", "val"):
        (tmp_path / "tests/fixtures/data/coco8/images" / split).mkdir(parents=True)
    (tmp_path / "home").mkdir()
    (tmp_path / "bin").mkdir()
    _write_executable(tmp_path / "bin" / "uv", FAKE_UV)
    _write_executable(tmp_path / "bin" / "curl", FAKE_CURL)
    _write_executable(tmp_path / "bin" / "kubectl", FAKE_KUBECTL)
    skill_dir = tmp_path / "skill"
    (skill_dir / "scripts").mkdir(parents=True)
    for stand, exports in SECRET_EXPORTS.items():
        _write_executable(
            skill_dir / "scripts" / f"{stand}.py",
            FAKE_HELPER.replace("@STAND@", stand).replace("@EXPORTS@", exports),
        )
    _write_executable(skill_dir / "scripts" / "infra.py", FAKE_INFRA)
    subprocess.run(  # noqa: S603 - fixed git arguments
        ["git", "init", "-q", str(tmp_path)],  # noqa: S607
        check=True,
    )
    subprocess.run(  # noqa: S603 - fixed git arguments
        ["git", "-C", str(tmp_path), "symbolic-ref", "HEAD", FEATURE_BRANCH],  # noqa: S607
        check=True,
    )
    return Tree(root=tmp_path, skill_dir=skill_dir)


class TestSkillDirectory:
    def test_an_explicit_skill_dir_must_carry_the_run_contract(
        self, tree: Tree
    ) -> None:
        (tree.skill_dir / "scripts" / "infra.py").unlink()
        outcome, _ = tree.env()
        assert outcome.returncode == 1
        assert "K8S_INFRA_SKILL_DIR" in outcome.stderr
        assert "infra.py" in outcome.stderr

    @pytest.mark.parametrize("installed_under", [".agents", ".claude"])
    def test_the_installed_skill_is_found_under_home(
        self, tree: Tree, installed_under: str
    ) -> None:
        installed = tree.root / "home" / installed_under / "skills" / "k8s-infra"
        installed.parent.mkdir(parents=True)
        shutil.copytree(tree.skill_dir, installed)
        outcome, values = tree.env(env={"K8S_INFRA_SKILL_DIR": ""})
        assert outcome.returncode == 0, outcome.stderr
        assert values["INTEGRATION_SKILL_DIR"] == str(installed)

    def test_no_skill_anywhere_is_an_error(self, tree: Tree) -> None:
        outcome, _ = tree.env(env={"K8S_INFRA_SKILL_DIR": ""})
        assert outcome.returncode == 1
        assert "~/.agents/skills" in outcome.stderr


class TestCredentials:
    def test_secrets_map_onto_the_integration_variables(self, tree: Tree) -> None:
        outcome, values = tree.env(env={"INFRA_RUN_TAG": MINTED_TAG})
        assert outcome.returncode == 0, outcome.stderr
        assert values["CVAT_INTEGRATION_HOST"] == "https://cvat.k8s.docker.internal"
        assert values["CVAT_INTEGRATION_USER"] == "cveta2"
        assert values["CVAT_INTEGRATION_PASSWORD"] == "pw with 'quotes'"
        assert values["CVAT_INTEGRATION_ORG"] == "agents"
        assert values["MINIO_ENDPOINT"] == "https://s3.k8s.docker.internal"
        assert values["MINIO_ENDPOINT_FOR_CVAT"] == "http://minio.minio.svc:9000"
        assert values["MINIO_ACCESS_KEY"] == "ak"
        assert values["MINIO_SECRET_KEY"] == "sk"
        assert values["MINIO_CONSOLE"] == "https://minio.k8s.docker.internal"
        assert values["MINIO_REGION"] == "us-east-1"
        assert values["CLEARML_API_HOST"] == "https://api.clearml.k8s.docker.internal"
        assert values["CLEARML_API_ACCESS_KEY"] == "cak"
        assert values["CLEARML_QUEUE"] == "agents"

    def test_the_helpers_ca_trust_reaches_every_process_of_the_run(
        self, tree: Tree
    ) -> None:
        """The stands are https with a local CA; the helpers' bundle is exported."""
        outcome, values = tree.env(env={"INFRA_RUN_TAG": MINTED_TAG})
        assert outcome.returncode == 0, outcome.stderr
        bundle = "/etc/ssl/certs/ca-certificates.crt"
        assert values["SSL_CERT_FILE"] == bundle
        assert values["REQUESTS_CA_BUNDLE"] == bundle
        assert values["AWS_CA_BUNDLE"] == bundle
        assert values["NODE_EXTRA_CA_CERTS"].endswith("k8s-infra-local-ca.crt")
        # Children of the run (pytest, seeding) inherit the trust as well.
        _write_executable(
            tree.root / "bin" / "uv",
            "#!/usr/bin/env bash\n"
            'echo "uv sees $SSL_CERT_FILE" >> "$FAKE_TOOL_CALLS"\n',
        )
        tree.run("up", env={"INFRA_RUN_TAG": MINTED_TAG})
        assert f"uv sees {bundle}" in tree.tool_calls()

    def test_nothing_runs_on_this_host_so_no_port_is_derived(self, tree: Tree) -> None:
        outcome, values = tree.env(env={"INFRA_RUN_TAG": MINTED_TAG})
        assert outcome.returncode == 0, outcome.stderr
        assert not [key for key in values if key.endswith("_PORT")]
        assert "_PORT" not in LIFECYCLE.read_text(encoding="utf-8")

    @pytest.mark.parametrize("stand", ["cvat", "minio", "clearml"])
    def test_a_failing_helper_fails_the_run(self, tree: Tree, stand: str) -> None:
        outcome, values = tree.env(env={"FAKE_FAIL_STAND": stand})
        assert outcome.returncode == 1
        assert f"{stand}.py --project cveta2 env failed" in outcome.stderr
        assert "cannot read the Secret" in outcome.stderr
        assert not values

    @pytest.mark.parametrize(
        ("stand", "key"),
        [
            ("cvat", "CVAT_PASSWORD"),
            ("cvat", "CVAT_ORG"),
            ("minio", "S3_ENDPOINT_IN_CLUSTER"),
            ("minio", "S3_REGION"),
            ("clearml", "CLEARML_API_SECRET_KEY"),
        ],
    )
    def test_a_secret_without_a_needed_key_is_an_error_not_a_default(
        self, tree: Tree, stand: str, key: str
    ) -> None:
        outcome, values = tree.env(env={"FAKE_DROP_KEYS": key})
        assert outcome.returncode == 1
        assert f"the cveta2 {stand} Secret carries no {key}" in outcome.stderr
        assert not values


class TestRunTagPrecedence:
    def test_infra_run_tag_wins_and_names_everything(self, tree: Tree) -> None:
        tree.run_tag_file.write_text(f"{ACTIVE_TAG}\n", encoding="utf-8")
        outcome, values = tree.env(
            branch=MAIN_BRANCH, env={"INFRA_RUN_TAG": MINTED_TAG}
        )
        assert outcome.returncode == 0, outcome.stderr
        assert values["INTEGRATION_RUN_TAG"] == MINTED_TAG
        assert values["CVAT_INTEGRATION_PROJECT"] == f"{MINTED_TAG} coco8-dev"
        assert values["MINIO_BUCKET"] == MINTED_TAG

    def test_main_is_the_durable_slot(self, tree: Tree) -> None:
        tree.run_tag_file.write_text(f"{ACTIVE_TAG}\n", encoding="utf-8")
        outcome, values = tree.env(branch=MAIN_BRANCH)
        assert outcome.returncode == 0, outcome.stderr
        assert values["INTEGRATION_RUN_TAG"] == "cveta2-main"
        assert values["MINIO_BUCKET"] == "cveta2-main"
        assert values["CVAT_INTEGRATION_PROJECT"] == "cveta2-main coco8-dev"

    def test_a_branch_reads_the_run_tag_file(self, tree: Tree) -> None:
        tree.run_tag_file.write_text(f"{ACTIVE_TAG}\n", encoding="utf-8")
        outcome, values = tree.env()
        assert outcome.returncode == 0, outcome.stderr
        assert values["INTEGRATION_RUN_TAG"] == ACTIVE_TAG

    def test_no_tag_leaves_the_derived_names_empty(self, tree: Tree) -> None:
        outcome, values = tree.env()
        assert outcome.returncode == 0, outcome.stderr
        assert values["INTEGRATION_RUN_TAG"] == ""
        assert values["CVAT_INTEGRATION_PROJECT"] == ""
        assert values["MINIO_BUCKET"] == ""

    def test_stop_refuses_without_a_run(self, tree: Tree) -> None:
        outcome = tree.run("stop")
        assert outcome.returncode == 1
        assert "no run is active" in outcome.stderr
        assert "INFRA_RUN_TAG" in outcome.stderr
        assert tree.tool_calls() == []

    def test_a_corrupt_run_tag_file_is_an_error(self, tree: Tree) -> None:
        tree.run_tag_file.write_text("Not A Tag\n", encoding="utf-8")
        outcome, _ = tree.env()
        assert outcome.returncode == 1
        assert ".run-tag does not hold a run tag" in outcome.stderr

    def test_a_malformed_infra_run_tag_is_refused(self, tree: Tree) -> None:
        outcome, _ = tree.env(env={"INFRA_RUN_TAG": "Cveta2_Main"})
        assert outcome.returncode == 1
        assert "not lowercase [a-z0-9-]" in outcome.stderr

    def test_a_preset_integration_run_tag_that_disagrees_is_refused(
        self, tree: Tree
    ) -> None:
        tree.run_tag_file.write_text(f"{ACTIVE_TAG}\n", encoding="utf-8")
        outcome, _ = tree.env(env={"INTEGRATION_RUN_TAG": "nkt-feature"})
        assert outcome.returncode == 1
        assert "INTEGRATION_RUN_TAG=nkt-feature is set" in outcome.stderr
        assert "INFRA_RUN_TAG" in outcome.stderr

    def test_a_stale_export_from_a_stopped_run_is_harmless(self, tree: Tree) -> None:
        outcome, values = tree.env(env={"INTEGRATION_RUN_TAG": ACTIVE_TAG})
        assert outcome.returncode == 0, outcome.stderr
        assert values["INTEGRATION_RUN_TAG"] == ""


class TestUp:
    def test_up_mints_records_and_seeds_under_the_tag(self, tree: Tree) -> None:
        outcome = tree.run("up")
        assert outcome.returncode == 0, outcome.stderr
        assert tree.recorded_tag() == f"{MINTED_TAG}\n"
        assert tree.tool_calls() == up_calls(MINTED_TAG)
        assert f"project '{MINTED_TAG} coco8-dev'" in outcome.stdout

    def test_up_refuses_while_a_run_is_active(self, tree: Tree) -> None:
        tree.run_tag_file.write_text(f"{ACTIVE_TAG}\n", encoding="utf-8")
        outcome = tree.run("up")
        assert outcome.returncode == 1
        assert (
            "a run is active; stop it or export INFRA_RUN_TAG to adopt it"
            in outcome.stderr
        )
        assert ACTIVE_TAG in outcome.stderr
        assert tree.recorded_tag() == f"{ACTIVE_TAG}\n"
        assert tree.tool_calls() == ["clearml whoami"]

    def test_up_with_infra_run_tag_leaves_another_runs_file_alone(
        self, tree: Tree
    ) -> None:
        tree.run_tag_file.write_text(f"{ACTIVE_TAG}\n", encoding="utf-8")
        outcome = tree.run("up", env={"INFRA_RUN_TAG": MINTED_TAG})
        assert outcome.returncode == 0, outcome.stderr
        assert tree.tool_calls() == up_calls(MINTED_TAG)
        assert tree.recorded_tag() == f"{ACTIVE_TAG}\n"

    def test_up_on_main_writes_no_file(self, tree: Tree) -> None:
        outcome = tree.run("up", branch=MAIN_BRANCH)
        assert outcome.returncode == 0, outcome.stderr
        assert tree.tool_calls() == up_calls("cveta2-main")
        assert tree.recorded_tag() is None

    def test_a_refused_mint_records_nothing(self, tree: Tree) -> None:
        outcome = tree.run("up", env={"FAKE_FAIL_NEWTAG": "1"})
        assert outcome.returncode == 1
        assert "did not mint a tag" in outcome.stderr
        assert "already in use" in outcome.stderr
        assert tree.recorded_tag() is None
        assert tree.tool_calls() == ["clearml whoami"]

    def test_a_failing_step_stops_up(self, tree: Tree) -> None:
        outcome = tree.run("up", env={"FAKE_FAIL_COMMAND": "uv"})
        assert outcome.returncode == 1
        assert "cvat_stand.py verify failed" in outcome.stderr
        assert tree.tool_calls() == [
            "clearml whoami",
            cvat("verify"),
            *stop_calls(MINTED_TAG),
        ]


class TestStop:
    """Three stands, one accumulator, the tag file."""

    def test_removes_cvat_then_the_bucket_then_clearml_and_releases_the_tag(
        self, tree: Tree
    ) -> None:
        tree.run_tag_file.write_text(f"{ACTIVE_TAG}\n", encoding="utf-8")
        outcome = tree.run("stop")
        assert outcome.returncode == 0, outcome.stderr
        assert tree.tool_calls() == stop_calls(ACTIVE_TAG)
        assert tree.recorded_tag() is None

    def test_stop_keeps_another_runs_file(self, tree: Tree) -> None:
        tree.run_tag_file.write_text(f"{ACTIVE_TAG}\n", encoding="utf-8")
        outcome = tree.run("stop", env={"INFRA_RUN_TAG": MINTED_TAG})
        assert outcome.returncode == 0, outcome.stderr
        assert tree.tool_calls() == stop_calls(MINTED_TAG)
        assert tree.recorded_tag() == f"{ACTIVE_TAG}\n"

    def test_a_failing_clearml_cleanup_keeps_the_tag_and_names_the_retry(
        self, tree: Tree
    ) -> None:
        tree.run_tag_file.write_text(f"{ACTIVE_TAG}\n", encoding="utf-8")
        outcome = tree.run("stop", env={"FAKE_FAIL_COMMAND": "clearml cleanup"})
        assert outcome.returncode == 1
        assert tree.tool_calls()[-1] == f"clearml cleanup --prefix {ACTIVE_TAG}"
        assert "ClearML projects of tag" in outcome.stderr
        assert (
            f"clearml.py\" --project cveta2 cleanup --prefix '{ACTIVE_TAG}'"
            in outcome.stderr
        )
        assert "not fully torn down" in outcome.stderr
        assert tree.recorded_tag() == f"{ACTIVE_TAG}\n"

    def test_a_failing_cvat_cleanup_still_reaches_the_other_stands(
        self, tree: Tree
    ) -> None:
        tree.run_tag_file.write_text(f"{ACTIVE_TAG}\n", encoding="utf-8")
        outcome = tree.run("stop", env={"FAKE_FAIL_COMMAND": "uv"})
        assert outcome.returncode == 1
        assert len(tree.tool_calls()) == 3
        assert "CVAT data of tag" in outcome.stderr
        assert tree.recorded_tag() == f"{ACTIVE_TAG}\n"


def test_unknown_arguments_are_rejected(tree: Tree) -> None:
    outcome = tree.run("stop", "--force")
    assert outcome.returncode == 2
    assert "unrecognized arguments: --force" in outcome.stderr


def test_the_env_output_evaluates_in_a_shell(tree: Tree) -> None:
    outcome = tree.run("env", env={"INFRA_RUN_TAG": MINTED_TAG})
    assert outcome.returncode == 0, outcome.stderr
    script = (
        outcome.stdout + 'printf "%s|%s" "$CVAT_INTEGRATION_PASSWORD" "$MINIO_BUCKET"'
    )
    shell = subprocess.run(  # noqa: S603 - evaluates the tool's own output
        ["bash", "-c", script],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    )
    assert shell.stdout == f"pw with 'quotes'|{MINTED_TAG}"


@pytest.mark.parametrize("line", ["export =''", "export 'A B'=x", "rm -rf /", "export"])
def test_an_unexpected_helper_line_is_refused_not_evaluated(
    tree: Tree, line: str
) -> None:
    helper = tree.skill_dir / "scripts" / "cvat.py"
    text = helper.read_text(encoding="utf-8")
    helper.write_text(
        text + f"if command == ['env']:\n    print({line!r})\n", encoding="utf-8"
    )
    outcome, values = tree.env()
    assert outcome.returncode == 1
    assert "cvat.py env printed an unexpected line" in outcome.stderr
    assert not values


def test_the_claimed_tag_names_the_bucket_and_the_project(tree: Tree) -> None:
    assert tree.run("up").returncode == 0
    outcome, values = tree.env()
    assert outcome.returncode == 0, outcome.stderr
    assert values["INTEGRATION_RUN_TAG"] == MINTED_TAG
    assert values["MINIO_BUCKET"] == MINTED_TAG
    assert values["CVAT_INTEGRATION_PROJECT"] == f"{MINTED_TAG} coco8-dev"


def test_env_refuses_to_print_credentials_to_a_terminal(tree: Tree) -> None:
    leader, follower = pty.openpty()
    try:
        completed = subprocess.run(  # noqa: S603 - the module under test
            [
                sys.executable,
                "-m",
                "tests.integration.lifecycle",
                "--repo-root",
                str(tree.root),
                "env",
            ],
            env={
                "PATH": f"{tree.root / 'bin'}:/usr/bin:/bin",
                "HOME": str(tree.root / "home"),
                "K8S_INFRA_SKILL_DIR": str(tree.skill_dir),
            },
            cwd=REPO_ROOT,
            stdout=follower,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=60,
        )
        os.set_blocking(leader, False)
        try:
            shown = os.read(leader, 65536).decode()
        except BlockingIOError:
            shown = ""
    finally:
        os.close(leader)
        os.close(follower)
    assert completed.returncode == 1
    assert "evaluate it instead" in completed.stderr
    assert "pw with" not in shown


class TestProbe:
    """`up` probes the stands first; a zero wait timeout turns "down" into a refusal."""

    NO_WAIT: ClassVar[dict[str, str]] = {"CVETA2_STAND_WAIT_TIMEOUT": "0"}

    @pytest.mark.parametrize(
        ("env", "reason"),
        [
            ({"FAKE_KUBECTL_STATUS": "1"}, "docker-desktop cluster does not answer"),
            ({"FAKE_ROOM_STATUS": "3"}, "infra.py room answers WAIT"),
            (
                {"FAKE_CURL_URL": "cvat", "FAKE_CURL_STATUS": "7"},
                (
                    "CVAT stand at https://cvat.k8s.docker.internal/api/server/about "
                    "does not answer (curl exit 7)"
                ),
            ),
            (
                {"FAKE_CURL_URL": "minio/health", "FAKE_CURL_CODE": "503"},
                (
                    "MinIO stand at https://s3.k8s.docker.internal/minio/health/live "
                    "answers HTTP 503"
                ),
            ),
            (
                {"FAKE_CURL_URL": "debug.ping", "FAKE_CURL_STATUS": "28"},
                "ClearML stand",
            ),
        ],
    )
    def test_a_stopped_stand_is_waited_for_not_failed(
        self, tree: Tree, env: dict[str, str], reason: str
    ) -> None:
        outcome = tree.run("up", env={**self.NO_WAIT, **env})
        assert outcome.returncode == 1
        assert "CVETA2_STAND_WAIT_TIMEOUT" in outcome.stderr
        assert reason in outcome.stderr
        assert tree.tool_calls() == []
        assert tree.recorded_tag() is None

    def test_an_untrusted_certificate_fails_at_once_as_tls(self, tree: Tree) -> None:
        outcome = tree.run(
            "up", env={"FAKE_CURL_URL": "cvat", "FAKE_CURL_STATUS": "60"}
        )
        assert outcome.returncode == 1
        assert "TLS verification of the CVAT stand" in outcome.stderr
        assert "certificate-trust problem, not a stand that is down" in outcome.stderr
        assert "CVETA2_STAND_WAIT_TIMEOUT" not in outcome.stderr
        assert tree.tool_calls() == []

    @pytest.mark.parametrize(
        ("env", "message"),
        [
            ({"FAKE_ROOM_STATUS": "2"}, "infra.py room failed (exit 2)"),
            (
                {"FAKE_CURL_URL": "debug.ping", "FAKE_CURL_CODE": "404"},
                "answers HTTP 404; that is not a stopped stand",
            ),
        ],
    )
    def test_a_broken_check_fails_at_once_instead_of_waiting(
        self, tree: Tree, env: dict[str, str], message: str
    ) -> None:
        outcome = tree.run("up", env=env)
        assert outcome.returncode == 1
        assert message in outcome.stderr
        assert "CVETA2_STAND_WAIT_TIMEOUT" not in outcome.stderr
        assert tree.recorded_tag() is None

    def test_a_failed_seed_still_tears_the_run_down(self, tree: Tree) -> None:
        tree.root.joinpath("bin", "uv").write_text(
            '#!/usr/bin/env bash\necho "uv $*" >> "$FAKE_TOOL_CALLS"\n'
            '[[ "$*" != *seed_cvat* ]]\n',
            encoding="utf-8",
        )
        outcome = tree.run("up")
        assert outcome.returncode == 1
        assert "seed_cvat.py failed" in outcome.stderr
        assert tree.tool_calls()[-3:] == stop_calls(MINTED_TAG)
        assert tree.recorded_tag() is None

    def test_a_refused_clearml_identity_fails_at_once(self, tree: Tree) -> None:
        outcome = tree.run("up", env={"FAKE_FAIL_COMMAND": "clearml whoami"})
        assert outcome.returncode == 1
        assert "does not authenticate the cveta2 identity" in outcome.stderr
        assert tree.tool_calls() == ["clearml whoami"]

    def test_a_missing_skill_fails_at_once(self, tree: Tree) -> None:
        (tree.skill_dir / "scripts" / "infra.py").unlink()
        outcome = tree.run("up")
        assert outcome.returncode == 1
        assert "K8S_INFRA_SKILL_DIR" in outcome.stderr
        assert tree.tool_calls() == []


class FakeClock:
    def __init__(self) -> None:
        """Start at zero; every sleep advances the clock and is recorded."""
        self.now = 0.0
        self.sleeps: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class TestWaitForStands:
    """The wait loop with an injected probe and clock."""

    @staticmethod
    def wait(
        answers: list[str], clock: FakeClock, timeout: float | None = None
    ) -> tuple[object, list[str]]:
        ready = object()
        pending = iter(answers)
        notices: list[str] = []
        result = lifecycle.wait_for_stands(
            lambda: next(pending, ready),  # type: ignore[arg-type,return-value]
            notify=notices.append,
            sleep=clock.sleep,
            now=lambda: clock.now,
            timeout=timeout,
        )
        assert result is ready
        return result, notices

    def test_ready_stands_wait_for_nothing(self) -> None:
        clock = FakeClock()
        _, notices = self.wait([], clock)
        assert notices == []
        assert clock.sleeps == []

    def test_one_notice_backoff_heartbeats_and_a_recovery_notice(self) -> None:
        clock = FakeClock()
        _, notices = self.wait(["CVAT is down"] * 9, clock)
        assert clock.sleeps == [15, 30, 60, 60, 60, 60, 60, 60, 60]
        assert notices[0].startswith("Стенды недоступны: CVAT is down.")
        assert "Ctrl-C" in notices[0]
        heartbeats = [n for n in notices if n.startswith("Всё ещё жду стенды")]
        assert len(heartbeats) == 1
        assert notices[-1].startswith("Стенды снова доступны")

    def test_the_timeout_fails_with_the_last_reason(self) -> None:
        clock = FakeClock()
        with pytest.raises(lifecycle.LifecycleError) as error:
            self.wait(["room WAIT"] * 10, clock, timeout=40)
        assert "CVETA2_STAND_WAIT_TIMEOUT" in error.value.lines[0]
        assert "room WAIT" in error.value.lines[0]
        assert sum(clock.sleeps) == 40

    def test_ctrl_c_ends_the_wait(self) -> None:
        def interrupted(_seconds: float) -> None:
            raise KeyboardInterrupt

        with pytest.raises(KeyboardInterrupt):
            lifecycle.wait_for_stands(
                lambda: "down", notify=lambda _: None, sleep=interrupted
            )

    @pytest.mark.parametrize(("raw", "expected"), [("", None), ("90", 90.0)])
    def test_the_timeout_comes_from_the_environment(
        self, monkeypatch: pytest.MonkeyPatch, raw: str, expected: float | None
    ) -> None:
        monkeypatch.setenv("CVETA2_STAND_WAIT_TIMEOUT", raw)
        assert lifecycle.wait_timeout() == expected


class StubRun:
    def __init__(self, *, main: bool) -> None:
        """Stand in for a run on main or on a branch."""
        self.tag = "cveta2-main" if main else MINTED_TAG
        self.main = main
        self.stopped = False

    def on_main(self) -> bool:
        return self.main

    def stop(self) -> int:
        self.stopped = True
        return 0


@pytest.mark.parametrize(
    ("main", "keep", "stopped"),
    [(False, "", True), (True, "", False), (False, "1", False), (True, "0", True)],
)
def test_finish_keeps_main_or_an_explicit_keep_and_stops_the_rest(
    monkeypatch: pytest.MonkeyPatch, *, main: bool, keep: str, stopped: bool
) -> None:
    monkeypatch.setenv("INTEGRATION_KEEP_DATA", keep)
    run = StubRun(main=main)
    assert lifecycle.finish(run) == 0  # type: ignore[arg-type]
    assert run.stopped is stopped


def test_children_get_the_real_home_back(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / ".cache"))
    monkeypatch.setenv(
        "CVETA2_REAL_ENV", '{"HOME": "/home/real", "XDG_CACHE_HOME": null}'
    )
    environ = lifecycle.child_env()
    assert environ["HOME"] == "/home/real"
    assert "XDG_CACHE_HOME" not in environ


def _collected_live(*options: str) -> list[str]:
    """Node ids ``-m integration`` selects from the live and a unit directory."""
    completed = subprocess.run(  # noqa: S603 - this repository's own pytest
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-o",
            "addopts=-p tests.env_isolation",
            "-p",
            "no:cacheprovider",
            "-m",
            "integration",
            *options,
            "tests/integration",
            "tests/test_output.py",
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return [line for line in completed.stdout.splitlines() if "::" in line]


def test_live_tests_are_marked_and_keep_file_order_under_any_seed() -> None:
    in_file_order = _collected_live("-p", "no:randomly")
    assert in_file_order
    assert all(node.startswith("tests/integration/") for node in in_file_order)
    for seed in ("1", "2"):
        assert _collected_live(f"--randomly-seed={seed}") == in_file_order
