"""scripts/integration_env.sh: run tag precedence, the .run-tag file, credentials.

The script derives its paths from its own location, so a copy in a temporary
tree (``scripts/`` next to ``tests/integration/``) reads and writes only there.
The k8s-infra helpers are stand-ins that print the exports a Secret would give;
``PRE_COMMIT_REMOTE_BRANCH`` decides "main" so git is never consulted.
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

# mutmut runs the suite from `mutants/`, a copy of the tree without `scripts/`.
pytestmark = pytest.mark.skipif(
    not ENV_SCRIPT.exists(),
    reason="scripts/ not present (running from a copied source tree)",
)
FEATURE_BRANCH = "refs/heads/feature"
MAIN_BRANCH = "refs/heads/main"
MINTED_TAG = "cveta2-claude-20260905-integration-k3x9"
ACTIVE_TAG = "cveta2-claude-20260901-integration-a1b2"

FAKE_HELPER = '''#!/usr/bin/env python3
import os, sys
if sys.argv[1:3] != ["--project", "cveta2"] or sys.argv[3:] != ["env"]:
    sys.exit(f"unexpected arguments {sys.argv[1:]}")
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
""",
    "integration_stop.sh": """#!/usr/bin/env bash
echo stop >> tests/integration/calls
rm -f tests/integration/.run-tag
""",
}
FAKE_TOOL = "#!/usr/bin/env bash\nexit 0\n"

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
    "MINIO_BUCKET",
    "COMPOSE_PROJECT",
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
        """Install the real gate beside stubbed lifecycle scripts, docker and curl."""
        gate = self.root / "scripts" / "integration_gate.sh"
        shutil.copy(GATE_SCRIPT, gate)
        for name, text in FAKE_LIFECYCLE.items():
            _write_executable(self.root / "scripts" / name, text)
        (self.root / "bin").mkdir(exist_ok=True)
        for tool in ("docker", "curl"):
            _write_executable(self.root / "bin" / tool, FAKE_TOOL)
        return gate

    def calls(self) -> list[str]:
        record = self.root / "tests" / "integration" / "calls"
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
        assert outcome.values["CLEARML_API_HOST"] == "http://clearml-api.k8s.localhost"
        assert outcome.values["CLEARML_API_ACCESS_KEY"] == "cak"
        assert outcome.values["CLEARML_QUEUE"] == "agents"

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
        assert outcome.values["COMPOSE_PROJECT"] == f"{MINTED_TAG}-cveta2"

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
        assert outcome.values["COMPOSE_PROJECT"] == ""

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

    def test_main_keeps_the_durable_slot(self, tree: Tree) -> None:
        gate = tree.install_gate()
        completed = tree.bash(str(gate), branch=MAIN_BRANCH)
        assert completed.returncode == 0, completed.stderr
        assert tree.calls() == ["up", "test tests/integration"]
        assert "cveta2-main coco8-dev" in completed.stdout

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
