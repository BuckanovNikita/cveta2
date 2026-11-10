# Measurement evidence — 2026-11-10

Worktree `/mnt/wsl/data/nkt/_wt/cveta2-own-test-infra`, branch
`feat/own-test-infra`, starting at local `main` `0fa3310` (remote refs not
fetched). Cluster: Docker Desktop Kubernetes, context `docker-desktop`, one
node with 32 allocatable CPUs and about 62 GiB allocatable memory; both
`hostpath` and `local-path` marked default. Host load average about 3.6 and
about 28 GiB memory available at the start. pcboard could not identify this
session, so no game/video state was available; the work used moderate CPU.

Purpose: measure what the live suite really needs before the manifests are
fixed (spec clarifications, research R2-R10). Nothing here is implementation;
the manifests, harness and credentials used were scratch files, deleted
afterwards. No secret value is recorded.

## Method

- CVAT wiring came from `helm template` of the upstream chart at `v2.59.1`
  (a scratch copy of the k8s-infra `cvat/helm-chart`), with Ingress, frontend,
  analytics, ClickHouse, Nuclio, Traefik and the bitnami PostgreSQL disabled.
  The render contained no cluster-scoped object. No Helm release was installed:
  the output was applied with `kubectl apply` into the throwaway namespace.
- PostgreSQL 15, MinIO and a hand-written minimal ClearML (API server, file
  server, MongoDB, Elasticsearch 7.17.28, Redis) on `emptyDir`; CVAT's shared
  data claim on `hostpath`.
- `cveta2-it-m1` and `cveta2-it-m2` got a `ResourceQuota` and `LimitRange`
  before any workload. The short-lived `cveta2-it-probe` namespace (one pod)
  got a `ResourceQuota` only, without a `LimitRange`: a deviation from the
  measurement rule, harmless because its single container declared resources.
- Throwaway credentials were generated into a mode-0600 scratch file.
- Host access through `kubectl port-forward --address 127.0.0.1` to the CVAT
  backend, MinIO, ClearML API and ClearML file server.
- The CVAT user registered through `POST /api/auth/register` and created its
  organization: HTTP 201 for both, user not a superuser.
- The live suite ran unmodified through a scratch pytest plugin that replaced
  `lifecycle.prepare`/`finish` and set every variable the tests read, so no
  test could reach the shared stands or k8s-infra helpers. Command shape:
  `pytest tests/integration -p <scratch plugin> -n 2 --dist loadgroup -p no:randomly`
  with `CVETA2_TASK_VERIFICATION=1`.
- Queue usage was read from each CVAT worker's log (jobs per function).
- Resource peaks came from `docker stats --no-stream` every 10 s, filtered on
  the namespace (there is no metrics server). These are point samples; short
  spikes between samples are not seen.

## M1: every CVAT worker (`cveta2-it-m1`)

- Quota: pods 30, requests.cpu 8, requests.memory 12Gi, limits.memory 28Gi,
  2 claims (CVAT data, kvrocks), both `hostpath`.
- Readiness from namespace creation: MinIO 8 s, PostgreSQL 12 s, Redis 28 s,
  initializer Job finished 33 s, kvrocks 39 s, CVAT server 43 s, OPA 54 s.
  The ClearML API server crash-looped on the first apply: each Elasticsearch
  host entry needs `"scheme":"http"`. After the fix it was ready about 10 s
  after re-apply; the file server restarts until the API server answers.
- Suite, first pass (11:02:04-11:06:51 UTC): 30 passed, 8 failed in 283.5 s.
  All eight failures were `botocore.exceptions.NoCredentialsError`: the
  harness had not set the standard AWS variables that the k8s-infra MinIO
  helper used to export as a side effect. After adding `AWS_ACCESS_KEY_ID`,
  `AWS_SECRET_ACCESS_KEY`, `AWS_DEFAULT_REGION` and `AWS_ENDPOINT_URL`, the
  eight failed tests passed (8 passed in 103.4 s, separate seed). The four
  names were added together, so only the set is proven: the error proves the
  key pair is needed; whether region and endpoint are needed was not isolated.
- Queue usage over both passes: `import` 45 jobs
  (`cvat.apps.engine.task.create_thread`), `chunks` 5 jobs; `annotation`,
  `consensus`, `export`, `qualityreports`, `utils`, `webhooks`: none.
- Sum of per-container memory peaks about 3.8 GiB.
- Namespace deletion: 50 s; both PersistentVolumes were gone afterwards.

## M2: minimal candidate (`cveta2-it-m2`)

- Components: CVAT server, `import` and `chunks` workers, initializer Job,
  OPA, Redis (no persistence), kvrocks on `emptyDir`, PostgreSQL on
  `emptyDir`, one `hostpath` claim (5Gi) for `/home/django/data`; MinIO;
  ClearML API server, file server, MongoDB, Elasticsearch, Redis.
- Quota: pods 16, requests.cpu 3, requests.memory 6Gi, limits.memory 16Gi,
  persistentvolumeclaims 1, requests.storage 5Gi. LimitRange default request
  50m/128Mi, default limit 500m/512Mi, max 4 CPU/4Gi per container.
- Used at steady state: pods 13, requests.cpu 1250m, requests.memory 3840Mi,
  limits.memory 13056Mi, 1 claim, 5Gi. No quota rejection.
- Cold start with all images already in the local store: manifests applied 3 s
  after namespace creation; every pod Ready 70 s after creation. Per pod:
  chunks worker 5 s, MinIO 7 s, ClearML Redis 7 s, import worker 10 s,
  PostgreSQL 11 s, MongoDB 11 s, Elasticsearch 17 s, CVAT Redis 28 s,
  initializer finished 33 s, kvrocks 37 s, ClearML API 44 s, file server 54 s
  (2 restarts while waiting for the API), CVAT server 56 s, OPA 67 s.
- Bootstrap (register, organization): 0.3 s. Seeding runs inside the session
  fixture, which pytest charges to the first live test's setup; the slowest
  setup phase was 41.56 s on the first test, so seeding took at most about
  42 s; it was not measured on its own.
- Full live suite: **38 passed** in 307.7 s (wall 309 s), 0 failed.
- Queue usage: `import` 36 jobs, `chunks` 4 jobs.
- Peak memory per container (MiB): Elasticsearch 801, import worker 373,
  chunks worker 369, CVAT server 276, MongoDB 186, ClearML API 110, MinIO 109,
  PostgreSQL 61, kvrocks 53, file server 49, OPA 27, Redis 7 each. Sum of
  peaks about 2.4 GiB. Peak CPU: import and chunks workers about 1.2 cores
  each; everything else under 0.6 core.
- Namespace deletion: 50 s; the PersistentVolume was gone afterwards.

## Volume reclaim on the node

After M1 and M2 were deleted, a read-only probe pod in a separate quota'd
namespace (`cveta2-it-probe`) listed `/var/lib/k8s-pvs/cvat-backend-data`
(the `hostpath` provisioner's directory for that claim name): empty, 4.0K.
Deleting a session namespace therefore removes its `hostpath` data on the
node, not only the API objects.

## Images

`cvat/server:v2.59.1`, `openpolicyagent/opa:1.12.2`, `apache/kvrocks:2.12.1`,
`public.ecr.aws/docker/library/redis:7.2.11`, `postgres:15-alpine`,
`minio/minio:RELEASE.2025-09-07T16-13-09Z`,
`docker.io/allegroai/clearml:2.0.0-613`,
`docker.io/bitnamilegacy/mongodb:6.0.10-debian-11-r8`,
`docker.elastic.co/elasticsearch/elasticsearch:7.17.28` were present in the
local image store. The chart's permission-fix init container uses an untagged
`busybox` (that is `:latest`, pulled according to its pull policy); its
presence in the store was not checked, and the manifests must pin it. `cvat-sdk` is locked at 2.73.0 against server 2.59.1 and passed.

## Not measured

- Cold start with an empty image cache (first pull of the 2.4 GB CVAT image).
- Seeding time on its own (bounded above by about 42 s, see M2).
- Whether a single pod holding the CVAT server and both workers could replace
  the `hostpath` claim with `emptyDir`.
- Preflight, interruption, kept-session, vanished-namespace and concurrent
  session behavior of the future lifecycle tool (tasks T020-T021).
- Repeatability: one full minimal run; timings will vary with host load.

## Spec Kit analysis — 2026-11-10

Read-only cross-artifact pass over spec, plan, research, contracts and tasks,
then remediation by the author (no owner question was needed):

| ID | Severity | Finding | Disposition |
|---|---|---|---|
| A1 | High | FR-013/SC-005 listed bare helper names; `cvat.py` also names the product port `cveta2/application/ports/cvat.py` and appears in architecture.md | FR-013 names invocations of the helper scripts and exempts product modules; SC-005 gives an exact pattern scoped to scripts paths |
| A2 | Medium | SC-005 would match this feature's own records and older dated plans | Exclusions named: `specs/`, `docs/plans/`, `CHANGELOG.md` |
| A3 | Medium | Clarification implied namespace permission "under the prefix"; Kubernetes authorization cannot scope creation by name | Reworded: the prefix is the tool's rule, the check is create/delete namespaces |
| A4 | Low | Constitution IV keeps explicit operator waiting; spec did not say so | Added to FR-014 |
| A5 | Low | FR-020 and FR-021 had no explicit task | Mapped to T020 |
| A6 | Info | Constitution V conflict | Gated by T001 before any implementation |
| A7 | Medium | Prose naming the stands that SC-005 cannot see: the `integration` marker text in `pyproject.toml` and a comment in `tests/conftest.py` had no task (`git grep -i -E 'shared stand\|стенд\|the stands\|k8s-infra'` with the same exclusions) | Added to T019; every other hit is in a file a task already owns |
| A8 | Medium | Kept sessions: `.session` held only the name, but `env` and `stop` must find or recreate port-forwards, and ClearML stores absolute file-server URLs | `.session` records the four ports; `env` reuses them when free; `stop` matches port-forwards by exact namespace command line |

Coverage: every FR maps to at least one task; every task maps to an FR, SC or
verification gate. Running the SC-005 pattern on the current tree matched
exactly the files T006-T019 change (`.agents/skills/running-integration-tests/SKILL.md`,
`.gitignore`, `.specify/memory/engineering.md`, `scripts/mutation.py`,
`scripts/session_status.sh`, and `clearml_run.py`, `conftest.py`,
`cvat_stand.py`, `lifecycle.py`, `seed_cvat.py` under `tests/integration/`).
No unresolved critical or high finding remains.

## Cleanup

Deleted by exact name and waited for: `cveta2-it-m1`, `cveta2-it-m2`,
`cveta2-it-probe`. Afterwards (11:23:49 UTC) no `cveta2-it-*` namespace, no
PersistentVolume claimed from one, and no port-forward or sampler process of
this work remained. Two port-forwards of another agent's `cy-it-m5` namespace
were running and were left alone. The scratch directory, including the
throwaway credentials, was removed before committing.

# Implementation verification — 2026-11-10

Same worktree and branch. T020 and experiments 2, 4-7 ran on `d74addc`;
experiment 3 was rerun after the preflight fix `4bd3e32`, and the acceptance
below ran on `739c964`, which contains both. Host load average
about 4-6 on 32 CPUs. The shared stands still existed in the cluster; no test,
helper or variable referred to them (SC-005 below), and every exported host was
`http://127.0.0.1:<port>` of a session port-forward or the session's own
in-cluster MinIO Service.

## T020: live suite through Task (SC-001-SC-004)

- `task infra-check`: AVAILABLE, exit 0, nothing created.
- `task integration` (13:26:10-13:32:33 UTC): preflight AVAILABLE, then
  **38 passed** in 381.2 s, exit 0. Session `cveta2-it-20261110-132613-3b56`
  was created, used by the serial `live` group and reported deleted by the
  fixture. Afterwards no `cveta2-it-*` namespace, no session port-forward
  process and no `tests/integration/.session` remained.
- Kept session (`lifecycle up`, 13:18:02 UTC, 98 s wall): quota and limit
  range applied by their own `kubectl apply` before the workload apply; every
  service ready 51 s after creation; bootstrap, identity check and seeding
  passed. Quota use at steady state: pods 13/16, requests.cpu 1075m/3,
  requests.memory 3296Mi/6Gi, limits.memory 12032Mi/16Gi, 1/1 claim, 5Gi/5Gi
  storage, GPU 0/0. Namespace label `app.kubernetes.io/part-of=cveta2-integration`.

## T021: quickstart experiments

| # | Experiment | Outcome |
|---|---|---|
| 2 | `check` with a throwaway kubeconfig whose `docker-desktop` context is a ServiceAccount token minted in a quota'd `cveta2-it-probe-rbac` namespace | exit 1, "may not create namespaces"; nothing created; the probe namespace was deleted |
| 3 | `check` against an unreachable API server | **First run failed**: refused connection gave exit 1 because kubectl says "connection to the server ... was refused". Fixed in the preflight; rerun: exit 3 in under 1 s (refused) and exit 3 in 11 s with `CVETA2_INFRA_CHECK_TIMEOUT=10` (unroutable address) |
| 4 | Signal to the whole pytest process group while `seed_cvat.py` ran (`test_task_ops.py`, `-n 2`) | SIGINT: exit 130 after 7 s; the namespace was Terminating and gone by about 50 s later; no port-forward left. SIGTERM: exit 143; the namespace was gone 51 s later; no port-forward or worker process left |
| 5 | `up`, `env`, `stop`, `stop` again, `stop bogus-ns` | `env` refused a terminal only through its isatty check (not exercised here), printed 21 exports into a file (names checked, values not shown), restarted the 4 forwards on the recorded ports; CVAT `/api/server/about`, ClearML `debug.ping` and MinIO `/minio/health/ready` answered 200 through them. `stop` deleted the namespace (50 s), stopped the forwards and removed `.session`; the second `stop` by name reported "already gone" (exit 0); `stop` with nothing recorded exit 0; `bogus-ns` refused (exit 1) |
| 6 | Kept session deleted by hand, then `up` | `up` printed that the kept session no longer exists, forgot it and created a new namespace; `stop` of the vanished name succeeded as already gone |
| 7 | Two pytest runs at once in this checkout | Distinct namespaces (`...-c6db`, `...-f5b4`) and distinct local ports; both 5 passed; both namespaces and all forwards gone afterwards |

Experiments 4 and 7 used `pytest` directly with `CVETA2_TASK_VERIFICATION=1`,
the same options as the Task. Worker output under xdist is not shown, so the
teardown lines of experiment 4 were observed through the cluster, not the log.

## T022: SC-005

`git grep -E 'INFRA_RUN_TAG|INFRA_PROJECT|K8S_INFRA_SKILL_DIR|INFRA_REGISTRY|INTEGRATION_SKILL_DIR|infra\.py|scripts/(clearml|mongodb|cvat|lakefs|postgres|minio)\.py|--project cveta2|cveta2-main|\.run-tag' -- ':!specs/' ':!docs/plans/' ':!CHANGELOG.md'`
returned nothing.

## T024: mutation

`task mutation -- --base main`: "No changed cveta2 function can be mutated;
nothing to do." No product module changed in this feature.

## Not done here

- T025, a fresh independent review, was not run by the implementing agent.
- Cold start with an empty image cache is still unmeasured.
- Whether SIGTERM without the new handler leaked the namespace was not
  reproduced; the handler was added from reading pytest's default behavior.

## Acceptance on the clean tip `739c964`

`task acceptance` (13:54:48-14:01:55 UTC), exit 0: checks, build, randomized
properties (2384 passed), preflight AVAILABLE, then the full suite with
coverage, **2422 passed** (38 live) in 391.3 s, total coverage 92.23% (required
90%). Live session `cveta2-it-20261110-135527-99a4` was reported deleted;
afterwards no `cveta2-it-*` namespace and no session port-forward remained.
