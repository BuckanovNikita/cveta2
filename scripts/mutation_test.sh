#!/usr/bin/env bash
# Run mutmut over the modules listed in [tool.mutmut].only_mutate and fail if
# any mutant is not killed.
#
# `mutmut run` always exits 0 and has no threshold flag, so the gate is built
# from `mutmut export-cicd-stats`, which writes mutants/mutmut-cicd-stats.json.
#
#   ./scripts/mutation_test.sh                       # whole scope, cache honoured
#   ./scripts/mutation_test.sh --profile fast        # only the pre-commit subset
#   ./scripts/mutation_test.sh 'cveta2.dataset_partition.*'
#   ./scripts/mutation_test.sh --max-children 4
#
# Profiles live in [tool.cveta2.mutation.profiles]. An empty profile means "run
# everything with no positional filter", which is not the same as passing '*':
# mutmut reuses a cached verdict only when no mutant name is given, so a '*'
# filter would re-execute the entire scope on every run.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
STATS_FILE="$REPO_ROOT/mutants/mutmut-cicd-stats.json"
RESULTS_FILE="$REPO_ROOT/mutants/mutmut-results.txt"

cd "$REPO_ROOT"

# Keep pytest's temp root inside this checkout. By default every run shares
# /tmp/pytest-of-$USER, and a concurrent session's cleanup can delete the
# `pytest-current` symlink out from under a mutant's forked child. The child
# then dies for reasons unrelated to the mutation, which mutmut reads as
# "killed" - the gate lying in the unsafe direction. tests.env_isolation gives
# each mutation child its own PID-based basetemp beneath this root, avoiding
# races in pytest's numbered-directory cleanup between forked children.
# Created after sync-scope below, which may wipe mutants/ wholesale.
export PYTEST_DEBUG_TEMPROOT="$REPO_ROOT/mutants/.pytest-temproot"

PROFILE=""
PROFILE_SET=0
MUTMUT_ARGS=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --profile)
            PROFILE_SET=1
            PROFILE="$2"
            shift 2
            ;;
        --profile=*)
            PROFILE_SET=1
            PROFILE="${1#*=}"
            shift
            ;;
        *)
            MUTMUT_ARGS+=("$1")
            shift
            ;;
    esac
done

GATE_ARGS=()
if [[ "$PROFILE_SET" -eq 1 ]]; then
    # Command substitution preserves the resolver's exit status under set -e.
    # Process substitution would hide it and start an unfiltered mutation run.
    PROFILE_GLOBS=$(uv run python "$SCRIPT_DIR/mutation_config.py" globs --profile "$PROFILE")
    GATE_ARGS+=(--profile "$PROFILE")
    while IFS= read -r glob; do
        [[ -n "$glob" ]] || continue
        MUTMUT_ARGS+=("$glob")
        GATE_ARGS+=(--glob "$glob")
    done <<< "$PROFILE_GLOBS"
fi

# Validate the profile before changing the generated workspace.
# Drops a stale mutant tree when only_mutate / do_not_mutate_patterns changed.
uv run python "$SCRIPT_DIR/mutation_config.py" sync-scope
mkdir -p "$PYTEST_DEBUG_TEMPROOT"

# mutmut draws a carriage-return spinner. On a TTY that renders fine; when the
# output is captured (pre-commit, CI) it would otherwise dump tens of thousands
# of redraw frames, so keep only what a terminal would have shown per line.
if [[ -t 1 ]]; then
    uv run mutmut run "${MUTMUT_ARGS[@]}"
else
    uv run mutmut run "${MUTMUT_ARGS[@]}" | sed -u 's/.*\r//'
fi
uv run mutmut export-cicd-stats

if [[ ! -f "$STATS_FILE" ]]; then
    echo "ERROR: $STATS_FILE was not written; mutmut run produced no results." >&2
    exit 1
fi

uv run mutmut results > "$RESULTS_FILE"

# Prints the summary and exits non-zero when a mutant escaped without a
# justification, so the pre-commit hook fails.
if uv run python "$SCRIPT_DIR/mutation_gate.py" \
    "$STATS_FILE" "$RESULTS_FILE" "$REPO_ROOT/pyproject.toml" "${GATE_ARGS[@]}"; then
    exit 0
fi

echo
echo "==> Inspect a mutant with: uv run mutmut show <name>"
echo "==> Triage interactively with: uv run mutmut browse"
echo "==> A mutant no test can possibly kill belongs in"
echo "    [tool.cveta2.mutation.equivalent] in pyproject.toml, with a reason."
exit 1
