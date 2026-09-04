#!/usr/bin/env bash
# Shared environment for the integration scripts. Sourced, never executed:
#
#   source "$(dirname "${BASH_SOURCE[0]}")/integration_env.sh"
#
# One place derives everything a run owns, so up / test / stop / gate agree:
#
#   INTEGRATION_USER   container prefix, default $USER, sanitized
#   INTEGRATION_RUN_TAG
#                      names every CVAT object and the compose project of a run.
#                      On main (or when pre-commit pushes refs/heads/main) it is
#                      INTEGRATION_USER; on any other branch it is
#                      INTEGRATION_USER-<branch>, so a feature-branch run never
#                      replaces the data a main run left up for viewing.
#                      Set it explicitly to override.
#   COMPOSE_PROJECT    <tag>-cveta2 (MinIO + ClearML only; CVAT lives in the cluster)
#   CVAT_INTEGRATION_* host, credentials, organization and the seeded project
#                      name "<tag> coco8-dev" - CVAT_INTEGRATION_HOST/USER/
#                      PASSWORD/ORG come from tests/integration/.env
#   MINIO_ENDPOINT     MinIO as the host sees it (localhost:MINIO_PORT)
#   MINIO_ENDPOINT_FOR_CVAT
#                      the same MinIO as the CVAT pods see it, through the
#                      docker-desktop host gateway
#
# Missing .env keys are an error, never a default: a defaulted password would
# silently register a user on a shared server.

INTEGRATION_ENV_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INTEGRATION_REPO_ROOT="$(cd "$INTEGRATION_ENV_SCRIPT_DIR/.." && pwd)"
INTEGRATION_ENV_FILE="$INTEGRATION_REPO_ROOT/tests/integration/.env"
INTEGRATION_COMPOSE_FILE="$INTEGRATION_REPO_ROOT/tests/integration/docker-compose.yml"
INTEGRATION_STAND="$INTEGRATION_REPO_ROOT/tests/integration/cvat_stand.py"
INTEGRATION_HOST_GATEWAY="${INTEGRATION_HOST_GATEWAY:-192.168.65.254}"

integration_sanitize() { printf '%s' "$1" | sed 's/[^a-zA-Z0-9_.-]/-/g'; }

integration_on_main() {
    if [[ -n "${PRE_COMMIT_REMOTE_BRANCH:-}" ]]; then
        [[ "$PRE_COMMIT_REMOTE_BRANCH" == "refs/heads/main" ]]
        return
    fi
    [[ "$(git -C "$INTEGRATION_REPO_ROOT" symbolic-ref --quiet --short HEAD 2>/dev/null)" == "main" ]]
}

integration_branch_slug() {
    local ref
    if [[ -n "${PRE_COMMIT_REMOTE_BRANCH:-}" ]]; then
        ref="${PRE_COMMIT_REMOTE_BRANCH#refs/heads/}"
    else
        ref="$(git -C "$INTEGRATION_REPO_ROOT" symbolic-ref --quiet --short HEAD 2>/dev/null || echo detached)"
    fi
    integration_sanitize "$ref"
}

INTEGRATION_USER="$(integration_sanitize "${INTEGRATION_USER:-${USER:-default}}")"
if [[ -z "${INTEGRATION_RUN_TAG:-}" ]]; then
    if integration_on_main; then
        INTEGRATION_RUN_TAG="$INTEGRATION_USER"
    else
        INTEGRATION_RUN_TAG="${INTEGRATION_USER}-$(integration_branch_slug)"
    fi
fi
INTEGRATION_RUN_TAG="$(integration_sanitize "$INTEGRATION_RUN_TAG")"
COMPOSE_PROJECT="${INTEGRATION_RUN_TAG}-cveta2"

MINIO_PORT="${MINIO_PORT:-9989}"
MINIO_CONSOLE_PORT="${MINIO_CONSOLE_PORT:-9990}"
CLEARML_API_PORT="${CLEARML_API_PORT:-8880}"
CLEARML_FILES_PORT="${CLEARML_FILES_PORT:-8881}"
CLEARML_WEB_PORT="${CLEARML_WEB_PORT:-8882}"

if [[ ! -f "$INTEGRATION_ENV_FILE" ]]; then
    echo "ERROR: $INTEGRATION_ENV_FILE is missing." >&2
    echo "       cp tests/integration/.env.example tests/integration/.env  and fill it in." >&2
    return 1 2>/dev/null || exit 1
fi
set -a
# shellcheck disable=SC1090
. "$INTEGRATION_ENV_FILE"
set +a

for key in CVAT_INTEGRATION_HOST CVAT_INTEGRATION_USER CVAT_INTEGRATION_PASSWORD CVAT_INTEGRATION_ORG MINIO_BUCKET; do
    if [[ -z "${!key:-}" ]]; then
        echo "ERROR: $key is not set in $INTEGRATION_ENV_FILE." >&2
        echo "       The keys changed when the tests moved to the cluster CVAT;" >&2
        echo "       compare with tests/integration/.env.example." >&2
        return 1 2>/dev/null || exit 1
    fi
done
if [[ "$CVAT_INTEGRATION_PASSWORD" == "choose-a-password" ]]; then
    echo "ERROR: CVAT_INTEGRATION_PASSWORD still holds the placeholder from .env.example." >&2
    return 1 2>/dev/null || exit 1
fi

CVAT_INTEGRATION_HOST="${CVAT_INTEGRATION_HOST%/}"
CVAT_INTEGRATION_PROJECT="${INTEGRATION_RUN_TAG} coco8-dev"
MINIO_ENDPOINT="http://localhost:${MINIO_PORT}"
MINIO_ENDPOINT_FOR_CVAT="http://${INTEGRATION_HOST_GATEWAY}:${MINIO_PORT}"
MINIO_ROOT_USER="${MINIO_ROOT_USER:-minioadmin}"
MINIO_ROOT_PASSWORD="${MINIO_ROOT_PASSWORD:-minioadmin}"

export INTEGRATION_USER INTEGRATION_RUN_TAG COMPOSE_PROJECT
export MINIO_PORT MINIO_CONSOLE_PORT CLEARML_API_PORT CLEARML_FILES_PORT CLEARML_WEB_PORT
export CVAT_INTEGRATION_HOST CVAT_INTEGRATION_USER CVAT_INTEGRATION_PASSWORD
export CVAT_INTEGRATION_ORG CVAT_INTEGRATION_PROJECT
export MINIO_ENDPOINT MINIO_ENDPOINT_FOR_CVAT MINIO_BUCKET MINIO_ROOT_USER MINIO_ROOT_PASSWORD
