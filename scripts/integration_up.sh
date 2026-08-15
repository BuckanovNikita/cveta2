#!/usr/bin/env bash
# Start (or recreate) a minimal CVAT + MinIO stack for integration tests.
#
# Starts the services needed for API testing:
#   cvat_server  (+deps: db, redis x2, opa)
#   cvat_worker_import   (task creation)
#   cvat_worker_chunks   (image processing, if present in the version)
#   cveta2-minio         (S3 storage)
#
# Analytics (clickhouse, vector, grafana), the web UI (cvat_ui) and traefik are
# NOT started; cvat_server publishes its own nginx on CVAT_PORT. See the header
# of docker-compose.override.yml for why traefik is kept out of this stack.
# Container names are prefixed with username (INTEGRATION_USER) to avoid clashes.
#
# Usage:
#   ./scripts/integration_up.sh [--cvat-version v2.26.0] [--port 9080]
#
# If --port is omitted, fixed well-known ports are used:
#   CVAT API: 9988
#   MinIO API:          9989
#   MinIO console:      9990
#
# The base compose file is CVAT's own docker-compose.yml, downloaded once per
# version into .cache/cvat/ (gitignored). Set CVAT_COMPOSE_FILE to a local copy
# to skip the download on a machine that cannot reach raw.githubusercontent.com.
#
# Requirements: docker, docker compose v2, uv, curl, unzip

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

ENV_FILE="$REPO_ROOT/tests/integration/.env"
OVERRIDE_FILE="$REPO_ROOT/tests/integration/docker-compose.override.yml"
COCO8_IMAGES_DIR="$REPO_ROOT/tests/fixtures/data/coco8/images"
COMPOSE_CACHE_DIR="$REPO_ROOT/.cache/cvat"

CVAT_VERSION="v2.41.0"
CVAT_PORT="9988"
MINIO_PORT="9989"
MINIO_CONSOLE_PORT="9990"
CLEARML_API_PORT="8880"
CLEARML_FILES_PORT="8881"
CLEARML_WEB_PORT="8882"
HEALTH_TIMEOUT=180

# ── Container name prefix (username) ───────────────────────────────
INTEGRATION_USER=$(printf '%s' "${USER:-default}" | sed 's/[^a-zA-Z0-9_.-]/_/g')
INTEGRATION_USER="${INTEGRATION_USER:-default}"
export INTEGRATION_USER

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
        --minio-port)
            MINIO_PORT="$2"
            shift 2
            ;;
        --minio-port=*)
            MINIO_PORT="${1#*=}"
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [--cvat-version v2.X.X] [--port PORT]"
            echo ""
            echo "Start a minimal CVAT + MinIO stack for integration tests."
            echo "Always resets (docker compose down -v) before starting."
            echo ""
            echo "Options:"
            echo "  --cvat-version TAG   CVAT release tag: compose file and images (default: $CVAT_VERSION)"
            echo "  --port PORT          Host port for CVAT API and UI (default: 9988)"
            echo "  --minio-port PORT    Host port for MinIO API (default: 9989)"
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            exit 1
            ;;
    esac
done

# ── Check ports are free (called in step 3b, after our own teardown) ──
check_port_free() {
    local port=$1 label=$2
    if ss -tlnH "sport = :$port" 2>/dev/null | grep -q .; then
        echo "ERROR: Port $port ($label) is already in use." >&2
        echo "Free it or use --port / --minio-port to override." >&2
        exit 1
    fi
}

# CVAT_VERSION picks both the compose file and, through its own ${CVAT_VERSION:-...}
# defaults inside that file, every cvat/* image tag.
export CVAT_PORT MINIO_PORT MINIO_CONSOLE_PORT CLEARML_API_PORT CLEARML_FILES_PORT CLEARML_WEB_PORT CVAT_VERSION

COMPOSE_URL="https://raw.githubusercontent.com/cvat-ai/cvat/${CVAT_VERSION}/docker-compose.yml"
COMPOSE_DIR="$COMPOSE_CACHE_DIR/$CVAT_VERSION"
COMPOSE_FILE="${CVAT_COMPOSE_FILE:-$COMPOSE_DIR/docker-compose.yml}"

# ── Helpers ─────────────────────────────────────────────────────────
compose() {
    docker compose \
        --project-directory "${COMPOSE_FILE%/*}" \
        -p "${INTEGRATION_USER}-cvat" \
        -f "$COMPOSE_FILE" \
        -f "$OVERRIDE_FILE" \
        --env-file "$ENV_FILE" \
        "$@"
}

log() { echo "==> $*"; }

# ── 1-2. Resolve the CVAT compose file ─────────────────────────────
# Downloaded once per version, so every later run is offline. Only `up` needs the
# file at all: the teardowns here and in integration_stop.sh go by project label.
if [ -n "${CVAT_COMPOSE_FILE:-}" ]; then
    if [ ! -f "$CVAT_COMPOSE_FILE" ]; then
        echo "ERROR: CVAT_COMPOSE_FILE=$CVAT_COMPOSE_FILE does not exist" >&2
        exit 1
    fi
    log "Using CVAT compose file $CVAT_COMPOSE_FILE (images: $CVAT_VERSION)"
elif [ -f "$COMPOSE_FILE" ]; then
    log "Using cached CVAT $CVAT_VERSION compose file"
else
    log "Downloading CVAT $CVAT_VERSION compose file"
    mkdir -p "$COMPOSE_DIR"
    if ! curl -fsSL "$COMPOSE_URL" -o "$COMPOSE_FILE.part"; then
        rm -f "$COMPOSE_FILE.part"
        echo "ERROR: could not download $COMPOSE_URL" >&2
        echo "Set CVAT_COMPOSE_FILE to a local copy of CVAT's docker-compose.yml." >&2
        exit 1
    fi
    mv "$COMPOSE_FILE.part" "$COMPOSE_FILE"
fi

# ── 3. Tear down existing stack (always reset) ─────────────────────
# By project label rather than through compose(): the stack being replaced may
# have been started from a different CVAT version's compose file.
log "Tearing down existing CVAT stack (docker compose down -v)"
docker compose -p "${INTEGRATION_USER}-cvat" down -v --remove-orphans 2>/dev/null || true

# ── 3b. Check ports are free ───────────────────────────────────────
# After the teardown, never before it: the stack this script is about to
# replace is holding these very ports, so checking first makes a plain
# re-run fail on ports we were going to release anyway. What is worth
# refusing is a port held by something else -- another user's stack, or a
# second agent that picked the same --port.
check_port_free "$CVAT_PORT" "CVAT API"
check_port_free "$MINIO_PORT" "MinIO API"
check_port_free "$MINIO_CONSOLE_PORT" "MinIO console"
check_port_free "$CLEARML_API_PORT" "ClearML API"
check_port_free "$CLEARML_FILES_PORT" "ClearML fileserver"
check_port_free "$CLEARML_WEB_PORT" "ClearML webserver"

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
SERVICES="cvat_server cvat_worker_import cveta2-minio clearml-apiserver clearml-webserver clearml-fileserver"
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

# ── 6b. Wait for ClearML health ──────────────────────────────────────
log "Waiting for ClearML API to be healthy (timeout ${HEALTH_TIMEOUT}s)"
elapsed=0
until curl -sf "http://localhost:${CLEARML_API_PORT}/debug.ping" > /dev/null 2>&1; do
    if [ "$elapsed" -ge "$HEALTH_TIMEOUT" ]; then
        echo "ERROR: ClearML API did not become healthy within ${HEALTH_TIMEOUT}s" >&2
        echo "Check logs: compose logs clearml-apiserver" >&2
        exit 1
    fi
    sleep 3
    elapsed=$((elapsed + 3))
done
log "ClearML API is healthy"

# ── 7. Create superuser ────────────────────────────────────────────
log "Creating CVAT superuser"
DJANGO_SUPERUSER_USERNAME=$(grep '^DJANGO_SUPERUSER_USERNAME=' "$ENV_FILE" | cut -d= -f2)
DJANGO_SUPERUSER_PASSWORD=$(grep '^DJANGO_SUPERUSER_PASSWORD=' "$ENV_FILE" | cut -d= -f2)
DJANGO_SUPERUSER_EMAIL=$(grep '^DJANGO_SUPERUSER_EMAIL=' "$ENV_FILE" | cut -d= -f2)

docker exec \
    -e "DJANGO_SUPERUSER_USERNAME=$DJANGO_SUPERUSER_USERNAME" \
    -e "DJANGO_SUPERUSER_PASSWORD=$DJANGO_SUPERUSER_PASSWORD" \
    -e "DJANGO_SUPERUSER_EMAIL=$DJANGO_SUPERUSER_EMAIL" \
    "${INTEGRATION_USER}-cvat_server" \
    python3 manage.py createsuperuser --no-input 2>/dev/null || true

log "Superuser ready (${DJANGO_SUPERUSER_USERNAME})"

# ── 8. Create MinIO bucket ─────────────────────────────────────────
log "Ensuring MinIO bucket exists"
MINIO_BUCKET=$(grep '^MINIO_BUCKET=' "$ENV_FILE" | cut -d= -f2)
docker exec "${INTEGRATION_USER}-cveta2-minio" mc alias set local http://localhost:9000 minioadmin minioadmin 2>/dev/null || true
docker exec "${INTEGRATION_USER}-cveta2-minio" mc mb "local/${MINIO_BUCKET}" 2>/dev/null || true

# ── 9. Seed CVAT with test data ────────────────────────────────────
log "Seeding CVAT with coco8-dev test data"
cd "$REPO_ROOT"
CVAT_INTEGRATION_HOST="http://localhost:${CVAT_PORT}" \
    MINIO_ENDPOINT="http://localhost:${MINIO_PORT}" \
    uv run python tests/integration/seed_cvat.py

log "Done! CVAT is running at http://localhost:${CVAT_PORT}"
log "MinIO API: http://localhost:${MINIO_PORT}"
log "MinIO console: http://localhost:${MINIO_CONSOLE_PORT}"
log "ClearML API: http://localhost:${CLEARML_API_PORT}"
log "ClearML Web: http://localhost:${CLEARML_WEB_PORT}"
log ""
log "Run integration tests:"
log "  ./scripts/integration_test.sh"
log ""
log "Tear down:"
log "  ./scripts/integration_stop.sh"
