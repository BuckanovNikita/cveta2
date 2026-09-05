#!/usr/bin/env bash
# Tear down one run of the integration tests: this run tag's project and
# cloud storage on the cluster CVAT, its bucket on the shared MinIO, and the
# tests/integration/.run-tag file when it names this run.
#
# Usage:
#   ./scripts/integration_stop.sh
#
# The tag is INFRA_RUN_TAG when exported, the `cveta2-main` slot on main, else
# the one recorded by integration_up.sh. CVAT goes first, because its cloud
# storage points at the bucket; a failure on either stand is still reported
# through the exit code, and the tag file stays so the retry finds the run.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/integration_env.sh
source "$SCRIPT_DIR/integration_env.sh"
integration_require_run_tag

log() { echo "==> $*"; }

cd "$INTEGRATION_REPO_ROOT"
FAILED=0

log "Removing '$INTEGRATION_RUN_TAG' data from CVAT organization $CVAT_INTEGRATION_ORG (project '$CVAT_INTEGRATION_PROJECT')"
if ! uv run python tests/integration/cvat_stand.py cleanup --tag "$INTEGRATION_RUN_TAG"; then
    echo "WARNING: the CVAT data of tag '$INTEGRATION_RUN_TAG' could not be removed." >&2
    echo "         Retry once the stand is reachable:" >&2
    echo "         uv run python tests/integration/cvat_stand.py cleanup --tag '$INTEGRATION_RUN_TAG'" >&2
    FAILED=1
fi

log "Removing bucket '$MINIO_BUCKET' of '$INTEGRATION_RUN_TAG' from MinIO at $MINIO_ENDPOINT"
if ! integration_helper minio cleanup --prefix "$INTEGRATION_RUN_TAG"; then
    echo "WARNING: bucket '$MINIO_BUCKET' could not be removed." >&2
    echo "         Retry once the stand is reachable:" >&2
    echo "         python3 \"$INTEGRATION_SKILL_DIR/scripts/minio.py\" --project $INTEGRATION_PROJECT cleanup --prefix '$INTEGRATION_RUN_TAG'" >&2
    FAILED=1
fi

if (( FAILED )); then
    echo "ERROR: run '$INTEGRATION_RUN_TAG' is not fully torn down; the .run-tag file stays for the retry." >&2
    exit 1
fi
integration_release_run_tag
log "Done"
