---
name: running-integration-tests
description: |
  Use when the user wants to run integration tests for the cveta2 project against a live CVAT + MinIO + ClearML stack.
  Covers starting the stack, running tests, tearing down, and avoiding port/container conflicts when multiple agents run in parallel.
  Trigger on: "integration test", "run integration", "start CVAT stack", "integration_up", "integration_test", "integration_stop",
  "tear down integration", "parallel integration", "port conflict".
---

# Running cveta2 Integration Tests

Integration tests run against a real CVAT + MinIO + ClearML Docker stack. The full lifecycle is: **start stack -> run tests -> tear down**.

## Prerequisites

- Docker and Docker Compose v2.24.6+
- `uv` (Python package manager)
- Network access to `raw.githubusercontent.com` on the first run of a given CVAT
  version — `integration_up.sh` downloads CVAT's own `docker-compose.yml` into
  `.cache/cvat/<version>/` and reuses it offline afterwards. Without that access,
  point `CVAT_COMPOSE_FILE` at a local copy of that file.
- Free ports (defaults: 9988, 9989, 9990, 8880-8882) — see parallel section for overrides
- `tests/integration/.env` — gitignored, so a fresh clone does not have one and
  every script fails on `couldn't find env file` until you create it:

  ```bash
  cp tests/integration/.env.example tests/integration/.env
  ```

  The same file is the switch for the pre-push gate below. The username and
  password in it must match what `tests/integration/conftest.py` logs in with
  (`admin`/`admin` unless `CVAT_INTEGRATION_USER` / `CVAT_INTEGRATION_PASSWORD`
  say otherwise). `SMOKESCREEN_OPTS` is not optional: CVAT proxies outbound S3
  through smokescreen, which denies private ranges, so without it seeding dies
  registering the cloud storage with "The resource cveta2-test not found" while
  MinIO is healthy and reachable.

## Quick Start (Single Agent)

```bash
# 1. Start the stack (downloads images, seeds test data — slow on first run)
./scripts/integration_up.sh

# 2. Run all integration tests
./scripts/integration_test.sh

# 3. Tear down (removes containers AND volumes)
./scripts/integration_stop.sh
```

Forward extra pytest args to `integration_test.sh`:

```bash
./scripts/integration_test.sh -k upload        # only upload tests
./scripts/integration_test.sh -x --tb=long     # stop on first failure, long tracebacks
```

## The pre-push gate

`scripts/integration_gate.sh` runs the same lifecycle from the `integration-tests`
pre-push hook: start the stack, run `tests/integration`, tear it down. It owns the
whole cycle rather than reusing whatever is running because of caveat 2 below —
a stack that already ran the upload tests is not safe to run them against again.

It arms itself on `tests/integration/.env`, so a machine that was never set up
for integration testing skips it silently. That is the *only* silent skip: with
docker down or a port taken, an armed gate fails the push instead of waving it
through.

```bash
./scripts/integration_gate.sh                # the same thing by hand
./scripts/integration_gate.sh --keep-stack   # leave the stack up on failure
SKIP=integration-tests git push              # skip it for one push
```

Two consequences worth knowing before your first push: it **destroys a stack you
left running** (the cycle starts with `down -v`), and it runs only
`tests/integration` — the `live-cvat` re-run of the unit suite that
`CVAT_INTEGRATION_HOST` also switches on stays a manual
`./scripts/integration_test.sh`.

## What Each Script Does

### `integration_up.sh`

1. Resolves the base compose file: `CVAT_COMPOSE_FILE` if set, else
   `.cache/cvat/<version>/docker-compose.yml`, downloading it from the CVAT repo
   when that cache entry is missing. `--cvat-version` selects both this file and
   the `cvat/*` image tags (default `v2.41.0`).
2. Tears down any existing stack (`docker compose -p <project> down -v`, by project
   label, so it does not matter which CVAT version started it)
3. Checks that default ports (9988, 9989, 9990, 8880-8882) are free — in that
   order, so a plain re-run is not refused by the ports its own teardown just
   released. A port still taken here belongs to something else: another user's
   stack, or a second agent that picked the same `--port`.
4. Downloads coco8 dataset images (if missing)
5. Starts minimal CVAT services: `cvat_server`, `cvat_worker_import`, `cvat_worker_chunks`, `cveta2-minio`, plus ClearML (`clearml-apiserver`, `clearml-webserver`, `clearml-fileserver`). No `traefik` and no `cvat_ui`: `cvat_server` publishes its own nginx on the CVAT port, so the stack serves the API and has no web UI. See the header of `docker-compose.override.yml` for why traefik is kept out — in short, a traefik from any *other* CVAT stack on the machine discovers these containers through the Docker socket and breaks both stacks at once.
6. Waits for CVAT and ClearML health endpoints (up to 180s)
7. Creates CVAT superuser (`admin`/`admin`)
8. Creates MinIO bucket (`cveta2-test`)
9. Seeds CVAT with `coco8-dev` test project via `tests/integration/seed_cvat.py`

### `integration_test.sh`

1. Sets env vars: `CVAT_INTEGRATION_HOST`, `MINIO_ENDPOINT`, AWS credentials, ClearML endpoints
2. Disables xdist (`-o 'addopts=-v --tb=short'`) — parallel pytest workers cause CVAT 429 rate-limiting
3. Forwards any extra args to pytest

### `integration_stop.sh`

1. Runs `docker compose -p "${INTEGRATION_USER}-cvat" down -v --remove-orphans` to
   remove all containers, networks and volumes
2. Passes no compose file at all — docker compose finds everything by project
   label, so teardown needs no download and works whichever CVAT version started it

## Shutdown

Always tear down with `./scripts/integration_stop.sh` (not manual `docker compose down`), because:

- It uses the correct compose project name (`${INTEGRATION_USER}-cvat`)
- It removes volumes (`-v`) to ensure clean state for next run
- It removes orphan containers (`--remove-orphans`)

If a test run is interrupted (Ctrl-C, crash), the stack keeps running. Run `integration_stop.sh` to clean up. The stack is designed to be disposable — `integration_up.sh` always tears down first before starting.

To tear down another user's or another agent's stack, run the same command with
their project name:

```bash
# Find the project name
docker compose ls | grep cvat

# Manual teardown (replace USERNAME with the prefix that stack used)
docker compose -p "USERNAME-cvat" down -v --remove-orphans
```

## Parallel Agents: Avoiding Conflicts

See `./parallel-agents-guide.md` for the full strategy.

**Key points:**

- Container names and compose project names are prefixed with `$USER` by default (e.g., `nkt-cvat_server`)
- **Same-user agents** on the same machine WILL conflict because they share the same prefix and ports
- Use `--port` and `--minio-port` flags to assign unique ports per agent
- Set `INTEGRATION_USER` env var to give each agent a unique container prefix

Quick example for two parallel agents on the same machine:

```bash
# Agent A (default ports)
./scripts/integration_up.sh

# Agent B (different ports + unique prefix)
INTEGRATION_USER=agent-b ./scripts/integration_up.sh --port 9188 --minio-port 9189
```

## Important Caveats

1. **No xdist**: Do NOT add `-n auto` to integration tests. CVAT returns 429 errors under parallel load.
2. **Fresh state required**: Upload tests create tasks in the seeded project. Re-running against the same instance without re-seeding fails with `ValueError: Duplicate base task name`. Always tear down and restart between full runs — this is why the pre-push gate builds its own stack instead of reusing one.
3. **First run is slow**: Docker image pulls + coco8 download + CVAT startup. Subsequent runs are faster (images cached).
4. **Health timeout**: If CVAT doesn't become healthy within 180s, the script fails. Check `docker logs USERNAME-cvat_server`.
