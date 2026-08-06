#!/usr/bin/env bash
# Run mutmut over the modules listed in [tool.mutmut].only_mutate and fail if
# any mutant is not killed.
#
# `mutmut run` always exits 0 and has no threshold flag, so the gate is built
# from `mutmut export-cicd-stats`, which writes mutants/mutmut-cicd-stats.json.
# Extra args are forwarded to `mutmut run`:
#
#   ./scripts/mutation_test.sh                       # everything in scope
#   ./scripts/mutation_test.sh 'cveta2.dataset_partition.*'
#   ./scripts/mutation_test.sh --max-children 4

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
STATS_FILE="$REPO_ROOT/mutants/mutmut-cicd-stats.json"

cd "$REPO_ROOT"

# mutmut draws a carriage-return spinner. On a TTY that renders fine; when the
# output is captured (pre-commit, CI) it would otherwise dump tens of thousands
# of redraw frames, so keep only what a terminal would have shown per line.
if [[ -t 1 ]]; then
    uv run mutmut run "$@"
else
    uv run mutmut run "$@" | sed -u 's/.*\r//'
fi
uv run mutmut export-cicd-stats

if [[ ! -f "$STATS_FILE" ]]; then
    echo "ERROR: $STATS_FILE was not written; mutmut run produced no results." >&2
    exit 1
fi

# Prints the human-readable summary and exits non-zero when any mutant
# escaped, so the pre-commit hook fails.
if uv run python "$SCRIPT_DIR/mutation_gate.py" "$STATS_FILE"; then
    exit 0
fi

echo
echo "==> Surviving mutants (see 'uv run mutmut show <name>' for the diff):"
uv run mutmut results
echo
echo "==> Triage interactively with: uv run mutmut browse"
exit 1
