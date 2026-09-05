#!/usr/bin/env bash
# Run integration tests against the run prepared by integration_up.sh: this
# run's project on the cluster CVAT, its bucket on the shared MinIO, and the
# shared ClearML stand.
#
# Every variable the tests read (stand credentials, organization, project
# name, bucket, the CLEARML_* identity) is exported by integration_env.sh, so
# there is nothing to remember. Extra pytest args are forwarded as-is:
#
#   ./scripts/integration_test.sh -k upload
#   ./scripts/integration_test.sh -x --tb=long
#
# The run tag is INFRA_RUN_TAG when exported, else the one integration_up.sh
# recorded in tests/integration/.run-tag.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/integration_env.sh
source "$SCRIPT_DIR/integration_env.sh"
integration_require_run_tag

echo "==> CVAT:    $CVAT_INTEGRATION_HOST  (org $CVAT_INTEGRATION_ORG, project '$CVAT_INTEGRATION_PROJECT')"
echo "==> MinIO:   $MINIO_ENDPOINT  (bucket $MINIO_BUCKET)"
echo "==> ClearML: $CLEARML_API_HOST  (the shared stand)"
echo "==> Running pytest (xdist disabled for CVAT rate limits)"

cd "$INTEGRATION_REPO_ROOT"
# Repeats every addopts entry from pyproject.toml except "-n auto". Dropping
# xdist is the point of the override; dropping "-p tests.env_isolation" with it
# would let the suite read and write the developer's real ~/.config/cveta2/.
uv run pytest -o 'addopts=-v --tb=short -p tests.env_isolation' "$@"
