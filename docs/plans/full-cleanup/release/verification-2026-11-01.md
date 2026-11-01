# Release preparation verification: 2026-11-01

## Identity and scope

Source commit: `24d1045fe77605d8ed6b092b054c1c2a283d23ac` on `cleanup/contracts-and-release`.
Local/remote main verified at `a6b77f204790120650460f37dbacf32bd2e4ea6c` (v0.12.0); fetch succeeded and divergence was zero. The main working tree and two unrelated untracked skill links were preserved.

## Disposable release rehearsal

A task-owned local clone merged the source into its own main without conflicts. The maintained semantic-release configuration calculated 0.12.1. Its real `version --no-push --no-vcs-release` command then generated a release commit/tag only inside that disposable clone. No authoritative main/tag or remote ref changed, and no GitHub Release or package publication occurred.

Generated changes were exactly `CHANGELOG.md`, `pyproject.toml` version and the cveta2 version entry in `uv.lock`; all dependency pins stayed unchanged. A wheel and sdist built successfully. The frozen runtime lock export was used to install the wheel into two independent virtual environments, with imports and CLI executed outside the checkout.

## Built-wheel smoke checks

- Python 3.12.13: installed distribution version 0.12.1; package loaded from that environment; CLI and fetch help passed. Public imports, packaged preset, nullable completion, safe malformed-YAML diagnostic, valid/invalid Retry-After parsing and ordinary verification passed. Optional ClearML SDK was absent.
- Python 3.13.14: installed distribution version 0.12.1; package loaded from that environment; CLI and fetch help passed. Public imports, packaged preset, nullable completion, safe malformed-YAML diagnostic, valid/invalid Retry-After parsing and ordinary verification passed. Optional ClearML SDK was absent.

These are package smoke checks on both supported interpreters, not full-suite or live checks on both platforms. Earlier full source/coverage/mutation/review evidence remains in the [session verification](../verification-2026-11-01.md).

## Artifact fingerprints

- `cveta2-0.12.1-py3-none-any.whl`: SHA-256 `965460ae89a7a853a82d915599bc60431d5e663159d3b769784ef91c694c1102`.
- `cveta2-0.12.1.tar.gz`: SHA-256 `e30b7614218d4130931aae8284de6a3d85498bee208c62faf409a9e90225ca8e`.

## Live prerequisite and authorization gap

The configured live gate was reattempted and failed before tag/resource creation because the CVAT namespace/project Secret is absent. The cluster has only its default/system namespaces and the default hostpath class; maintained CVAT and ClearML read-only preflights additionally reported missing ingress, required local-path storage and internal DNS configuration. Infrastructure admission returned GO. Maintained scripts and existing private credential sources are available; values were not printed or copied. An unrelated existing edit in the infrastructure skill source is preserved.

Restoring the storage provisioner, ingress, internal DNS and CVAT/MinIO/ClearML with configured identities requires the separately requested shared-infrastructure authorization. No such restoration has been performed. No run tag or live resource was created; no cleanup of another run or stand was attempted.

## Remaining acceptance

Live verification and exact-tag cleanup, native task closure/final review, actual main merge, authoritative release generation, required push gates, Git-only delivery and remote-ref verification remain open. The user goal remains active. A successful disposable rehearsal does not prove a published verified release.

## Current goal completion audit

| Required outcome | Current authoritative evidence | State |
| --- | --- | --- |
| Release version calculation and generation | Disposable merge succeeded; maintained tool generated 0.12.1 with only the three expected metadata files changed | Verified rehearsal |
| Wheel/sdist and supported-interpreter installation | Both artifacts built; wheel installed and smoke-checked on Python 3.12.13 and 3.13.14 outside the checkout using frozen runtime pins | Passed |
| Release preparation documentation/architecture | 14 documentation tests passed; scoped no-impact architecture record passed planning and acceptance validation; whitespace check passed | Passed |
| Current source local verification | Existing ordinary/static/architecture/review and fast/full mutation evidence remains applicable to unchanged committed runtime/test source | Passed locally |
| Mandatory live integration | Fresh configured gate attempt fails before resource creation; required environment and identities are absent; restoration authorization pending | Missing prerequisite |
| Actual main merge and generated release tag | Main remains a6b77f2; 0.12.1 exists only in the disposable rehearsal | Not performed |
| Published commit/tag and remote verification | Remote main rechecked at a6b77f204790120650460f37dbacf32bd2e4ea6c; no remote v0.12.1 | Not performed |

The full user objective is not achieved. Preparation made concrete progress this
goal turn; keep the goal active while awaiting the required authorization. Do not
replace the requested verified release with the successful local rehearsal.

## Release continuation recheck

The next continuation rechecked the configured live gate: it again failed before
resource creation with the CVAT namespace/project identity absent. No restoration
authorization has arrived; the same external prerequisite remains. Preparation
records are being saved in a documentation-only commit through normal hooks;
actual live acceptance, main merge, version/tag creation and remote delivery stay
open. This preserves concrete verified preparation without narrowing the goal.

## Authorized environment restoration

The user explicitly approved restoring the Kubernetes stand after the earlier
authorization blocker. The release goal is active again. Restore only the named
integration prerequisites and CVAT/MinIO/ClearML through the maintained private
infrastructure scripts; preserve unrelated source edits, old data and workloads.
The restored shared services are intended to remain available after verification;
only per-run integration objects and temporary probes are cleanup targets.

Before apply, admission returned GO, host ingress ports were unoccupied, and
storage/ingress checks confirmed missing prerequisites. The maintained storage
installer completed successfully: it proved host/VM disk identity, installed and
verified the provisioner/class and removed its owned probe. Infrastructure source
and registry were not changed by this project task. Subsequent restoration/live
results will be appended after execution.

Ingress and in-pod DNS restoration passed. MinIO initially failed its host-side
self-check because this host resolver did not implement wildcard localhost
resolution. The maintained host-entry fallback was applied only to the six
restored service names, preserving existing entries and a backup. The original
MinIO deployment path then completed successfully on retry, including its identity
self-check; cveta2 separately authenticated and listed its empty namespace. No
project pins or infrastructure source/registry changes were needed. The host
fallback follows existing WSL hosts-regeneration behavior; permanent machine DNS
migration is outside this release. CVAT and ClearML restore checks passed before
applying either stand.

CVAT restoration completed and the cveta2 identity authenticated against the
restored organization. ClearML's server restored successfully; the glue step
initially found no local Docker socket in this distro. The existing configured
image was verified through Docker Desktop's working CLI, and a task-scoped CLI
bridge let the unchanged maintained script finish. All service-user credentials
and the glue's restricted ServiceAccount were verified. The bridge was temporary;
no daemon or infrastructure source/registry settings were changed.

## Live acceptance closure

`integration_gate.sh` completed successfully on the cleanup branch with
`INTEGRATION_KEEP_DATA=0`: **37 passed**, 380 dependency deprecation warnings,
234.25 seconds. Owned tag: `cveta2-codex-20261101-integration-yb0u`.
This covered real CVAT fetch/promotion/cache, issues, upload/recovery/task changes,
S3 transfer/sync safety and explicit ClearML publication/parent/tamper behavior.
The gate removed the tagged project/cloud storage, bucket and ClearML objects.
Separate exact-tag listings then proved 0 CVAT projects/tasks/storages, 0 MinIO
buckets and 0 ClearML projects/tasks; `.run-tag` was absent. The earlier missing
live prerequisite is resolved. Restored shared services remain intentionally up.

## Fresh parent verification after restoration

The ordinary suite passed **2666 tests in 11.96 seconds** with configured coverage
above its 90% gate. Ruff check/format, strict mypy (309 source files), Vulture,
10/10 import contracts and the canonical effect checker passed. Runtime, tests,
dependency pins and hooks are unchanged from the previously reviewed source;
only dated release evidence/status is being updated. The final required full
mutation and live gate will also execute through the actual main/tag push hooks.
A fresh independent release-readiness reviewer is checking this integrated state
and evidence before main merge/version generation.

Fresh independent release-readiness review returned **ship**, with no findings;
173 focused/docs checks, 10 import contracts, effects and all four architecture
validators passed independently. See [review](review-2026-11-01.md). Native source
acceptance is now closed; main/version/tag/remote delivery steps remain open.
