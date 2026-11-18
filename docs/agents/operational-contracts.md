# Operational contracts

These maintained engineering requirements retain the verification and session-lifecycle
obligations formerly specified in features 001 and 002. They do not assert implementation
or acceptance status. Source mapping: `specs/001-task-verification/spec.md` and
`specs/002-own-test-infra/spec.md` at migration baseline `63cd255`, plus feature 002's
`contracts/environment.md` and `contracts/lifecycle-cli.md`. Frozen originals remain
historical evidence. Requirements embedded in scenarios remain binding.

Feature 002 supersedes feature 001's shared-stand capacity, trust and cleanup model.
The approved Linear/GitHub migration supersedes feature 001 FR-009/010 and feature 002
FR-022 only in workflow authority and delivery; amendments are identified below.
Executable values remain in maintained Task/configuration/manifests. Human workflows
and current skill instructions govern execution; these contracts govern outcomes.

## Development verification (feature 001)

### Preserved session clarifications from feature 002

There is no project-wide run cap: concurrent sessions are limited by node admission,
each owning its namespace and local ports. Namespace prefixes are enforced by the
lifecycle tool, not namespace-create RBAC. Sessions are stopped by default on `main`
too; only an explicit keep override retains them. ClearML deploys its API server,
file server and stores, without a web UI, agent or async-delete service. The session
creates a regular non-superuser CVAT account through the public registration API
and an organization it owns. CVAT remains pinned to the verified server version;
changing that version is a separate change. Repository-owned plain Kubernetes
manifests are applied with `kubectl`; Helm is not required. Manifest image tags stay
pinned. Loopback port-forwards use plain HTTP without Ingress or a local CA.

## User Scenarios & Testing

### User Story 1 - Verify a change once (Priority: P1)

A contributor runs explicit safe fixes, stages the complete change and verifies
it without duplicate stages or unnecessary execution of unaffected unit tests.

**Why this priority**: Reduce redundant work while preserving meaningful checks.

**Independent Test**: In a disposable checkout, observe initial, unchanged,
changed-input, failure and interrupted runs and their actual execution counts.

**Acceptance Scenarios**:

1. **Given** successful unit history, **when** unchanged inputs are checked again,
   **then** unaffected tests are omitted while required static commands still run.
2. **Given** changed Python behavior, **when** verification runs, **then** affected
   tests run; failed tests run again on the next attempt.
3. **Given** configuration, dependency, static asset or relative file membership
   changes, **when** units run, **then** conservative coverage uses a fresh baseline for an unseen input namespace;
   matching verified history may be reused when inputs revert.
4. **Given** an interrupted command, **when** a contributor reports completion,
   **then** that run cannot establish successful verification.

### User Story 2 - Commit in isolated worktrees (Priority: P2)

A contributor commits fully staged repository inputs with checks applying to the
invoking worktree, while older worktrees retain their previous workflow.

**Why this priority**: Prevent claims about staged content that was not verified.

**Independent Test**: Exercise staged, partially staged, untracked and ignored
inputs, and new and legacy worktree hook paths, in disposable repositories.

**Acceptance Scenarios**:

1. **Given** unstaged tracked or nonignored untracked inputs, **when** a commit
   starts, **then** it is rejected before the hook runner can hide inputs.
2. **Given** two worktrees, **when** their hooks run, **then** each uses its own
   configuration, environment and mutable verification data.
3. **Given** an older worktree, **when** shared hooks run, **then** its existing
   configuration remains usable and the prior hook installation is recoverable.

### User Story 3 - Defer unavailable live verification (Priority: P3)

A contributor receives a bounded infrastructure result and can continue local
work while live acceptance remains explicitly incomplete.

**Why this priority**: An unavailable stand must neither stall unrelated work nor
silently become a passed acceptance gate.

**Independent Test**: Observe bounded available, unavailable and erroneous
preflights, then exercise actual live acceptance and exact-namespace cleanup when available.

**Acceptance Scenarios**:

1. **Given** a temporary cluster outage or inability to admit the session quota, **when** preflight runs,
   **then** it reports UNAVAILABLE and exits 3 within the configured deadline.
2. **Given** missing prerequisites, credentials or authorization,
   **when** preflight runs, **then** it reports ERROR and exits 1.
3. **Given** available services, **when** preflight runs, **then** it reports
   AVAILABLE and exits 0 without creating a namespace or service resources.
4. **Given** deferred live checks, **when** local work finishes, **then** acceptance,
   merge and release remain blocked pending successful live verification.

### Edge Cases

Failed setup with owned resources requires exact-namespace cleanup and a leftovers
report. Loss of availability during setup is blocked setup; assertion failures
remain test failures. Interruptions provide no success evidence. Additions,
removals and moves use full relative paths. Explicit operator waits remain
available; default verification waits are bounded. No concurrent edits and
verification may run within one worktree.

## Requirements

### Functional Requirements

- **FR-001**: Each verification run MUST invoke each required command once,
  preserving failures and distinguishing execution from affected-test omission.
- **FR-002**: Unit selection MUST cover changed Python behavior and failed tests;
  untracked dependency inputs MUST conservatively invalidate the baseline.
- **FR-003**: Automatic safe fixes MUST be explicit and MUST NOT stage files.
- **FR-004**: Commits MUST reject unstaged tracked and nonignored untracked inputs
  before running verification; Conventional Commit validation MUST remain active.
- **FR-005**: Worktrees MUST isolate mutable environments, history and caches,
  preserve legacy hooks and retain a recoverable prior installation.
- **FR-006**: Read-only preflight MUST preserve outcomes 0/3/1 and use a configurable
  overall deadline defaulting to 60 seconds; live runs MUST recheck availability.
- **FR-007**: Deferred checks MUST be reported separately from failures, MUST block
  acceptance/merge/release, and MUST allow independent local work to continue.
- **FR-008**: Acceptance MUST require a clean tip, checks, packaging, randomized
  properties and full-suite coverage including live tests without a preceding
  duplicate affected-unit stage.
- **FR-009 (amended by the approved workflow migration)**: Humans integrate GitHub PRs. Code releases are suspended. Replacement tooling must retain shared locking, semantic-release ownership, accepted-source checks and separate publication authorization. Any restored version/changelog/lockfile exception requires explicit release checks.
- **FR-010 (amended by the approved workflow migration)**: Authored guidance and skills MUST expose one Linear/PR completion procedure. Generated Spec Kit tools remain archived unchanged; the dataset glossary remains maintained domain vocabulary.
- **FR-011**: Verification MUST use no persisted completion receipts or orchestration
  freshness to infer success. Mutation survivors remain advisory; tool errors
  remain unresolved. Property, mutation, preflight and live checks are never cached.
- **FR-012**: Packaging MUST clean only uniquely owned temporary output; shared
  services and unrelated resources MUST remain intact.

## Success Criteria

### Measurable Outcomes

- **SC-001**: Dated experiments record commands, exit codes, selected tests and
  execution counts for every scenario in US1 and US2.
- **SC-002**: An unchanged unit repeat executes fewer tests than its initial run;
  every changed-input scenario receives the required coverage.
- **SC-003**: Availability outcomes and interruptions propagate without any false
  success claim, and unavailable live acceptance remains visibly incomplete.
- **SC-004**: Integrated verification and fresh independent review establish one
  discoverable procedure shared by both agent hosts.


## Session-owned integration infrastructure (feature 002)

## User Scenarios & Testing

### User Story 1 - Run the live suite on services the session owns (Priority: P1)

A contributor or agent runs the live tests. The session creates its own namespace
with a quota, deploys CVAT, MinIO and ClearML, seeds them, runs the suite and
removes everything, with no dependency on shared stands or k8s-infra helpers.

**Why this priority**: Live verification must remain independent of shared stands.

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

**Why this priority**: Bounded preflight must preserve honest deferral with session-owned infrastructure.

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
- **FR-011**: The session MUST export the names the tests read today: `INTEGRATION_RUN_TAG`, `CVAT_INTEGRATION_HOST/USER/PASSWORD/ORG/PROJECT`, `MINIO_ENDPOINT`, `MINIO_ENDPOINT_FOR_CVAT`, `MINIO_ACCESS_KEY/SECRET_KEY/REGION/BUCKET`, the `CLEARML_API_HOST`, `CLEARML_FILES_HOST`, `CLEARML_WEB_HOST`, `CLEARML_API_ACCESS_KEY` and `CLEARML_API_SECRET_KEY` identity, and the standard `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_DEFAULT_REGION` and `AWS_ENDPOINT_URL` for the session's MinIO. `INTEGRATION_RUN_TAG` carries the session identifier that names the run's objects. Names the tests do not read (for example the helpers' `CVAT_URL`, `CVAT_TOKEN`, `S3_*` and CA-bundle variables) are not exported.
- **FR-012**: Lifecycle code uses only session-owned namespaces, never the retired shared-stand registry, helpers, durable slot or adoption mechanism.
- **FR-013**: Code, tests, scripts, skills and active guidance must not reference the retired shared-stand variables or invoke its helpers. The exact retired names remain documented in frozen `specs/002-own-test-infra/spec.md`, FR-013, for removal audits. Historical archives, dated evidence and changelog retain provenance; product modules sharing a helper filename remain valid product modules.
- **FR-014**: Preflight MUST stay bounded by `CVETA2_INFRA_CHECK_TIMEOUT`, read-only and creation-free, with exit codes 0 AVAILABLE, 3 UNAVAILABLE and 1 ERROR as clarified above. Explicit operator waiting for an unavailable cluster (`CVETA2_STAND_WAIT_TIMEOUT`) remains available outside Task-driven runs.
- **FR-015**: Setup MUST be bounded by a cold-start deadline. Services not ready in time MUST be reported as blocked setup, and the namespace MUST be deleted.
- **FR-016**: Teardown MUST delete exactly the session's namespace, wait until it is gone within a bounded time, stop the session's port-forwards, and report incomplete cleanup by namespace name with the exact retry command. It MUST run on success, failure and interruption unless keeping was requested.
- **FR-017**: `lifecycle` MUST keep `check`, `up`, `env` and `stop`. `up` starts a kept session; `stop` accepts the session to stop and removes only that namespace; `env` prints the session's variables for a session started by `up`.
- **FR-018**: A vanished namespace MUST NOT require manual repair: a new session creates a new namespace, and stopping a vanished session succeeds as already removed.
- **FR-019**: Concurrent sessions from different worktrees MUST NOT share a namespace, a local port or credentials.
- **FR-020**: A session MUST finish well inside the platform's 48-hour namespace lifetime; no test may depend on data from an earlier session.
- **FR-021**: Live tests MUST stay one serial `live` xdist group, with `--dist loadgroup` and the existing environment isolation.
- **FR-022 (amended by the approved workflow migration)**: Active engineering guidance, `AGENTS.md`, the `running-integration-tests` and `verification-workflow` skills, the Russian `README.md` and the repository scripts that know run tags MUST describe the session-owned model, with no instruction to use shared stands.

### Key Entities

- **Session**: one live run; identified by its namespace name; owns its services, credentials, local ports and seed data; kept or stopped at its end.
- **Session namespace**: `cveta2-it-<id>` with its quota and limit range; the unit of deployment, teardown and sweeper lifetime.
- **Service set**: the CVAT, MinIO and ClearML components a session deploys, with pinned images and declared resources.
- **Port-forward**: a session-owned `kubectl port-forward` process mapping one service to a loopback port.


## Session infrastructure acceptance outcomes

- The full live suite must pass without shared stands, external infrastructure skills
  or local CA trust.
- Passed, failed and interrupted sessions must leave no owned namespace or forwarding
  process unless keeping was requested.
- With service images cached, readiness to seed must fit the configured five-minute
  cold-start target; failure to become ready is blocked setup, not an assertion result.
- Quota exists before workload creation and admits every container in a full suite.
- The retired-variable/helper removal audit in frozen feature 002 SC-005 must remain
  satisfied outside historical archives, dated evidence and changelog. This migration
  preserves archived skills as historical sources, never as active helper instructions.
- Preflight must return its documented outcome within its deadline in all scenarios.

The cluster and configured context must exist. Shared-volume claims use the hostpath
class; first image pulls can consume cold-start time. Sessions must tolerate sweeper
or restart deletion and never depend on earlier session data. Removing obsolete shell
profile variables is an operator responsibility. Suite assertions, CVAT SDK/server
version and product dataset contracts are unaffected by the workflow migration.

## Setup and cleanup safeguards

Preflight admits only Ready, uncordoned nodes without an untolerated
`NoSchedule` or `NoExecute` taint. Connectivity lost during later probes remains
UNAVAILABLE; an authorization refusal remains ERROR.

`CVETA2_SESSION_SEED_TIMEOUT` bounds stand verification, image download and
seeding together. Socket activity does not extend this deadline. An interrupted
or timed-out child gets a bounded cleanup grace period, then its entire owned
process group is terminated, including descendants whose leader has exited.
Teardown requests namespace deletion before stopping forwards and waiting for
deletion. A namespace create with an uncertain result authorizes automatic
cleanup only when its per-session token matches. Blocked setup is cleaned even
when keeping was requested; a new kept run refuses an existing live session
record rather than overwriting it.

## Session environment interface

Every live test and helper reads these names; their values describe the current
session. Values are never printed except by `lifecycle env` into a pipe.

| Name | Value |
|---|---|
| `INTEGRATION_RUN_TAG` | the session namespace |
| `CVAT_INTEGRATION_HOST` | `http://127.0.0.1:<port>` of the CVAT backend port-forward |
| `CVAT_INTEGRATION_USER` / `CVAT_INTEGRATION_PASSWORD` | the session's regular CVAT user |
| `CVAT_INTEGRATION_ORG` | the organization that user owns |
| `CVAT_INTEGRATION_PROJECT` | `<namespace> coco8-dev` |
| `MINIO_ENDPOINT` | `http://127.0.0.1:<port>` of the MinIO port-forward |
| `MINIO_ENDPOINT_FOR_CVAT` | the in-cluster MinIO Service URL |
| `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` / `MINIO_REGION` | the session MinIO credentials and region |
| `MINIO_BUCKET` | the session namespace |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_DEFAULT_REGION` / `AWS_ENDPOINT_URL` | the same MinIO, for boto's default chain |
| `CLEARML_API_HOST` / `CLEARML_FILES_HOST` | `http://127.0.0.1:<port>` of the API and file-server port-forwards |
| `CLEARML_WEB_HOST` | the API URL (no web UI is deployed) |
| `CLEARML_API_ACCESS_KEY` / `CLEARML_API_SECRET_KEY` | the session's ClearML key pair |

The names exported by the session are listed in `CVETA2_LIVE_EXPORTED`, so
`tests/conftest.py` keeps hiding them from unit tests.


## Session lifecycle interface

Standard library only, as today. Every cluster call uses
`kubectl --context docker-desktop`. Output lines keep the `==> ` and `ERROR:`
shapes; nothing prints a credential.

| Command | Behavior | Exit |
|---|---|---|
| `check` | Read-only preflight within `CVETA2_INFRA_CHECK_TIMEOUT` (default 60 s): kubectl present, cluster ready, namespace create/delete allowed, node can admit the session quota. Creates nothing. | 0 AVAILABLE, 3 UNAVAILABLE, 1 ERROR |
| `up` | Preflight (or explicit operator wait), create a session, deploy, wait (cold-start deadline `CVETA2_SESSION_READY_TIMEOUT`, default 300 s), bootstrap, seed; keep it and record it in `tests/integration/.session`; stop its own port-forwards on exit. Refuses while `.session` names a namespace that still exists; forgets a recorded namespace that vanished. | 0, 3 blocked setup, 1 error |
| `env [<namespace>]` | Refuses a terminal first. For the recorded (or given) session: stop that namespace's earlier port-forwards, read its credentials from its Secrets, start port-forwards on the recorded ports when free (else new ports, with a warning that stored ClearML file URLs may not resolve, and the record is updated), print `export NAME=<quoted>` lines for the names in [session environment](#session-environment-interface). These forwards outlive the command until `stop`. | 0, 1 |
| `stop [<namespace>]` | Delete exactly the given or recorded `cveta2-it-*` namespace and wait until it is gone; stop the port-forwards whose command line is exactly `kubectl --context docker-desktop -n <namespace> port-forward ...`; remove `.session` when it names it. An absent namespace is success, and so is `stop` without a name when nothing is recorded. A name without the prefix is refused. | 0, 1 incomplete cleanup or refused name |

Session fixture (`tests/integration/conftest.py::live_run`): `prepare` performs
`up` without recording `.session`; `finish` stops the session unless
`INTEGRATION_KEEP_DATA=1`, in which case it records `.session` and prints the
exact `stop` command. A teardown failure fails the session with the namespace
name and the retry command, as today.

Retained: `CVETA2_TASK_VERIFICATION=1` bounded setup, `CVETA2_STAND_WAIT_TIMEOUT`
for explicit operator waiting on an unavailable cluster, the `UNAVAILABLE:` and
`ERROR:` reporting, waiting for an interrupted child before teardown.
