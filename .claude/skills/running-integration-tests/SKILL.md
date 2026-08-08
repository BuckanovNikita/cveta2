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
- CVAT git submodule initialized: `git submodule update --init`
- Free ports (defaults: 9988, 9989, 9990, 8880-8882) — see parallel section for overrides
- `tests/integration/.env` — gitignored, so a fresh clone does not have one and
  every script fails on `couldn't find env file` until you write it:

  ```dotenv
  DJANGO_SUPERUSER_USERNAME=admin
  DJANGO_SUPERUSER_PASSWORD=admin
  DJANGO_SUPERUSER_EMAIL=admin@example.com

  MINIO_BUCKET=cveta2-test

  # CVAT proxies outbound S3 through smokescreen, which denies private ranges
  # by default. Without this, seeding dies registering the cloud storage with
  # "The resource cveta2-test not found" while MinIO is healthy and reachable.
  SMOKESCREEN_OPTS=--unsafe-allow-private-ranges
  ```

  The username and password must match what `tests/integration/conftest.py`
  logs in with (`admin`/`admin` unless `CVAT_INTEGRATION_USER` /
  `CVAT_INTEGRATION_PASSWORD` say otherwise).

## Quick Start (Single Agent)

```bash
# 1. Start the stack (downloads images, seeds test data — takes 2-3 min first time)
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

## What Each Script Does

### `integration_up.sh`

1. Tears down any existing stack (`docker compose down -v`)
2. Checks that default ports (9988, 9989, 9990, 8880-8882) are free — in that
   order, so a plain re-run is not refused by the ports its own teardown just
   released. A port still taken here belongs to something else: another user's
   stack, or a second agent that picked the same `--port`.
3. Downloads coco8 dataset images (if missing)
4. Starts minimal CVAT services: `cvat_server`, `cvat_worker_import`, `cvat_worker_chunks`, `cveta2-minio`, plus ClearML (`clearml-apiserver`, `clearml-webserver`, `clearml-fileserver`). No `traefik` and no `cvat_ui`: `cvat_server` publishes its own nginx on the CVAT port, so the stack serves the API and has no web UI. See the header of `docker-compose.override.yml` for why traefik is kept out — in short, a traefik from any *other* CVAT stack on the machine discovers these containers through the Docker socket and breaks both stacks at once.
5. Waits for CVAT and ClearML health endpoints (up to 180s)
6. Creates CVAT superuser (`admin`/`admin`)
7. Creates MinIO bucket (`cveta2-test`)
8. Seeds CVAT with `coco8-dev` test project via `tests/integration/seed_cvat.py`

### `integration_test.sh`

1. Sets env vars: `CVAT_INTEGRATION_HOST`, `MINIO_ENDPOINT`, AWS credentials, ClearML endpoints
2. Disables xdist (`-o 'addopts=-v --tb=short'`) — parallel pytest workers cause CVAT 429 rate-limiting
3. Forwards any extra args to pytest

### `integration_stop.sh`

1. Runs `docker compose down -v --remove-orphans` to remove all containers and volumes
2. Uses the same `INTEGRATION_USER` prefix so it targets the correct compose project

## Shutdown

Always tear down with `./scripts/integration_stop.sh` (not manual `docker compose down`), because:

- It uses the correct compose project name (`${INTEGRATION_USER}-cvat`)
- It passes the right `-f` flags (both base + override compose files)
- It removes volumes (`-v`) to ensure clean state for next run
- It removes orphan containers (`--remove-orphans`)

If a test run is interrupted (Ctrl-C, crash), the stack keeps running. Run `integration_stop.sh` to clean up. The stack is designed to be disposable — `integration_up.sh` always tears down first before starting.

If `integration_stop.sh` itself fails (e.g., missing CVAT submodule), fall back to:

```bash
# Find your project name
docker compose ls | grep cvat

# Manual teardown (replace USERNAME with your $USER)
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
2. **Fresh state required**: Upload tests create tasks in the seeded project. Re-running against the same instance without re-seeding fails with `ValueError: Duplicate base task name`. Always tear down and restart between full runs.
3. **First run is slow**: Docker image pulls + coco8 download + CVAT startup takes 2-3 minutes. Subsequent runs are faster (images cached).
4. **Health timeout**: If CVAT doesn't become healthy within 180s, the script fails. Check `docker logs USERNAME-cvat_server`.
