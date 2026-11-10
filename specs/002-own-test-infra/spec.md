# Feature Specification: Session-owned live-test infrastructure

**Feature Branch**: `feat/own-test-infra`

**Created**: 2026-11-10

**Status**: Draft

**Input**: Owner-approved plan `docs/plans/2026-11-09-managed-infrastructure-reset.md`
in the k8s-infra repository (rewritten 2026-11-10): its "Rules for every project",
the cveta2 block under "One-time migration for consumer projects", and the two
interim rules of its phase P5.

This changes how the live tests obtain their CVAT, MinIO and ClearML services, and
the development and operational policy around them. The product behavior in
[the baseline](../baseline.md), the public CLI and API, and
[the dataset contract](../../docs/dataset-contract.md) remain unchanged. The
tests themselves keep their assertions; only the services they run against move.

## Context

The shared CVAT, MinIO and ClearML stands of the docker-desktop cluster, the
k8s-infra helper scripts (`infra.py`, `cvat.py`, `minio.py`, `clearml.py`), run
tags, capacity WAIT, the durable `cveta2-main` slot and the project's shared
credentials are being retired. They are deleted in one sitting without backup.
After that, every live session deploys and removes its own services in the
cluster. cveta2 is migrated first so that it never loses its live tests to the
wipe.

## Clarifications

### Session 2026-11-10

Answered from the approved plan and from the dated measurements in
[evidence.md](evidence.md); no question was left to the owner.

- Q: One deployment per test session, or one long-lived deployment reused by sessions? → A: One per session. The plan's outcome is "its own CVAT, MinIO and ClearML per test session"; a namespace may also vanish at 48 hours or after a restart, so nothing durable is relied on.
- Q: What replaces the durable `cveta2-main` slot and its "keep on `main`" default? → A: Nothing durable. Every session is stopped after its last live test, on `main` too. `INTEGRATION_KEEP_DATA=1` still keeps a session for inspection until an explicit stop or the platform sweeper removes it.
- Q: What identifies a session's resources now that run tags are gone? → A: One namespace per session, named `cveta2-it-<id>`, where `<id>` is generated locally and unique. Teardown deletes that exact namespace and nothing else.
- Q: How does the host reach the services? → A: Only through `kubectl port-forward` on the loopback interface, started and stopped by the session (interim rule until platform name lookup is proven; the plan's rule 9). Traffic is plain HTTP over loopback; no Ingress, host name or local CA is used.
- Q: Which storage? → A: `emptyDir` wherever the data may die with its pod. Where several pods must share files (CVAT's data directory, shared by the server and its workers) a claim is unavoidable and names `storageClassName: hostpath` explicitly, because the cluster currently has two default classes. Nothing references `local-path` or `/mnt/wsl/data/k8s-volumes`.
- Q: Which CVAT components? → A: The minimal set the measurements showed the suite needs, which must include the chunks worker (tests read frames with `quality="original"`). The frontend, analytics, serverless functions and any worker the suite does not use are not deployed. The exact set is recorded in [research.md](research.md).
- Q: Which ClearML components? → A: API server, file server and their stores only (no web UI, agent or async-delete service), as measured. Datasets upload through the file server.
- Q: Which identity do the tests use in the fresh CVAT? → A: A regular (non-superuser) user created through CVAT's public registration API by the session, owning one organization it creates. The organization is still required because the tests run organization-scoped.
- Q: How are credentials handled? → A: Generated per session, held only in the session namespace's Secrets and the test process environment; never written to tracked files, never logged. `lifecycle env` keeps refusing to print to a terminal.
- Q: What does preflight and deferral mean without registry capacity? → A: The bounded read-only check keeps its exit codes (0 AVAILABLE, 3 UNAVAILABLE, 1 ERROR) and `CVETA2_INFRA_CHECK_TIMEOUT`. It checks cluster access, the right to create and delete namespaces (Kubernetes authorization cannot restrict this to a name prefix; the prefix is the tool's own rule), and whether the node's allocatable resources can admit the session quota. A cluster that does not answer or a node that cannot admit the quota is UNAVAILABLE; a missing tool or a forbidden action is ERROR. A session whose services do not become ready within its bounded cold-start deadline is blocked setup and is torn down.
- Q: May several sessions run at once (several worktrees or agents)? → A: Yes. Each owns its own namespace and local ports; the only shared limit is the node, which preflight checks. There is no project-wide run cap.
- Q: Which versions? → A: The CVAT server version the suite is verified against today stays pinned; changing it is a separate change. Images are pinned by tag in the project's own manifests.
- Q: Where do the manifests come from now that the k8s-infra CVAT stand and its upstream chart submodule are dropped? → A: cveta2 owns plain Kubernetes manifests in its own repository, applied with `kubectl`. Helm is not a prerequisite of a live run.

## User Scenarios & Testing

### User Story 1 - Run the live suite on services the session owns (Priority: P1)

A contributor or agent runs the live tests. The session creates its own namespace
with a quota, deploys CVAT, MinIO and ClearML, seeds them, runs the suite and
removes everything, with no dependency on shared stands or k8s-infra helpers.

**Why this priority**: The shared stands are about to be wiped; without this the
project has no live verification and acceptance is blocked.

**Independent Test**: With only the docker-desktop cluster and the project
checkout, run the integration task; observe the namespace appear with a quota,
the suite pass, and the namespace and port-forwards disappear.

**Acceptance Scenarios**:

1. **Given** a reachable cluster and no k8s-infra skill installed, **when** the integration task runs, **then** the session creates `cveta2-it-<id>` with a quota and limit range before any workload, deploys the services, seeds the run and the full live suite passes.
2. **Given** a passing or failing session, **when** the last live test ends, **then** the namespace is deleted, the session waits until it is gone, its port-forwards are stopped, and the report names the deleted namespace.
3. **Given** `INTEGRATION_KEEP_DATA=1`, **when** the session ends, **then** the namespace and its credentials stay and the report names the exact stop command.
4. **Given** the tests read `CVAT_INTEGRATION_HOST/USER/PASSWORD/ORG/PROJECT`, `MINIO_*` and `CLEARML_*`, **when** a session is prepared, **then** the same names carry this session's values.

---

### User Story 2 - Defer honestly when the cluster cannot run a session (Priority: P2)

A contributor learns in bounded time whether a live session can start, and a
session that cannot become ready leaves nothing behind.

**Why this priority**: The constitution's deferral rules must keep holding without
the registry and capacity WAIT they were built on.

**Independent Test**: Run `infra-check` with the cluster stopped, with a context
that cannot create namespaces, and with a reachable cluster; observe exit codes
3, 1 and 0 within the deadline and no namespace created.

**Acceptance Scenarios**:

1. **Given** the cluster does not answer, **when** preflight runs, **then** it reports UNAVAILABLE (exit 3) within `CVETA2_INFRA_CHECK_TIMEOUT` and creates nothing.
2. **Given** the context cannot create or delete namespaces, or `kubectl` is missing, **when** preflight runs, **then** it reports ERROR (exit 1).
3. **Given** the node cannot admit the session quota, **when** preflight runs, **then** it reports UNAVAILABLE.
4. **Given** services that do not become ready within the cold-start deadline, **when** setup runs, **then** setup is reported as blocked, the namespace is deleted, and no assertion result is claimed.

---

### User Story 3 - Recover from interruption and vanished namespaces (Priority: P3)

A contributor can always clean up after a crash and can start a new session after
the platform sweeper removed an old namespace.

**Why this priority**: The platform may delete any project namespace at 48 hours
or after a restart, and interrupted sessions must not leak namespaces.

**Independent Test**: Interrupt a session during seeding, then stop it by name;
delete a kept namespace by hand and start a new session.

**Acceptance Scenarios**:

1. **Given** an interrupted session, **when** the interruption is handled, **then** the session's own namespace is deleted unless keeping was requested, and a failed deletion is reported with the exact retry command.
2. **Given** a kept or leaked session, **when** the operator runs `stop` for it, **then** only that exact namespace is deleted.
3. **Given** a session namespace that no longer exists, **when** a new session starts, **then** it creates a fresh namespace without manual repair, and `stop` of the vanished one reports it as already gone.
4. **Given** several worktrees, **when** each starts a session, **then** each gets its own namespace and ports and none acts on another's.

### Edge Cases

- The namespace is deleted by the sweeper or a restart while tests run: remaining tests fail as lost infrastructure (blocked setup is only before the first test), and teardown treats an absent namespace as removed.
- A local port chosen for a port-forward is taken: the session picks another free loopback port; it never reuses a port another process holds.
- A port-forward dies mid-run: the session reports which service connection was lost.
- Namespace deletion hangs in `Terminating`: the session reports it as incomplete cleanup with the namespace name and does not report success.
- A second `stop` for the same session: it succeeds as already removed.
- A namespace with the prefix that the current session did not create: never touched by automatic teardown; only an explicit `stop <name>` acts on it.
- Images not yet in the local image store: the first cold start is slower; the deadline must allow for that or report it as blocked setup rather than as a failed test.

## Requirements

### Functional Requirements

- **FR-001**: Each live session MUST deploy its own CVAT, MinIO and ClearML into a namespace it creates, from manifests owned by this repository, and MUST remove them through its own teardown.
- **FR-002**: Session namespaces MUST be named `cveta2-it-<id>` with a locally generated unique `<id>`, and MUST NOT reuse a platform-protected name (`default`, `kube-*`, `ingress-nginx`, `infra-janitor`, `clearml`, `mongodb`).
- **FR-003**: Each session namespace MUST carry a `ResourceQuota` and a `LimitRange` chosen by the project, created before any workload. Every container MUST declare requests and limits that fit that quota.
- **FR-004**: Disposable data MUST use `emptyDir`. A claim MAY exist only where several pods must share data, and it MUST name `storageClassName: hostpath`. Nothing MAY reference `local-path` or `/mnt/wsl/data/k8s-volumes`.
- **FR-005**: The host MUST reach every service only through `kubectl --context docker-desktop port-forward` bound to `127.0.0.1` and started and stopped by the session. The services MUST NOT publish an Ingress, a NodePort or a host port.
- **FR-006**: The CVAT deployment MUST include the chunks worker and every other component the live suite needs, and MUST NOT include components it does not need (frontend, analytics, serverless functions, unused queues).
- **FR-007**: The ClearML deployment MUST provide the API and file server the dataset tests use, with no web UI, agent or GPU. No session MAY use the platform's dedicated ClearML or FiftyOne MongoDB.
- **FR-008**: No workload MAY request `nvidia.com/gpu`.
- **FR-009**: The session MUST bootstrap a regular CVAT user and an organization owned by it, and a ClearML key pair, through the services' own interfaces, with credentials generated per session.
- **FR-010**: Session credentials MUST exist only in the session namespace's Secrets and the test process environment. They MUST NOT be printed, logged or written to tracked files; `lifecycle env` MUST refuse to print to a terminal.
- **FR-011**: The session MUST export the names the tests read today: `INTEGRATION_RUN_TAG`, `CVAT_INTEGRATION_HOST/USER/PASSWORD/ORG/PROJECT`, `MINIO_ENDPOINT`, `MINIO_ENDPOINT_FOR_CVAT`, `MINIO_ACCESS_KEY/SECRET_KEY/REGION/BUCKET`, the `CLEARML_API_HOST`, `CLEARML_FILES_HOST`, `CLEARML_WEB_HOST`, `CLEARML_API_ACCESS_KEY` and `CLEARML_API_SECRET_KEY` identity, and the standard `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_DEFAULT_REGION` and `AWS_ENDPOINT_URL` for the session's MinIO. The k8s-infra MinIO helper exported the AWS names implicitly; eight live tests fail with `NoCredentialsError` without them and passed with all four set (measured as a set; see [evidence.md](evidence.md)). `INTEGRATION_RUN_TAG` carries the session identifier that names the run's objects. Names the tests do not read (for example the helpers' `CVAT_URL`, `CVAT_TOKEN`, `S3_*` and CA-bundle variables) are not exported.
- **FR-012**: `tests/integration/lifecycle.py` MUST no longer mint run tags, call `infra.py room` or `newtag`, read the k8s-infra registry or skill, or call any k8s-infra helper. The durable `cveta2-main` slot and adoption through `INFRA_RUN_TAG` MUST be removed.
- **FR-013**: The repository MUST NOT reference `INFRA_RUN_TAG`, `INFRA_PROJECT`, `K8S_INFRA_SKILL_DIR`, `INFRA_REGISTRY`, `INTEGRATION_SKILL_DIR`, or invoke the k8s-infra helper scripts `infra.py`, `clearml.py`, `mongodb.py`, `cvat.py`, `lakefs.py`, `postgres.py` or `minio.py`, in code, tests, scripts, skills or guidance; feature records under `specs/`, dated records under `docs/plans/` and `CHANGELOG.md` keep their history. The product's own modules that share a helper's file name (for example `cveta2/application/ports/cvat.py`) are not helpers and stay.
- **FR-014**: Preflight MUST stay bounded by `CVETA2_INFRA_CHECK_TIMEOUT`, read-only and creation-free, with exit codes 0 AVAILABLE, 3 UNAVAILABLE and 1 ERROR as clarified above. Explicit operator waiting for an unavailable cluster (`CVETA2_STAND_WAIT_TIMEOUT`) remains available outside Task-driven runs.
- **FR-015**: Setup MUST be bounded by a cold-start deadline. Services not ready in time MUST be reported as blocked setup, and the namespace MUST be deleted.
- **FR-016**: Teardown MUST delete exactly the session's namespace, wait until it is gone within a bounded time, stop the session's port-forwards, and report incomplete cleanup by namespace name with the exact retry command. It MUST run on success, failure and interruption unless keeping was requested.
- **FR-017**: `lifecycle` MUST keep `check`, `up`, `env` and `stop`. `up` starts a kept session; `stop` accepts the session to stop and removes only that namespace; `env` prints the session's variables for a session started by `up`.
- **FR-018**: A vanished namespace MUST NOT require manual repair: a new session creates a new namespace, and stopping a vanished session succeeds as already removed.
- **FR-019**: Concurrent sessions from different worktrees MUST NOT share a namespace, a local port or credentials.
- **FR-020**: A session MUST finish well inside the platform's 48-hour namespace lifetime; no test may depend on data from an earlier session.
- **FR-021**: Live tests MUST stay one serial `live` xdist group, with `--dist loadgroup` and the existing environment isolation.
- **FR-022**: The constitution, engineering guidance, `AGENTS.md`, the `running-integration-tests` and `verification-workflow` skills, the Russian `README.md` and the repository scripts that know run tags MUST describe the session-owned model, with no instruction to use shared stands.

### Key Entities

- **Session**: one live run; identified by its namespace name; owns its services, credentials, local ports and seed data; kept or stopped at its end.
- **Session namespace**: `cveta2-it-<id>` with its quota and limit range; the unit of deployment, teardown and sweeper lifetime.
- **Service set**: the CVAT, MinIO and ClearML components a session deploys, with pinned images and declared resources.
- **Port-forward**: a session-owned `kubectl port-forward` process mapping one service to a loopback port.

## Success Criteria

### Measurable Outcomes

- **SC-001**: The full live suite passes against a session's own services on a machine without the k8s-infra skill, shared stands or local CA trust.
- **SC-002**: After every session, passed, failed or interrupted, no namespace and no port-forward process of that session remains unless keeping was requested.
- **SC-003**: With images already in the local image store, a session is ready to seed within five minutes of namespace creation.
- **SC-004**: Every session namespace carries a quota from the moment it exists; no pod is rejected by the quota during a full suite.
- **SC-005**: `git grep -E 'INFRA_RUN_TAG|INFRA_PROJECT|K8S_INFRA_SKILL_DIR|INFRA_REGISTRY|INTEGRATION_SKILL_DIR|infra\.py|scripts/(clearml|mongodb|cvat|lakefs|postgres|minio)\.py|--project cveta2|cveta2-main|\.run-tag'` is empty outside the feature records under `specs/`, the dated records under `docs/plans/` and `CHANGELOG.md`.
- **SC-006**: Preflight returns within its deadline with the documented exit code in each scenario of User Story 2.

## Assumptions

- The docker-desktop cluster and `kubectl` with the `docker-desktop` context are available to the contributor; Helm is not required.
- Docker Desktop's `hostpath` class exists and is usable for the one shared claim; after the platform wipe it is the only default class.
- The service images are pulled once into the local image store; later sessions start from cache.
- The platform sweeper may delete the namespace at any time after 48 hours or after a restart; sessions are far shorter.
- Removing the variables of FR-013 from contributors' shell profiles is an operator step outside the repository; the guidance names it.
- The suite's assertions and fixtures, the CVAT SDK, the server version and the dataset contract are unchanged by this feature.
