---
name: running-integration-tests
description: |
  Use when the user wants to run integration tests for the cveta2 project against a live CVAT + MinIO + ClearML stack.
  Covers starting the stack, running tests, tearing down, and avoiding port/container conflicts when multiple agents run in parallel.
  Trigger on: "integration test", "run integration", "start CVAT stack", "integration_up", "integration_test", "integration_stop",
  "tear down integration", "parallel integration", "port conflict".
---

# Running cveta2 Integration Tests

Integration tests run against a real CVAT + MinIO + ClearML. CVAT is the
**persistent stand in the local Kubernetes cluster** (`http://cvat.k8s.localhost`,
namespace `cvat`, described by the `k8s-infra` skill); the scripts never start
or stop it. MinIO and ClearML run in Docker Compose next to the tests and are
recreated per run. The lifecycle is **prepare run -> run tests -> stop (or keep)**.

## Prerequisites

- The CVAT stand is deployed and answers on `http://cvat.k8s.localhost/api/server/about`
  (if not: `k8s-infra` skill, `cvat-stand/deploy_cvat.sh`).
- Docker and Docker Compose v2.24.6+, `uv`, `curl`, `unzip`.
- Free host ports for MinIO and ClearML (defaults: 9989, 9990, 8880-8882);
  see the parallel section for overrides.
- `tests/integration/.env` — gitignored, so a fresh clone does not have one and
  every script fails on it until you create it:

  ```bash
  cp tests/integration/.env.example tests/integration/.env
  ```

  Fill in `CVAT_INTEGRATION_PASSWORD`. The first `integration_up.sh` registers
  the account (`CVAT_INTEGRATION_USER`, default `cveta2`) on the stand with that
  password and creates the organization (`CVAT_INTEGRATION_ORG`, default
  `cveta2-tests`) it owns. A missing or placeholder key is a hard error on
  purpose: a defaulted password would register a user on a shared server
  without anyone noticing. The same file is the switch for the pre-push gate below.

## Quick Start (Single Agent)

```bash
# 1. Prepare the run: check the stand, recreate MinIO + ClearML, seed this run's project
./scripts/integration_up.sh

# 2. Run all integration tests
./scripts/integration_test.sh

# 3. Tear down: compose stack (volumes included) AND this run's CVAT project
./scripts/integration_stop.sh
```

Forward extra pytest args to `integration_test.sh`:

```bash
./scripts/integration_test.sh -k upload        # only upload tests
./scripts/integration_test.sh -x --tb=long     # stop on first failure, long tracebacks
```

## The run tag: what a run owns

`scripts/integration_env.sh` (sourced by every script) derives one **run tag**
and names everything the run owns after it:

| Situation | Tag |
|---|---|
| `main` checked out, or pre-commit pushing `refs/heads/main` | `<INTEGRATION_USER>` |
| any other branch | `<INTEGRATION_USER>-<branch slug>` |
| `INTEGRATION_RUN_TAG` set | that value |

`INTEGRATION_USER` defaults to `$USER`. The tag names the compose project
(`<tag>-cveta2`, containers `<tag>-cveta2-minio`, `<tag>-clearml-*`), the CVAT
cloud storage (`<tag> minio`, pointing at this run's MinIO through the
docker-desktop host gateway) and the CVAT project (`<tag> coco8-dev`, 80 labels,
the seeded tasks). Tests find the project through `CVAT_INTEGRATION_PROJECT`.

Everything happens inside organization `CVAT_INTEGRATION_ORG` as the
integration account. To look at a run in the CVAT UI, log in as the stand's
`admin` (a superuser sees every organization) or as the integration account
with the `.env` password, and switch to the organization.

## The pre-push gate

`scripts/integration_gate.sh` runs from the `integration-tests` pre-push hook:
prepare the run, run `tests/integration`, then decide by branch:

- **`main`** (a push of `refs/heads/main`, or `main` checked out): the run is
  **kept** — the compose stack stays up so images still render, and the
  `<tag> coco8-dev` project stays on the stand for inspection. The next `main`
  run replaces it.
- **any other branch**: `integration_stop.sh` removes the stack and the CVAT data.
- `INTEGRATION_KEEP_DATA=1` / `=0` overrides the decision either way.

It arms itself on `tests/integration/.env`, so a machine that was never set up
skips it silently. That is the *only* silent skip: with docker down, the stand
not answering or a port taken, an armed gate fails the push.

```bash
./scripts/integration_gate.sh                # the same thing by hand
./scripts/integration_gate.sh --keep-stack   # leave the stack up on failure
SKIP=integration-tests git push              # skip it for one push
```

The gate runs only `tests/integration` — the `live-cvat` re-run of the unit
suite that `CVAT_INTEGRATION_HOST` also switches on stays a manual
`./scripts/integration_test.sh`.

## What Each Script Does

### `integration_env.sh` (sourced)

Sanitizes `INTEGRATION_USER`, derives the run tag and compose project name,
loads `tests/integration/.env`, and exports `CVAT_INTEGRATION_{HOST,USER,
PASSWORD,ORG,PROJECT}`, `MINIO_ENDPOINT` (host view), `MINIO_ENDPOINT_FOR_CVAT`
(pod view, `http://192.168.65.254:<MINIO_PORT>`) and the port variables.

### `integration_up.sh`

1. `cvat_stand.py bootstrap` — registers the account and creates the
   organization when missing, and proves the stand is reachable.
2. `docker compose -p <tag>-cveta2 down -v`, then checks the MinIO/ClearML
   ports are free — in that order, so a plain re-run is not refused by ports
   its own teardown just released. A port still taken belongs to something else.
3. Downloads coco8 images (if missing), starts MinIO + ClearML, waits for both
   health endpoints, creates the bucket.
4. `cvat_stand.py cleanup --tag <tag>` — removes this tag's previous project,
   tasks and cloud storage from the organization and fails if anything remains.
5. `seed_cvat.py` — uploads the images to MinIO, registers the cloud storage,
   creates `<tag> coco8-dev` and its tasks. It refuses to run if a project with
   that name already exists, so a hand-run seeder cannot create a duplicate.

Options: `--minio-port PORT`; `CLEARML_API_PORT` / `CLEARML_FILES_PORT` /
`CLEARML_WEB_PORT` / `MINIO_CONSOLE_PORT` through the environment.

### `integration_test.sh`

Sources the env file, exports the MinIO credentials and the ClearML endpoints
(soft-gated on `/debug.ping`; ClearML tests skip when it is down), disables
xdist (`-o 'addopts=-v --tb=short -p tests.env_isolation'` — parallel workers
trip CVAT rate limits), forwards extra args to pytest. Give it the same
`INTEGRATION_USER` / ports as `integration_up.sh`.

### `integration_stop.sh`

`docker compose -p <tag>-cveta2 down -v --remove-orphans` first, then
`cvat_stand.py cleanup --tag <tag>`. If the stand is unreachable the containers
are still gone; the exit code reports the failed CVAT step and the command to
retry it.

### `tests/integration/cvat_stand.py`

```bash
uv run python tests/integration/cvat_stand.py bootstrap                 # account, organization, reachability
uv run python tests/integration/cvat_stand.py ls                        # projects, tasks, storages in the org
uv run python tests/integration/cvat_stand.py cleanup --tag <tag>       # one run's objects
uv run python tests/integration/cvat_stand.py cleanup --stale 24 --dry-run   # orphans from dead runs
```

Needs the `CVAT_INTEGRATION_*` variables: run it as
`source scripts/integration_env.sh && uv run python tests/integration/cvat_stand.py ls`,
or from inside a script that already sourced them. `--tag` matches
`"<tag> "` (tag plus a space), so `nkt` never matches `nkt-feature coco8-dev`.

## Parallel Agents: Avoiding Conflicts

See `./parallel-agents-guide.md` for the full strategy.

**Key points:**

- Isolation on both sides comes from the run tag: compose project and
  containers on the host, project and cloud storage in the shared organization.
- **Two runs with the same tag conflict twice**: on ports, and — new with the
  shared CVAT — the second run's pre-run cleanup deletes the first run's
  project. Give parallel agents distinct `INTEGRATION_USER` values and distinct
  ports.
- The stand throttles only anonymous requests (per client IP); each run logs
  in serially and cveta2 retries 429s, so several agents fit comfortably.

```bash
# Agent A (default ports)
./scripts/integration_up.sh

# Agent B (different ports + unique prefix)
INTEGRATION_USER=agent-b MINIO_CONSOLE_PORT=9190 CLEARML_API_PORT=8890 CLEARML_FILES_PORT=8891 CLEARML_WEB_PORT=8892 \
  ./scripts/integration_up.sh --minio-port 9189
```

## Important Caveats

1. **No xdist**: Do NOT add `-n auto` to integration tests. CVAT returns 429 errors under parallel load.
2. **Fresh project per run**: Upload tests create tasks with fixed names in the
   seeded project, and the `live-cvat` unit re-run fails on
   `ValueError: Duplicate base task name` when a project holds two tasks of one
   name. `integration_up.sh` removes the tag's previous project before seeding,
   so re-running `up` between full runs is what keeps that true — do not run
   the suite twice against one seeded project.
3. **First run is slow**: image pulls for MinIO/ClearML and the coco8 download.
4. **Health timeout**: MinIO or ClearML not healthy within 180s fails the
   script. Check `docker compose -p <tag>-cveta2 logs`.
5. **The stand is shared**: never run `cvat_stand.py cleanup --stale` without
   `--dry-run` first, and never point the scripts at another organization.
