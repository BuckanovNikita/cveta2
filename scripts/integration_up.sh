#!/usr/bin/env bash
# Prepare one run of the integration tests.
#
# CVAT is the persistent stand in the local Kubernetes cluster
# (http://cvat.k8s.localhost, see the k8s-infra skill); this script never
# starts or stops it. What it does own, per run tag (scripts/integration_env.sh):
#
#   1. cvat_stand.py bootstrap   the integration account and organization exist,
#                                the stand is reachable
#   2. docker compose            MinIO + ClearML, recreated from scratch
#                                (project <tag>-cveta2, volumes included)
#   3. port checks               MinIO and ClearML host ports are free
#   4. coco8 images              downloaded once into tests/fixtures/data/
#   5. MinIO bucket
#   6. cvat_stand.py cleanup     this tag's previous project / storage are gone
#   7. seed_cvat.py              "<tag> coco8-dev" and "<tag> minio" created
#
# Usage:
#   ./scripts/integration_up.sh [--minio-port 9189]
#
# Every port can also be set through the environment (MINIO_PORT,
# MINIO_CONSOLE_PORT, CLEARML_API_PORT, CLEARML_FILES_PORT, CLEARML_WEB_PORT);
# a second run next to one that holds the defaults needs distinct ports AND a
# distinct INTEGRATION_USER, since the tag also names the CVAT objects.
#
# Requirements: docker, docker compose v2, uv, curl, unzip, tests/integration/.env

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/integration_env.sh
source "$SCRIPT_DIR/integration_env.sh"

COCO8_IMAGES_DIR="$INTEGRATION_REPO_ROOT/tests/fixtures/data/coco8/images"
HEALTH_TIMEOUT=180

while [[ $# -gt 0 ]]; do
    case "$1" in
        --minio-port)
            MINIO_PORT="$2"
            shift 2
            ;;
        --minio-port=*)
            MINIO_PORT="${1#*=}"
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [--minio-port PORT]"
            echo ""
            echo "Prepare the integration stack: MinIO + ClearML in Docker Compose,"
            echo "this run's project on the cluster CVAT. Always recreates both."
            echo ""
            echo "Options:"
            echo "  --minio-port PORT    Host port for MinIO API (default: 9989)"
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            exit 1
            ;;
    esac
done
export MINIO_PORT
MINIO_ENDPOINT="http://localhost:${MINIO_PORT}"
MINIO_ENDPOINT_FOR_CVAT="http://${INTEGRATION_HOST_GATEWAY}:${MINIO_PORT}"
export MINIO_ENDPOINT MINIO_ENDPOINT_FOR_CVAT

log() { echo "==> $*"; }

check_port_free() {
    local port=$1 label=$2
    if ss -tlnH "sport = :$port" 2>/dev/null | grep -q .; then
        echo "ERROR: Port $port ($label) is already in use." >&2
        echo "Free it or use --minio-port / the CLEARML_*_PORT variables to override." >&2
        exit 1
    fi
}

compose() {
    docker compose -p "$COMPOSE_PROJECT" -f "$INTEGRATION_COMPOSE_FILE" "$@"
}

wait_healthy() {
    local url=$1 label=$2 elapsed=0
    log "Waiting for $label (timeout ${HEALTH_TIMEOUT}s)"
    until curl -sf "$url" > /dev/null 2>&1; do
        if [ "$elapsed" -ge "$HEALTH_TIMEOUT" ]; then
            echo "ERROR: $label did not become healthy within ${HEALTH_TIMEOUT}s" >&2
            echo "Check logs: docker compose -p $COMPOSE_PROJECT logs" >&2
            exit 1
        fi
        sleep 3
        elapsed=$((elapsed + 3))
    done
    log "$label is healthy"
}

cd "$INTEGRATION_REPO_ROOT"

# ── 1. The stand: account, organization, reachability ─────────────────
log "Run tag '$INTEGRATION_RUN_TAG': checking the CVAT stand at $CVAT_INTEGRATION_HOST"
uv run python tests/integration/cvat_stand.py bootstrap

# ── 2. Recreate MinIO + ClearML ───────────────────────────────────────
log "Tearing down compose project $COMPOSE_PROJECT (down -v)"
docker compose -p "$COMPOSE_PROJECT" down -v --remove-orphans 2>/dev/null || true

# ── 3. Ports, after our own teardown released them ────────────────────
check_port_free "$MINIO_PORT" "MinIO API"
check_port_free "$MINIO_CONSOLE_PORT" "MinIO console"
check_port_free "$CLEARML_API_PORT" "ClearML API"
check_port_free "$CLEARML_FILES_PORT" "ClearML fileserver"
check_port_free "$CLEARML_WEB_PORT" "ClearML webserver"

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

log "Starting MinIO + ClearML (project $COMPOSE_PROJECT, MinIO on port $MINIO_PORT)"
compose up -d --pull=missing
wait_healthy "http://localhost:${MINIO_PORT}/minio/health/live" "MinIO"
wait_healthy "http://localhost:${CLEARML_API_PORT}/debug.ping" "ClearML API"

# ── 5. Bucket ─────────────────────────────────────────────────────────
log "Ensuring MinIO bucket $MINIO_BUCKET exists"
docker exec "${INTEGRATION_RUN_TAG}-cveta2-minio" mc alias set local http://localhost:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" > /dev/null
docker exec "${INTEGRATION_RUN_TAG}-cveta2-minio" mc mb --ignore-existing "local/${MINIO_BUCKET}" > /dev/null

# ── 6-7. This tag's CVAT data: wipe the previous run, seed this one ───
log "Removing the previous '$INTEGRATION_RUN_TAG' run from organization $CVAT_INTEGRATION_ORG"
uv run python tests/integration/cvat_stand.py cleanup --tag "$INTEGRATION_RUN_TAG"

log "Seeding '$CVAT_INTEGRATION_PROJECT'"
uv run python tests/integration/seed_cvat.py

log "Done."
log "CVAT:          $CVAT_INTEGRATION_HOST  (organization $CVAT_INTEGRATION_ORG, project '$CVAT_INTEGRATION_PROJECT')"
log "MinIO API:     $MINIO_ENDPOINT  (for CVAT: $MINIO_ENDPOINT_FOR_CVAT)"
log "MinIO console: http://localhost:${MINIO_CONSOLE_PORT}"
log "ClearML API:   http://localhost:${CLEARML_API_PORT}"
log "ClearML Web:   http://localhost:${CLEARML_WEB_PORT}"
log ""
log "Run integration tests:  ./scripts/integration_test.sh"
log "Tear down:              ./scripts/integration_stop.sh"
