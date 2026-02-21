#!/usr/bin/env bash
# Start (or recreate) a minimal CVAT + MinIO stack for integration tests.
#
# Only starts the services needed for API testing:
#   cvat_server  (+deps: db, redis x2, opa)
#   cvat_worker_import   (task creation)
#   cvat_worker_chunks   (image processing, if present in the version)
#   cveta2-minio         (S3 storage)
#
# Analytics (clickhouse, vector, grafana), UI, traefik, and non-essential
# workers are NOT started. The server port is exposed directly.
#
# Usage:
#   ./scripts/integration_up.sh [--cvat-version v2.26.0] [--port 9080]
#
# Requirements: docker, docker compose v2, uv, curl, unzip

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

CVAT_SUBMODULE="$REPO_ROOT/vendor/cvat"
ENV_FILE="$REPO_ROOT/tests/integration/.env"
OVERRIDE_FILE="$REPO_ROOT/tests/integration/docker-compose.override.yml"
COCO8_IMAGES_DIR="$REPO_ROOT/tests/fixtures/data/coco8/images"

CVAT_VERSION=""
export CVAT_PORT=8080
HEALTH_TIMEOUT=180

# ── Parse arguments ─────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --cvat-version)
            CVAT_VERSION="$2"
            shift 2
            ;;
        --cvat-version=*)
            CVAT_VERSION="${1#*=}"
            shift
            ;;
        --port)
            CVAT_PORT="$2"
            shift 2
            ;;
        --port=*)
            CVAT_PORT="${1#*=}"
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [--cvat-version v2.X.X] [--port PORT]"
            echo ""
            echo "Start a minimal CVAT + MinIO stack for integration tests."
            echo "Always resets (docker compose down -v) before starting."
            echo ""
            echo "Options:"
            echo "  --cvat-version TAG   CVAT version tag to check out (default: submodule HEAD)"
            echo "  --port PORT          Host port for CVAT API (default: 8080)"
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            exit 1
            ;;
    esac
done

# ── Helpers ─────────────────────────────────────────────────────────
compose() {
    docker compose \
        --project-directory "$CVAT_SUBMODULE" \
        -f "$CVAT_SUBMODULE/docker-compose.yml" \
        -f "$OVERRIDE_FILE" \
        --env-file "$ENV_FILE" \
        "$@"
}

log() { echo "==> $*"; }

# ── 1. Verify submodule ────────────────────────────────────────────
if [ ! -f "$CVAT_SUBMODULE/docker-compose.yml" ]; then
    echo "ERROR: CVAT submodule not initialized at vendor/cvat/" >&2
    echo "Run:  git submodule update --init" >&2
    exit 1
fi

# ── 2. Checkout CVAT version ───────────────────────────────────────
if [ -n "$CVAT_VERSION" ]; then
    log "Checking out CVAT $CVAT_VERSION"
    git -C "$CVAT_SUBMODULE" fetch --tags --quiet
    git -C "$CVAT_SUBMODULE" checkout "$CVAT_VERSION" --quiet
else
    CVAT_VERSION=$(git -C "$CVAT_SUBMODULE" describe --tags --always 2>/dev/null || echo "dev")
    log "Using CVAT at current submodule HEAD ($CVAT_VERSION)"
fi

# ── 3. Tear down existing stack (always reset) ─────────────────────
log "Tearing down existing CVAT stack (docker compose down -v)"
compose down -v --remove-orphans 2>/dev/null || true

# ── 4. Download coco8 images if missing ────────────────────────────
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

# ── 5. Start minimal CVAT stack ───────────────────────────────────
SERVICES="cvat_server cvat_worker_import cveta2-minio"
if compose config --services 2>/dev/null | grep -q '^cvat_worker_chunks$'; then
    SERVICES="$SERVICES cvat_worker_chunks"
fi

log "Starting minimal CVAT stack on port $CVAT_PORT ($SERVICES)"
# shellcheck disable=SC2086
compose up -d --pull=missing $SERVICES

# ── 6. Wait for CVAT health ────────────────────────────────────────
log "Waiting for CVAT to be healthy (timeout ${HEALTH_TIMEOUT}s)"
elapsed=0
until curl -sf "http://localhost:${CVAT_PORT}/api/server/about" > /dev/null 2>&1; do
    if [ "$elapsed" -ge "$HEALTH_TIMEOUT" ]; then
        echo "ERROR: CVAT did not become healthy within ${HEALTH_TIMEOUT}s" >&2
        echo "Check logs: compose logs cvat_server" >&2
        exit 1
    fi
    sleep 3
    elapsed=$((elapsed + 3))
done
log "CVAT is healthy"

# ── 7. Create superuser ────────────────────────────────────────────
log "Creating CVAT superuser"
DJANGO_SUPERUSER_USERNAME=$(grep '^DJANGO_SUPERUSER_USERNAME=' "$ENV_FILE" | cut -d= -f2)
DJANGO_SUPERUSER_PASSWORD=$(grep '^DJANGO_SUPERUSER_PASSWORD=' "$ENV_FILE" | cut -d= -f2)
DJANGO_SUPERUSER_EMAIL=$(grep '^DJANGO_SUPERUSER_EMAIL=' "$ENV_FILE" | cut -d= -f2)

docker exec \
    -e "DJANGO_SUPERUSER_USERNAME=$DJANGO_SUPERUSER_USERNAME" \
    -e "DJANGO_SUPERUSER_PASSWORD=$DJANGO_SUPERUSER_PASSWORD" \
    -e "DJANGO_SUPERUSER_EMAIL=$DJANGO_SUPERUSER_EMAIL" \
    cvat_server \
    python3 manage.py createsuperuser --no-input 2>/dev/null || true

log "Superuser ready (${DJANGO_SUPERUSER_USERNAME})"

# ── 8. Create MinIO bucket ─────────────────────────────────────────
log "Ensuring MinIO bucket exists"
MINIO_BUCKET=$(grep '^MINIO_BUCKET=' "$ENV_FILE" | cut -d= -f2)
docker exec cveta2-minio mc alias set local http://localhost:9000 minioadmin minioadmin 2>/dev/null || true
docker exec cveta2-minio mc mb "local/${MINIO_BUCKET}" 2>/dev/null || true

# ── 9. Seed CVAT with test data ────────────────────────────────────
log "Seeding CVAT with coco8-dev test data"
cd "$REPO_ROOT"
CVAT_INTEGRATION_HOST="http://localhost:${CVAT_PORT}" uv run python tests/integration/seed_cvat.py

log "Done! CVAT is running at http://localhost:${CVAT_PORT}"
log ""
log "Run integration tests:"
log "  CVAT_INTEGRATION_HOST=http://localhost:${CVAT_PORT} uv run pytest"
log ""
log "Tear down:"
log "  docker compose --project-directory vendor/cvat -f vendor/cvat/docker-compose.yml -f tests/integration/docker-compose.override.yml --env-file tests/integration/.env down -v"
