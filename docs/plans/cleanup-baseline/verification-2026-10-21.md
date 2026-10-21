# Cleanup verification — 2026-10-21

## Starting state and archive preparation

Local and published main matched
`f6717f0211169f8f94c78da2bfa8dee86bfab602`. The source checkout's only untracked
paths were the explicitly included bugs tree and two unrelated skill links.
An isolated worktree uses branch `refactor/cleanup-baseline`; the source files
remain unchanged while archival prerequisites run.

- `uv sync --frozen --extra clearml`: passed using the existing lockfile and Python 3.12.13.
- `uv run --frozen pytest -n 4 -q --no-header`: 2764 passed in 12.90 seconds; this is the non-live baseline, not integration evidence.
- Shared architecture validator, `--phase plan`: passed after correcting the record's string-valued documentation/contract fields.
- Archive inventory: 110 tracked historical files plus 129 untracked review files, 239 total. Every native-path source equals the isolated checkout; every tar member equals its source bytes.
- Deterministic archive SHA-256: `66dbe1f2eab4385017542e828031e7ff64bb23a5109e4fddec33fa7444ba6211`.
- Existing review SHA256SUMS: 115 matches and 13 mismatches. Both the original manifest and current files are preserved; the new manifest identifies each mismatch without claiming original proof integrity.
- Selected-content scan found no private-key, AWS/GitHub-token, generic literal-credential or inherited-secret matches. One inherited secret value was checked. This bounded pattern scan is not an exhaustive secret audit; existing captured logs use redacted output.

Planning inspection also passed Vulture, the effect checker, all ten import
contracts and 290 documentation/architecture tests in the original checkout.
These pre-change outcomes do not establish final implementation acceptance.

Task status lives in [tasks.md](tasks.md). Results below distinguish the
starting state, intermediate checks and final acceptance.

## Checkpoint and baseline cutover

Checkpoint `af0073e5bd8a8799f0cfd322cfb27c8efd7b747d` passed all configured
pre-commit and commit-message hooks: formatting/lint, imports/effects, mypy,
Vulture, full ordinary tests with coverage, fast mutation, build and lock check.
All 239 committed native-file/archive-member hashes were independently read back
from Git and verified against the committed manifest before retiring any file.

The actual cutover transformation was exercised without writes across the retained
tracked Markdown/Python/TOML inventory. It resolved 13 Markdown references across
10 changed files, including repeated references and the verification deep link;
every original archive source still matched before application. The applied
transformation removes only the 110 inventoried historical tracked records plus
the now-checkpointed archive/manifest. Source-checkout bug files remain intact
until delivery reconciliation. Fixtures stay in tests and were not regenerated.

The 622-line baseline preserves the 30-column schema and current contracts from
features 001 through 008, including both independently named 002 features. It
reconciles later closure of all 134 checked tasks and superseded automatic
publication rather than reviving historical findings. Decision sources use full
implementation SHAs; archive retrieval uses the separate checkpoint SHA.

Constitution 1.5.0 adds recoverable consolidation and baseline deltas without
removing principles or changing templates. Its resolver succeeded; no extension
hooks or unresolved placeholders were present. The temporary sync-impact comment
was reviewed and removed before commit. Governance and Russian contributor
guidance now distinguish module-impact runtime maintenance from documentation-only
no-impact work.

- `uv run --frozen pytest -n 0 -q tests/test_docs.py`: 45 passed, including a new check that the baseline's ordered schema equals the public CSV_COLUMNS contract and expanded nested maintenance-link coverage.
- Next-feature dry run: `001-next-feature`; no new feature directory or active pointer was created.
- `uv build --out-dir <temporary-output>`: wheel and sdist passed. The sdist contains only `specs/baseline.md` under specs and contains no archive container.
- `git diff --check`: passed.

These are cutover checks. Final runtime, mutation/live, independent-review and
release acceptance remain pending.

## Runtime refactoring and compatibility

Baseline cutover commit `e69022727a73747bbd5723e34fa96b093f42c34c` passed
all configured commit hooks before runtime work began.

Three bounded workstreams were integrated without overlapping write ownership.
Upload/client checks preserved ten transformation ASTs and the workflow ASTs
except shared row selection and one corrected nested docstring. All existing
upload tests remain; eight cases add mixed rows, duplicate indices, diagnostics
and dataclass identity coverage. Focused checks: 391 passed.

CVAT extraction preserves all 23 endpoint signatures/bodies and decorator orders:
14 read, seven non-idempotent write and two idempotent write policies. Added checks
cover status versus transport errors, ambiguous append failures and concurrent
context-local timeouts. Focused checks: 157 passed, plus 50 architecture cases.

API/CLI comparison matches all 65 captured public exports (signatures, module and
qualified names), all 20 parser help/action snapshots and a Connection pickle
created before the split. The existing 90 API test functions and 124 assertion
expressions were preserved; 26 serialization/identity cases were added. Focused
checks: 393 passed. These temporary snapshots verify this move; lasting tests
cover behavior and serialization without freezing every help string.

The parent migrated timeout composition to the transport owner and added negative
import/cycle checks for moved upload, API, mapping and parser modules. The first
integrated suite passed 2625 tests with 93.36% branch-aware coverage (90% required).
Ruff, formatting, strict mypy, all ten import contracts and effect checks passed.
Vulture initially reported quoted Self imports after the API test split removed
the last evaluated reference; evaluating the test annotation with its imported
Self restored detection without adding exclusions. Scoped lint/type/Vulture checks
then passed. Final post-triage verification follows below.

## Installed artifacts and live services

`uv build` produced wheel/sdist for 0.11.0. Isolated installs outside the checkout
on CPython 3.12.13 and 3.13.14, constrained by the unchanged frozen lock, passed
public/API imports, serialization, all 14 new module imports and root/verify/
upload-dataset CLI help. Both environments passed `uv pip check`. Default installs
had no ClearML and did not import it eagerly. Installing the extra on 3.12 loaded
locked ClearML 2.1.12 explicitly; provider construction and local validation passed
with service connections prohibited. Both task-owned environments were removed.

Wheel and sdist contain all 174 current Python modules with byte-identical contents.
The sdist's specification inventory is exactly `specs/baseline.md`, with no archive,
bug-review or historical maintenance members. No artifact was published.

The shared-infra capacity preflight returned GO. The armed branch integration gate
ran all 37 live tests serially under `cveta2-codex-20261021-integration-kek5`:
37 passed in 241.70 seconds, with 380 upstream warnings and no skips. The suite
covered real fetch/cache/status, upload, issues, rate limiting, interrupted-upload
recovery and explicit bundle publication. Teardown removed the owned CVAT project
and storage, MinIO bucket and residual ClearML objects. Independent exact-tag
listings afterward returned zero projects/tasks/storages, zero buckets and zero
ClearML projects/tasks. The run-tag file was released. Shared stands were unchanged.

## Mutation scope and final ordinary verification

The scope follows every previously gated moved function and preserves the former
fast-profile assembly functions at their new owners. Transport remains outside
scope because the original SDK adapter was outside it; connection remains gated.
No runtime function was excluded to obtain a pass.

A complete first run exposed seven stale diagnostic IDs and real assertion gaps
in resume-flag parsing, missing-label index alignment and empty StringDtype frames.
Eleven new cases cover these behaviors. The empty-frame early guard is necessary:
its `or` to `and` mutation triggers pandas' unsupported string reduction instead
of accepting the empty table. The regenerated run kills all seven functional
mutants identified by this triage.

The 57 moved/renumbered equivalence entries were checked against exact diffs:
56 match their original mutation expressions. One original cached whats-new
mutant was unavailable; the current cutoff-to-None mutation was re-inspected
against the client, where cutoff is diagnostic-only and returned cutoff and task
membership remain unchanged. All existing equivalences still name live survivors.

Moving upload parser declarations into a gated module also admits new mutants.
Narrow `help=`/`metavar=` patterns exclude display literals. Line-based matching
cannot exclude every keyword deletion or multiline literal without suppressing
behavioral options on the same call. The remaining 51 entries were individually
reviewed: 37 help and two metavar display mutations, eight identity conversions
of already-string argv values and four redundant argparse None defaults. AST
comparison confirmed no other keyword changes; nine argv/exit scenarios for each
matched the unchanged parser contract. Existing policy treats presentation as
outside behavioral mutation acceptance; no entire parser/function was excluded.

The regenerated full run executed 8026 mutants: 7743 killed, 283 justified,
zero no-tests, timeouts or unchecked mutants. The gate over these results passes
with zero unexplained survivors and zero stale justifications. Configured full
and fast wrapper outcomes are recorded after their replay completes.

Post-triage ordinary verification: 2636 tests passed, 93.36% coverage; Ruff check,
format check (351 files), strict mypy (303 source files), Vulture, ten import
contracts, effect checks and diff whitespace checks passed. Python dependency
pins and runtime behavior remain unchanged.

## Companion usage source

The isolated latest-origin corpus checkout contains commit `4475ebe`, updating
only the cveta2 dataset-contract link plus task/release records for 0.4.2. The
original corpus checkout and its unrelated work remain untouched. Discovery found
all four skills; collection Markdown lint checked 59 files with zero issues;
strict frontmatter/duplicate-key checks, all package-local links and the baseline
heading passed. Architecture no-impact acceptance and bounded independent review
passed. New behavior/model evaluations are unnecessary for this link-only change;
none are claimed. Publication follows cveta2 delivery so the destination is live.

## Final gates and fresh independent review

Configured full wrapper replay passed: 8026 executed mutants, 7743 killed and
283 individually justified survivors; zero unexplained survivors, stale entries,
no-tests, timeouts or unchecked mutants. The fast wrapper passed its selected
749 mutants: 728 killed and 21 justified. Scope grew from 58 to 68 files through
moves/admission; all 440 previously scoped function/method definitions remain
covered. No threshold, hook or behavioral scope was weakened.

Fresh read-only reviewer `runtime_review` accepted the integrated runtime and
architecture diff with no actionable findings. Independently checked all 65 public
metadata snapshots, 20 parser snapshots, historical Connection serialization,
runtime-resolvable annotation parity, 168 eligibility combinations, 23 endpoint
AST/policy comparisons, all 90 prior API tests/124 assertion expressions and all
440 previously mutation-scoped definitions. It inspected all 51 new equivalent
mutations, reran the ten import contracts without cache, and passed effect and
staged whitespace checks. It did not rerun full/live/mutation suites.

Fresh read-only reviewer `baseline_review` independently verified all 239 archive
hashes, 129 archive modes/current bug files, 110 native original documents,
historical 115/13 checksum reconciliation, immutable source resolution, exact
retirement inventory, 45 documentation checks and the next feature number 001.
It found one P2 completeness issue: missing explicit unknown/empty mutation-profile
preflight, newly-deleted-only/no-op task-mark counts, and preservation of --resume
in echoed prompted commands. These three current contracts and the immutable
September evidence link were added to the baseline; 45 documentation checks passed
again. Focused reviewer reinspection accepted the fix with no remaining findings.
This correction changes documentation only; implementation/regressions already
preserved all three behaviors.

The parent reconciled added packages/modules/tests, moved/deleted owners, runtime
composition, mutation configuration, baseline/governance, packaging references and
archival retirement against the complete task-owned diff. Original unrelated skill
links and corpus edits are excluded. No runtime modifications followed verification
or review. Architecture acceptance is recorded in architecture.json and validated
before the runtime commit. Final publication and original-checkout retirement are
recorded in the delivery section when complete.

## Delivery

Runtime commit `db4514c05f6652b4ed96020d7b1e4d7feb43db0d` passed every configured
commit hook, including ordinary coverage tests, fast mutation and package build.
Main received the task branch through merge
`b9d93f30e5feccf06b8117005d465b7ff457b8de`. On main,
`uv run semantic-release version --no-push --no-vcs-release` exited successfully:
0.11.0 was already released and these compatible maintenance changes produced no
new version or tag.

The main push passed full mutation, version drift and live integration gates;
37 live tests passed in 224.85 seconds, with 380 upstream deprecation warnings.
Remote main was independently confirmed at the merge SHA above. The configured
main gate intentionally retains the durable `cveta2-main` fixture: CVAT project
`cveta2-main coco8-dev` and MinIO bucket `cveta2-main`. ClearML test projects are
removed at session end. The earlier isolated branch run was separately cleaned
and verified as recorded above.

Before retiring the original checkout's untracked bugs tree, all 129 paths,
SHA-256 digests and modes were rechecked against the committed archive manifest;
the exact inventory contained no additional file. Only those preserved files and
their empty directories were removed. The ignored active-feature pointer was
removed only after confirming it named the archived
`specs/008-dataset-verification-publication` feature. Both unrelated skill links
were preserved. A post-merge `create-new-feature.sh --json --dry-run` returned
`001-next-feature` without creating a feature or branch.

The companion collection's documentation patch was published atomically as main
commit `f6148927336d83cac3cdc59dec68a44b6064a32b` and annotated tag `v0.4.2`;
remote main and the peeled tag both resolve to that commit. Before publication,
the GitHub contents API confirmed this repository's published baseline and its
dataset heading at the exact main merge. Collection Markdown lint checked 59
files with zero issues, architecture acceptance passed, and whitespace checks
passed after the final evidence update. GitHub reported the collection's new
location as `BuckanovNikita/custom-opencode-skills`; the configured `corp-skills`
remote continued to work and was not rewritten. The original collection checkout
and its unrelated edits remain untouched. No installed skill copy was changed.

All task items are complete. This delivery-only update records already-verified
results and changes no runtime module or contract. It follows the same configured
commit and push gates; no hooks are bypassed. No GitHub Release, release asset or
package publication was created.
