#!/usr/bin/env bash
# Run integration tests against the CVAT + MinIO stack started by integration_up.sh.
#
# Sets all required env vars (ports, credentials, xdist override) so you
# don't have to remember them. Extra pytest args are forwarded as-is:
#
#   ./scripts/integration_test.sh -k upload
#   ./scripts/integration_test.sh -x --tb=long

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

export CVAT_INTEGRATION_HOST="${CVAT_INTEGRATION_HOST:-http://localhost:${CVAT_PORT:-9988}}"
export MINIO_ENDPOINT="${MINIO_ENDPOINT:-http://localhost:${MINIO_PORT:-9989}}"
export AWS_ACCESS_KEY_ID=minioadmin
export AWS_SECRET_ACCESS_KEY=minioadmin

CLEARML_API_URL="http://localhost:${CLEARML_API_PORT:-8880}"
if curl -sf "$CLEARML_API_URL/debug.ping" > /dev/null 2>&1; then
    export CLEARML_API_HOST="$CLEARML_API_URL"
    export CLEARML_WEB_HOST="http://localhost:${CLEARML_WEB_PORT:-8882}"
    export CLEARML_FILES_HOST="http://localhost:${CLEARML_FILES_PORT:-8881}"
    export CLEARML_API_ACCESS_KEY="EGRTCO8JMSIGI6S39GTP43NFWXDQOW"
    export CLEARML_API_SECRET_KEY="LPEJbGJ6bK4tujQcmrD3i1dbMBDdwUwelVa-LG0K0FFmY9bzH_H0Sw"
    CLEARML_STATUS="$CLEARML_API_HOST"
else
    CLEARML_STATUS="not running (ClearML tests will be skipped)"
fi

echo "==> CVAT:    $CVAT_INTEGRATION_HOST"
echo "==> MinIO:   $MINIO_ENDPOINT"
echo "==> ClearML: $CLEARML_STATUS"
echo "==> Running pytest (xdist disabled for CVAT rate limits)"

cd "$REPO_ROOT"
# Repeats every addopts entry from pyproject.toml except "-n auto". Dropping
# xdist is the point of the override; dropping "-p tests.env_isolation" with it
# would let the suite read and write the developer's real ~/.config/cveta2/.
uv run pytest -o 'addopts=-v --tb=short -p tests.env_isolation' "$@"
