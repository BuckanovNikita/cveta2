#!/usr/bin/env bash
# Tear down one run of the integration stack: the leftover Compose project
# (volumes included), this run tag's project and cloud storage on the cluster
# CVAT, and the tests/integration/.run-tag file when it names this run.
#
# Usage:
#   ./scripts/integration_stop.sh
#
# The tag is INFRA_RUN_TAG when exported, the `cveta2-main` slot on main, else
# the one recorded by integration_up.sh. Compose goes first, so the containers
# are gone even when the CVAT step fails; that failure is still reported
# through the exit code, and the tag file stays so the retry finds the run.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/integration_env.sh
source "$SCRIPT_DIR/integration_env.sh"
integration_require_run_tag

log() { echo "==> $*"; }

# No compose file: docker compose finds containers, networks and volumes by
# their project label.
log "Stopping compose project $COMPOSE_PROJECT and removing volumes"
docker compose -p "$COMPOSE_PROJECT" down -v --remove-orphans

log "Removing '$INTEGRATION_RUN_TAG' data from CVAT organization $CVAT_INTEGRATION_ORG (project '$CVAT_INTEGRATION_PROJECT')"
cd "$INTEGRATION_REPO_ROOT"
if ! uv run python tests/integration/cvat_stand.py cleanup --tag "$INTEGRATION_RUN_TAG"; then
    echo "WARNING: compose stack is down, but the CVAT data of tag '$INTEGRATION_RUN_TAG' could not be removed." >&2
    echo "         Retry once the stand is reachable:" >&2
    echo "         uv run python tests/integration/cvat_stand.py cleanup --tag '$INTEGRATION_RUN_TAG'" >&2
    exit 1
fi
integration_release_run_tag
log "Done"
