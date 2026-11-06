#!/usr/bin/env python3
"""Run mutmut over [tool.mutmut].only_mutate and fail if a mutant escapes.

``mutmut run`` always exits 0 and has no threshold flag, so this gate builds the
verdict itself: ``mutmut export-cicd-stats`` writes the counters,
``mutmut results`` lists every mutant not conclusively killed, and survivors are
checked against the allowlist in ``[tool.cveta2.mutation.equivalent]``.

    uv run python scripts/mutation.py                     # whole scope, cache honoured
    uv run python scripts/mutation.py --profile fast      # the pre-commit subset
    uv run python scripts/mutation.py 'cveta2.domain.partition.*'
    uv run python scripts/mutation.py --max-children 4

Arguments other than ``--profile`` pass through to ``mutmut run``.

Profiles live in ``[tool.cveta2.mutation.profiles]``. An empty profile means
"run everything with no positional filter", which is not the same as passing
``"*"``: mutmut honours a cached verdict only when no mutant name is given
(``if not mutant_names and result is not None: continue``), so a ``"*"`` filter
would re-execute the entire scope on every run.

Scope fingerprint. ``Config.config_fingerprint()`` deliberately hashes only
pytest args, timeouts and the type-check command; ``only_mutate`` and
``do_not_mutate_patterns`` are excluded because mutmut assumes new mutants are
born uncached and dropped ones stop being walked. That breaks in both
directions: adding a file to ``only_mutate`` leaves the mutant tree stale
("0 files mutated, N unmodified", observed), and suppressing a call renumbers a
function's mutants so an old verdict re-attaches to a different mutation. Both
are silent, so ``mutants/`` is wiped whenever the scope fields change.

Allowlist. Both of mutmut's suppression mechanisms (``# pragma: no mutate`` and
``do_not_mutate_patterns``) key on the first line of the mutated node, so
neither can exempt one argument of a multi-line call without also dropping the
killable mutants that share that line. The allowlist works per mutant, and an
entry that no longer matches a live survivor is itself an error: a
justification cannot rot into a blanket pass. Under a profile the glob narrows
the allowlist as well as the survivors, because ``mutmut results`` walks every
file in ``only_mutate`` regardless of what the run filtered on.
"""

import argparse
import fnmatch
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"
MUTANTS_DIR = REPO_ROOT / "mutants"
FINGERPRINT_FILE = MUTANTS_DIR / ".cveta2-scope-fingerprint"
STATS_FILE = MUTANTS_DIR / "mutmut-cicd-stats.json"
RESULTS_FILE = MUTANTS_DIR / "mutmut-results.txt"
# Keep pytest's temp root inside this checkout. By default every run shares
# /tmp/pytest-of-$USER, and a concurrent session's cleanup can delete the
# `pytest-current` symlink out from under a mutant's forked child. The child
# then dies for reasons unrelated to the mutation, which mutmut reads as
# "killed" - the gate lying in the unsafe direction. tests.env_isolation gives
# each mutation child its own PID-based basetemp beneath this root.
PYTEST_TEMPROOT = MUTANTS_DIR / ".pytest-temproot"

# The mutmut settings that decide *which* mutants exist. A change to any of
# them invalidates the whole tree, not just one function's verdicts.
SCOPE_KEYS = ("only_mutate", "do_not_mutate", "do_not_mutate_patterns", "source_paths")
# `mutmut results` lists every mutant it did not conclusively kill. These
# statuses are benign; anything else means the mutation escaped the tests.
BENIGN_STATUSES = frozenset({"killed", "skipped", "caught by type check"})


class GateError(Exception):
    """A configuration or run failure that stops the gate before a verdict."""


def _load_pyproject() -> dict[str, object]:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def _tool_table(config: dict[str, object], *path: str) -> dict[str, object]:
    node: object = config
    for key in path:
        if not isinstance(node, dict):
            return {}
        node = node.get(key, {})
    return node if isinstance(node, dict) else {}


def profile_globs(name: str) -> list[str]:
    """Return the mutant-name globs of profile *name*."""
    profiles = _tool_table(_load_pyproject(), "tool", "cveta2", "mutation", "profiles")
    if name not in profiles:
        known = ", ".join(sorted(profiles)) or "(none defined)"
        msg = f"Unknown mutation profile {name!r}. Known profiles: {known}"
        raise GateError(msg)
    globs = profiles[name]
    if not isinstance(globs, list) or not all(isinstance(g, str) for g in globs):
        msg = f"Profile {name!r} must be a list of mutant-name glob strings."
        raise GateError(msg)
    return [str(g) for g in globs]


def scope_fingerprint() -> str:
    """Hash of the mutmut settings that decide which mutants exist."""
    mutmut_config = _tool_table(_load_pyproject(), "tool", "mutmut")
    scope = {key: mutmut_config.get(key) for key in SCOPE_KEYS}
    payload = json.dumps(scope, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def sync_scope() -> None:
    """Drop a stale mutant tree so the next run regenerates it from scratch."""
    current = scope_fingerprint()
    previous = (
        FINGERPRINT_FILE.read_text(encoding="utf-8").strip()
        if FINGERPRINT_FILE.is_file()
        else None
    )
    if previous == current:
        return
    if MUTANTS_DIR.exists():
        if previous is None:
            print("==> mutants/ has no scope fingerprint; regenerating from scratch.")
        else:
            print(
                f"==> Mutation scope changed ({previous} -> {current}); "
                "wiping mutants/."
            )
        shutil.rmtree(MUTANTS_DIR, ignore_errors=True)
    MUTANTS_DIR.mkdir(parents=True, exist_ok=True)
    FINGERPRINT_FILE.write_text(f"{current}\n", encoding="utf-8")


def _mutmut(*args: str) -> list[str]:
    return ["uv", "run", "mutmut", *args]


def run_mutmut(args: list[str]) -> int:
    """Run ``mutmut run``; strip the CR spinner when stdout is not a terminal.

    On a TTY the spinner renders fine. Captured (pre-commit), it would dump tens
    of thousands of redraw frames, so keep only what a terminal would have shown
    on each line.
    """
    command = _mutmut("run", *args)
    if sys.stdout.isatty():
        return subprocess.run(command, check=False, cwd=REPO_ROOT).returncode  # noqa: S603
    with subprocess.Popen(command, stdout=subprocess.PIPE, cwd=REPO_ROOT) as process:  # noqa: S603
        assert process.stdout is not None  # noqa: S101 - set by stdout=PIPE
        for raw in process.stdout:
            line = raw.decode("utf-8", errors="replace").rsplit("\r", 1)[-1]
            sys.stdout.write(line)
            sys.stdout.flush()
    return process.returncode


def _load_allowlist() -> dict[str, str]:
    table = _tool_table(_load_pyproject(), "tool", "cveta2", "mutation", "equivalent")
    return {str(name): str(reason) for name, reason in table.items()}


def _parse_results(results: str) -> dict[str, str]:
    statuses: dict[str, str] = {}
    for line in results.splitlines():
        name, separator, status = line.strip().partition(": ")
        if separator and name and not name.startswith("#"):
            statuses[name] = status
    return statuses


def _in_profile(name: str, globs: list[str]) -> bool:
    return not globs or any(fnmatch.fnmatch(name, glob) for glob in globs)


def _report_score(stats: dict[str, int], escaped: dict[str, str], profile: str) -> None:
    """Print the score, preferring profile-local numbers over mutmut's totals.

    mutmut's cicd stats always cover the whole ``only_mutate`` set and count
    not-checked mutants inside ``total``. Under a profile those totals describe
    a different population than the verdict below them, so report the filtered
    counts and keep the global figure only as context.
    """
    total = stats.get("total", 0)
    killed = stats.get("killed", 0)
    counts = ", ".join(
        f"{name}={stats.get(name, 0)}"
        for name in ("survived", "no_tests", "not_checked", "skipped", "timeout")
    )
    if profile:
        print(f"Profile '{profile}': {len(escaped)} mutant(s) not killed")
    score = f"{killed / total:.1%}" if total else "n/a"
    print(f"Mutation score (whole scope): {killed}/{total} killed ({score})")
    print(f"Breakdown: {counts}")


def verdict(
    stats: dict[str, int], results: str, globs: list[str], profile: str
) -> bool:
    """Print the gate verdict; True when no unexplained mutant escaped."""
    escaped = {
        name: status
        for name, status in _parse_results(results).items()
        if status not in BENIGN_STATUSES and _in_profile(name, globs)
    }
    allowlist = {
        name: reason
        for name, reason in _load_allowlist().items()
        if _in_profile(name, globs)
    }
    _report_score(stats, escaped, profile)

    unexplained = {n: s for n, s in escaped.items() if n not in allowlist}
    stale = [name for name in allowlist if name not in escaped]
    if allowlist:
        print(f"Allowlisted as equivalent: {len(allowlist) - len(stale)}")
    if stale:
        print(
            "FAILED: these [tool.cveta2.mutation.equivalent] entries no longer "
            "match a surviving mutant. mutmut renumbers mutants when a function "
            "changes, so re-review and update or drop them:"
        )
        for name in stale:
            print(f"    {name}")
    if unexplained:
        print(f"FAILED: {len(unexplained)} mutant(s) escaped the tests:")
        for name, status in sorted(unexplained.items()):
            print(f"    {name}: {status}")
    if stale or unexplained:
        return False
    print("No unexplained mutants escaped.")
    return True


def gate(profile: str | None, mutmut_args: list[str]) -> int:
    """Run the whole gate and return the process exit status."""
    globs: list[str] = []
    if profile is not None:
        # Resolve before touching the generated workspace: an unknown profile
        # must neither wipe mutants/ nor start an unfiltered mutation run.
        globs = profile_globs(profile)
    sync_scope()
    PYTEST_TEMPROOT.mkdir(parents=True, exist_ok=True)
    os.environ["PYTEST_DEBUG_TEMPROOT"] = str(PYTEST_TEMPROOT)

    status = run_mutmut([*mutmut_args, *globs])
    if status != 0:
        print(f"ERROR: mutmut run exited with status {status}.", file=sys.stderr)
        return status
    subprocess.run(_mutmut("export-cicd-stats"), check=True, cwd=REPO_ROOT)  # noqa: S603
    if not STATS_FILE.is_file():
        msg = f"{STATS_FILE} was not written; mutmut run produced no results."
        raise GateError(msg)
    results = subprocess.run(  # noqa: S603
        _mutmut("results"), check=True, stdout=subprocess.PIPE, text=True, cwd=REPO_ROOT
    ).stdout
    RESULTS_FILE.write_text(results, encoding="utf-8")

    stats = json.loads(STATS_FILE.read_text(encoding="utf-8"))
    if verdict(stats, results, globs, profile or ""):
        return 0
    print()
    print("==> Inspect a mutant with: uv run mutmut show <name>")
    print("==> Triage interactively with: uv run mutmut browse")
    print("==> A mutant no test can possibly kill belongs in")
    print("    [tool.cveta2.mutation.equivalent] in pyproject.toml, with a reason.")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Mutation gate: mutmut run plus an allowlist-aware verdict.",
        epilog="Other arguments pass through to `mutmut run`.",
    )
    parser.add_argument(
        "--profile", help="mutant-name globs from [tool.cveta2.mutation.profiles]"
    )
    args, mutmut_args = parser.parse_known_args(argv)
    try:
        return gate(args.profile, mutmut_args)
    except (GateError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
