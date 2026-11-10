---
name: running-integration-tests
description: Run cveta2 live tests through Task with bounded preflight, explicit infrastructure deferral, one owned session namespace per run and exact-namespace teardown. Use for integration or acceptance runs, blocked setup, assertion failures, cluster access errors, kept sessions, cleanup leftovers or explicitly requested operator waiting.
---

# Run cveta2 live tests

Every live session deploys its own CVAT, MinIO and ClearML into its own
namespace of the `docker-desktop` cluster and deletes that namespace afterwards.
There are no shared stands, run tags, registry or helper scripts from another
repository. The session generates its credentials into the namespace's Secrets
and the test process environment; they are never written to a tracked file or
printed. Prerequisites: `kubectl` with the `docker-desktop` context and
`uv sync --locked`. Helm, a local CA and the k8s-infra skill are not needed.

The live tests are ordinary pytest tests under `tests/integration`. Development
verification excludes this directory; invoke live checks explicitly. The full
suite with coverage, including live tests, remains required before merging.
`tests/conftest.py` marks them `integration` and puts them in the `live` xdist
group, so under the configured `--dist loadgroup` one worker runs them
serially; unit tests stay parallel. The autouse session fixture `live_run`
(`tests/integration/conftest.py`) does the following through
`tests/integration/lifecycle.py`:

1. Rechecks availability with a bounded preflight in Task-driven runs (see below).
2. Creates `cveta2-it-<UTC yyyymmdd-hhmmss>-<4 hex>` with the quota and limit
   range of `tests/integration/k8s/quota.yaml` before any workload, generates
   the Secrets, applies `tests/integration/k8s/{cvat,minio,clearml}.yaml`,
   waits for readiness within the cold-start deadline, starts loopback
   port-forwards, registers a regular CVAT user that owns one organization,
   and seeds the run. The namespace name is the run tag.
3. Deletes the namespace after the last live test, waits until it is gone and
   stops the port-forwards, unless `INTEGRATION_KEEP_DATA=1`.

```bash
uv run --locked task --exit-code infra-check
uv run --locked task --exit-code integration
uv run --locked task --exit-code acceptance  # clean-tip full coverage, including live tests
uv run --locked task --exit-code test        # affected units, integration directory excluded
```

`L` below abbreviates `uv run --locked python -m tests.integration.lifecycle`,
for manual lifecycle operations after reading this skill:

```bash
L check              # read-only bounded availability; creates nothing
L up                 # start, seed and keep a session; records tests/integration/.session
eval "$(L env)"      # port-forwards and variables of the kept session; refuses a terminal
L stop [<namespace>] # delete exactly that session namespace and stop its port-forwards
```

## Bounded preflight and deferral

`infra-check` checks that `kubectl` exists, that the cluster answers `/readyz`,
that the context may create and delete namespaces, and that a node's
unrequested CPU and memory can admit the session quota's requests.
`CVETA2_INFRA_CHECK_TIMEOUT` bounds the whole read-only check (60 seconds by
default). It creates nothing. Task uses `--exit-code` to retain these results:

| Result | Exit | Action |
| --- | --- | --- |
| AVAILABLE | 0 | Live verification may start; setup rechecks availability. |
| UNAVAILABLE | 3 | Cluster does not answer, node cannot admit the quota, or timeout: defer live verification. |
| ERROR | 1 | Diagnose a missing tool or context, refused namespace permission or unexpected failure. |

Setup is bounded by `CVETA2_SESSION_READY_TIMEOUT` (300 seconds by default) for
the services to become ready. Services not ready in time are blocked setup:
the namespace is deleted and the run is UNAVAILABLE, never a test failure. A
first pull of the CVAT server image may exceed the deadline; pull it once or
raise the deadline. An availability result is not a test result. Loss of
availability during setup is blocked setup; assertion failures are test
failures.

When unavailable, report the reason and required checks left deferred. Continue
independent implementation, documentation, review and local verification. Retry
at a meaningful milestone or after restored availability, without continuous
polling. When only blocked checks remain, stop and ask for the user's decision.
Deferred live verification blocks acceptance, merge and release.

Explicit operator waiting for an unavailable cluster remains available through
`L up` and `CVETA2_STAND_WAIT_TIMEOUT`; use it only when waiting was requested.
Keep the waiting process observable, report its state and retain interruption
cleanup. Task verification must not silently revert to indefinite waiting.
Never restart Docker Desktop, change cluster settings or touch other namespaces
to make verification pass.

For a focused live selector, first run `infra-check`, then invoke pytest with
`CVETA2_TASK_VERIFICATION=1` as in `Taskfile.yml`, preserving environment
isolation and `--dist loadgroup`. Do not use an unbounded ad hoc command as
acceptance.

## Rules

- **One session, one namespace.** The session acts only on the namespace it
  created. `L stop` accepts only `cveta2-it-` names and deletes exactly the one
  given or recorded; never delete another session's namespace, another
  project's namespace or a platform namespace.
- **Quota first.** Every session namespace carries the quota and limit range
  before any workload; every container declares requests and limits. Change
  sizes in `tests/integration/k8s/`, never by removing the quota. No workload
  requests `nvidia.com/gpu`.
- **Storage.** `emptyDir`, plus one claim for CVAT's shared data directory that
  names `storageClassName: hostpath`. Never reference `local-path`.
- **Host access.** Only `kubectl --context docker-desktop port-forward` on
  127.0.0.1, started and stopped by the session. No Ingress, NodePort or host
  port. Plain HTTP over loopback; there is no certificate to trust.
- **Keep or stop.** Every session is deleted after its last live test, on
  `main` too. `INTEGRATION_KEEP_DATA=1` keeps it and records it in the
  gitignored `tests/integration/.session` (namespace and local ports, no
  credentials); it stays until `L stop`. `L up` always keeps.
- **A kept session blocks `L up`** in this checkout while its namespace exists;
  stop it first. A recorded namespace that vanished is forgotten automatically.
- **Vanished namespaces.** The platform may delete any project namespace 48
  hours after creation or after a cluster restart. A session never relies on
  an earlier one; a new session starts from scratch and `L stop` of a vanished
  namespace succeeds as already removed.
- **Parallelism.** Do not split the `live` group across workers, and keep
  `--dist loadgroup`: each worker would otherwise start its own session.
- **Shell profile.** Remove the exports of the retired shared-stand model
  (listed in `specs/002-own-test-infra/spec.md`, FR-013) from your shell
  profile; nothing reads them any more.

## Concurrency

Sessions from several worktrees or agents may run at once: each owns its own
namespace, local ports and credentials. The node is the only shared limit, and
preflight checks that it can admit one more session quota. There is no
project-wide run cap.

## Completion evidence

Report the session namespace, the selector, the pytest result, and whether the
namespace was deleted or kept (by name). Distinguish passed tests, actual
failures, deferred verification and incomplete cleanup. After a failed or
interrupted run, prove cleanup with `kubectl --context docker-desktop get ns`
(no namespace of the run left) and no remaining
`kubectl --context docker-desktop -n <namespace> port-forward` process; report
anything left by name with the `L stop <namespace>` retry. A successful
preflight without executed live tests is not acceptance.
