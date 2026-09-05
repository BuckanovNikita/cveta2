#!/usr/bin/env bash
# Shared environment for the integration scripts. Sourced, never executed:
#
#   source "$(dirname "${BASH_SOURCE[0]}")/integration_env.sh"
#
# One place derives everything a run owns, so up / test / stop / gate agree.
# The run acts as project `cveta2` of the shared docker-desktop stands
# (k8s-infra skill, references/run-contract.md): the tag is minted by the
# skill, the credentials come from the project's Secrets, and the objects a
# run creates are named by the tag.
#
#   INTEGRATION_RUN_TAG
#                      this run's tag. In order of precedence:
#                        1. INFRA_RUN_TAG, when exported (the contract's own
#                           variable; also how a shell adopts an active run);
#                        2. on main (or when pre-commit pushes refs/heads/main)
#                           the durable slot `cveta2-main`, which the next main
#                           run replaces;
#                        3. tests/integration/.run-tag, the gitignored file
#                           integration_up.sh writes when it mints a tag and
#                           integration_stop.sh deletes;
#                        4. nothing: integration_up.sh mints one; test and stop
#                           refuse (integration_require_run_tag).
#   CVAT_INTEGRATION_HOST / USER / PASSWORD / ORG
#                      the cveta2 CVAT identity (Secret cvat/cvat-cveta2-access:
#                      CVAT_URL, CVAT_USERNAME, CVAT_PASSWORD, CVAT_ORG)
#   CVAT_INTEGRATION_PROJECT
#                      the seeded project, "<tag> coco8-dev"
#   MINIO_ENDPOINT     the shared MinIO as the host sees it (S3_ENDPOINT)
#   MINIO_ENDPOINT_FOR_CVAT
#                      the same MinIO as the CVAT pods see it (S3_ENDPOINT_IN_CLUSTER)
#   MINIO_ACCESS_KEY / MINIO_SECRET_KEY / MINIO_REGION / MINIO_CONSOLE
#                      the cveta2 MinIO key, its region and the console URL
#   MINIO_BUCKET       this run's bucket, <tag>
#   CLEARML_*          the cveta2 ClearML identity, exported by the helper as is
#
# Nothing runs on this host: the stands are the cluster's, so there are no
# ports to pick and no Compose stack to start.
#
# tests/integration/.env must exist: its presence arms the machine for
# integration tests (and the pre-push gate). It holds optional overrides only,
# see tests/integration/.env.example; a value in the file wins over the shell,
# which is why the harness label (INFRA_HARNESS) is not one of them.
#
# A missing Secret key is an error, never a default: a defaulted credential
# would silently act as somebody else on a shared stand.

INTEGRATION_ENV_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INTEGRATION_REPO_ROOT="$(cd "$INTEGRATION_ENV_SCRIPT_DIR/.." && pwd)"
INTEGRATION_ENV_FILE="$INTEGRATION_REPO_ROOT/tests/integration/.env"
INTEGRATION_RUN_TAG_FILE="$INTEGRATION_REPO_ROOT/tests/integration/.run-tag"
INTEGRATION_PROJECT="cveta2"
INTEGRATION_MAIN_TAG="cveta2-main"
INTEGRATION_TAG_SLUG="integration"

integration_fail() {
    printf 'ERROR: %s\n' "$1" >&2
    shift
    if (( $# )); then
        printf '       %s\n' "$@" >&2
    fi
    return 1
}

integration_on_main() {
    if [[ -n "${PRE_COMMIT_REMOTE_BRANCH:-}" ]]; then
        [[ "$PRE_COMMIT_REMOTE_BRANCH" == "refs/heads/main" ]]
        return
    fi
    [[ "$(git -C "$INTEGRATION_REPO_ROOT" symbolic-ref --quiet --short HEAD 2>/dev/null)" == "main" ]]
}

# The k8s-infra skill: K8S_INFRA_SKILL_DIR when set (and then it must be the
# migrated skill), else the two places the skill is installed.
integration_skill_dir() {
    local candidate
    if [[ -n "${K8S_INFRA_SKILL_DIR:-}" ]]; then
        if [[ ! -f "$K8S_INFRA_SKILL_DIR/scripts/infra.py" ]]; then
            integration_fail "K8S_INFRA_SKILL_DIR=$K8S_INFRA_SKILL_DIR has no scripts/infra.py;" \
                "point it at k8s-infra/skills/k8s-infra of a checkout that carries the run contract."
            return
        fi
        printf '%s' "$K8S_INFRA_SKILL_DIR"
        return
    fi
    for candidate in "$HOME/.agents/skills/k8s-infra" "$HOME/.claude/skills/k8s-infra"; do
        if [[ -f "$candidate/scripts/infra.py" ]]; then
            printf '%s' "$candidate"
            return
        fi
    done
    integration_fail "the k8s-infra skill was not found under ~/.agents/skills or ~/.claude/skills," \
        "or the installed one predates the run contract (no scripts/infra.py)." \
        "Install or update it, or export K8S_INFRA_SKILL_DIR=<k8s-infra>/skills/k8s-infra."
}

integration_helper() {
    python3 "$INTEGRATION_SKILL_DIR/scripts/$1.py" --project "$INTEGRATION_PROJECT" "${@:2}"
}

# eval "$(helper env)" would swallow the helper's exit status; capture first.
integration_eval_env() {
    local stand=$1 exports
    if ! exports="$(integration_helper "$stand" env)"; then
        integration_fail "$stand.py --project $INTEGRATION_PROJECT env failed (see above);" \
            "the cveta2 $stand Secret is missing or the cluster is not reachable."
        return
    fi
    eval "$exports"
}

integration_require_secret_keys() {
    local stand=$1 key
    for key in "${@:2}"; do
        if [[ -z "${!key:-}" ]]; then
            integration_fail "the cveta2 $stand Secret carries no $key;" \
                "re-run the $stand stand deploy from the k8s-infra repository."
            return
        fi
    done
}

integration_valid_tag() {
    [[ "$1" =~ ^[a-z0-9]+(-[a-z0-9]+)*$ ]]
}

# Everything named by the tag is derived here, once, for every script.
integration_set_run_tag() {
    INTEGRATION_RUN_TAG="$1"
    CVAT_INTEGRATION_PROJECT=""
    MINIO_BUCKET=""
    if [[ -n "$INTEGRATION_RUN_TAG" ]]; then
        CVAT_INTEGRATION_PROJECT="${INTEGRATION_RUN_TAG} coco8-dev"
        MINIO_BUCKET="$INTEGRATION_RUN_TAG"
    fi
    export INTEGRATION_RUN_TAG CVAT_INTEGRATION_PROJECT MINIO_BUCKET
}

integration_read_run_tag_file() {
    local tag=""
    [[ -f "$INTEGRATION_RUN_TAG_FILE" ]] || return 1
    IFS= read -r tag < "$INTEGRATION_RUN_TAG_FILE" || true
    if ! integration_valid_tag "$tag"; then
        integration_fail "$INTEGRATION_RUN_TAG_FILE does not hold a run tag;" \
            "remove it if the run it named is gone."
        return
    fi
    printf '%s' "$tag"
}

# Precedence: INFRA_RUN_TAG, the main slot, the .run-tag file, nothing.
integration_resolve_run_tag() {
    local tag=""
    if [[ -n "${INFRA_RUN_TAG:-}" ]]; then
        tag="$INFRA_RUN_TAG"
    elif integration_on_main; then
        tag="$INTEGRATION_MAIN_TAG"
    elif [[ -f "$INTEGRATION_RUN_TAG_FILE" ]]; then
        tag="$(integration_read_run_tag_file)" || return 1
    fi
    if [[ -n "$tag" ]] && ! integration_valid_tag "$tag"; then
        integration_fail "run tag '$tag' is not lowercase [a-z0-9-]; mint it with infra.py newtag."
        return
    fi
    if [[ -n "${INTEGRATION_RUN_TAG:-}" && -n "$tag" && "$INTEGRATION_RUN_TAG" != "$tag" ]]; then
        integration_fail "INTEGRATION_RUN_TAG=$INTEGRATION_RUN_TAG is set in the shell but the tag is derived now;" \
            "unset it and export INFRA_RUN_TAG=<tag> to run under an explicit tag."
        return
    fi
    integration_set_run_tag "$tag"
}

integration_require_run_tag() {
    [[ -n "${INTEGRATION_RUN_TAG:-}" ]] && return 0
    integration_fail "no run is active: run ./scripts/integration_up.sh first," \
        "or export INFRA_RUN_TAG=<tag> to act on a run started elsewhere."
}

# Whether integration_up.sh would have to mint a tag: an exported INFRA_RUN_TAG
# and the main slot need none.
integration_would_mint() {
    [[ -z "${INFRA_RUN_TAG:-}" ]] && ! integration_on_main
}

# A .run-tag file where a tag would be minted means another run is active;
# the gate checks this before arming its teardown, up before doing anything.
integration_refuse_active_run() {
    if integration_would_mint && [[ -f "$INTEGRATION_RUN_TAG_FILE" ]]; then
        integration_fail "a run is active; stop it or export INFRA_RUN_TAG to adopt it" \
            "    ($INTEGRATION_RUN_TAG_FILE names '$(integration_read_run_tag_file 2>/dev/null || echo '?')')."
        return
    fi
}

# integration_up.sh: settle on the tag this run owns; when one has to be
# minted, assign first and record second, so a refused mint leaves nothing.
integration_claim_run_tag() {
    local tag=""
    integration_would_mint || return 0
    integration_refuse_active_run || return 1
    if ! tag="$(python3 "$INTEGRATION_SKILL_DIR/scripts/infra.py" newtag --project "$INTEGRATION_PROJECT" --slug "$INTEGRATION_TAG_SLUG")" \
        || ! integration_valid_tag "$tag"; then
        integration_fail "infra.py newtag --project $INTEGRATION_PROJECT --slug $INTEGRATION_TAG_SLUG did not mint a tag (see above)."
        return
    fi
    printf '%s\n' "$tag" > "$INTEGRATION_RUN_TAG_FILE"
    integration_set_run_tag "$tag"
}

# integration_stop.sh: forget the tag, but only the file that names this run.
integration_release_run_tag() {
    local recorded=""
    [[ -f "$INTEGRATION_RUN_TAG_FILE" ]] || return 0
    recorded="$(integration_read_run_tag_file 2>/dev/null || true)"
    if [[ "$recorded" == "$INTEGRATION_RUN_TAG" || -z "$recorded" ]]; then
        rm -f "$INTEGRATION_RUN_TAG_FILE"
    fi
}

if [[ ! -f "$INTEGRATION_ENV_FILE" ]]; then
    integration_fail "$INTEGRATION_ENV_FILE is missing." \
        "       cp tests/integration/.env.example tests/integration/.env  arms this machine."
    return 1 2>/dev/null || exit 1
fi
set -a
# shellcheck disable=SC1090
. "$INTEGRATION_ENV_FILE"
set +a

INTEGRATION_SKILL_DIR="$(integration_skill_dir)" || return 1 2>/dev/null || exit 1
integration_resolve_run_tag || return 1 2>/dev/null || exit 1

integration_eval_env cvat || return 1 2>/dev/null || exit 1
integration_require_secret_keys cvat CVAT_URL CVAT_USERNAME CVAT_PASSWORD CVAT_ORG || return 1 2>/dev/null || exit 1
CVAT_INTEGRATION_HOST="${CVAT_URL%/}"
CVAT_INTEGRATION_USER="$CVAT_USERNAME"
CVAT_INTEGRATION_PASSWORD="$CVAT_PASSWORD"
CVAT_INTEGRATION_ORG="$CVAT_ORG"

integration_eval_env minio || return 1 2>/dev/null || exit 1
integration_require_secret_keys minio S3_ENDPOINT S3_ENDPOINT_IN_CLUSTER S3_ACCESS_KEY S3_SECRET_KEY S3_REGION || return 1 2>/dev/null || exit 1
MINIO_ENDPOINT="${S3_ENDPOINT%/}"
MINIO_ENDPOINT_FOR_CVAT="${S3_ENDPOINT_IN_CLUSTER%/}"
MINIO_ACCESS_KEY="$S3_ACCESS_KEY"
MINIO_SECRET_KEY="$S3_SECRET_KEY"
MINIO_REGION="$S3_REGION"
MINIO_CONSOLE="${S3_CONSOLE:-}"

integration_eval_env clearml || return 1 2>/dev/null || exit 1
integration_require_secret_keys clearml CLEARML_API_HOST CLEARML_API_ACCESS_KEY CLEARML_API_SECRET_KEY || return 1 2>/dev/null || exit 1

export INTEGRATION_SKILL_DIR INTEGRATION_PROJECT
export CVAT_INTEGRATION_HOST CVAT_INTEGRATION_USER CVAT_INTEGRATION_PASSWORD CVAT_INTEGRATION_ORG
export MINIO_ENDPOINT MINIO_ENDPOINT_FOR_CVAT MINIO_ACCESS_KEY MINIO_SECRET_KEY MINIO_REGION MINIO_CONSOLE
