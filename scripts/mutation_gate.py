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
"""

from __future__ import annotations

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


def _report_score(stats_path: Path) -> None:
    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    total = stats.get("total", 0)
    killed = stats.get("killed", 0)
    score = f"{killed / total:.1%}" if total else "n/a"
    print(f"Mutation score: {killed}/{total} killed ({score})")
    counts = ", ".join(
        f"{name}={stats.get(name, 0)}"
        for name in ("survived", "no_tests", "skipped", "timeout", "suspicious")
    )
    print(f"Breakdown: {counts}")


def main(stats_path: Path, results_path: Path, pyproject: Path) -> int:
    _report_score(stats_path)

    statuses = _parse_results(results_path.read_text(encoding="utf-8"))
    escaped = {
        name: status
        for name, status in statuses.items()
        if status not in BENIGN_STATUSES
    }
    allowlist = _load_allowlist(pyproject)

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
    sys.exit(main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])))
