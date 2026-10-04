# Integrated remediation verification — 2026-10-04

This evidence covers [all 26 findings](remediation-ledger.md) and the linked
[CVAT](../../002-cvat-write-safety/spec.md),
[dataset](../../003-dataset-correctness/spec.md), and [storage/interface](../spec.md)
features. It distinguishes the nine existing commits through `875dca9` from this
remediation. The existing version remains 0.6.0; no release or merge is authorized.

## Baseline and regression boundaries

An unchanged isolated checkout reproduced all 25 Python historical observations
under an isolated non-root configuration. Exit 0 meant the reproducer observed its
bug. OPS-003 used the actual wrapper and resolver with a mutation-engine sentinel;
an invalid profile incorrectly reached the engine. Baseline pytest passed 1,777
tests with 92.07% branch-aware coverage, demonstrating the missing assertions.

The original CVAT-005 post-write failure was simulated. Regression tests cover
one-effect-only ambiguous create/append outcomes, required manifest checkpoints,
changed/legacy recovery intent, exact shape multiplicity, partial/conflicting
remote content and cleanup denial. Live fault injection affects only a task-owned
client after a real successful annotation append; it is not evidence of a natural
CVAT outage.

Other regression boundaries include real boto3 `S3UploadFailedError` wrapping via
botocore Stubber; real non-root filesystem permissions; actual CLI subprocess exit
codes; source class mapping and task frame correspondence; and metadata-owned
COCO replacement with unrelated-file preservation. See the feature evidence for
per-ID tests and observed red/green results.

## Integrated checks

| Check | Actual result |
|---|---|
| Full pytest and branch coverage | 2,209 passed; 92.84%, above the configured 90% gate |
| Serial cache/concurrency/storage | 268 passed, serially |
| Ruff / formatting / mypy | Passed; 261 formatted files and 172 checked source files at the recorded run |
| Import-linter / Vulture | Four import contracts kept; dead-code check passed |
| Markdown / local links | 125 documentation cases passed, including local links and documented examples |
| Version consistency | 0.6.0 matches `v0.6.0` |
| Packaging | Wheel and sdist built; inventories inspected; package presets and dataset contract present; no audit corpus or Python test sources shipped |
| Installed runtime matrix | Python 3.10.20, 3.11.15, 3.12.13 and 3.13.14: 626 selected tests passed and nine helper-script-only cases skipped per runtime; installed CLI/API smoke checks passed |
| Mutation | Full configured 40-file scope: 7,441 evaluations, 7,234 killed, 207 reviewed equivalents, zero timeouts/unexplained survivors; five older false equivalent claims replaced by regression assertions |
| Live integration | 38 passed; successful gate and exact-tag zero-resource cleanup verified |
| Independent review | Fresh read-only Sol review: `ship`; independently ran 352 remediation regressions and inspected candidate/contracts/equivalence samples; no blocking findings |

Runtime environments were created separately from the repository environment and
imported the installed package from `site-packages`. Python 3.12 was installed from
the sdist; the other runtimes used the wheel. Development gates run on Python 3.12;
the runtime matrix does not claim every development tool supports every advertised
Python version. The nine skipped cases load repository operator scripts, which
are intentionally absent from the wheel; those cases pass in the repository suite.
The matrix covers Linux, not Windows or macOS.

The sdist's pre-existing include patterns also include nested README/LICENSE
documents. This remediation does not change packaging scope or dependencies.

## Mutation validity

The first attempted run was discarded after pytest's shared numbered-directory
cleanup raced between mutation children. Each child now gets a distinct PID-based
temporary directory; a subprocess regression verifies this isolation. A later
setup-only attempt was discarded because an overlapping generated-tree move
removed package resources. Neither attempt supplies accepted mutant verdicts.

Reader nontermination mutants initially timed out before reaching the bounded EOF
test because mutmut supplies caller tests from an unordered set. A stable pytest
collection hook puts the bounded termination guard first and retains every other
selected test in order. An ordinary subprocess collection test verifies that
behavior without depending on mutation environment variables. Scope and the
ratchet are unchanged. Equivalent entries describe exact inspected diffs;
renumbered or disproven entries are removed, not used to suppress semantic gaps.

## Live runs and cleanup

All runs use the repository integration lifecycle and the global infrastructure
ownership contract. Capacity preflight returned GO. Credentials came from the
maintained identity helpers and were not written into repository configuration.

| Owned run tag | Result and disposition |
|---|---|
| `cveta2-codex-20261004-integration-zf6y` | 36 passed, one old resilience test failed at its legacy fingerprint assertion. The test now identifies the complete request and injects death after frame attachment. Exact-tag cleanup verified zero CVAT projects/tasks/storages, MinIO buckets and ClearML projects. |
| `cveta2-codex-20261004-integration-grc0` | 37 passed, one new sync fixture failed because MinIO rejects doubled-separator object names at PUT. The corrected live test uses valid objects and colliding local destinations; noncanonical remote listings remain deterministic unit fixtures. Exact-tag cleanup verified zero objects on all three stands. |
| `cveta2-codex-20261004-integration-zzme` | 38 passed; complete gate succeeded. Exact-tag inspection after teardown found zero CVAT projects/tasks/storages, MinIO buckets, and ClearML projects/tasks. |

The new live tests exercise actual annotation read-back after an injected
post-write 503, cloning different task lengths/orders with byte and frame/shape
correspondence, and parallel S3 sync accounting with a preserved directory
destination. Existing live tests cover fetch/cache, upload, issues, deleted
frames, job state and ClearML publication. The stand reports a CVAT server/SDK
version warning (2.59.1 versus 2.73.0); no dependency or stand replacement was made.

## Compatibility and limits

Ambiguous names require explicit IDs. Legacy manifests cannot authorize automatic
resume; uncertain task creation and partial/conflicting remote data require
inspection. Mandatory recovery checkpoints must be writable before the next CVAT
write. Basename-only server metadata can establish unique name/order correspondence
but cannot prove an unavailable directory identity. Concurrent remote edits remain
possible; this change does not introduce a distributed transaction.

Repeated COCO export replaces only metadata-owned output. Unsafe or ambiguous
ownership and noncanonical/colliding S3 destinations are rejected. Encoded cache
components can change paths for formerly unsafe project names. Doctor's required
CVAT configuration checks determine exit 0/1; optional AWS/cache warnings do not.
See the updated [CLI](../../../docs/cli.md),
[configuration](../../../docs/configuration.md),
[cache](../../../docs/images-and-cache.md), and
[API](../../../docs/python-api.md) guidance.

## Final Spec Kit convergence and independent review

Each feature was explicitly selected and checked against its current spec, plan,
tasks and the five constitution principles. The combined inventory covered 27
functional requirements, 11 success criteria and 25 acceptance scenarios. The
implementation, shared documentation and completed verification satisfy that
inventory; no missing, partial, contradictory or unrequested work remains.
Convergence appended no tasks and left the completed task files unchanged.

The fresh reviewer owned no writes and returned **ship** after independently
running 352 remediation regressions, checking the diff and inspecting all 26
ledger entries, safety boundaries and sampled exact mutation equivalence claims.
It reviewed the parent full-suite/mutation/live logs; packaging/runtime/static
results remain parent-run evidence. Residual limitations agree with those above.
