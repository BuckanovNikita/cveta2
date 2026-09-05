#!/usr/bin/env bash
# Prepare one run of the integration tests.
#
# CVAT, MinIO and ClearML are the shared stands in the local Kubernetes
# cluster (k8s-infra skill); this script never starts or stops them and runs
# nothing on this host. It acts as project `cveta2` under one run tag
# (scripts/integration_env.sh):
#
#   1. the run tag             INFRA_RUN_TAG when exported; `cveta2-main` on
#                              main; otherwise a fresh tag from
#                              `infra.py newtag --project cveta2 --slug integration`,
#                              recorded in tests/integration/.run-tag. An
#                              existing file means a run is active: stop it,
#                              or export INFRA_RUN_TAG to adopt it.
#   2. cvat_stand.py verify   the cveta2 user of the Secret logs in and is a
#                              member of the organization; nothing is registered
#   3. previous run objects    this tag's CVAT project / cloud storage
#                              (cvat_stand.py cleanup --tag) and bucket <tag>
#                              on the shared MinIO (minio.py cleanup --prefix)
#                              are gone; on main this clears the durable
#                              `cveta2-main` slot
#   4. coco8 images            downloaded once into tests/fixtures/data/
#   5. seed_cvat.py            bucket <tag> created with the cveta2 key and the
#                              images uploaded; cloud storage "<tag> minio"
#                              registered against the in-cluster MinIO
#                              endpoint; project "<tag> coco8-dev" and its
#                              tasks created
#
# Usage:
#   ./scripts/integration_up.sh
#
# Requirements: uv, curl, unzip, python3, kubectl, the k8s-infra skill,
# tests/integration/.env

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/integration_env.sh
source "$SCRIPT_DIR/integration_env.sh"

COCO8_IMAGES_DIR="$INTEGRATION_REPO_ROOT/tests/fixtures/data/coco8/images"

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            echo "Usage: $0"
            echo ""
            echo "Prepare one integration run on the shared stands: bucket <tag> on"
            echo "MinIO, project '<tag> coco8-dev' on CVAT. Always recreates both."
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            exit 1
            ;;
    esac
done
integration_claim_run_tag

log() { echo "==> $*"; }

cd "$INTEGRATION_REPO_ROOT"

# ── 1-2. The stand: the account and its membership ────────────────────
log "Run tag '$INTEGRATION_RUN_TAG': verifying user $CVAT_INTEGRATION_USER on the CVAT stand at $CVAT_INTEGRATION_HOST"
uv run python tests/integration/cvat_stand.py verify

# ── 3. This tag's previous run: CVAT objects first, then the bucket ───
# A freshly minted tag owns nothing yet; an adopted tag and the main slot do.
# The cloud storage points at the bucket, so it goes before the bucket.
log "Removing the previous '$INTEGRATION_RUN_TAG' run from organization $CVAT_INTEGRATION_ORG"
uv run python tests/integration/cvat_stand.py cleanup --tag "$INTEGRATION_RUN_TAG"
log "Removing bucket '$MINIO_BUCKET' of the previous '$INTEGRATION_RUN_TAG' run from MinIO at $MINIO_ENDPOINT"
integration_helper minio cleanup --prefix "$INTEGRATION_RUN_TAG"

# ── 4. coco8 images ───────────────────────────────────────────────────
if [ ! -d "$COCO8_IMAGES_DIR/train" ] || [ ! -d "$COCO8_IMAGES_DIR/val" ]; then
    log "Downloading coco8 dataset images"
    COCO8_ZIP=$(mktemp /tmp/coco8-XXXX.zip)
    curl -fsSL "https://github.com/ultralytics/assets/releases/download/v0.0.0/coco8.zip" \
        -o "$COCO8_ZIP"
    COCO8_TMP=$(mktemp -d /tmp/coco8-extract-XXXX)
    unzip -qo "$COCO8_ZIP" -d "$COCO8_TMP"
    mkdir -p "$COCO8_IMAGES_DIR"
    cp -r "$COCO8_TMP/coco8/images/train" "$COCO8_IMAGES_DIR/train"
    cp -r "$COCO8_TMP/coco8/images/val" "$COCO8_IMAGES_DIR/val"
    rm -rf "$COCO8_ZIP" "$COCO8_TMP"
    log "coco8 images extracted to $COCO8_IMAGES_DIR"
else
    log "coco8 images already present"
fi

# ── 5. Bucket, images, cloud storage, project, tasks ──────────────────
log "Seeding bucket '$MINIO_BUCKET' and project '$CVAT_INTEGRATION_PROJECT'"
uv run python tests/integration/seed_cvat.py

log "Done."
log "CVAT:          $CVAT_INTEGRATION_HOST  (organization $CVAT_INTEGRATION_ORG, project '$CVAT_INTEGRATION_PROJECT')"
log "MinIO bucket:  $MINIO_BUCKET at $MINIO_ENDPOINT  (for CVAT: $MINIO_ENDPOINT_FOR_CVAT)"
log "MinIO console: ${MINIO_CONSOLE:-not published by the Secret}"
log "ClearML:       $CLEARML_API_HOST  (the shared stand)"
log ""
log "Run integration tests:  ./scripts/integration_test.sh"
log "Tear down:              ./scripts/integration_stop.sh"
