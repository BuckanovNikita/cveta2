#!/usr/bin/env bash
# Stop the CVAT + MinIO integration stack started by integration_up.sh.
#
# Usage:
#   ./scripts/stop_integration.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

CVAT_SUBMODULE="$REPO_ROOT/vendor/cvat"
ENV_FILE="$REPO_ROOT/tests/integration/.env"
OVERRIDE_FILE="$REPO_ROOT/tests/integration/docker-compose.override.yml"

INTEGRATION_USER=$(printf '%s' "${USER:-default}" | sed 's/[^a-zA-Z0-9_.-]/_/g')
INTEGRATION_USER="${INTEGRATION_USER:-default}"
export INTEGRATION_USER

compose() {
  docker compose \
    --project-directory "$CVAT_SUBMODULE" \
    -p "${INTEGRATION_USER}-cvat" \
    -f "$CVAT_SUBMODULE/docker-compose.yml" \
    -f "$OVERRIDE_FILE" \
    --env-file "$ENV_FILE" \
    "$@"
}

log() { echo "==> $*"; }

log "Stopping CVAT stack (project: ${INTEGRATION_USER}-cvat) and removing volumes"
compose down -v --remove-orphans
log "Done"
