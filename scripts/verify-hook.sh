#!/usr/bin/env bash
# Commit-hook entry for development verification.
# The full Task output goes to an ignored per-worktree log. A passing run prints
# the test selection summary; a failing run prints everything, as before.
# The log is informational: it never establishes that verification passed.
set -eu
cd "$(git rev-parse --show-toplevel)"
mkdir -p .cache
# Each run writes its own file, so an overlapping run cannot mix into this summary.
log=$(mktemp .cache/verify-run.XXXXXX)
trap 'rm -f -- "$log"' EXIT
printf 'verify at %s, HEAD %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$(git rev-parse --short HEAD 2>/dev/null || echo unborn)" >"$log"
status=0
uv run --locked task --exit-code verify >>"$log" 2>&1 || status=$?
if [ "$status" -ne 0 ]; then
    cat -- "$log"
    exit "$status"
fi
# testmon reports the files it compared, xdist the number of selected tests and
# pytest's closing line the results. testmon drops unaffected tests before
# collection, so no deselected count exists to print. The patterns are not
# anchored, because a forced colour mode puts escape codes before them.
if ! grep -E '(testmon: |[0-9]+ workers \[[0-9]+ items\]|=+ .+ in [0-9.]+s)' -- "$log"; then
    echo 'No pytest summary in the verify output.'
fi
mv -f -- "$log" .cache/verify-last.log
trap - EXIT
printf 'Full verify output: %s\n' .cache/verify-last.log
