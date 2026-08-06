#!/usr/bin/env python3
"""Turn mutmut's CI/CD stats JSON into a pass/fail verdict.

``mutmut run`` always exits 0, so ``scripts/mutation_test.sh`` calls this on
``mutants/mutmut-cicd-stats.json`` to decide whether the pre-commit hook fails.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# A mutant in any of these buckets was not conclusively killed by the tests.
ESCAPED_BUCKETS = ("survived", "timeout", "suspicious", "segfault")
# Reported but not fatal: mutmut found no test exercising the mutated code.
# `mutate_only_covered_lines = true` should keep these near zero.
INFORMATIONAL_BUCKETS = ("no_tests", "skipped")


def main(stats_path: Path) -> int:
    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    total = stats.get("total", 0)
    killed = stats.get("killed", 0)
    escaped = {name: stats.get(name, 0) for name in ESCAPED_BUCKETS}
    escaped_total = sum(escaped.values())

    score = f"{killed / total:.1%}" if total else "n/a"
    print(f"Mutation score: {killed}/{total} killed ({score})")

    informational = ", ".join(
        f"{name}={stats.get(name, 0)}" for name in INFORMATIONAL_BUCKETS
    )
    print(f"Not counted against the gate: {informational}")

    if escaped_total == 0:
        print("No mutants escaped.")
        return 0

    detail = ", ".join(f"{name}={count}" for name, count in escaped.items() if count)
    print(f"FAILED: {escaped_total} mutant(s) escaped ({detail})")
    return 1


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
