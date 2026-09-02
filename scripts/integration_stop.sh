#!/usr/bin/env bash
# Stop the CVAT + MinIO integration stack started by integration_up.sh.
#
# Usage:
#   ./scripts/integration_stop.sh

set -euo pipefail

INTEGRATION_USER=$(printf '%s' "${INTEGRATION_USER:-${USER:-default}}" | sed 's/[^a-zA-Z0-9_.-]/_/g')

log() { echo "==> $*"; }

# No compose files: docker compose finds the containers, networks and volumes by
# their project label, so teardown works whichever CVAT version started them and
# needs nothing downloaded.
log "Stopping CVAT stack (project: ${INTEGRATION_USER}-cvat) and removing volumes"
docker compose -p "${INTEGRATION_USER}-cvat" down -v --remove-orphans
log "Done"
