# Data model: Session-owned live-test infrastructure

No product data changes. These are the operational entities a live session owns.

## Session

| Field | Meaning | Rules |
|---|---|---|
| namespace | `cveta2-it-<UTC yyyymmdd-hhmmss>-<4 hex>` | Unique per session; never a protected name; also the run tag, the MinIO bucket and the CVAT/ClearML name prefix |
| kept | whether teardown is skipped | True for `lifecycle up` and for `INTEGRATION_KEEP_DATA=1`; false otherwise, on `main` too |
| ports | loopback ports of the four port-forwards | Chosen by kubectl per session; recorded only in the gitignored `.session` of a kept session |
| credentials | generated values for PostgreSQL, Redis, kvrocks, MinIO, CVAT user, ClearML pairs | Only in the namespace's Secrets and the process environment |

States: `created` (namespace and quota exist) → `deployed` (workloads applied) →
`ready` (initializer complete, every workload available) → `seeded` (user,
organization, bucket, cloud storage, project) → `finished`. From any state an
error or interruption goes to `tearing down` unless kept; `tearing down` ends in
`removed` (namespace absent) or `cleanup incomplete` (reported with the retry
command). A namespace that vanished externally is `removed`.

## Session namespace contents

- `ResourceQuota` and `LimitRange`, created first.
- Secrets holding the generated credentials.
- CVAT: server, `import` and `chunks` workers, initializer Job, OPA, Redis,
  kvrocks, PostgreSQL; one `hostpath` claim for the shared data directory.
- MinIO with `emptyDir`.
- ClearML: API server, file server, MongoDB, Elasticsearch, Redis, all `emptyDir`.
- Services for in-cluster access; no Ingress, NodePort or host port.
- Label `app.kubernetes.io/part-of=cveta2-integration` on the namespace.

## Kept-session record

`tests/integration/.session`, gitignored: the namespace of the kept session in
this checkout and its four local ports; no credentials. Written by `up`, removed by a successful `stop`. It
replaces `tests/integration/.run-tag`. A fresh `up` refuses while it names a
namespace that still exists, and discards it when the namespace is gone.

## Seeded objects (unchanged shape)

Bucket `<namespace>` with the coco8 images; CVAT cloud storage `<namespace> minio`
pointing at `MINIO_ENDPOINT_FOR_CVAT`; project `<namespace> coco8-dev` with its
tasks from `tests/fixtures/cvat/coco8-dev/`; ClearML projects named
`<namespace> <what>`. Their names keep the existing `"<tag> "` prefix rules.
