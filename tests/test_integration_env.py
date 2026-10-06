"""The integration lifecycle scripts against a fake skill and a fake ``uv``.

``scripts/integration_env.sh`` derives its paths from its own location, so a
copy in a temporary tree (``scripts/`` next to ``tests/integration/``) reads
and writes only there; the gate, stop and test scripts are copied beside it.
The k8s-infra helpers are stand-ins that print the exports a Secret would give
and record every other call; ``PRE_COMMIT_REMOTE_BRANCH`` decides "main" so
git is never consulted.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from pydantic import BaseModel

if TYPE_CHECKING:
    from collections.abc import Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_SCRIPT = REPO_ROOT / "scripts" / "integration_env.sh"
GATE_SCRIPT = REPO_ROOT / "scripts" / "integration_gate.sh"
STOP_SCRIPT = REPO_ROOT / "scripts" / "integration_stop.sh"
TEST_SCRIPT = REPO_ROOT / "scripts" / "integration_test.sh"

# mutmut runs the suite from `mutants/`, a copy of the tree without `scripts/`.
pytestmark = pytest.mark.skipif(
    not ENV_SCRIPT.exists(),
    reason="scripts/ not present (running from a copied source tree)",
)
FEATURE_BRANCH = "refs/heads/feature"
MAIN_BRANCH = "refs/heads/main"
MINTED_TAG = "cveta2-claude-20260905-integration-k3x9"
ACTIVE_TAG = "cveta2-claude-20260901-integration-a1b2"

# A helper answers `env` with the Secret's exports; every other subcommand is
# recorded in FAKE_TOOL_CALLS as "<stand> <args>" and succeeds, unless
# FAKE_FAIL_COMMAND names it ("clearml whoami", "clearml cleanup").
FAKE_HELPER = '''#!/usr/bin/env python3
import os, sys
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
for line in """@EXPORTS@""".strip().splitlines():
    key, _, value = line.partition("=")
    if key in os.environ.get("FAKE_DROP_KEYS", "").split(","):
        continue
    print(f"export {key}='{value}'")
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

# Stand-ins for the lifecycle scripts the gate drives: each records its call in
# tests/integration/calls (the gate runs them from the repository root), and
# "up" records a minted tag the way the real one does.
FAKE_LIFECYCLE = {
    "integration_up.sh": """#!/usr/bin/env bash
echo up >> tests/integration/calls
[[ -n "${INFRA_RUN_TAG:-}" ]] || printf '%s\\n' "$FAKE_TAG" > tests/integration/.run-tag
""",
    "integration_test.sh": """#!/usr/bin/env bash
echo "test $*" >> tests/integration/calls
[[ -z "${FAKE_FAIL_TESTS:-}" ]]
""",
    "integration_stop.sh": """#!/usr/bin/env bash
echo stop >> tests/integration/calls
rm -f tests/integration/.run-tag
""",
}
FAKE_TOOL = "#!/usr/bin/env bash\nexit 0\n"
# `uv run ...` from the real stop and test scripts: recorded, never executed.
FAKE_UV = """#!/usr/bin/env bash
echo "uv $*" >> "$FAKE_TOOL_CALLS"
[[ "${FAKE_FAIL_COMMAND:-}" != "uv" ]]
"""

SECRET_EXPORTS = {
    "cvat": """
CVAT_URL=http://cvat.k8s.localhost/
CVAT_ORG=agents
CVAT_USERNAME=cveta2
CVAT_TOKEN=tok
CVAT_PASSWORD=pw
""",
    "minio": """
S3_ENDPOINT=http://minio.k8s.localhost/
S3_ENDPOINT_IN_CLUSTER=http://minio.minio.svc:9000
S3_CONSOLE=http://minio-console.k8s.localhost
S3_ACCESS_KEY=ak
S3_SECRET_KEY=sk
S3_REGION=us-east-1
AWS_ACCESS_KEY_ID=ak
AWS_SECRET_ACCESS_KEY=sk
""",
    "clearml": """
CLEARML_API_HOST=http://clearml-api.k8s.localhost
CLEARML_WEB_HOST=http://clearml.k8s.localhost
CLEARML_FILES_HOST=http://clearml-files.k8s.localhost
CLEARML_API_ACCESS_KEY=cak
CLEARML_API_SECRET_KEY=csk
CLEARML_QUEUE=agents
""",
}

OBSERVED = (
    "INTEGRATION_RUN_TAG",
    "CVAT_INTEGRATION_HOST",
    "CVAT_INTEGRATION_USER",
    "CVAT_INTEGRATION_PASSWORD",
    "CVAT_INTEGRATION_ORG",
    "CVAT_INTEGRATION_PROJECT",
    "MINIO_ENDPOINT",
    "MINIO_ENDPOINT_FOR_CVAT",
    "MINIO_ACCESS_KEY",
    "MINIO_SECRET_KEY",
    "MINIO_CONSOLE",
    "MINIO_REGION",
    "MINIO_BUCKET",
    "MINIO_PORT",
    "CLEARML_API_PORT",
    "CLEARML_API_HOST",
    "CLEARML_API_ACCESS_KEY",
    "CLEARML_QUEUE",
    "INTEGRATION_SKILL_DIR",
)


class Outcome(BaseModel):
    returncode: int
    stderr: str
    values: dict[str, str]
    run_tag_file: str | None


class Tree(BaseModel):
    """A copy of the script in its own tree, with a fake skill beside it."""

    root: Path
    skill_dir: Path

    @property
    def script(self) -> Path:
        return self.root / "scripts" / "integration_env.sh"

    @property
    def env_file(self) -> Path:
        return self.root / "tests" / "integration" / ".env"

    @property
    def run_tag_file(self) -> Path:
        return self.root / "tests" / "integration" / ".run-tag"

    @property
    def tool_calls_file(self) -> Path:
        return self.root / "tool-calls"

    def run(
        self,
        *commands: str,
        branch: str = FEATURE_BRANCH,
        env: dict[str, str] | None = None,
        skill_dir: Path | None = None,
        observed: Iterable[str] = OBSERVED,
    ) -> Outcome:
        script = " && ".join(
            [
                "set -euo pipefail",
                f"source {self.script}",
                *commands,
                "for name in " + " ".join(observed) + "; do "
                'printf "%s=%s\\n" "$name" "${!name:-}"; done',
            ]
        )
        completed = self.bash(script, branch=branch, env=env, skill_dir=skill_dir)
        values = dict(
            line.split("=", 1) for line in completed.stdout.splitlines() if "=" in line
        )
        return Outcome(
            returncode=completed.returncode,
            stderr=completed.stderr,
            values=values,
            run_tag_file=self.recorded_tag(),
        )

    def bash(
        self,
        script: str,
        *,
        branch: str = FEATURE_BRANCH,
        env: dict[str, str] | None = None,
        skill_dir: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        run_env = {
            "PATH": f"{self.root / 'bin'}:/usr/bin:/bin",
            "HOME": str(self.root / "home"),
            "PRE_COMMIT_REMOTE_BRANCH": branch,
            "K8S_INFRA_SKILL_DIR": str(skill_dir or self.skill_dir),
            "FAKE_TAG": MINTED_TAG,
            "FAKE_TOOL_CALLS": str(self.tool_calls_file),
            **(env or {}),
        }
        return subprocess.run(  # noqa: S603  the script is this test's own text
            ["bash", "-c", script],  # noqa: S607  bash comes from the PATH set above
            check=False,
            capture_output=True,
            text=True,
            env=run_env,
            timeout=60,
        )

    def recorded_tag(self) -> str | None:
        if not self.run_tag_file.exists():
            return None
        return self.run_tag_file.read_text(encoding="utf-8")

    def install_gate(self) -> Path:
        """Install the real gate beside stubbed lifecycle scripts and curl."""
        gate = self.root / "scripts" / "integration_gate.sh"
        shutil.copy(GATE_SCRIPT, gate)
        for name, text in FAKE_LIFECYCLE.items():
            _write_executable(self.root / "scripts" / name, text)
        (self.root / "bin").mkdir(exist_ok=True)
        _write_executable(self.root / "bin" / "curl", FAKE_TOOL)
        return gate

    def install_script(self, source: Path) -> Path:
        """Install one real lifecycle script with a recording `uv` beside it."""
        script = self.root / "scripts" / source.name
        shutil.copy(source, script)
        (self.root / "bin").mkdir(exist_ok=True)
        _write_executable(self.root / "bin" / "uv", FAKE_UV)
        return script

    def calls(self) -> list[str]:
        return _lines(self.root / "tests" / "integration" / "calls")

    def tool_calls(self) -> list[str]:
        """Return what the skill helpers (beyond `env`) and `uv` were asked to do."""
        return _lines(self.tool_calls_file)


def _lines(record: Path) -> list[str]:
    if not record.exists():
        return []
    return record.read_text(encoding="utf-8").splitlines()


def _write_executable(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


@pytest.fixture
def tree(tmp_path: Path) -> Tree:
    (tmp_path / "scripts").mkdir()
    (tmp_path / "tests" / "integration").mkdir(parents=True)
    (tmp_path / "home").mkdir()
    shutil.copy(ENV_SCRIPT, tmp_path / "scripts" / "integration_env.sh")
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
        outcome = tree.run()
        assert outcome.returncode == 1
        assert ".env.example" in outcome.stderr
        assert not outcome.values

    def test_the_env_file_may_carry_the_skill_dir(self, tree: Tree) -> None:
        tree.env_file.write_text(
            f"K8S_INFRA_SKILL_DIR={tree.skill_dir}\n", encoding="utf-8"
        )
        outcome = tree.run(skill_dir=tree.root / "nowhere")
        assert outcome.returncode == 0, outcome.stderr
        assert outcome.values["INTEGRATION_SKILL_DIR"] == str(tree.skill_dir)


class TestSkillDirectory:
    def test_an_explicit_skill_dir_must_carry_the_run_contract(
        self, tree: Tree
    ) -> None:
        (tree.skill_dir / "scripts" / "infra.py").unlink()
        outcome = tree.run()
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
        outcome = tree.run(env={"K8S_INFRA_SKILL_DIR": ""})
        assert outcome.returncode == 0, outcome.stderr
        assert outcome.values["INTEGRATION_SKILL_DIR"] == str(installed)

    def test_no_skill_anywhere_is_an_error(self, tree: Tree) -> None:
        outcome = tree.run(env={"K8S_INFRA_SKILL_DIR": ""})
        assert outcome.returncode == 1
        assert "~/.agents/skills" in outcome.stderr


class TestCredentials:
    def test_secrets_map_onto_the_integration_variables(self, tree: Tree) -> None:
        outcome = tree.run(env={"INFRA_RUN_TAG": MINTED_TAG})
        assert outcome.returncode == 0, outcome.stderr
        assert outcome.values["CVAT_INTEGRATION_HOST"] == "http://cvat.k8s.localhost"
        assert outcome.values["CVAT_INTEGRATION_USER"] == "cveta2"
        assert outcome.values["CVAT_INTEGRATION_PASSWORD"] == "pw"
        assert outcome.values["CVAT_INTEGRATION_ORG"] == "agents"
        assert outcome.values["MINIO_ENDPOINT"] == "http://minio.k8s.localhost"
        assert (
            outcome.values["MINIO_ENDPOINT_FOR_CVAT"] == "http://minio.minio.svc:9000"
        )
        assert outcome.values["MINIO_ACCESS_KEY"] == "ak"
        assert outcome.values["MINIO_SECRET_KEY"] == "sk"
        assert outcome.values["MINIO_CONSOLE"] == "http://minio-console.k8s.localhost"
        assert outcome.values["MINIO_REGION"] == "us-east-1"
        assert outcome.values["CLEARML_API_HOST"] == "http://clearml-api.k8s.localhost"
        assert outcome.values["CLEARML_API_ACCESS_KEY"] == "cak"
        assert outcome.values["CLEARML_QUEUE"] == "agents"

    def test_nothing_runs_on_this_host_so_no_port_is_derived(self, tree: Tree) -> None:
        outcome = tree.run(env={"INFRA_RUN_TAG": MINTED_TAG})
        assert outcome.returncode == 0, outcome.stderr
        assert outcome.values["MINIO_PORT"] == ""
        assert outcome.values["CLEARML_API_PORT"] == ""
        assert "PORT" not in ENV_SCRIPT.read_text(encoding="utf-8")

    @pytest.mark.parametrize("stand", ["cvat", "minio", "clearml"])
    def test_a_failing_helper_fails_the_script(self, tree: Tree, stand: str) -> None:
        outcome = tree.run(env={"FAKE_FAIL_STAND": stand})
        assert outcome.returncode == 1
        assert f"{stand}.py --project cveta2 env failed" in outcome.stderr
        assert "cannot read the Secret" in outcome.stderr
        assert not outcome.values

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
        outcome = tree.run(env={"FAKE_DROP_KEYS": key})
        assert outcome.returncode == 1
        assert f"the cveta2 {stand} Secret carries no {key}" in outcome.stderr
        assert not outcome.values


class TestRunTagPrecedence:
    def test_infra_run_tag_wins_and_names_everything(self, tree: Tree) -> None:
        tree.run_tag_file.write_text(f"{ACTIVE_TAG}\n", encoding="utf-8")
        outcome = tree.run(branch=MAIN_BRANCH, env={"INFRA_RUN_TAG": MINTED_TAG})
        assert outcome.returncode == 0, outcome.stderr
        assert outcome.values["INTEGRATION_RUN_TAG"] == MINTED_TAG
        assert outcome.values["CVAT_INTEGRATION_PROJECT"] == f"{MINTED_TAG} coco8-dev"
        assert outcome.values["MINIO_BUCKET"] == MINTED_TAG

    def test_main_is_the_durable_slot(self, tree: Tree) -> None:
        tree.run_tag_file.write_text(f"{ACTIVE_TAG}\n", encoding="utf-8")
        outcome = tree.run(branch=MAIN_BRANCH)
        assert outcome.returncode == 0, outcome.stderr
        assert outcome.values["INTEGRATION_RUN_TAG"] == "cveta2-main"
        assert outcome.values["MINIO_BUCKET"] == "cveta2-main"
        assert outcome.values["CVAT_INTEGRATION_PROJECT"] == "cveta2-main coco8-dev"

    def test_a_branch_reads_the_run_tag_file(self, tree: Tree) -> None:
        tree.run_tag_file.write_text(f"{ACTIVE_TAG}\n", encoding="utf-8")
        outcome = tree.run()
        assert outcome.returncode == 0, outcome.stderr
        assert outcome.values["INTEGRATION_RUN_TAG"] == ACTIVE_TAG

    def test_no_tag_leaves_the_derived_names_empty(self, tree: Tree) -> None:
        outcome = tree.run()
        assert outcome.returncode == 0, outcome.stderr
        assert outcome.values["INTEGRATION_RUN_TAG"] == ""
        assert outcome.values["CVAT_INTEGRATION_PROJECT"] == ""
        assert outcome.values["MINIO_BUCKET"] == ""

    def test_require_run_tag_refuses_without_a_run(self, tree: Tree) -> None:
        outcome = tree.run("integration_require_run_tag")
        assert outcome.returncode == 1
        assert "no run is active" in outcome.stderr
        assert "INFRA_RUN_TAG" in outcome.stderr

    def test_a_corrupt_run_tag_file_is_an_error(self, tree: Tree) -> None:
        tree.run_tag_file.write_text("Not A Tag\n", encoding="utf-8")
        outcome = tree.run()
        assert outcome.returncode == 1
        assert ".run-tag does not hold a run tag" in outcome.stderr

    def test_a_malformed_infra_run_tag_is_refused(self, tree: Tree) -> None:
        outcome = tree.run(env={"INFRA_RUN_TAG": "Cveta2_Main"})
        assert outcome.returncode == 1
        assert "not lowercase [a-z0-9-]" in outcome.stderr

    def test_a_preset_integration_run_tag_that_disagrees_is_refused(
        self, tree: Tree
    ) -> None:
        tree.run_tag_file.write_text(f"{ACTIVE_TAG}\n", encoding="utf-8")
        outcome = tree.run(env={"INTEGRATION_RUN_TAG": "nkt-feature"})
        assert outcome.returncode == 1
        assert "INTEGRATION_RUN_TAG=nkt-feature is set" in outcome.stderr
        assert "INFRA_RUN_TAG" in outcome.stderr

    def test_a_stale_export_from_a_stopped_run_is_harmless(self, tree: Tree) -> None:
        outcome = tree.run(env={"INTEGRATION_RUN_TAG": ACTIVE_TAG})
        assert outcome.returncode == 0, outcome.stderr
        assert outcome.values["INTEGRATION_RUN_TAG"] == ""


class TestClaimAndRelease:
    def test_claim_mints_and_records_a_tag(self, tree: Tree) -> None:
        outcome = tree.run("integration_claim_run_tag")
        assert outcome.returncode == 0, outcome.stderr
        assert outcome.values["INTEGRATION_RUN_TAG"] == MINTED_TAG
        assert outcome.values["MINIO_BUCKET"] == MINTED_TAG
        assert outcome.run_tag_file == f"{MINTED_TAG}\n"

    def test_claim_refuses_while_a_run_is_active(self, tree: Tree) -> None:
        tree.run_tag_file.write_text(f"{ACTIVE_TAG}\n", encoding="utf-8")
        outcome = tree.run("integration_claim_run_tag")
        assert outcome.returncode == 1
        assert (
            "a run is active; stop it or export INFRA_RUN_TAG to adopt it"
            in outcome.stderr
        )
        assert ACTIVE_TAG in outcome.stderr
        assert outcome.run_tag_file == f"{ACTIVE_TAG}\n"

    def test_claim_with_infra_run_tag_leaves_another_runs_file_alone(
        self, tree: Tree
    ) -> None:
        tree.run_tag_file.write_text(f"{ACTIVE_TAG}\n", encoding="utf-8")
        outcome = tree.run(
            "integration_claim_run_tag", env={"INFRA_RUN_TAG": MINTED_TAG}
        )
        assert outcome.returncode == 0, outcome.stderr
        assert outcome.values["INTEGRATION_RUN_TAG"] == MINTED_TAG
        assert outcome.run_tag_file == f"{ACTIVE_TAG}\n"

    def test_claim_on_main_writes_no_file(self, tree: Tree) -> None:
        outcome = tree.run("integration_claim_run_tag", branch=MAIN_BRANCH)
        assert outcome.returncode == 0, outcome.stderr
        assert outcome.values["INTEGRATION_RUN_TAG"] == "cveta2-main"
        assert outcome.run_tag_file is None

    def test_a_refused_mint_records_nothing(self, tree: Tree) -> None:
        outcome = tree.run("integration_claim_run_tag", env={"FAKE_FAIL_NEWTAG": "1"})
        assert outcome.returncode == 1
        assert "did not mint a tag" in outcome.stderr
        assert "already in use" in outcome.stderr
        assert outcome.run_tag_file is None

    def test_release_forgets_this_runs_file(self, tree: Tree) -> None:
        tree.run_tag_file.write_text(f"{ACTIVE_TAG}\n", encoding="utf-8")
        outcome = tree.run("integration_release_run_tag")
        assert outcome.returncode == 0, outcome.stderr
        assert outcome.run_tag_file is None

    def test_release_keeps_another_runs_file(self, tree: Tree) -> None:
        tree.run_tag_file.write_text(f"{ACTIVE_TAG}\n", encoding="utf-8")
        outcome = tree.run(
            "integration_release_run_tag", env={"INFRA_RUN_TAG": MINTED_TAG}
        )
        assert outcome.returncode == 0, outcome.stderr
        assert outcome.run_tag_file == f"{ACTIVE_TAG}\n"


class TestGate:
    def test_a_branch_push_runs_up_test_stop_under_the_minted_tag(
        self, tree: Tree
    ) -> None:
        gate = tree.install_gate()
        completed = tree.bash(str(gate))
        assert completed.returncode == 0, completed.stderr
        assert tree.calls() == ["up", "test tests/integration", "stop"]
        assert f"run tag '{MINTED_TAG}'" in completed.stdout
        assert tree.recorded_tag() is None

    def test_the_clearml_identity_is_verified_before_the_run_is_prepared(
        self, tree: Tree
    ) -> None:
        gate = tree.install_gate()
        completed = tree.bash(str(gate))
        assert completed.returncode == 0, completed.stderr
        assert tree.tool_calls() == ["clearml whoami"]
        assert completed.stdout.index("clearml whoami ok") < completed.stdout.index(
            "preparing the run"
        )

    def test_a_clearml_stand_refusing_the_identity_fails_the_armed_gate(
        self, tree: Tree
    ) -> None:
        gate = tree.install_gate()
        completed = tree.bash(str(gate), env={"FAKE_FAIL_COMMAND": "clearml whoami"})
        assert completed.returncode == 1
        assert "the integration gate is armed" in completed.stderr
        assert "ClearML stand" in completed.stderr
        assert "clearml.py --project cveta2 whoami failed" in completed.stderr
        assert "k8s-infra skill" in completed.stderr
        assert "deploy" not in completed.stderr
        assert tree.calls() == []
        assert tree.recorded_tag() is None

    def test_main_keeps_the_durable_slot(self, tree: Tree) -> None:
        gate = tree.install_gate()
        completed = tree.bash(str(gate), branch=MAIN_BRANCH)
        assert completed.returncode == 0, completed.stderr
        assert tree.calls() == ["up", "test tests/integration"]
        assert "durable slot 'cveta2-main'" in completed.stdout
        assert "cveta2-main coco8-dev" in completed.stdout
        assert "ClearML" in completed.stdout

    def test_keep_data_keeps_a_branch_run_and_its_tag_file(self, tree: Tree) -> None:
        gate = tree.install_gate()
        completed = tree.bash(str(gate), env={"INTEGRATION_KEEP_DATA": "1"})
        assert completed.returncode == 0, completed.stderr
        assert tree.calls() == ["up", "test tests/integration"]
        assert tree.recorded_tag() == f"{MINTED_TAG}\n"
        assert "INTEGRATION_KEEP_DATA=1" in completed.stdout
        assert ".run-tag still names it" in completed.stdout

    def test_keep_data_zero_stops_the_main_slot(self, tree: Tree) -> None:
        gate = tree.install_gate()
        completed = tree.bash(
            str(gate), branch=MAIN_BRANCH, env={"INTEGRATION_KEEP_DATA": "0"}
        )
        assert completed.returncode == 0, completed.stderr
        assert tree.calls() == ["up", "test tests/integration", "stop"]

    def test_a_failed_branch_run_is_stopped_and_the_message_only_diagnoses(
        self, tree: Tree
    ) -> None:
        gate = tree.install_gate()
        completed = tree.bash(str(gate), env={"FAKE_FAIL_TESTS": "1"})
        assert completed.returncode == 1
        assert tree.calls() == ["up", "test tests/integration", "stop"]
        assert "integration gate FAILED" in completed.stderr
        assert "k8s-infra skill" in completed.stderr
        assert "deploy" not in completed.stderr.replace("never deploy one", "")

    def test_keep_stack_keeps_a_failed_branch_run(self, tree: Tree) -> None:
        gate = tree.install_gate()
        completed = tree.bash(f"{gate} --keep-stack", env={"FAKE_FAIL_TESTS": "1"})
        assert completed.returncode == 1
        assert tree.calls() == ["up", "test tests/integration"]
        assert tree.recorded_tag() == f"{MINTED_TAG}\n"
        assert "--keep-stack" in completed.stdout

    def test_an_active_run_is_refused_before_the_teardown_is_armed(
        self, tree: Tree
    ) -> None:
        gate = tree.install_gate()
        tree.run_tag_file.write_text(f"{ACTIVE_TAG}\n", encoding="utf-8")
        completed = tree.bash(str(gate))
        assert completed.returncode == 1
        assert (
            "a run is active; stop it or export INFRA_RUN_TAG to adopt it"
            in completed.stderr
        )
        assert tree.calls() == []
        assert tree.recorded_tag() == f"{ACTIVE_TAG}\n"

    def test_a_missing_env_file_skips_without_touching_anything(
        self, tree: Tree
    ) -> None:
        gate = tree.install_gate()
        tree.env_file.unlink()
        tree.run_tag_file.write_text(f"{ACTIVE_TAG}\n", encoding="utf-8")
        completed = tree.bash(str(gate))
        assert completed.returncode == 0, completed.stderr
        assert "integration gate skipped" in completed.stdout
        assert tree.calls() == []
        assert tree.recorded_tag() == f"{ACTIVE_TAG}\n"


class TestStopScript:
    """The real integration_stop.sh: three stands, one accumulator, the tag file."""

    CVAT_CLEANUP = (
        f"uv run python tests/integration/cvat_stand.py cleanup --tag {ACTIVE_TAG}"
    )

    def test_removes_cvat_then_the_bucket_then_clearml_and_releases_the_tag(
        self, tree: Tree
    ) -> None:
        stop = tree.install_script(STOP_SCRIPT)
        tree.run_tag_file.write_text(f"{ACTIVE_TAG}\n", encoding="utf-8")
        completed = tree.bash(str(stop))
        assert completed.returncode == 0, completed.stderr
        assert tree.tool_calls() == [
            self.CVAT_CLEANUP,
            f"minio cleanup --prefix {ACTIVE_TAG}",
            f"clearml cleanup --prefix {ACTIVE_TAG}",
        ]
        assert tree.recorded_tag() is None

    def test_a_failing_clearml_cleanup_keeps_the_tag_and_names_the_retry(
        self, tree: Tree
    ) -> None:
        stop = tree.install_script(STOP_SCRIPT)
        tree.run_tag_file.write_text(f"{ACTIVE_TAG}\n", encoding="utf-8")
        completed = tree.bash(str(stop), env={"FAKE_FAIL_COMMAND": "clearml cleanup"})
        assert completed.returncode == 1
        assert tree.tool_calls()[-1] == f"clearml cleanup --prefix {ACTIVE_TAG}"
        assert "ClearML projects of tag" in completed.stderr
        assert (
            f"clearml.py\" --project cveta2 cleanup --prefix '{ACTIVE_TAG}'"
            in completed.stderr
        )
        assert "not fully torn down" in completed.stderr
        assert tree.recorded_tag() == f"{ACTIVE_TAG}\n"

    def test_a_failing_cvat_cleanup_still_reaches_the_other_stands(
        self, tree: Tree
    ) -> None:
        stop = tree.install_script(STOP_SCRIPT)
        tree.run_tag_file.write_text(f"{ACTIVE_TAG}\n", encoding="utf-8")
        completed = tree.bash(str(stop), env={"FAKE_FAIL_COMMAND": "uv"})
        assert completed.returncode == 1
        assert len(tree.tool_calls()) == 3
        assert "CVAT data of tag" in completed.stderr
        assert tree.recorded_tag() == f"{ACTIVE_TAG}\n"

    def test_refuses_without_a_run(self, tree: Tree) -> None:
        stop = tree.install_script(STOP_SCRIPT)
        completed = tree.bash(str(stop))
        assert completed.returncode == 1
        assert "no run is active" in completed.stderr
        assert tree.tool_calls() == []


class TestTestScript:
    """The real integration_test.sh: whoami first, then pytest with the SDK extra."""

    def test_whoami_then_pytest_without_xdist_and_with_the_clearml_extra(
        self, tree: Tree
    ) -> None:
        script = tree.install_script(TEST_SCRIPT)
        tree.run_tag_file.write_text(f"{ACTIVE_TAG}\n", encoding="utf-8")
        completed = tree.bash(f"{script} tests/integration -k upload")
        assert completed.returncode == 0, completed.stderr
        whoami, pytest_call = tree.tool_calls()
        assert whoami == "clearml whoami"
        assert pytest_call.startswith("uv run --extra clearml pytest -o addopts=")
        assert "-p tests.env_isolation" in pytest_call
        assert "-n auto" not in pytest_call
        assert pytest_call.endswith(" tests/integration -k upload")

    def test_a_refused_identity_runs_no_test(self, tree: Tree) -> None:
        script = tree.install_script(TEST_SCRIPT)
        tree.run_tag_file.write_text(f"{ACTIVE_TAG}\n", encoding="utf-8")
        completed = tree.bash(str(script), env={"FAKE_FAIL_COMMAND": "clearml whoami"})
        assert completed.returncode == 1
        assert tree.tool_calls() == ["clearml whoami"]
        assert "clearml.py --project cveta2 whoami failed" in completed.stderr
        assert "never skipped" in completed.stderr
        assert "k8s-infra skill" in completed.stderr

    def test_the_source_carries_no_soft_gate_and_no_key_pair(self) -> None:
        source = TEST_SCRIPT.read_text(encoding="utf-8")
        assert "debug.ping" not in source
        assert "CLEARML_API_ACCESS_KEY=" not in source
        assert "CLEARML_API_SECRET_KEY=" not in source
        assert "localhost:" not in source
