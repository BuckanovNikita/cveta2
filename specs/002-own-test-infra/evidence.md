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
- Each namespace got a `ResourceQuota` and `LimitRange` before any workload.
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
  eight failed tests passed (8 passed in 103.4 s, separate seed).
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
- Bootstrap (register, organization): 0.3 s. Seeding was not among the five
  slowest test phases, so it took under 11.5 s.
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

## Images (all already present in the local image store)

`cvat/server:v2.59.1`, `openpolicyagent/opa:1.12.2`, `apache/kvrocks:2.12.1`,
`public.ecr.aws/docker/library/redis:7.2.11`, `postgres:15-alpine`,
`minio/minio:RELEASE.2025-09-07T16-13-09Z`,
`docker.io/allegroai/clearml:2.0.0-613`,
`docker.io/bitnamilegacy/mongodb:6.0.10-debian-11-r8`,
`docker.elastic.co/elasticsearch/elasticsearch:7.17.28`, and an untagged
`busybox` in the chart's permission-fix init container, which the manifests
must pin. `cvat-sdk` is locked at 2.73.0 against server 2.59.1 and passed.

## Not measured

- Cold start with an empty image cache (first pull of the 2.4 GB CVAT image).
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
