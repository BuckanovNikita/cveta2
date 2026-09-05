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
#
# The ClearML stand is checked first: `clearml.py --project cveta2 whoami`
# must authenticate as the cveta2 identity, or nothing runs. There is no soft
# path that skips the ClearML tests when the stand is down - a machine armed
# for integration tests fails, it never quietly passes. The tests need the SDK,
# which is the optional `clearml` extra; `uv run --extra clearml` adds it to
# the project environment (a plain `uv sync` removes it again).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/integration_env.sh
source "$SCRIPT_DIR/integration_env.sh"
integration_require_run_tag

echo "==> ClearML: $CLEARML_API_HOST  (the shared stand)"
if ! integration_helper clearml whoami; then
    echo "ERROR: the ClearML stand does not authenticate the cveta2 identity" >&2
    echo "       (clearml.py --project $INTEGRATION_PROJECT whoami failed, see above)." >&2
    echo "       Diagnose the stand and the Secret with the k8s-infra skill;" >&2
    echo "       the ClearML tests are never skipped on an armed machine." >&2
    exit 1
fi

echo "==> CVAT:    $CVAT_INTEGRATION_HOST  (org $CVAT_INTEGRATION_ORG, project '$CVAT_INTEGRATION_PROJECT')"
echo "==> MinIO:   $MINIO_ENDPOINT  (bucket $MINIO_BUCKET)"
echo "==> Running pytest (xdist disabled for CVAT rate limits)"

cd "$INTEGRATION_REPO_ROOT"
# Repeats every addopts entry from pyproject.toml except "-n auto". Dropping
# xdist is the point of the override; dropping "-p tests.env_isolation" with it
# would let the suite read and write the developer's real ~/.config/cveta2/.
uv run --extra clearml pytest -o 'addopts=-v --tb=short -p tests.env_isolation' "$@"
