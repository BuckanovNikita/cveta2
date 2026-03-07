# Parallel Agents: Avoiding Conflicts

When multiple Claude Code agents (or CI jobs, or developers) run integration tests simultaneously on the same machine, they can clash on **ports** and **container names**. The scripts have built-in isolation via `INTEGRATION_USER`, but same-user parallel runs require extra care.

## How Isolation Works

The scripts use two isolation mechanisms:

### 1. Container Name Prefix (`INTEGRATION_USER`)

Every container is named `${INTEGRATION_USER}-<service>` (e.g., `nkt-cvat_server`). The compose project name is `${INTEGRATION_USER}-cvat`. By default, `INTEGRATION_USER=$USER`.

This means:
- **Different OS users** on the same machine are isolated automatically
- **Same OS user** running two agents will collide — both try to create `nkt-cvat_server`

### 2. Port Binding

Default ports are fixed:
| Service        | Default Port |
|----------------|-------------|
| CVAT API (traefik) | 9988   |
| MinIO API      | 9989        |
| MinIO console  | 9990        |
| ClearML API    | 8880        |
| ClearML files  | 8881        |
| ClearML web    | 8882        |

Two agents using the same ports will fail at startup (`check_port_free` in `integration_up.sh`).

## Strategy for Parallel Agents

### Option 1: Unique INTEGRATION_USER + Unique Ports (Recommended)

Give each agent a unique prefix and port range:

```bash
# Agent A
INTEGRATION_USER=agent-a ./scripts/integration_up.sh --port 9988 --minio-port 9989
INTEGRATION_USER=agent-a CVAT_INTEGRATION_HOST=http://localhost:9988 \
  MINIO_ENDPOINT=http://localhost:9989 \
  uv run pytest -o 'addopts=-v --tb=short' tests/integration/
INTEGRATION_USER=agent-a ./scripts/integration_stop.sh

# Agent B
INTEGRATION_USER=agent-b ./scripts/integration_up.sh --port 10088 --minio-port 10089
INTEGRATION_USER=agent-b CVAT_INTEGRATION_HOST=http://localhost:10088 \
  MINIO_ENDPOINT=http://localhost:10089 \
  uv run pytest -o 'addopts=-v --tb=short' tests/integration/
INTEGRATION_USER=agent-b ./scripts/integration_stop.sh
```

Each agent gets:
- Its own compose project (`agent-a-cvat`, `agent-b-cvat`)
- Its own containers (`agent-a-cvat_server`, `agent-b-cvat_server`)
- Its own ports (no bind conflicts)
- Its own Docker volumes (`agent-a-cvat_cveta2-minio-data`, etc.)

### Option 2: Sequential Execution

If parallel isolation is too complex, run agents sequentially. Each agent does the full cycle (up -> test -> stop) before the next starts. The `integration_up.sh` script always tears down first, so leftover state from a previous run is cleaned automatically.

### Option 3: Shared Stack, Partitioned Tests

Start the stack once, then run non-overlapping test subsets:

```bash
# Start once
./scripts/integration_up.sh

# Agent A runs fetch/partition tests (read-only, safe to parallelize)
./scripts/integration_test.sh -k "not upload and not clearml"

# Agent B runs upload tests (creates tasks, must run alone)
./scripts/integration_test.sh -k "upload"
```

**Warning**: Upload tests mutate CVAT state (create tasks). Running two upload test sessions against the same CVAT instance causes `Duplicate base task name` errors. Only use this option if you can guarantee non-overlapping mutations.

## ClearML Port Conflicts

ClearML uses three additional ports (8880-8882). Currently, `integration_up.sh` does NOT accept `--clearml-port` flags — ports are set via env vars in `.env`. To override for parallel agents:

```bash
export CLEARML_API_PORT=18880
export CLEARML_FILES_PORT=18881
export CLEARML_WEB_PORT=18882
```

Set these before running `integration_up.sh`.

## Cleanup After Parallel Failures

If an agent crashes mid-test, its containers and volumes remain. Clean up by name prefix:

```bash
# List all integration compose projects
docker compose ls | grep cvat

# Stop a specific agent's stack
INTEGRATION_USER=agent-b ./scripts/integration_stop.sh

# Nuclear option: stop ALL integration stacks on this machine
for project in $(docker compose ls --format json | jq -r '.[].Name' | grep -- '-cvat$'); do
  docker compose -p "$project" down -v --remove-orphans
done
```

## Summary

| Scenario | Container Isolation | Port Isolation | Mutation Safety |
|----------|-------------------|----------------|-----------------|
| Different OS users | Automatic (`$USER` prefix) | Must override ports | Independent stacks |
| Same user, unique `INTEGRATION_USER` | Yes | Must override ports | Independent stacks |
| Same user, default settings | NO — collides | NO — collides | NO |
| Shared stack, split tests | N/A (one stack) | N/A | Only if tests don't overlap on writes |
