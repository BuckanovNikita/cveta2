#!/usr/bin/env bash
# Pre-push gate: run tests/integration against a freshly prepared stack, on
# the machines that are set up for it.
#
# The gate arms itself on tests/integration/.env - the same gitignored file every
# integration script hard-requires, so "this machine has an .env" and "this
# machine was set up for integration tests" are the same statement. A missing
# .env is the ONLY silent skip: once armed, the gate passes, fails, or is skipped
# on purpose. A gate that quietly passes because docker or the CVAT stand is
# down is worse than no gate, because it teaches everyone to ignore it.
#
#   ./scripts/integration_gate.sh                # what the hook runs
#   ./scripts/integration_gate.sh -k upload      # extra args go to pytest
#   ./scripts/integration_gate.sh --keep-stack   # leave the stack up on failure
#
# What happens to the run's data afterwards depends on the branch:
#   - main (a push of refs/heads/main, or main checked out): everything stays -
#     the MinIO/ClearML stack and the "<tag> coco8-dev" project on the stand -
#     so the last main run can be inspected in the CVAT UI. The next main run
#     replaces it.
#   - any other branch: stack and CVAT data are removed.
#   INTEGRATION_KEEP_DATA=1 / =0 overrides that decision.
#
# Skip it for one push (mutmut-full still runs):
#   SKIP=integration-tests git push

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$REPO_ROOT/tests/integration/.env"

KEEP_STACK=0
PYTEST_ARGS=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --keep-stack)
            KEEP_STACK=1
            shift
            ;;
        *)
            PYTEST_ARGS+=("$1")
            shift
            ;;
    esac
done

log() { echo "==> $*"; }

if [[ ! -f "$ENV_FILE" ]]; then
    log "integration gate skipped: no tests/integration/.env on this machine"
    log "    arm it with: cp tests/integration/.env.example tests/integration/.env"
    exit 0
fi

# shellcheck source=scripts/integration_env.sh
source "$SCRIPT_DIR/integration_env.sh"

if ! docker info > /dev/null 2>&1; then
    echo "ERROR: the integration gate is armed (tests/integration/.env exists)" >&2
    echo "       but the docker daemon is not reachable." >&2
    echo "       Start docker, or push without this gate:" >&2
    echo "           SKIP=integration-tests git push" >&2
    exit 1
fi

if ! curl -sf "$CVAT_INTEGRATION_HOST/api/server/about" > /dev/null 2>&1; then
    echo "ERROR: the integration gate is armed (tests/integration/.env exists)" >&2
    echo "       but the CVAT stand at $CVAT_INTEGRATION_HOST does not answer." >&2
    echo "       Deploy it (k8s-infra skill: cvat-stand/deploy_cvat.sh), or push without this gate:" >&2
    echo "           SKIP=integration-tests git push" >&2
    exit 1
fi

keep_data() {
    case "${INTEGRATION_KEEP_DATA:-}" in
        1) return 0 ;;
        0) return 1 ;;
    esac
    integration_on_main
}

cd "$REPO_ROOT"

# Fresh state comes from integration_up.sh: it wipes this tag's previous
# project on the stand and recreates MinIO/ClearML, so the upload tests never
# meet their own leftovers ("Duplicate base task name").
#
# The trap is armed only here, past the skip and the preflight, so a run that
# never prepared a stack cannot tear one down.
teardown() {
    local rc=$?
    if keep_data; then
        log "keeping the run for inspection (main):"
        log "    CVAT:  $CVAT_INTEGRATION_HOST  organization $CVAT_INTEGRATION_ORG, project '$CVAT_INTEGRATION_PROJECT'"
        log "    MinIO/ClearML compose project $COMPOSE_PROJECT stays up"
        log "    remove both with ./scripts/integration_stop.sh"
        return
    fi
    if [[ $rc -ne 0 && $KEEP_STACK -eq 1 ]]; then
        log "leaving the stack up for triage (--keep-stack);"
        log "    stop it with ./scripts/integration_stop.sh"
        return
    fi
    log "tearing down the integration stack"
    "$SCRIPT_DIR/integration_stop.sh" || true
}
trap teardown EXIT

log "integration gate: preparing the stack (tag '$INTEGRATION_RUN_TAG')"
"$SCRIPT_DIR/integration_up.sh"

# Scoped to tests/integration rather than the whole suite: CVAT_INTEGRATION_HOST
# also adds a `live-cvat` parameter to the coco8_fixtures session fixture, which
# re-runs a large slice of the unit tests against live CVAT - serially, since
# xdist is off here. That re-run is worth doing by hand, not on every push.
log "integration gate: running tests/integration"
if "$SCRIPT_DIR/integration_test.sh" tests/integration "${PYTEST_ARGS[@]}"; then
    log "integration gate: passed"
    exit 0
fi

echo >&2
echo "==> integration gate FAILED. Reproduce and triage with:" >&2
echo "      ./scripts/integration_up.sh" >&2
echo "      ./scripts/integration_test.sh tests/integration -x --tb=long" >&2
echo "      ./scripts/integration_stop.sh" >&2
echo "==> To push without this gate (mutmut-full still runs):" >&2
echo "      SKIP=integration-tests git push" >&2
exit 1
