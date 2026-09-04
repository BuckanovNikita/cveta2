# Parallel Agents: Avoiding Conflicts

When multiple Claude Code agents (or developers) run integration tests at the
same time on this machine, they share two things: the host's ports and the CVAT
stand's organization. The scripts isolate both through the **run tag**, but
same-tag runs collide, and the collision on the CVAT side is silent.

## How Isolation Works

### 1. The run tag (`INTEGRATION_USER`, the branch, or `INTEGRATION_RUN_TAG`)

`scripts/integration_env.sh` derives the tag: `<INTEGRATION_USER>` on `main`,
`<INTEGRATION_USER>-<branch>` elsewhere, or `INTEGRATION_RUN_TAG` verbatim.
`INTEGRATION_USER` defaults to `$USER`.

The tag names:

| Side | Object |
|---|---|
| host | compose project `<tag>-cveta2`; containers `<tag>-cveta2-minio`, `<tag>-clearml-*`; their volumes |
| CVAT stand, organization `cveta2-tests` | cloud storage `<tag> minio`, project `<tag> coco8-dev` and its tasks |

`integration_up.sh` starts by removing everything with its own tag on both
sides; `integration_stop.sh` ends the same way. Objects of other tags are never
touched: the match is `"<tag> "` with a trailing space, so `nkt` does not match
`nkt-feature coco8-dev`.

### 2. Port Binding

Default ports are fixed:

| Service        | Default Port | Override |
|----------------|-------------|---|
| MinIO API      | 9989        | `--minio-port` / `MINIO_PORT` |
| MinIO console  | 9990        | `MINIO_CONSOLE_PORT` |
| ClearML API    | 8880        | `CLEARML_API_PORT` |
| ClearML files  | 8881        | `CLEARML_FILES_PORT` |
| ClearML web    | 8882        | `CLEARML_WEB_PORT` |

Two agents using the same ports fail at startup (`check_port_free` in
`integration_up.sh`). CVAT has no port of its own any more: it is reached at
`http://cvat.k8s.localhost` by everyone.

## Strategy: Unique tag + unique ports (the only safe one)

```bash
# Agent A (defaults)
./scripts/integration_up.sh
./scripts/integration_test.sh tests/integration
./scripts/integration_stop.sh

# Agent B
export INTEGRATION_USER=agent-b
export MINIO_PORT=10089 MINIO_CONSOLE_PORT=10090
export CLEARML_API_PORT=18880 CLEARML_FILES_PORT=18881 CLEARML_WEB_PORT=18882
./scripts/integration_up.sh
./scripts/integration_test.sh tests/integration
./scripts/integration_stop.sh
```

Export the variables once per shell: `integration_test.sh` and
`integration_stop.sh` derive the same tag and ports from them, so a run that
was prepared as `agent-b` on port 10089 must be tested and stopped with the
same environment.

Agents in worktrees get a distinct tag for free (the branch is part of it), but
still need distinct ports and, if two worktrees share one branch name, a
distinct `INTEGRATION_USER`.

### Why same-tag parallel runs are worse than before

With the Compose CVAT, two same-tag runs failed loudly on the CVAT port. Now
the second run's `cvat_stand.py cleanup --tag` deletes the first run's project
on the stand while its tests are using it. Nothing detects that; the first run
just starts failing on missing tasks. Do not share a tag.

## Sequential Execution

If isolation is not worth the setup, run agents one after another. Each does
the full cycle (up -> test -> stop). `integration_up.sh` always cleans its own
tag first, so leftover state from an interrupted run is replaced automatically.

## Rate limits on the shared stand

The stand throttles anonymous requests only (100/min per client IP): the
`about` and login calls that every client open makes. A full suite opens a few
dozen clients over several minutes, so two or three concurrent agents stay
under the limit, and cveta2 retries 429s. If a run does see 429s on login,
stagger the agents; do not add xdist.

## Cleanup After Failures

An interrupted run leaves its containers and its CVAT project behind. Clean up
by tag:

```bash
# Host side: which compose projects exist
docker compose ls | grep -- '-cveta2'

# Both sides, for one tag
INTEGRATION_RUN_TAG=agent-b-feature ./scripts/integration_stop.sh

# CVAT side only: what is in the organization, and orphans older than a day
source scripts/integration_env.sh
uv run python tests/integration/cvat_stand.py ls
uv run python tests/integration/cvat_stand.py cleanup --stale 24 --dry-run   # read the list first
uv run python tests/integration/cvat_stand.py cleanup --stale 24
```

A `main` run is kept on purpose (see the gate in `SKILL.md`); `--stale` will
list it too once it is a day old — leave it unless the human agrees.

## Summary

| Scenario | Host isolation | CVAT isolation | Safe? |
|----------|----------------|----------------|-------|
| Different `INTEGRATION_USER`, different ports | yes | yes | yes |
| Same user, different branches (worktrees), different ports | yes | yes | yes |
| Same user, same branch, different ports | NO — same compose project | NO — same project on the stand | NO |
| Same user, default settings | NO — collides | NO — collides | NO |
