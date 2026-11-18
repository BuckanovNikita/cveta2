#!/usr/bin/env bash
# Commit-hook entry for development verification.
# The full Task output goes to an ignored per-worktree log. A passing run prints
# the test selection summary; a failing run prints everything, as before.
# The log is informational: it never establishes that verification passed.
set -eu
cd "$(git rev-parse --show-toplevel)"
log=.cache/verify-last.log
mkdir -p .cache
status=0
uv run --locked task --exit-code verify >"$log" 2>&1 || status=$?
if [ "$status" -ne 0 ]; then
    cat -- "$log"
    exit "$status"
fi
# testmon reports what it selected; pytest's closing line carries the counts.
if ! grep -E '^(testmon: |=+ .+ in [0-9.]+s)' -- "$log"; then
    echo 'No pytest summary in the verify output.'
fi
printf 'Full verify output: %s\n' "$log"
