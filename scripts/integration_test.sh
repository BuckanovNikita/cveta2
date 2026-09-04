#!/usr/bin/env bash
# Run integration tests against the stack prepared by integration_up.sh:
# this run's project on the cluster CVAT, MinIO + ClearML in Docker Compose.
#
# Sets all required env vars (stand credentials, organization, project name,
# ports, xdist override) so you don't have to remember them. Extra pytest
# args are forwarded as-is:
#
#   ./scripts/integration_test.sh -k upload
#   ./scripts/integration_test.sh -x --tb=long
#
# The same INTEGRATION_USER / MINIO_PORT / CLEARML_*_PORT values that were
# given to integration_up.sh must be in the environment here too.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/integration_env.sh
source "$SCRIPT_DIR/integration_env.sh"

export AWS_ACCESS_KEY_ID="$MINIO_ROOT_USER"
export AWS_SECRET_ACCESS_KEY="$MINIO_ROOT_PASSWORD"

CLEARML_API_URL="http://localhost:${CLEARML_API_PORT}"
if curl -sf "$CLEARML_API_URL/debug.ping" > /dev/null 2>&1; then
    export CLEARML_API_HOST="$CLEARML_API_URL"
    export CLEARML_WEB_HOST="http://localhost:${CLEARML_WEB_PORT}"
    export CLEARML_FILES_HOST="http://localhost:${CLEARML_FILES_PORT}"
    export CLEARML_API_ACCESS_KEY="EGRTCO8JMSIGI6S39GTP43NFWXDQOW"
    export CLEARML_API_SECRET_KEY="LPEJbGJ6bK4tujQcmrD3i1dbMBDdwUwelVa-LG0K0FFmY9bzH_H0Sw"
    CLEARML_STATUS="$CLEARML_API_HOST"
else
    CLEARML_STATUS="not running (ClearML tests will be skipped)"
fi

echo "==> CVAT:    $CVAT_INTEGRATION_HOST  (org $CVAT_INTEGRATION_ORG, project '$CVAT_INTEGRATION_PROJECT')"
echo "==> MinIO:   $MINIO_ENDPOINT"
echo "==> ClearML: $CLEARML_STATUS"
echo "==> Running pytest (xdist disabled for CVAT rate limits)"

cd "$INTEGRATION_REPO_ROOT"
# Repeats every addopts entry from pyproject.toml except "-n auto". Dropping
# xdist is the point of the override; dropping "-p tests.env_isolation" with it
# would let the suite read and write the developer's real ~/.config/cveta2/.
uv run pytest -o 'addopts=-v --tb=short -p tests.env_isolation' "$@"
