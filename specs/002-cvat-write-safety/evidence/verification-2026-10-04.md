# CVAT safety verification — 2026-10-04

## Evidence boundary

Baseline is commit `875dca9b5cfc5bb48218257624defe3c18bc4f6e`.
Parent independently ran the unchanged historical Python reproducers: all 25
returned exit status 0 with the reported bug observations. The baseline full
suite passed 1777 tests, coverage 92.07%. Historical review files were read-only;
this feature stores its own evidence and does not link the untracked corpus.
All CVAT failure injection here is simulated. No shared stand was touched by
this bounded agent; no live 503 incidence or remote cleanup failure is claimed.

## Original observations and remediation

| ID | Original observation and boundary | Implemented behavior | Acceptance evidence |
| --- | --- | --- | --- |
| CVAT-001 | Real resolver over injected duplicate-name project/task lists selected whichever matching ID came first. | Collect casefold matches, reject with all IDs; preserve scoped list semantics, numeric IDs and cached-miss server fallback. | New duplicate project/task regressions plus existing client/fetch and task-operation tests. |
| CVAT-002 | Real upload annotation method with fake port silently returned zero for a labelled box missing one coordinate. | Pure validation rejects incomplete, nonnumeric and nonfinite labelled boxes before staging; direct write retains missing-context contract. Empty and deletion records return no shapes. | Four coordinate cases assert direct and service rejection with zero side effects; empty/deleted tests pass. |
| CVAT-003 | Component reproduction proved content-blind fingerprints and positive-count skip. End-to-end connection was static historical evidence. | Schema 3 identity hashes normalized row content, ordered image intent, deletions, selected labels, task name and behavior options; frozen mapping has a checksum. Insufficient state is rejected. Known target project/size/frame order and semantic shape multiset are read before S3 staging; conflicting/partial shapes stop without append. Unknown create identity and empty unfinished attachment stop for manual reconciliation. | Fingerprint content/property/order normalization tests, changed-options service rejection before staging, conflicting shape test, existing exact-resume tests. |
| CVAT-004 | Component unlink PermissionError reproduced; post-remote-success call placement was static historical evidence. | Save completed counts before unlink. Cleanup catches OSError and warns with task/path/stale-state wording. Both resume and same-intent fresh invocation return the completed outcome without staging or remote writes. | Direct cleanup-denial test and full simulated upload with denied unlink, stale manifest, repeated resume/fresh outcome equality and zero staging calls. |
| CVAT-005 | Ambiguous-write fake recorded an effect before real retry wrapper received 503 Retry-After; two effects resulted. Not observed live. | Create/append policy retries only proven 429 refusal; every 503 stops and warns of unknown outcome. Reads retain retry policy; explicit deleted-frame/job-value replacement retains transient-status retries through a separate predicate. | Applied-then-503 wrapper records exactly one effect; existing read/refusal/retry and transport tests pass. |

## Regression-first checkpoint

Before implementation, `uv run --no-sync pytest -n 0 tests/test_review_cvat.py --no-cov -q`
failed 10 tests. Nine failures demonstrated missing behavior/new safety interfaces;
one task fixture was initially missing required fields and was corrected before
implementation verification. The independent historical baseline reproduction
covers all five original paths. This distinction prevents counting a malformed
fixture as product evidence.

## Performed checks

- `uv run --no-sync pytest -n 0 tests/test_review_cvat.py tests/test_upload_service.py tests/test_upload_manifest.py tests/test_client_ops_fetch.py tests/test_retry_policy.py tests/test_task_ops.py --no-cov -q`: 184 passed in 0.54s.
- After replacing test mocks with real typed TaskWriteSession and explicit option
  reconstruction: `uv run --no-sync pytest -n 0 tests/test_review_cvat.py --no-cov -q`:
  24 passed in 0.11s.
- `uv run --no-sync mypy .`: no issues in 171 source files after test typing repairs.
- Ruff check and format of owned source/test paths passed. A final test-only Ruff
  check passed after moving option construction outside the raises block.

## Limitations and parent gates

No live CVAT/S3 behavior was established by these tests. Frame comparison preserves available full/nested path names, allowing only exact
cloud-prefix-relative omission. When metadata actually supplies basename-only
names, unique basenames can establish ordering but cannot prove the original
source path; a warning states that limitation, and repeated basename ambiguity
rejects. Frozen mapping remains separately checksummed. Shape read-back assumes the existing
rectangle upload contract: frame/label/type/points plus default occlusion, z-order,
rotation and empty attributes; generated IDs/authors are ignored. Unsupported
CSV attribute columns still participate in recovery identity, while their upload
support is outside this remediation. Concurrent edits between read-back and write
remain possible without a server-side conditional transaction. Unknown task ID
after an ambiguous create requires manual CVAT inspection.

Parent owns shared Russian documentation, docs/import/full-suite gates, mutation
validation, fresh independent review and integration-test lifecycle. These gates
remain unchecked until parent evidence is recorded. No commit or push occurred.

## Follow-up regression and verification

A pre-fix focused run for the discovered recovery gaps produced two failures and
one pass: columnless empty input raised `KeyError("instance_label")`; the changed
remote directory with the same basename passed the old preflight and reached the
mocked staging boundary, then failed with a later size mismatch instead of the
required early frame rejection. Empty input retaining CSV columns already passed.

Recovery now bypasses shape construction for empty/deleted annotation rows while
still reading existing remote shapes, and staging normalizes empty required
columns. A complete deletion-only request can finish and resume with zero shapes.
Frame verification compares POSIX paths, permits exact omission of the configured
cloud prefix, and permits basename fallback only when metadata itself has no
directory and intended basenames are unique. Changed nested directories, changed
full directories, reordered names and duplicate basename ambiguity all reject.

- `uv run --no-sync pytest -n 0 tests/test_review_cvat.py tests/test_upload_service.py tests/test_upload_manifest.py tests/test_client_ops_fetch.py tests/test_retry_policy.py tests/test_task_ops.py --no-cov -q`: 195 passed in 0.53s, including 35 CVAT regression cases.
- `uv run --no-sync mypy .`: no issues in 172 source files.
- `uv run --no-sync ruff check cveta2/services/upload.py tests/test_review_cvat.py`: passed.
- `uv run --no-sync ruff format --check cveta2/services/upload.py tests/test_review_cvat.py`: both files already formatted.

Only the two owned source/test paths and this feature's artifacts were changed
in the follow-up. Parent mutation/integration/review gates remain separate.

## Parent static review corrections: implemented

Required recovery state must fail closed if it cannot be persisted. A denied
creation-pending save followed by an ambiguously applied create would otherwise
leave older on-disk state able to authorize another create. Likewise a local
single-match project cache can mask a newly duplicated remote project name.
These are static findings, not live observations, recorded as T013/T014. Required
saves now protect initial intent, pending-create and created-task-ID checkpoints.
Active name queries now list current authoritative scoped projects, retaining
disconnected cached-only resolution. Denied-save and stale-cache regressions
verify refusal before the next mutation.


## Final owned follow-up checks and mutation preparation

A confirmed-404 replacement task must erase the obsolete task ID before its
required pending-create save. Otherwise a lost replacement-create reply could
leave that old missing ID authorizing another create. The regression simulates
remote creation followed by 503 without a reply: durable state contains no task
ID plus pending creation, and the next resume refuses without another create.
This is simulated applied-write evidence, not an observed live 503 incident.

Semantic tests additionally exercise every storage identity field, nested frame
paths and order, partial/conflicting shape values and multiplicities, normalized
annotation/options identity, nonfinite custom properties, completed-state cleanup,
and fresh manifests with and without a known task ID. They assert behavioral
identity distinctions and write boundaries rather than literal hash values or
complete diagnostic prose. Read-only exact mutation diff review distinguishes
canonical-order gaps from opaque payload-key and presentation equivalents;
bulky local capture data is not part of committed feature documentation. The
parent must confirm equivalent IDs against freshly generated mutants because
reshaped functions can renumber mutations.

Final owned verification after the two fresh-state guard regressions:

- `uv run --no-sync pytest -n 0 tests/test_review_cvat.py tests/test_upload_service.py tests/test_upload_manifest.py tests/test_client_ops_fetch.py tests/test_retry_policy.py tests/test_task_ops.py --no-cov -q`: **256 passed in 1.03s**, including **96 CVAT regression cases**.
- `uv run --no-sync mypy .`: no issues in **172 source files**.
- `uv run --no-sync ruff check tests/test_review_cvat.py`: passed.
- `uv run --no-sync ruff format tests/test_review_cvat.py`: completed; focused tests and type/lint checks then passed.

Source/tests are frozen for the parent's fresh full regression, mutation and live
integration runs. No verdict from failed mutation setup is accepted as evidence.
No commit, push, further delegation or live stand action was performed by this
bounded task.


## Round-three survivor follow-up

Exact current survivor diffs exposed additional semantic test boundaries: direct
disconnected cached-name propagation and miss filtering, missing-label rows,
blank labels during staging, optional completion-save failure, literal cloud-prefix
characters, false basename uncertainty warnings, and unknown-ID preflight advice.
Nine cases were added and the first successful cleanup warning assertion was
strengthened to require the actual task identity. No production change was needed.
Capitalization, decoration and unavailable-image placeholder differences were
reviewed separately as presentation equivalents; approval remains with the parent.

- Focused owned suite: **265 passed in 0.94s**, including **105 CVAT cases**.
- `uv run --no-sync ruff check tests/test_review_cvat.py`: passed.
- `uv run --no-sync mypy .`: no issues in **172 source files**.

These results establish regression coverage, not a mutation verdict; the parent
must run and review the remaining selected mutations. Source/tests are frozen.
