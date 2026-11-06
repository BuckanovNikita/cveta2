"""scripts/mutation.py: diff-to-function mapping, the per-run workspace, the verdict.

The end-to-end cases run the tool in-process against a throwaway git repository
with a fake ``mutmut`` that records how it was called and plays ``run``,
``results`` and ``show``.
"""

import json
import os
import shutil
import subprocess
import sys
import textwrap
import time
import tomllib
from pathlib import Path

import pytest

from scripts import mutation

FAKE_MUTMUT = """#!{python}
import json, os, sys, tomllib
from pathlib import Path
args = sys.argv[1:]
log = Path(os.environ["FAKE_LOG"])
config = tomllib.loads(Path("pyproject.toml").read_text())["tool"]["mutmut"]
record = {{
    "args": args,
    "cwd": os.getcwd(),
    "only_mutate": config.get("only_mutate"),
    "temproot": os.environ.get("PYTEST_DEBUG_TEMPROOT", ""),
    "stand": sorted(
        k for k in os.environ
        if k.startswith(
            ("CVAT_INTEGRATION_", "MINIO_", "CLEARML_", "INTEGRATION_", "GIT_")
        )
        or k == "INFRA_RUN_TAG"
    ),
    "staged": Path("cveta2/mod.py").read_text(),
}}
with log.open("a") as handle:
    handle.write(json.dumps(record) + "\\n")
if args[0] == "run":
    sys.stdout.write("frame 1\\rframe 2\\rdone\\n")
    if os.environ.get("FAKE_NO_TESTS"):
        print("Stopping early, because we could not find any test case for any mutant.")
        sys.exit(1)
    if os.environ.get("FAKE_NOTHING"):
        print("AssertionError: Filtered for specific mutants, but nothing matches")
        sys.exit(1)
    if os.environ.get("FAKE_HANG"):
        import subprocess, time
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        Path(os.environ["FAKE_HANG"]).write_text(str(child.pid))
        time.sleep(60)
    sys.exit(int(os.environ.get("FAKE_RUN_STATUS", "0")))
if args[0] == "results":
    print(os.environ.get("FAKE_RESULTS", ""))
    sys.exit(0)
if args[0] == "show":
    print(f"# {{args[1]}}: survived\\n--- a\\n+++ b\\n-x\\n+y")
    sys.exit(0)
sys.exit(f"unexpected mutmut call {{args}}")
"""

PYPROJECT = """[project]
name = "fake"

[tool.mutmut]
source_paths = ["cveta2"]
"""

MODULE = textwrap.dedent(
    """\
    def alpha(x):
        return x + 1


    def beta(x):
        return x * 2


    class Box:
        def size(self):
            return 3

        @property
        def label(self):
            return "box"
    """
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)  # noqa: S603, S607


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Build a committed repository with one cveta2 module and a fake mutmut."""
    root = tmp_path / "repo"
    (root / "cveta2").mkdir(parents=True)
    (root / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    (root / "cveta2" / "__init__.py").write_text("", encoding="utf-8")
    (root / "cveta2" / "mod.py").write_text(MODULE, encoding="utf-8")
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", ".")
    _git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")

    fake = tmp_path / "bin" / "mutmut"
    fake.parent.mkdir()
    fake.write_text(FAKE_MUTMUT.format(python=sys.executable), encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setattr(mutation, "REPO_ROOT", root)
    monkeypatch.setattr(mutation, "mutmut_binary", lambda: fake)
    monkeypatch.setenv("FAKE_LOG", str(tmp_path / "calls.jsonl"))
    return root


def _calls(repo: Path) -> list[dict[str, object]]:
    log = repo.parent / "calls.jsonl"
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text("utf-8").splitlines()]


def _stage(repo: Path, text: str) -> None:
    (repo / "cveta2" / "mod.py").write_text(text, encoding="utf-8")
    _git(repo, "add", "cveta2/mod.py")


# -- mapping changed lines to mutant globs ---------------------------------


def test_targets_cover_only_functions_containing_changed_lines() -> None:
    targets = mutation.targets_for("cveta2/mod.py", MODULE, {6})
    assert [t.qualname for t in targets] == ["beta"]
    assert targets[0].globs == ("cveta2.mod.x_beta*",)


def test_methods_use_mutmut_class_mangling_and_skip_decorated_ones() -> None:
    targets = mutation.targets_for("cveta2/mod.py", MODULE, None)
    names = {t.qualname: t.names for t in targets}
    assert names["Box.size"] == ("cveta2.mod.xǁBoxǁsize",)
    assert "Box.label" not in names


def test_decorated_functions_and_classes_are_not_targets() -> None:
    source = textwrap.dedent(
        """\
        import functools

        @functools.cache
        def cached():
            return 1

        @staticmethod
        def plain():
            return 2

        @dataclass
        class Data:
            def method(self):
                return 3
        """
    )
    targets = mutation.targets_for("cveta2/m.py", source, None)
    assert [t.qualname for t in targets] == ["plain"]


def test_changed_decorator_line_selects_its_function() -> None:
    source = "@staticmethod\ndef f():\n    return 1\n"
    assert [t.qualname for t in mutation.targets_for("cveta2/m.py", source, {1})] == [
        "f"
    ]


def test_package_init_globs_cover_both_module_spellings() -> None:
    targets = mutation.targets_for(
        "cveta2/pkg/__init__.py", "def f():\n    return 1\n", None
    )
    assert targets[0].names == ("cveta2.pkg.__init__.x_f", "cveta2.pkg.x_f")


def test_changed_lines_reads_the_staged_diff_only(repo: Path) -> None:
    _stage(repo, MODULE.replace("x * 2", "x * 3"))
    (repo / "cveta2" / "mod.py").write_text(
        MODULE.replace("x + 1", "x + 5"), encoding="utf-8"
    )  # unstaged edit of another function
    assert mutation.changed_lines("HEAD") == {"cveta2/mod.py": {6}}


# -- workspace -------------------------------------------------------------


def test_narrow_scope_inserts_the_changed_files(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(PYPROJECT, encoding="utf-8")
    mutation.narrow_scope(pyproject, ["cveta2/a.py", "cveta2/b.py"])
    config = tomllib.loads(pyproject.read_text("utf-8"))["tool"]["mutmut"]
    assert config["only_mutate"] == ["cveta2/a.py", "cveta2/b.py"]
    assert config["use_git_change_detection"] is False
    assert config["source_paths"] == ["cveta2"]


def test_narrow_scope_refuses_a_checked_in_scope(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(PYPROJECT + 'only_mutate = ["x.py"]\n', encoding="utf-8")
    with pytest.raises(mutation.MutationError, match="only_mutate"):
        mutation.narrow_scope(pyproject, ["cveta2/a.py"])


def test_child_env_drops_stand_and_git_variables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CVAT_INTEGRATION_HOST", "https://cvat")
    monkeypatch.setenv("MINIO_ENDPOINT", "https://minio")
    monkeypatch.setenv("INFRA_RUN_TAG", "t")
    monkeypatch.setenv("GIT_INDEX_FILE", "/repo/.git/index")
    env = mutation.child_env(tmp_path)
    dropped = {
        "CVAT_INTEGRATION_HOST",
        "MINIO_ENDPOINT",
        "INFRA_RUN_TAG",
        "GIT_INDEX_FILE",
    }
    assert not dropped & set(env)
    assert env["PYTEST_DEBUG_TEMPROOT"] == str(tmp_path / ".pytest-temproot")


# -- end to end ------------------------------------------------------------


def test_clean_index_runs_nothing(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert mutation.main([]) == 0
    assert "nothing to do" in capsys.readouterr().out
    assert _calls(repo) == []


def test_run_uses_a_private_workspace_of_the_staged_tree(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    staged = MODULE.replace("x * 2", "x * 3")
    _stage(repo, staged)
    (repo / "cveta2" / "mod.py").write_text("broken(", encoding="utf-8")
    monkeypatch.setenv("CVAT_INTEGRATION_HOST", "https://cvat")
    monkeypatch.setenv("CLEARML_API_HOST", "https://clearml")
    monkeypatch.setenv("INTEGRATION_RUN_TAG", "t")
    monkeypatch.setenv("FAKE_RESULTS", "    cveta2.mod.x_beta__mutmut_1: killed")

    assert mutation.main(["--max-children", "3"]) == 0

    run, results = _calls(repo)
    workspace = Path(str(run["cwd"]))
    assert workspace != repo
    assert not workspace.exists()  # removed after the run
    assert run["args"] == ["run", "--max-children", "3", "cveta2.mod.x_beta*"]
    assert run["only_mutate"] == ["cveta2/mod.py"]
    assert run["staged"] == staged
    assert run["stand"] == []
    assert str(run["temproot"]).startswith(str(workspace))
    assert results["args"] == ["results", "--all", "true"]
    out = capsys.readouterr().out
    assert "frame 1" not in out
    assert "killed: 1, survived: 0" in out


def test_survivors_are_reported_with_diffs_and_pass_unless_strict(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stage(repo, MODULE.replace("x * 2", "x * 3"))
    monkeypatch.setenv(
        "FAKE_RESULTS",
        "    cveta2.mod.x_beta__mutmut_1: survived\n"
        "    cveta2.mod.x_beta__mutmut_2: killed\n"
        "    cveta2.mod.x_beta_two__mutmut_1: survived\n"
        "    cveta2.mod.x_alpha__mutmut_1: not checked",
    )
    assert mutation.main([]) == 0
    out = capsys.readouterr().out
    assert "Mutants in changed functions: 2, killed: 1, survived: 1" in out
    assert "# cveta2.mod.x_beta__mutmut_1: survived" in out
    assert "x_alpha" not in out
    assert "x_beta_two" not in out
    assert mutation.main(["--strict"]) == 1


def test_functions_without_mutants_pass(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stage(repo, MODULE.replace("x * 2", "x * 3"))
    monkeypatch.setenv("FAKE_NOTHING", "1")
    assert mutation.main([]) == 0
    assert "produce no mutants" in capsys.readouterr().out


def test_mutmut_failure_fails_the_run(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stage(repo, MODULE.replace("x * 2", "x * 3"))
    monkeypatch.setenv("FAKE_RUN_STATUS", "1")
    assert mutation.main([]) == 2
    assert "exited with status 1" in capsys.readouterr().err


def test_explicit_files_mutate_every_function_and_keep_leaves_the_workspace(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(repo)
    assert mutation.main(["--keep", "cveta2/mod.py"]) == 0
    run = _calls(repo)[0]
    assert sorted(run["args"][1:]) == sorted(  # type: ignore[index]
        [
            "cveta2.mod.x_alpha*",
            "cveta2.mod.x_beta*",
            "cveta2.mod.xǁBoxǁsize*",
        ]
    )
    workspace = Path(str(run["cwd"]))
    assert workspace.is_dir()
    assert "Workspace kept" in capsys.readouterr().out
    shutil.rmtree(workspace)


def test_explicit_file_outside_the_package_is_refused(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(repo)
    assert mutation.main(["pyproject.toml"]) == 2
    assert "is not a cveta2/ Python file" in capsys.readouterr().err


def test_a_deletion_only_hunk_selects_its_function(repo: Path) -> None:
    longer = MODULE.replace("    return x * 2\n", "    x = abs(x)\n    return x * 2\n")
    _stage(repo, longer)
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "two")
    _stage(repo, MODULE)  # removes `x = abs(x)` only
    lines = mutation.changed_lines("HEAD")["cveta2/mod.py"]
    names = [t.qualname for t in mutation.targets_for("cveta2/mod.py", MODULE, lines)]
    assert names == ["beta"]


def test_user_diff_prefix_configuration_cannot_hide_a_change(repo: Path) -> None:
    _git(repo, "config", "diff.noprefix", "true")
    _git(repo, "config", "diff.mnemonicPrefix", "true")
    _stage(repo, MODULE.replace("x * 2", "x * 3"))
    assert mutation.changed_lines("HEAD") == {"cveta2/mod.py": {6}}


def test_base_uses_the_merge_base_not_the_moving_branch_tip(repo: Path) -> None:
    _git(repo, "branch", "-q", "work")
    _stage(repo, MODULE.replace("x + 1", "x + 9"))
    _git(
        repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "main moves"
    )
    _git(repo, "checkout", "-q", "work")
    _stage(repo, MODULE.replace("x * 2", "x * 3"))
    # alpha changed only on the other branch; it must not count as changed here.
    assert mutation.changed_lines("main") == {"cveta2/mod.py": {6}}


def test_changes_no_unit_test_reaches_pass_unless_strict(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stage(repo, MODULE.replace("x * 2", "x * 3"))
    monkeypatch.setenv("FAKE_NO_TESTS", "1")
    assert mutation.main([]) == 0
    assert "No unit test exercises the changed functions" in capsys.readouterr().out
    assert mutation.main(["--strict"]) == 1


def test_no_selected_mutant_is_not_reported_as_all_killed(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stage(repo, MODULE.replace("x * 2", "x * 3"))
    monkeypatch.setenv("FAKE_RESULTS", "    cveta2.mod.x_beta_two__mutmut_1: killed")
    assert mutation.main([]) == 0
    out = capsys.readouterr().out
    assert "produce no mutants" in out
    assert "was killed" not in out


def test_a_path_outside_the_repository_is_refused(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert mutation.main([str(repo.parent / "elsewhere.py")]) == 2
    assert "is not a cveta2/ Python file" in capsys.readouterr().err


def test_a_custom_index_file_is_honoured(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A partial or `commit -a` commit hands hooks its own GIT_INDEX_FILE."""
    alternate = repo / ".git" / "alternate-index"
    shutil.copyfile(repo / ".git" / "index", alternate)
    (repo / "cveta2" / "mod.py").write_text(
        MODULE.replace("x * 2", "x * 3"), encoding="utf-8"
    )
    monkeypatch.setenv("GIT_INDEX_FILE", str(alternate))
    _git(repo, "add", "cveta2/mod.py")
    assert mutation.changed_lines("HEAD") == {"cveta2/mod.py": {6}}
    monkeypatch.delenv("GIT_INDEX_FILE")
    assert mutation.changed_lines("HEAD") == {}


def test_pytest_sessions_never_see_git_hook_variables() -> None:
    """tests.env_isolation strips GIT_* so throwaway repos never touch the real one.

    The pre-commit pytest hook runs with git's GIT_INDEX_FILE exported.
    """
    assert not [name for name in os.environ if name.startswith("GIT_")]


def test_unjudged_mutants_are_counted_not_reported_as_survivors(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stage(repo, MODULE.replace("x * 2", "x * 3"))
    monkeypatch.setenv(
        "FAKE_RESULTS",
        "    cveta2.mod.x_beta__mutmut_1: killed\n"
        "    cveta2.mod.x_beta__mutmut_2: not checked\n"
        "    cveta2.mod.x_beta__mutmut_3: no tests",
    )
    assert mutation.main(["--strict"]) == 0
    out = capsys.readouterr().out
    assert "survived: 0, not reached by tests: 1, not run (budget): 1" in out


def test_max_functions_limits_and_lists_the_rest(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(repo)
    assert mutation.main(["--max-functions", "1", "cveta2/mod.py"]) == 0
    run = _calls(repo)[0]
    assert len(run["args"][1:]) == 1  # type: ignore[index]
    out = capsys.readouterr().out
    assert "mutating 1 of 3 changed functions" in out


def test_the_budget_interrupts_mutmut_and_its_children(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    _stage(repo, MODULE.replace("x * 2", "x * 3"))
    child_pid_file = tmp_path / "child.pid"
    monkeypatch.setenv("FAKE_HANG", str(child_pid_file))
    monkeypatch.setenv("FAKE_RESULTS", "    cveta2.mod.x_beta__mutmut_1: not checked")
    started = time.monotonic()
    assert mutation.main(["--budget-seconds", "1"]) == 0
    assert time.monotonic() - started < 30
    out = capsys.readouterr().out
    assert "mutmut stopped after 1.0 s" in out
    assert "not run (budget): 1" in out
    child = int(child_pid_file.read_text())
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.kill(child, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        pytest.fail("mutmut's forked child outlived the budget")
