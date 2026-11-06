"""tests/integration/lifecycle.py against a fake k8s-infra skill and a fake ``uv``.

The lifecycle runs as a subprocess with ``--repo-root`` pointing at a temporary
tree, so it reads and writes only there. The k8s-infra helpers are stand-ins
that print the exports a Secret would give and record every other call; ``uv``
and ``curl`` are recording stubs; ``PRE_COMMIT_REMOTE_BRANCH`` decides "main" so
git is never consulted. These cases were ported one for one from the shell
scripts' suite and are the parity specification of the replacement.
"""

import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import BaseModel

REPO_ROOT = Path(__file__).resolve().parent.parent
LIFECYCLE = REPO_ROOT / "tests" / "integration" / "lifecycle.py"
FEATURE_BRANCH = "refs/heads/feature"
MAIN_BRANCH = "refs/heads/main"
MINTED_TAG = "cveta2-claude-20260905-integration-k3x9"
ACTIVE_TAG = "cveta2-claude-20260901-integration-a1b2"
PYTEST_CALL = (
    "uv run --extra clearml pytest -o addopts=-v --tb=short -p tests.env_isolation"
)

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
# The gate's preflight: FAKE_CURL_STATUS is the exit status it reports
# (60 is curl's "peer certificate cannot be authenticated", 7 "connection refused").
FAKE_CURL = '#!/usr/bin/env bash\nexit "${FAKE_CURL_STATUS:-0}"\n'

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


TEST_CALLS = ["clearml whoami", f"{PYTEST_CALL} tests/integration"]


class Outcome(BaseModel):
    returncode: int
    stdout: str
    stderr: str


class Tree(BaseModel):
    """A temporary repository root with a fake skill and fake tools beside it."""

    root: Path
    skill_dir: Path

    @property
    def env_file(self) -> Path:
        return self.root / "tests" / "integration" / ".env"

    @property
    def run_tag_file(self) -> Path:
        return self.root / "tests" / "integration" / ".run-tag"

    def run(
        self,
        *args: str,
        branch: str = FEATURE_BRANCH,
        env: dict[str, str] | None = None,
    ) -> Outcome:
        run_env = {
            "PATH": f"{self.root / 'bin'}:/usr/bin:/bin",
            "HOME": str(self.root / "home"),
            "PRE_COMMIT_REMOTE_BRANCH": branch,
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
    skill_dir = tmp_path / "skill"
    (skill_dir / "scripts").mkdir(parents=True)
    for stand, exports in SECRET_EXPORTS.items():
        _write_executable(
            skill_dir / "scripts" / f"{stand}.py",
            FAKE_HELPER.replace("@STAND@", stand).replace("@EXPORTS@", exports),
        )
    _write_executable(skill_dir / "scripts" / "infra.py", FAKE_INFRA)
    result = Tree(root=tmp_path, skill_dir=skill_dir)
    result.env_file.write_text("", encoding="utf-8")
    return result


class TestArming:
    def test_a_missing_env_file_refuses_and_names_the_example(self, tree: Tree) -> None:
        tree.env_file.unlink()
        outcome, values = tree.env()
        assert outcome.returncode == 1
        assert ".env.example" in outcome.stderr
        assert not values

    def test_the_env_file_may_carry_the_skill_dir(self, tree: Tree) -> None:
        tree.env_file.write_text(
            f"# a comment\nexport K8S_INFRA_SKILL_DIR='{tree.skill_dir}'\n",
            encoding="utf-8",
        )
        outcome, values = tree.env(env={"K8S_INFRA_SKILL_DIR": str(tree.root / "no")})
        assert outcome.returncode == 0, outcome.stderr
        assert values["INTEGRATION_SKILL_DIR"] == str(tree.skill_dir)


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
        tree.run("test", env={"INFRA_RUN_TAG": MINTED_TAG})
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

    @pytest.mark.parametrize("command", ["test", "stop"])
    def test_test_and_stop_refuse_without_a_run(self, tree: Tree, command: str) -> None:
        outcome = tree.run(command)
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
        assert tree.tool_calls() == []

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
        assert tree.tool_calls() == []

    def test_a_failing_step_stops_up(self, tree: Tree) -> None:
        outcome = tree.run("up", env={"FAKE_FAIL_COMMAND": "uv"})
        assert outcome.returncode == 1
        assert "cvat_stand.py verify failed" in outcome.stderr
        assert tree.tool_calls() == [cvat("verify")]


class TestGate:
    def test_a_branch_push_runs_up_test_stop_under_the_minted_tag(
        self, tree: Tree
    ) -> None:
        outcome = tree.run("gate")
        assert outcome.returncode == 0, outcome.stderr
        assert tree.tool_calls() == [
            "clearml whoami",
            *up_calls(MINTED_TAG),
            *TEST_CALLS,
            *stop_calls(MINTED_TAG),
        ]
        assert f"run tag '{MINTED_TAG}'" in outcome.stdout
        assert tree.recorded_tag() is None

    def test_extra_arguments_reach_pytest(self, tree: Tree) -> None:
        outcome = tree.run("gate", "-k", "upload")
        assert outcome.returncode == 0, outcome.stderr
        assert f"{PYTEST_CALL} tests/integration -k upload" in tree.tool_calls()

    def test_the_clearml_identity_is_verified_before_the_run_is_prepared(
        self, tree: Tree
    ) -> None:
        outcome = tree.run("gate")
        assert outcome.returncode == 0, outcome.stderr
        assert outcome.stdout.index("clearml whoami ok") < outcome.stdout.index(
            "preparing the run"
        )

    def test_a_clearml_stand_refusing_the_identity_fails_the_armed_gate(
        self, tree: Tree
    ) -> None:
        outcome = tree.run("gate", env={"FAKE_FAIL_COMMAND": "clearml whoami"})
        assert outcome.returncode == 1
        assert "the integration gate is armed" in outcome.stderr
        assert "ClearML stand" in outcome.stderr
        assert "clearml.py --project cveta2 whoami failed" in outcome.stderr
        assert "certificate or SSL error in that output is a trust problem" in (
            outcome.stderr
        )
        assert "k8s-infra skill" in outcome.stderr
        assert "deploy" not in outcome.stderr
        assert tree.tool_calls() == ["clearml whoami"]
        assert tree.recorded_tag() is None

    def test_an_untrusted_certificate_is_reported_as_tls_not_as_a_down_stand(
        self, tree: Tree
    ) -> None:
        outcome = tree.run("gate", env={"FAKE_CURL_STATUS": "60"})
        assert outcome.returncode == 1
        assert "the integration gate is armed" in outcome.stderr
        assert "TLS verification of the CVAT stand" in outcome.stderr
        assert "curl exit 60" in outcome.stderr
        assert "certificate-trust problem, not a stand that is down" in (outcome.stderr)
        assert "k8s-infra-local-ca.crt" in outcome.stderr
        assert "does not answer" not in outcome.stderr
        assert "deploy" not in outcome.stderr
        assert tree.tool_calls() == []

    def test_a_cvat_stand_that_does_not_answer_says_so(self, tree: Tree) -> None:
        outcome = tree.run("gate", env={"FAKE_CURL_STATUS": "7"})
        assert outcome.returncode == 1
        assert "does not answer (curl exit 7)" in outcome.stderr
        assert "TLS" not in outcome.stderr
        assert tree.tool_calls() == []

    def test_main_keeps_the_durable_slot(self, tree: Tree) -> None:
        outcome = tree.run("gate", branch=MAIN_BRANCH)
        assert outcome.returncode == 0, outcome.stderr
        assert tree.tool_calls() == [
            "clearml whoami",
            *up_calls("cveta2-main"),
            *TEST_CALLS,
        ]
        assert "durable slot 'cveta2-main'" in outcome.stdout
        assert "cveta2-main coco8-dev" in outcome.stdout
        assert "ClearML" in outcome.stdout

    def test_keep_data_keeps_a_branch_run_and_its_tag_file(self, tree: Tree) -> None:
        outcome = tree.run("gate", env={"INTEGRATION_KEEP_DATA": "1"})
        assert outcome.returncode == 0, outcome.stderr
        assert tree.tool_calls()[-1] == TEST_CALLS[-1]
        assert tree.recorded_tag() == f"{MINTED_TAG}\n"
        assert "INTEGRATION_KEEP_DATA=1" in outcome.stdout
        assert ".run-tag still names it" in outcome.stdout

    def test_keep_data_zero_stops_the_main_slot(self, tree: Tree) -> None:
        outcome = tree.run(
            "gate", branch=MAIN_BRANCH, env={"INTEGRATION_KEEP_DATA": "0"}
        )
        assert outcome.returncode == 0, outcome.stderr
        assert tree.tool_calls()[-3:] == stop_calls("cveta2-main")

    def test_a_failed_branch_run_is_stopped_and_the_message_only_diagnoses(
        self, tree: Tree
    ) -> None:
        outcome = tree.run("gate", env={"FAKE_FAIL_TESTS": "1"})
        assert outcome.returncode == 1
        assert tree.tool_calls()[-3:] == stop_calls(MINTED_TAG)
        assert "integration gate FAILED" in outcome.stderr
        assert "k8s-infra skill" in outcome.stderr
        assert "deploy" not in outcome.stderr.replace("never deploys one", "")
        assert tree.recorded_tag() is None

    def test_keep_stack_keeps_a_failed_branch_run(self, tree: Tree) -> None:
        outcome = tree.run("gate", "--keep-stack", env={"FAKE_FAIL_TESTS": "1"})
        assert outcome.returncode == 1
        assert tree.tool_calls()[-1] == TEST_CALLS[-1]
        assert tree.recorded_tag() == f"{MINTED_TAG}\n"
        assert "--keep-stack" in outcome.stdout

    def test_a_failed_preparation_is_still_torn_down(self, tree: Tree) -> None:
        tree.root.joinpath("bin", "uv").write_text(
            '#!/usr/bin/env bash\necho "uv $*" >> "$FAKE_TOOL_CALLS"\n'
            '[[ "$*" != *seed_cvat* ]]\n',
            encoding="utf-8",
        )
        outcome = tree.run("gate")
        assert outcome.returncode == 1
        assert "seed_cvat.py failed" in outcome.stderr
        assert tree.tool_calls()[-3:] == stop_calls(MINTED_TAG)
        assert tree.recorded_tag() is None

    def test_an_active_run_is_refused_before_the_teardown_is_armed(
        self, tree: Tree
    ) -> None:
        tree.run_tag_file.write_text(f"{ACTIVE_TAG}\n", encoding="utf-8")
        outcome = tree.run("gate")
        assert outcome.returncode == 1
        assert (
            "a run is active; stop it or export INFRA_RUN_TAG to adopt it"
            in outcome.stderr
        )
        assert tree.tool_calls() == ["clearml whoami"]
        assert tree.recorded_tag() == f"{ACTIVE_TAG}\n"

    def test_a_missing_env_file_skips_without_touching_anything(
        self, tree: Tree
    ) -> None:
        tree.env_file.unlink()
        tree.run_tag_file.write_text(f"{ACTIVE_TAG}\n", encoding="utf-8")
        outcome = tree.run("gate")
        assert outcome.returncode == 0, outcome.stderr
        assert "integration gate skipped" in outcome.stdout
        assert tree.tool_calls() == []
        assert tree.recorded_tag() == f"{ACTIVE_TAG}\n"


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


class TestTest:
    """Whoami first, then pytest without xdist and with the ClearML extra."""

    def test_whoami_then_pytest_with_the_clearml_extra(self, tree: Tree) -> None:
        tree.run_tag_file.write_text(f"{ACTIVE_TAG}\n", encoding="utf-8")
        outcome = tree.run("test", "tests/integration", "-k", "upload")
        assert outcome.returncode == 0, outcome.stderr
        whoami, pytest_call = tree.tool_calls()
        assert whoami == "clearml whoami"
        assert pytest_call == f"{PYTEST_CALL} tests/integration -k upload"
        assert "-n auto" not in pytest_call

    def test_the_pytest_status_is_the_exit_status(self, tree: Tree) -> None:
        tree.run_tag_file.write_text(f"{ACTIVE_TAG}\n", encoding="utf-8")
        outcome = tree.run("test", env={"FAKE_FAIL_TESTS": "1"})
        assert outcome.returncode == 1

    def test_a_refused_identity_runs_no_test(self, tree: Tree) -> None:
        tree.run_tag_file.write_text(f"{ACTIVE_TAG}\n", encoding="utf-8")
        outcome = tree.run("test", env={"FAKE_FAIL_COMMAND": "clearml whoami"})
        assert outcome.returncode == 1
        assert tree.tool_calls() == ["clearml whoami"]
        assert "clearml.py --project cveta2 whoami failed" in outcome.stderr
        assert "certificate or SSL error in that output is a trust problem" in (
            outcome.stderr
        )
        assert "never skipped" in outcome.stderr
        assert "k8s-infra skill" in outcome.stderr

    def test_the_source_carries_no_soft_gate_and_no_key_pair(self) -> None:
        source = LIFECYCLE.read_text(encoding="utf-8")
        assert "debug.ping" not in source
        assert "CLEARML_API_ACCESS_KEY=" not in source
        assert "CLEARML_API_SECRET_KEY=" not in source
        assert "localhost:" not in source


def test_unknown_arguments_are_rejected_outside_test_and_gate(tree: Tree) -> None:
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
