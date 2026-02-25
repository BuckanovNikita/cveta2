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

export CVAT_INTEGRATION_HOST="http://localhost:9988"
export MINIO_ENDPOINT="http://localhost:9989"
export AWS_ACCESS_KEY_ID=minioadmin
export AWS_SECRET_ACCESS_KEY=minioadmin

echo "==> CVAT:  $CVAT_INTEGRATION_HOST"
echo "==> MinIO: $MINIO_ENDPOINT"
echo "==> Running pytest (xdist disabled for CVAT rate limits)"

cd "$REPO_ROOT"
uv run pytest -o 'addopts=-v --tb=short' "$@"
