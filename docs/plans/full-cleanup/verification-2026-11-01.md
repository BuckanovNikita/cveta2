# Cleanup verification: 2026-11-01

## Scope and audit

Starting commit `d1a40ac`, branch `cleanup/contracts-and-release`. No tracked
pre-existing edits; two unrelated untracked skill links were preserved. Three
read-only auditors inherited the session model/effort: runtime/architecture,
specification consistency and test/release cost. They did not delegate further.
Parent inspected findings and implemented shared artifacts/hooks/docs; bounded
implementers owned disjoint runtime/test files. Final independent review completed after parent verification;
see [review-2026-11-01.md](review-2026-11-01.md).

All selected candidates and retained behavior are in [plan.md](plan.md).
No feature retirement, dependency updates, history consolidation, shared-service
changes or deployment. Published portable skill source inspected at
`13766a1ecb36fdc584cc7588f39ba713155753bc`; the local checkout is stale/dirty.
No usage edits are needed: commands/signatures/defaults stay compatible and these
fixes restore the existing completion/failure contracts. Current architecture
memory needs no module-map change: policy remains in domain, parsing/SDK errors
at existing outgoing boundaries, explanatory help at incoming interfaces.

## Native planning and architecture

Spec Kit specify and clarify completed for 002 and 003; compatibility was the
only user question and was answered: preserve supported behavior. No additional
material ambiguity remained. Plan, research, data model, interface contract and
quickstart were generated; quality checklists reviewed 6/6 in each feature.
Tasks contain 8 items for 002 and 10 for 003. Read-only analyze found requirement
coverage 3/3 and 4/4 respectively, no unmapped implementation tasks and no
blocking constitution, duplication or ambiguity findings. No extension hooks
file is configured. All three architecture records passed `--phase plan` before
implementation. Maintenance amended its scope before batching documentation checks.

## Original failures and focused checks

- Nullable completion regressions first failed twice: nullable legacy IDs were
  `{1,2,3,4}` rather than `{4}`; nullable explicit/fallback IDs `{1,2,4}` rather
  than `{2,4}`. Normalizing unknown finished-mask entries after explicit overrides
  fixes the original path. `uv run pytest -n 0 tests/test_partition.py
  tests/test_whats_new.py`: 63 passed. Tests cover missing stage/state/both,
  object/string equivalence, nullable boolean completion and true/false overrides.
- Operational regressions before fixes: 15 failed, 8 passed. Malformed YAML echoed
  a sentinel password through its source excerpt; actual decorated CVAT reads with
  negative/NaN delay raised sleep-related ValueError after 1 of 3 attempts.
  Config diagnostics now show only category/path/available numeric location,
  retaining the cause; the SDK boundary rejects negative/nonfinite delays.
  `uv run pytest tests/test_review_interfaces.py tests/test_config_sections.py
  tests/test_config_helpers.py tests/test_retry_policy.py tests/test_cvat_diagnostics.py`:
  implementer observed 229 passed in 5.55s. Parser/scanner/constructor, missing
  marks, context fallback, CLI rendering, actual retry budget and valid delays are covered.
- Test cleanup focused suite: 275 passed serially in 2.50s. Parent corrected an
  initially proposed lexical batch that mixed numeric and nonnumeric tokens:
  four per-token tables retain the original leading-zero inference signal.
  Lexical cases 16 -> 1; dimensions 48 file-backed cases -> 24 pure policy cases
  plus two public exporter prewrite probes. This removes 37 redundant collected
  cases and 58 CSV round trips without dropping an input combination.
- Noninteractive numeric-task project inference: auditor ran seven inference
  tests, then the original inference case with noninteractive mode enabled; pass.
  Help/docs now agree on inference, ignore exclusion, untouched default .tasks
  and new-directory refusal for verification/preparation.

## Parent checks

- Baseline `uv run pytest --cov --cov-report=term-missing --durations=25`:
  2741 passed in 16.81s; coverage 93.39%, 12 xdist workers.
- After runtime/test changes, same command: 2761 passed in 9.69s; coverage 93.40%.
  New spec Markdown added per-document test cases; batching two pure document
  invariants keeps every path/token and aggregated per-path failures.
- Final integrated suite with 15 durations: 2666 passed in 15.78s; coverage 93.40%.
  This run overlapped full mutation CPU work, so it is not a stable speed benchmark.
  Net suite reduction versus baseline is 75 collected cases, including new bug
  regressions and every new document. Assertions/file coverage were retained.
- HTTP poll microbenchmark (three trials each, auditor): default shutdown waits
  0.4956s; 0.01 polling waits 0.0050–0.0051s. Owned shutdown/close/join unchanged.
  The uncontended after-suite observation improves wall time, but single-run
  variation and different suite sizes prevent a guaranteed release-speed claim.
- Ruff check/format, strict mypy, Vulture, import-linter (10 contracts), canonical
  effect check, `git diff --check`, pre-commit config validation and `uv lock
  --check`: passed. Import dependencies increased only by the math import in
  the outgoing CVAT transport. `uv run pytest tests/test_docs.py
  tests/test_architecture.py`: 70 passed, including forbidden-edge/effect fixtures.
- `uv build --out-dir /tmp/cveta2-cleanup-build-20261101`: wheel and sdist built.
- Actual pre-commit probes in five disposable Git repositories: failing version
  exits before mutation/live; failed/re-written lock exits before analysis/tests;
  valid pre-push runs all three gates in order and valid pre-commit runs every
  existing hook with lock first. This verifies fail_fast, not only YAML order.
  Probe log: `/tmp/cveta2-cleanup-hook-probes.log`. No test repository was pushed.

First full mutation: 8118 total, 7835 killed, 283 existing justified equivalents;
zero unexplained survivors, stale entries, no-tests or timeouts; exit 0. Final
mutation refresh, fast commit hook, architecture acceptance and local commit
results will be appended after execution. Raw suite/mutation
logs are task-owned files under `/tmp/cveta2-cleanup-*`.

## Live environment limitation

The configured live gate failed before run creation: the active cluster has
only its four system/default namespaces; `cvat` and the `cvat-cveta2-access`
Secret do not exist. The default WSL kubeconfig first failed certificate
validation. A read-only command using the current Windows Docker kubeconfig
verified Kubernetes v1.36.1 and admission GO, then the configured integration
script confirmed the missing namespace/Secret. No TLS bypass, kubeconfig edits,
stand deployment, tag minting or resource writes were performed. No .run-tag or
run-owned remote resources exist to clean. Other shared services were untouched.

Live integration is an acceptance/release gap. The configured hook cannot pass
until the required CVAT/MinIO/ClearML stands and project identity are restored.
No hook bypass or claim of successful live verification is authorized. Source
work can be reviewed and committed locally; main merge/release/push remain blocked.

## Release-path findings

The implemented prerequisite ordering avoids expensive gates for rejected pushes
and rewritten/invalid locks; every existing gate remains. Successful-release
savings have not been measured. Full mutation remains the main unmeasured cost:
fast positional profiles deliberately rerun; test changes invalidate cached
verdicts. The observed run also reports architecture JSON and pre-existing
untracked skill links as non-Python dependency changes. Narrowing invalidation
requires a separate cache-correctness investigation; this session preserves it
and the entire mutation scope rather than trading evidence for speed.

## Independent review and convergence

Fresh `/root/final_review` approved the complete integrated source/artifact diff
for local commit through normal hooks, with no actionable findings. Its 504
focused and 14 documentation tests, 10 import contracts, effect check and three
plan validations passed; see the review record. Parent original-failure suites
also passed together: 292 tests in 3.99s.

Convergence inspected current code against all 3 nullable-completion requirements
and 4 operational-error requirements, their scenarios, data/interfaces and five
constitution principles. No missing/contradicting product behavior or unrequested
code was found. Required live acceptance and delivery are partial: one traceable
follow-up task was appended to each native ledger (T009 and T011). Existing task
history remains intact. These features are not reported fully converged/released.

Architecture acceptance: all three records passed the shared validator with
`--phase acceptance --repo-root .` after complete diff reconciliation and the
independent review. Declared local import/behavior/documentation/hook checks all
have passing evidence. Additional exact parent acceptance commands passed:
56 architecture tests (plus import-linter/effects), and 397 maintenance tests.
This structural/architectural acceptance does not close the live/release gap.

## Local commit and final mutation refresh

Source commit: `bce719b` — `fix: preserve incomplete tasks and operational error handling`.
All normal commit hooks passed without skips: lock, formatting/lint, import/effect
contracts, strict mypy, Vulture, pytest/coverage, fast mutation, build and
Conventional Commit validation. Only the two original untracked skill links
remained afterward; version stayed 0.12.0.

The final full mutation refresh against that committed source completed with exit 0:
8118 total, 7835 killed, 283 existing justified equivalents; no unexplained or
stale entries, no-tests, not-checked, skips or timeouts. Throughput observation was
60.16 mutations/second; this is not an end-to-end release benchmark. Scope,
profiles, cache policy and the equivalence table were unchanged. Final docs check
passed 14 tests; actual version-drift check confirms 0.12.0 matches v0.12.0.

The final run still reported two existing untracked agent-skill links and the
new spec architecture JSON as non-Python changes, forcing a full rerun. Installed
mutmut supports `cache_invalidation_exclude`. A future bounded investigation can
prove exact agent/spec artifact exclusions never affect mutation tests and retain
negative tests showing runtime/config/test changes still invalidate results;
only then apply exclusions. This is an actionable release-cost opportunity, not
an implemented cache relaxation or a measured successful-release saving.

Local source and architecture work is accepted. Native live/release tasks remain
unchecked, and convergence follow-ups remain open. Main, version tags and remote
refs were not changed; semantic-release cannot complete the native delivery while
the configured live gate lacks its external prerequisites. Restoring the shared
stands requires separate authorization; no such deployment was performed. The
handoff preserves all logs and the untracked user links, with no task-owned live
run or background test process left running.
