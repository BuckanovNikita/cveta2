# Research: Session-owned live-test infrastructure

Decisions for [spec.md](spec.md). Measured facts and their dates are in
[evidence.md](evidence.md); this file keeps the decisions, why, and what was
rejected. Numbers (quota, resources, deadlines) belong to the manifests and the
evidence, not here.

## R1. Manifest source

**Decision**: cveta2 commits plain Kubernetes manifests under
`tests/integration/k8s/` and applies them with `kubectl`. The CVAT part is
derived once from the upstream CVAT Helm chart at the pinned server release with
the frontend, analytics, serverless functions, Traefik, Ingress and unused
workers removed, then maintained as plain YAML with a header naming the chart
version it came from.

**Rationale**: The k8s-infra `cvat/` submodule, its values and its PostgreSQL
manifest are retired with the shared stand. Plain manifests make Helm an
unnecessary prerequisite and keep the reviewable component set small. The
measurement rendered the chart with `helm template` only to obtain correct
CVAT wiring; the render contains no cluster-scoped object.

**Alternatives rejected**: running `helm install` per session (adds a tool and
release Secrets; teardown would want `helm uninstall`, while deleting the
namespace already removes everything); vendoring the whole chart (carries
dependency subcharts the session never runs); depending on another repository's
chart at run time (the session must work from this checkout alone).

## R2. CVAT component set

**Decision**: backend server, the `import` and `chunks` workers, the
initializer Job (migrations), OPA, Redis (in-memory queues and cache), kvrocks
(on-disk cache) and PostgreSQL. No frontend, no `annotation`, `export`,
`webhooks`, `qualityreports`, `consensus` or `utils` workers, no analytics,
no Nuclio, no Traefik.

**Rationale**: With every worker deployed, only the `import` queue (task
creation, `create_thread`) and the `chunks` queue received jobs during two full
suite runs; the minimal set then passed the whole suite. The chunks worker is
required because tests read frames with `quality="original"`. OPA is consulted
by every permission check. kvrocks is the chunk cache store the server and
chunks worker use.

**Alternatives rejected**: the shared stand's full set (eight workers and a
frontend: more memory and start time for queues the suite never uses).

## R3. Storage

**Decision**: `emptyDir` for PostgreSQL, Redis, kvrocks, MinIO and every
ClearML store. One claim, CVAT's shared data directory (`/home/django/data`,
mounted by the server, the import worker and the chunks worker), with
`storageClassName: hostpath`, `ReadWriteOnce` (single node), small size. Redis
persistence is off.

**Rationale**: The plan prefers `emptyDir` and allows an explicitly named
`hostpath` claim where unavoidable. An `emptyDir` is per pod, while the server
and two workers are separate pods that read each other's files (task data and
chunks). Deleting the namespace released the `hostpath` volumes in the
measurements: the PersistentVolumes were gone on deletion and the claim's
directory on the node was empty afterwards.

**Alternatives considered, not measured**: one pod holding the server and both
workers as containers sharing one `emptyDir`. It would remove the last claim but
departs from the upstream layout, and the CVAT images run supervisord per
container; left as a possible follow-up, not a requirement.

## R4. ClearML component set and identity

**Decision**: API server, file server, MongoDB, Elasticsearch (single node,
security off, 7.17 line) and Redis. No web UI, agent, async-delete service or
GPU. The session generates the server's `apiserver` and `tests` credential pairs
and the auth token secret into a namespace Secret; the tests use the `tests`
pair as `CLEARML_API_ACCESS_KEY/SECRET_KEY`. `CLEARML_WEB_HOST` points at the
API port-forward because no web UI is deployed and the tests do not open it.

**Rationale**: Dataset tests upload through the file server and query through
the API; both passed. The server's own configured `tests` credentials are the
smallest identity setup that needs no user-management call.

**Notes**: Each Elasticsearch host entry needs an explicit `"scheme":"http"`,
or the API server crashes at start. The file server must wait for the API
server (an init container or a readiness-gated start), otherwise it restarts
until the API server is up.

## R5. CVAT identity and organization

**Decision**: After the server is ready, the session registers a regular user
through `POST /api/auth/register` and creates one organization as that user.
The user owns the organization. No superuser and no `kubectl exec` are needed.

**Rationale**: Registration is enabled in the default configuration and
returned 201 in both measurements; the user is not a superuser. Owner is a
superset of the maintainer role the tests had on the shared stand, which they
needed to register a cloud storage.

## R6. Host access

**Decision**: one `kubectl --context docker-desktop port-forward --address
127.0.0.1 svc/<name> :<port>` per host-facing service (CVAT backend, MinIO,
ClearML API, ClearML file server), started by the session, which reads the
local port kubectl chose and stops the processes at teardown. CVAT reaches
MinIO in-cluster at the Service name, which becomes `MINIO_ENDPOINT_FOR_CVAT`.
CVAT's backend runs with smokescreen allowing private ranges, because the
MinIO Service address is a private address.

**Rationale**: Interim rule until platform name lookup is proven. Letting
kubectl choose the port avoids collisions between concurrent sessions.

## R7. Session identity and state

**Decision**: namespace `cveta2-it-<UTC yyyymmdd-hhmmss>-<4 random hex>`,
labelled `app.kubernetes.io/part-of=cveta2-integration`. The namespace name is
also `INTEGRATION_RUN_TAG`, the MinIO bucket and the prefix of CVAT and
ClearML object names. A kept session (`up` or `INTEGRATION_KEEP_DATA=1`) is
recorded in the gitignored `tests/integration/.session`: the namespace name and
the four local ports, no credentials. `env` reads credentials from the
namespace's Secrets and starts port-forwards on the recorded ports when they are
free, because ClearML stores absolute file-server URLs in dataset metadata and a
new port would break links to files a kept session already holds; when a port is
taken it picks a new one and warns about that limitation. Port-forward processes
are found by exact command-line match on `kubectl --context docker-desktop -n
<namespace> port-forward`, so `stop` only ever kills that session's forwards;
`stop [<namespace>]` then deletes exactly that namespace.

**Rationale**: The name is unique per session and valid as a bucket name, a
namespace name and a CVAT name prefix; it sorts by start time for an operator
reading `kubectl get ns`.

## R8. Readiness, cold start and teardown bounds

**Decision**: apply quota and limit range, then the workloads; wait for the
initializer Job to complete and every Deployment and StatefulSet to be
available within a cold-start deadline (default five minutes, overridable by
`CVETA2_SESSION_READY_TIMEOUT`); then start port-forwards, bootstrap identities
and seed. Teardown deletes the namespace and waits up to a bounded time.

**Rationale**: With cached images the measured cold start and namespace
deletion fit well inside this deadline (figures in evidence.md, M2). A first
pull of the CVAT server image is not measured and may exceed it; that is
reported as blocked setup, never as a test failure.

## R9. Preflight without a registry

**Decision**: read-only and creation-free, within `CVETA2_INFRA_CHECK_TIMEOUT`:
`kubectl` present (ERROR if not); `/readyz` answers (UNAVAILABLE if not);
`auth can-i create namespaces` and `delete namespaces` (ERROR if no); node
allocatable minus the requests of running pods can admit the session quota's
requests (UNAVAILABLE if not). No capacity cap per project.

**Rationale**: Keeps the constitution's three outcomes and their meaning while
the platform has no admission logic of its own (plan decision 4).

## R10. Environment contract

**Decision**: export the names the tests read (spec FR-011), including the
standard AWS names for the session's MinIO.

**Rationale**: Measured: without the AWS names, eight live tests fail with
`NoCredentialsError`, which proves the key pair is needed; they passed with all
four set (region and endpoint were not isolated, and are kept because the old
helper exported them). The k8s-infra MinIO helper used to export them as a side
effect. Product configuration names
such as `CVAT_USERNAME` were not needed by any test.

## R11. Versions

**Decision**: keep CVAT server `v2.59.1`, the release the suite is verified
against today, with the locked `cvat-sdk` (newer, used with the server-version
check disabled as before). Pin every image by tag in the manifests: the CVAT
server, OPA, kvrocks, Redis, PostgreSQL 15, MinIO, the ClearML server image,
MongoDB, Elasticsearch 7.17.28 and the `busybox` permission-fix init container,
which the chart leaves untagged. Upgrades are separate changes.

## R12. Retired pieces

**Decision**: remove from the repository: run-tag minting, `infra.py room`
and `newtag`, the k8s-infra skill lookup, registry capacity, the `cveta2-main`
slot, `INFRA_RUN_TAG` adoption, `.run-tag`, the exact-tag helper cleanups and
listings, and the TLS trust classification for the stands (`stand_tls.py`): a
loopback plain-HTTP port-forward has no certificate to distrust. The
constitution's "one owned run tag and exact-tag cleanup" becomes "one owned
session namespace and exact-namespace teardown", by amendment.
