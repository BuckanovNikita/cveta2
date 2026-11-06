"""scripts/mutation.py: profile resolution, workspace hygiene and the verdict.

The gate runs from a copy in a temporary tree (``scripts/`` beside its own
``pyproject.toml``) with a fake ``uv`` on PATH that records each call and plays
mutmut: ``run`` prints spinner frames, ``export-cicd-stats`` writes the stats
file and ``results`` prints ``FAKE_RESULTS``.
"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "scripts" / "mutation.py"
pytestmark = pytest.mark.skipif(
    not TOOL.is_file(), reason="mutation workspace does not copy operator scripts"
)

PYPROJECT = """
[tool.mutmut]
only_mutate = ["pkg/a.py"]

[tool.cveta2.mutation.profiles]
fast = ["pkg.a.x_fast*"]
full = []

[tool.cveta2.mutation.equivalent]
"pkg.a.x_fast__mutmut_2" = "help text only"
"pkg.a.x_slow__mutmut_9" = "help text only"
"""

FAKE_UV = """#!{python}
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
expected_cwd = os.environ.get("FAKE_EXPECT_CWD")
if expected_cwd and os.getcwd() != expected_cwd:
    sys.exit(f"uv ran in {{os.getcwd()}}, not {{expected_cwd}}")
with open(os.environ["CALL_LOG"], "a") as log:
    print(" ".join(args), file=log)
mutants = Path(os.environ["TREE"]) / "mutants"
if args[:3] == ["run", "mutmut", "run"]:
    with open(os.environ["CALL_LOG"], "a") as log:
        print("TEMPROOT=" + os.environ.get("PYTEST_DEBUG_TEMPROOT", ""), file=log)
    sys.stdout.write("frame 1\\rframe 2\\rdone 4/4\\n")
    sys.exit(int(os.environ.get("FAKE_RUN_STATUS", "0")))
if args[:3] == ["run", "mutmut", "export-cicd-stats"]:
    if not os.environ.get("FAKE_NO_STATS"):
        stats = {{"total": 4, "killed": 2, "survived": 2}}
        (mutants / "mutmut-cicd-stats.json").write_text(json.dumps(stats))
    sys.exit(0)
if args[:3] == ["run", "mutmut", "results"]:
    print(os.environ.get("FAKE_RESULTS", ""))
    sys.exit(0)
sys.exit(f"unexpected uv call {{args}}")
"""


class Tree:
    def __init__(self, root: Path) -> None:
        """Lay out the tool, its pyproject and the fake uv under *root*."""
        self.root = root
        (root / "scripts").mkdir()
        shutil.copyfile(TOOL, root / "scripts" / "mutation.py")
        (root / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
        bin_dir = root / "bin"
        bin_dir.mkdir()
        uv = bin_dir / "uv"
        uv.write_text(FAKE_UV.format(python=sys.executable), encoding="utf-8")
        uv.chmod(0o755)
        self.call_log = root / "calls"

    def run(self, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603 - the test's own copy of the tool
            [sys.executable, str(self.root / "scripts" / "mutation.py"), *args],
            env=os.environ
            | {
                "PATH": f"{self.root / 'bin'}:{os.environ['PATH']}",
                "CALL_LOG": str(self.call_log),
                "TREE": str(self.root),
                **env,
            },
            capture_output=True,
            text=True,
            check=False,
        )

    def calls(self) -> list[str]:
        if not self.call_log.exists():
            return []
        return self.call_log.read_text(encoding="utf-8").splitlines()


@pytest.fixture
def tree(tmp_path: Path) -> Tree:
    return Tree(tmp_path)


SURVIVORS_EXPLAINED = (
    "pkg.a.x_fast__mutmut_1: killed\n"
    "pkg.a.x_fast__mutmut_2: survived\n"
    "pkg.a.x_slow__mutmut_9: survived\n"
)


@pytest.mark.parametrize("profile", ["unknown-review-profile", ""])
def test_an_unknown_profile_stops_before_any_work(tree: Tree, profile: str) -> None:
    result = tree.run("--profile", profile)
    assert result.returncode == 1
    assert f"Unknown mutation profile {profile!r}" in result.stderr
    assert tree.calls() == []
    assert not (tree.root / "mutants").exists()


def test_an_empty_profile_is_a_bare_run_that_honours_the_cache(tree: Tree) -> None:
    result = tree.run("--profile", "full", FAKE_RESULTS=SURVIVORS_EXPLAINED)
    assert result.returncode == 0, result.stdout + result.stderr
    assert tree.calls()[0] == "run mutmut run"


def test_a_profile_filters_the_run_and_passes_other_arguments_through(
    tree: Tree,
) -> None:
    result = tree.run(
        "--profile", "fast", "--max-children", "4", FAKE_RESULTS=SURVIVORS_EXPLAINED
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert tree.calls()[0] == "run mutmut run --max-children 4 pkg.a.x_fast*"
    # The slow entry is outside the profile, so it is not reported stale.
    assert "Profile 'fast': 1 mutant(s) not killed" in result.stdout
    assert "Allowlisted as equivalent: 1" in result.stdout


def test_the_whole_scope_passes_when_every_survivor_is_allowlisted(
    tree: Tree,
) -> None:
    result = tree.run(FAKE_RESULTS=SURVIVORS_EXPLAINED)
    assert result.returncode == 0, result.stdout + result.stderr
    assert tree.calls()[1:] == [
        f"TEMPROOT={tree.root / 'mutants' / '.pytest-temproot'}",
        "run mutmut export-cicd-stats",
        "run mutmut results",
    ]
    assert (tree.root / "mutants" / ".pytest-temproot").is_dir()
    assert "Mutation score (whole scope): 2/4 killed (50.0%)" in result.stdout
    assert "No unexplained mutants escaped." in result.stdout
    assert (
        (tree.root / "mutants" / "mutmut-results.txt")
        .read_text(encoding="utf-8")
        .startswith("pkg.a.x_fast__mutmut_1: killed")
    )


def test_an_unexplained_survivor_fails(tree: Tree) -> None:
    results = SURVIVORS_EXPLAINED + "pkg.a.x_slow__mutmut_3: timeout\n"
    result = tree.run(FAKE_RESULTS=results)
    assert result.returncode == 1
    assert "FAILED: 1 mutant(s) escaped the tests:" in result.stdout
    assert "pkg.a.x_slow__mutmut_3: timeout" in result.stdout
    assert "uv run mutmut show <name>" in result.stdout


def test_a_stale_allowlist_entry_fails(tree: Tree) -> None:
    result = tree.run(FAKE_RESULTS="pkg.a.x_fast__mutmut_2: survived\n")
    assert result.returncode == 1
    assert "no longer match a surviving mutant" in result.stdout
    assert "pkg.a.x_slow__mutmut_9" in result.stdout


def test_missing_stats_fail(tree: Tree) -> None:
    result = tree.run(FAKE_NO_STATS="1")
    assert result.returncode == 1
    assert "was not written" in result.stderr


def test_a_failing_mutmut_run_passes_its_status_through(tree: Tree) -> None:
    result = tree.run(FAKE_RUN_STATUS="91")
    assert result.returncode == 91
    assert "mutmut run exited with status 91" in result.stderr
    assert tree.calls()[-1].startswith("TEMPROOT=")


def test_captured_output_keeps_only_the_last_spinner_frame(tree: Tree) -> None:
    result = tree.run(FAKE_RESULTS=SURVIVORS_EXPLAINED)
    assert "done 4/4" in result.stdout
    assert "frame 1" not in result.stdout
    assert "\r" not in result.stdout


def test_a_scope_change_wipes_the_mutant_tree(tree: Tree) -> None:
    tree.run(FAKE_RESULTS=SURVIVORS_EXPLAINED)
    marker = tree.root / "mutants" / "stale-mutant"
    marker.write_text("x", encoding="utf-8")
    tree.run(FAKE_RESULTS=SURVIVORS_EXPLAINED)
    assert marker.exists(), "an unchanged scope keeps the tree"

    pyproject = tree.root / "pyproject.toml"
    pyproject.write_text(
        PYPROJECT.replace('["pkg/a.py"]', '["pkg/a.py", "pkg/b.py"]'),
        encoding="utf-8",
    )
    result = tree.run(FAKE_RESULTS=SURVIVORS_EXPLAINED)
    assert "Mutation scope changed" in result.stdout
    assert not marker.exists()
    stats = json.loads(
        (tree.root / "mutants" / "mutmut-cicd-stats.json").read_text(encoding="utf-8")
    )
    assert stats["total"] == 4


def test_the_repository_profiles_resolve() -> None:
    """The hooks pass --profile fast and full; both must exist in pyproject."""
    spec = importlib.util.spec_from_file_location("mutation_tool", TOOL)
    assert spec is not None
    assert spec.loader is not None
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    assert tool.profile_globs("fast")
    assert tool.profile_globs("full") == []


def test_the_gate_runs_from_the_repository_root(tree: Tree) -> None:
    (tree.root / "sub").mkdir()
    result = subprocess.run(
        [sys.executable, "../scripts/mutation.py"],
        cwd=tree.root / "sub",
        env=os.environ
        | {
            "PATH": f"{tree.root / 'bin'}:{os.environ['PATH']}",
            "CALL_LOG": str(tree.call_log),
            "TREE": str(tree.root),
            "FAKE_RESULTS": SURVIVORS_EXPLAINED,
            "FAKE_EXPECT_CWD": str(tree.root),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
