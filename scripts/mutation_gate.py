#!/usr/bin/env python3
"""Turn mutmut's results into a pass/fail verdict for the pre-commit hook.

``mutmut run`` always exits 0, so ``scripts/mutation_test.sh`` calls this to
decide whether the run passed.

Mutants listed under ``[tool.cveta2.mutation.equivalent]`` in pyproject.toml are
subtracted from the survivor set. Both of mutmut's own suppression mechanisms
(``# pragma: no mutate`` and ``do_not_mutate_patterns``) key on the first line
of the mutated node, so neither can exempt a single argument of a multi-line
call without also dropping the killable mutants that share that line. The
allowlist works per mutant instead, and an entry that no longer matches a live
survivor is itself an error - a justification cannot rot into a blanket pass.

When a profile restricts the run to some of the mutants, ``--glob`` narrows the
verdict to match. It must narrow the allowlist as well as the survivors:
``mutmut results`` walks every file in ``only_mutate`` regardless of what the
run filtered on, so filtering survivors alone would leave every out-of-profile
allowlist entry looking stale and fail the hook for no reason.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import sys
import tomllib
from pathlib import Path

# `mutmut results` lists every mutant it did not conclusively kill. These
# statuses are benign; anything else means the mutation escaped the tests.
BENIGN_STATUSES = frozenset({"killed", "skipped", "caught by type check"})


def _load_allowlist(pyproject: Path) -> dict[str, str]:
    config = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    tool = config.get("tool", {}).get("cveta2", {}).get("mutation", {})
    allowlist: dict[str, str] = tool.get("equivalent", {})
    return allowlist


def _parse_results(results: str) -> dict[str, str]:
    statuses: dict[str, str] = {}
    for line in results.splitlines():
        name, separator, status = line.strip().partition(": ")
        if separator and name and not name.startswith("#"):
            statuses[name] = status
    return statuses


def _in_profile(name: str, globs: list[str]) -> bool:
    return not globs or any(fnmatch.fnmatch(name, glob) for glob in globs)


def _report_score(stats_path: Path, escaped: dict[str, str], profile: str) -> None:
    """Print the score, preferring profile-local numbers over mutmut's totals.

    mutmut's cicd stats always cover the whole ``only_mutate`` set and count
    not-checked mutants inside ``total``. Under a profile those totals describe
    a different population than the verdict below them, so report the filtered
    counts and keep the global figure only as context.
    """
    stats = json.loads(stats_path.read_text(encoding="utf-8"))
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gate a mutmut run.")
    parser.add_argument("stats", type=Path, help="mutmut-cicd-stats.json")
    parser.add_argument("results", type=Path, help="output of `mutmut results`")
    parser.add_argument(
        "pyproject", type=Path, help="pyproject.toml with the allowlist"
    )
    parser.add_argument(
        "--glob",
        action="append",
        default=[],
        dest="globs",
        help="restrict the verdict to matching mutant names (repeatable)",
    )
    parser.add_argument(
        "--profile", default="", help="profile name, for reporting only"
    )
    args = parser.parse_args(argv)

    statuses = _parse_results(args.results.read_text(encoding="utf-8"))
    escaped = {
        name: status
        for name, status in statuses.items()
        if status not in BENIGN_STATUSES and _in_profile(name, args.globs)
    }
    allowlist = {
        name: reason
        for name, reason in _load_allowlist(args.pyproject).items()
        if _in_profile(name, args.globs)
    }

    _report_score(args.stats, escaped, args.profile)

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
        return 1
    print("No unexplained mutants escaped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
