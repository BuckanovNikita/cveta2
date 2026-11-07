#!/usr/bin/env python3
"""Mutation-test only the functions a change touches, in a throwaway workspace.

    uv run python scripts/mutation.py                  # staged change vs HEAD
    uv run python scripts/mutation.py --base main      # staged tree vs main
    uv run python scripts/mutation.py cveta2/x.py      # every function of a file
    uv run python scripts/mutation.py --keep --strict  # keep it; fail on survivors
    uv run python scripts/mutation.py --budget-seconds 0 --max-functions 0  # no limits

The pre-commit hook runs the first form, within a budget: at most
``--max-functions`` (default 8) changed functions are mutated and the rest are
listed; mutmut stops after ``--budget-seconds`` (default 120), and mutants it
did not reach by then count as "not run", not as survivors. Changed lines of
staged ``cveta2/**/*.py`` files are mapped to the top-level functions and
methods that contain them, and mutmut runs only their mutants. The verdict is
advisory: surviving mutants are printed (the first few with diffs) and the run
passes, unless ``--strict`` is given. Mutants no unit test reaches are counted
separately. A tool, configuration or clean-test failure always fails.

Nothing is shared between runs. Each run exports the *staged* tree with
``git checkout-index`` into a fresh temporary directory, narrows that copy's
``[tool.mutmut].only_mutate`` to the changed files, and runs the repository
venv's ``mutmut`` there. No mutmut cache, scope fingerprint or pytest temp root
outlives the run, so concurrent runs from other worktrees or agents cannot
corrupt each other, and a stale verdict cannot be reused. The price is a fresh
stats pass (the whole unit suite, serially) on every run.

mutmut only mutates code inside undecorated top-level functions and methods
(a lone ``@staticmethod``/``@classmethod`` is allowed), never f-strings, and
skips lines matched by ``do_not_mutate_patterns``. A change outside those
produces no mutants, and a change no unit test reaches cannot be tested; both
are reported and pass.
"""

import argparse
import ast
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
from collections import deque
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE = "cveta2"
# `mutmut results` statuses that mean the mutant did not escape.
BENIGN_STATUSES = frozenset({"killed", "skipped", "caught by type check"})
# Statuses of mutants that were never judged: the budget ran out first, or no
# unit test reaches the line. Reported as counts, never as survivors.
UNRUN_STATUSES = frozenset({"not checked"})
UNREACHED_STATUSES = frozenset({"no tests"})
# mutmut asserts when a name filter matches no generated mutant.
NOTHING_MATCHES = "Filtered for specific mutants, but nothing matches"
# mutmut stops when no unit test reaches any mutated function at all.
NO_TESTS = "could not find any test case for any mutant"
# Live-stand variables an earlier `eval "$(lifecycle env)"` may have left in the
# shell. The unit suite must never see them: some fixtures switch to live CVAT.
STAND_PREFIXES = ("CVAT_INTEGRATION_", "MINIO_", "CLEARML_", "INTEGRATION_")
STAND_NAMES = frozenset({"INFRA_RUN_TAG"})
CLASS_SEPARATOR = "ǁ"
HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
MAX_DIFFS = 5
DEFAULT_MAX_FUNCTIONS = 8
DEFAULT_BUDGET_SECONDS = 120


class MutationError(Exception):
    """A tool or configuration failure: the run cannot produce a verdict."""


@dataclass(frozen=True)
class Target:
    """One mutable function and the mutmut names that select its mutants.

    ``names`` are mangled function names (``pkg.mod.x_func``). The run filter is
    ``<name>*`` rather than ``<name>__mutmut_*``: mutmut also matches the filter
    against mangled function names to pick the clean-run tests, and a pattern
    with the ``__mutmut_`` suffix matches none of them, which silently makes the
    clean run execute the whole suite. The wider glob can also run mutants of a
    function whose name extends this one; the report counts exact names only.
    """

    path: str
    qualname: str
    names: tuple[str, ...]

    @property
    def globs(self) -> tuple[str, ...]:
        """Return the ``mutmut run`` filters for this function."""
        return tuple(f"{name}*" for name in self.names)


def git(*args: str) -> str:
    """Run git in the repository and return stdout; a failure is a tool error."""
    completed = subprocess.run(  # noqa: S603 - fixed program, caller-built args
        ["git", *args],  # noqa: S607
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        msg = f"git {' '.join(args)} failed: {completed.stderr.strip()}"
        raise MutationError(msg)
    return completed.stdout


def changed_lines(base: str) -> dict[str, set[int]]:
    """Return staged ``cveta2`` Python files and their changed lines.

    The index is compared with the merge base of *base* and ``HEAD``, so a moving
    ``main`` does not count its own changes as this branch's. A deletion-only
    hunk marks the lines on both sides of the gap. The prefixes, quoting and
    external-diff options are pinned so that user git configuration cannot
    change the format this parser reads.
    """
    diff = git(
        "-c", "core.quotePath=false",
        "diff", "--cached", "--merge-base", "--unified=0", "--no-color",
        "--no-renames", "--no-ext-diff", "--no-textconv",
        "--src-prefix=a/", "--dst-prefix=b/",
        "--diff-filter=AM", base, "--", f"{PACKAGE}/*.py",
    )  # fmt: skip
    files: dict[str, set[int]] = {}
    current: str | None = None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            target = line[4:]
            if not target.startswith("b/"):
                msg = f"unexpected diff header {line!r}"
                raise MutationError(msg)
            current = target[2:]
            files.setdefault(current, set())
        elif current is not None and (match := HUNK.match(line)):
            start, count = int(match.group(1)), int(match.group(2) or "1")
            if count == 0:
                # `-U0` numbers a pure deletion by the line before the gap.
                files[current].update({max(start, 1), start + 1})
            else:
                files[current].update(range(start, start + count))
    return {path: lines for path, lines in files.items() if lines}


def _module_names(path: str) -> list[str]:
    parts = list(Path(path).with_suffix("").parts)
    names = [".".join(parts)]
    if parts[-1] == "__init__":
        names.append(".".join(parts[:-1]))
    return names


def _decorated_out(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Tell whether mutmut skips *node*: decorated, bar one static/classmethod."""
    if not node.decorator_list:
        return False
    if len(node.decorator_list) > 1:
        return True
    decorator = node.decorator_list[0]
    return not (isinstance(decorator, ast.Name) and decorator.id in {"staticmethod", "classmethod"})


def _span(node: ast.stmt) -> range:
    decorators = getattr(node, "decorator_list", [])
    first = min([node.lineno, *(d.lineno for d in decorators)])
    return range(first, (node.end_lineno or node.lineno) + 1)


def _functions(tree: ast.Module) -> Iterator[tuple[str, str, range]]:
    """Yield (qualname, mangled mutmut name, line span) of every mutable function."""
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            if not _decorated_out(node):
                yield node.name, f"x_{node.name}", _span(node)
        elif isinstance(node, ast.ClassDef) and not node.decorator_list:
            for member in node.body:
                if isinstance(member, ast.FunctionDef | ast.AsyncFunctionDef) and not _decorated_out(member):
                    yield (
                        f"{node.name}.{member.name}",
                        f"x{CLASS_SEPARATOR}{node.name}{CLASS_SEPARATOR}{member.name}",
                        _span(member),
                    )


def targets_for(path: str, source: str, lines: set[int] | None) -> list[Target]:
    """Return the mutable functions of *source* that contain any of *lines*."""
    tree = ast.parse(source, filename=path)
    found: list[Target] = []
    for qualname, mangled, span in _functions(tree):
        if lines is None or any(line in span for line in lines):
            names = tuple(f"{module}.{mangled}" for module in _module_names(path))
            found.append(Target(path, qualname, names))
    return found


def export_staged_tree(workspace: Path) -> None:
    """Write the index (exactly what a commit would contain) into *workspace*."""
    git("checkout-index", "--all", "--force", f"--prefix={workspace}{os.sep}")


def narrow_scope(pyproject: Path, files: Sequence[str]) -> None:
    """Point the workspace's ``[tool.mutmut]`` at *files* and nothing else."""
    text = pyproject.read_text(encoding="utf-8")
    header = re.search(r"^\[tool\.mutmut\]\s*$", text, flags=re.MULTILINE)
    if header is None:
        msg = "pyproject.toml has no [tool.mutmut] table."
        raise MutationError(msg)
    if re.search(r"^only_mutate\s*=", text, flags=re.MULTILINE):
        msg = "pyproject.toml sets [tool.mutmut].only_mutate; the scope is derived from the change, remove the setting."
        raise MutationError(msg)
    scope = ", ".join(json.dumps(name) for name in files)
    # Git change detection would compare against a repository this copy is not.
    addition = f"\nonly_mutate = [{scope}]\nuse_git_change_detection = false\n"
    pyproject.write_text(text[: header.end()] + addition + text[header.end() :], encoding="utf-8")


def child_env(workspace: Path) -> dict[str, str]:
    """Build mutmut's environment: no stand or git variables, a private temp root."""
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in STAND_NAMES
        and not key.startswith(STAND_PREFIXES)
        # git's hook variables (GIT_INDEX_FILE) point at the real repository.
        and not key.startswith("GIT_")
    }
    temproot = workspace / ".pytest-temproot"
    temproot.mkdir(parents=True, exist_ok=True)
    # Shared /tmp/pytest-of-$USER lets a concurrent session delete this run's
    # `pytest-current` link, which kills a mutant for unrelated reasons.
    env["PYTEST_DEBUG_TEMPROOT"] = str(temproot)
    return env


def mutmut_binary() -> Path:
    """Locate the repo venv's mutmut (``uv run`` in the copy builds a new venv)."""
    binary = Path(sys.executable).with_name("mutmut")
    if not binary.is_file():
        msg = f"{binary} not found; run this script with `uv run python`."
        raise MutationError(msg)
    return binary


BUDGET_GRACE_SECONDS = 15


def _stop_group(process: subprocess.Popen[bytes], spent: threading.Event) -> None:
    """Interrupt mutmut's whole process group, then kill what is left.

    mutmut forks one child per mutant and stops them only on KeyboardInterrupt,
    so the group gets SIGINT first; children still alive after the grace period
    (they hold the output pipe) get SIGKILL.
    """
    spent.set()
    try:
        os.killpg(process.pid, signal.SIGINT)
        process.wait(timeout=BUDGET_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        pass
    except ProcessLookupError:
        return
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return


def run_mutmut(
    binary: Path,
    workspace: Path,
    env: dict[str, str],
    args: Sequence[str],
    budget_seconds: float = 0,
) -> tuple[int | None, str]:
    """Stream ``mutmut run``; return its status (None: budget spent) and tail.

    Captured output (pre-commit) would otherwise hold every spinner redraw, so
    only what a terminal would have left on each line is printed. mutmut runs
    in its own session; with a budget, a timer interrupts that process group
    once the budget is spent, and the mutants judged so far keep their results.
    """
    tail: deque[str] = deque(maxlen=40)
    spent = threading.Event()
    with subprocess.Popen(  # noqa: S603 - the venv's own mutmut
        [str(binary), "run", *args],
        cwd=workspace,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    ) as process:
        timer = threading.Timer(budget_seconds, _stop_group, (process, spent)) if budget_seconds > 0 else None
        if timer is not None:
            timer.start()
        try:
            assert process.stdout is not None  # noqa: S101 - set by stdout=PIPE
            for raw in process.stdout:
                line = raw.decode("utf-8", errors="replace").rsplit("\r", 1)[-1]
                tail.append(line)
                sys.stdout.write(line)
                sys.stdout.flush()
        finally:
            if timer is not None:
                timer.cancel()
                timer.join()
    if spent.is_set() and process.returncode != 0:
        return None, "".join(tail)
    return process.returncode, "".join(tail)


def parse_results(text: str) -> dict[str, str]:
    """``name: status`` lines of ``mutmut results`` as a mapping."""
    statuses: dict[str, str] = {}
    for line in text.splitlines():
        name, separator, status = line.strip().partition(": ")
        if separator and name and not name.startswith("#"):
            statuses[name] = status
    return statuses


def _selected(mutant: str, functions: Iterable[str]) -> bool:
    return mutant.partition("__mutmut_")[0] in functions


class ShowFn:
    """``mutmut show`` in the workspace, as a callable."""

    def __init__(self, binary: Path, workspace: Path, env: dict[str, str]) -> None:
        """Bind the mutmut binary, workspace and environment of this run."""
        self.binary, self.workspace, self.env = binary, workspace, env

    def __call__(self, name: str) -> str:
        """Return the diff of mutant *name*."""
        completed = subprocess.run(  # noqa: S603 - the venv's own mutmut
            [str(self.binary), "show", name],
            cwd=self.workspace,
            env=self.env,
            check=False,
            capture_output=True,
            text=True,
        )
        return completed.stdout or f"# {name}: (no diff available)"


def report(
    statuses: dict[str, str],
    functions: Sequence[str],
    show: ShowFn,
) -> list[str]:
    """Print the verdict; return the names of mutants that escaped."""
    selected = {n: s for n, s in statuses.items() if _selected(n, functions)}
    if not selected:
        print("The changed functions produce no mutants; nothing to do.")
        return []
    judged = BENIGN_STATUSES | UNRUN_STATUSES | UNREACHED_STATUSES
    escaped = sorted(n for n, s in selected.items() if s not in judged)
    killed = sum(1 for s in selected.values() if s == "killed")
    unrun = sum(1 for s in selected.values() if s in UNRUN_STATUSES)
    unreached = sum(1 for s in selected.values() if s in UNREACHED_STATUSES)
    print(f"Mutants in changed functions: {len(selected)}, killed: {killed}, "
          f"survived: {len(escaped)}, not reached by tests: {unreached}, "
          f"not run (budget): {unrun}")  # fmt: skip
    if not escaped:
        print("No judged mutant of the changed functions survived.")
    for name in escaped[:MAX_DIFFS]:
        print()
        print(show(name).rstrip())
    if len(escaped) > MAX_DIFFS:
        print(f"... and {len(escaped) - MAX_DIFFS} more:")
        for name in escaped[MAX_DIFFS:]:
            print(f"    {name}: {selected[name]}")
    return escaped


def collect_targets(workspace: Path, base: str, files: Sequence[str]) -> list[Target]:
    """Targets from explicit *files* (whole files) or the staged diff."""
    scope: dict[str, set[int] | None]
    if files:
        scope = {}
        for name in files:
            resolved = Path(name).resolve()
            if not resolved.is_relative_to(REPO_ROOT):
                msg = f"{name} is not a {PACKAGE}/ Python file."
                raise MutationError(msg)
            relative = resolved.relative_to(REPO_ROOT).as_posix()
            if not relative.startswith(f"{PACKAGE}/") or not relative.endswith(".py"):
                msg = f"{name} is not a {PACKAGE}/ Python file."
                raise MutationError(msg)
            scope[relative] = None
    else:
        scope = dict(changed_lines(base))
    targets: list[Target] = []
    for path, lines in sorted(scope.items()):
        source_file = workspace / path
        if not source_file.is_file():
            msg = f"{path} is not in the index; stage it first."
            raise MutationError(msg)
        targets.extend(targets_for(path, source_file.read_text("utf-8"), lines))
    return targets


def limit_targets(targets: list[Target], limit: int) -> list[Target]:
    """Keep the first *limit* targets (0 keeps all) and list the others."""
    if not 0 < limit < len(targets):
        return targets
    print(f"Budget: mutating {limit} of {len(targets)} changed functions "
          "(--max-functions); not mutated:")  # fmt: skip
    for target in targets[limit:]:
        print(f"    {target.path}: {target.qualname}")
    return targets[:limit]


def run(args: argparse.Namespace) -> int:
    """Export, narrow, mutate, report. Returns the process exit status."""
    workspace = Path(tempfile.mkdtemp(prefix="cveta2-mutation-"))
    try:
        export_staged_tree(workspace)
        targets = collect_targets(workspace, args.base, args.files)
        if not targets:
            print("No changed cveta2 function can be mutated; nothing to do.")
            return 0
        targets = limit_targets(targets, args.max_functions)
        files = sorted({t.path for t in targets})
        globs = [glob for t in targets for glob in t.globs]
        print(f"Mutating {len(targets)} function(s) in {len(files)} file(s):")
        for target in targets:
            print(f"    {target.path}: {target.qualname}")
        narrow_scope(workspace / "pyproject.toml", files)

        binary = mutmut_binary()
        env = child_env(workspace)
        mutmut_args = [*(["--max-children", str(args.max_children)]
                         if args.max_children else []), *globs]  # fmt: skip
        status, tail = run_mutmut(binary, workspace, env, mutmut_args, args.budget_seconds)
        if status is None:
            print(f"Budget: mutmut stopped after {args.budget_seconds} s "
                  "(--budget-seconds); unjudged mutants count as not run.")  # fmt: skip
        elif status != 0:
            if NOTHING_MATCHES in tail:
                print("The changed functions produce no mutants; nothing to do.")
                return 0
            if NO_TESTS in tail:
                print("No unit test exercises the changed functions.")
                print("Advisory: add tests that call them.")
                return 1 if args.strict else 0
            msg = f"mutmut run exited with status {status} (output above)."
            raise MutationError(msg)
        results = subprocess.run(  # noqa: S603 - the venv's own mutmut
            [str(binary), "results", "--all", "true"],
            cwd=workspace,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        functions = [name for t in targets for name in t.names]
        escaped = report(parse_results(results), functions, ShowFn(binary, workspace, env))
        if not escaped:
            return 0
        print()
        print("Advisory: strengthen a test that should observe these mutations,")
        print("or leave them when the mutation cannot change observable behaviour.")
        return 1 if args.strict else 0
    finally:
        if args.keep:
            mutmut = Path(sys.executable).with_name("mutmut")
            print(f"Workspace kept: {workspace}")
            print(f"    cd there; {mutmut} show <name>  (or browse)")
        else:
            shutil.rmtree(workspace, ignore_errors=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Mutation-test the functions a change touches (advisory).",
    )
    parser.add_argument("files", nargs="*", help="cveta2/ files to mutate whole instead of the diff")
    parser.add_argument(
        "--base",
        default="HEAD",
        help="diff the staged tree against the merge base with REV (default HEAD)",
    )
    parser.add_argument("--keep", action="store_true", help="keep the workspace")
    parser.add_argument("--strict", action="store_true", help="exit 1 when a mutant survives")
    parser.add_argument("--max-children", type=int, help="mutmut worker count")
    parser.add_argument(
        "--max-functions",
        type=int,
        default=DEFAULT_MAX_FUNCTIONS,
        help="mutate at most N changed functions, 0 for all (default %(default)s)",
    )
    parser.add_argument(
        "--budget-seconds",
        type=float,
        default=DEFAULT_BUDGET_SECONDS,
        help="stop mutmut after N seconds, 0 for no limit (default %(default)s)",
    )
    args = parser.parse_args(argv)
    try:
        return run(args)
    except (MutationError, subprocess.CalledProcessError, SyntaxError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
