# Concurrent integration runs

Read this reference when another developer or automated run may use the shared
CVAT stand or local Docker ports.

## Isolation model

A run needs both a unique tag and unique ports.

`scripts/integration_env.sh` uses explicit `INTEGRATION_RUN_TAG` when set.
Otherwise it derives `<INTEGRATION_USER>` on main or
`<INTEGRATION_USER>-<branch>` elsewhere. The sanitized tag names the Compose
project, containers, CVAT project `<tag> coco8-dev`, and cloud storage
`<tag> minio`.

The current defaults are:

| Service | Port | Override |
|---|---:|---|
| MinIO API | 9989 | `MINIO_PORT` or `integration_up.sh --minio-port` |
| MinIO console | 9990 | `MINIO_CONSOLE_PORT` |
| ClearML API | 8880 | `CLEARML_API_PORT` |
| ClearML files | 8881 | `CLEARML_FILES_PORT` |
| ClearML web | 8882 | `CLEARML_WEB_PORT` |

Different ports with the same tag are unsafe: the second setup removes the
first run's Compose project and exact-tag CVAT objects. Different tags with the
same ports fail at startup. Worktrees usually make branch-derived tags
different, but do not isolate ports and do not help when two worktrees share a
branch name.

## Start an isolated run

Choose values that belong to this run and keep them in the same shell:

```bash
export INTEGRATION_RUN_TAG=cveta2-review-<unique-suffix>
export MINIO_PORT=<free-port>
export MINIO_CONSOLE_PORT=<free-port>
export CLEARML_API_PORT=<free-port>
export CLEARML_FILES_PORT=<free-port>
export CLEARML_WEB_PORT=<free-port>

./scripts/integration_up.sh
./scripts/integration_test.sh tests/integration/<target>.py
./scripts/integration_stop.sh
```

The scripts must see the same variables for setup, test, and stop. Do not reuse
a tag shown by another active run. If assigning ports is not worthwhile, run
sequentially and still preserve exact tag ownership.

## Diagnose collisions

`integration_up.sh` first removes its own Compose project, then checks ports.
A remaining occupied port therefore belongs to another process or run. Inspect
before acting:

```bash
docker compose ls
source scripts/integration_env.sh
uv run python tests/integration/cvat_stand.py ls
```

Do not stop an unknown Compose project or change a running process. Choose
different ports and a different tag.

Same-tag collisions on CVAT can appear as missing projects or tasks because the
second setup uses `cleanup --tag`. The selector includes a trailing space
(`"<tag> "`) to avoid prefix collisions, but it cannot distinguish two runs
that deliberately share the exact tag.

## Cleanup after failure

Clean only the tag recorded for the current run:

```bash
INTEGRATION_RUN_TAG=<owned-tag> \
MINIO_PORT=<owned-port> MINIO_CONSOLE_PORT=<owned-port> \
CLEARML_API_PORT=<owned-port> CLEARML_FILES_PORT=<owned-port> CLEARML_WEB_PORT=<owned-port> \
./scripts/integration_stop.sh
```

If only CVAT cleanup needs retrying, source the same environment and use
`cvat_stand.py cleanup --tag <owned-tag>`. Never substitute a broader prefix.

For possible orphan inventory, `cleanup --stale <hours> --dry-run` is
read-only. Do not remove its results until the user explicitly authorizes the
deletion and every object's ownership has been verified. A retained main run
is expected and may appear stale.
