# Full cleanup session

Date: 2026-11-01. Starting commit: `d1a40ac` (v0.12.0 plus committed delivery receipt).
Branch: `cleanup/contracts-and-release`. User selected preservation of all supported behavior.

## Contract and inspected evidence

Audit runtime, specifications, tests and release work; implement evidence-backed
simplifications and correct demonstrated defects. The bug tracks use native
Spec Kit: [nullable completion](../../../specs/002-nullable-completion/spec.md)
and [operational errors](../../../specs/003-operational-errors/spec.md).
This lightweight maintenance ledger owns only behavior-preserving test/tooling
and documentation work, never a competing application specification.

Python >=3.12,<3.14; development 3.12; uv/Hatchling, Ruff, strict mypy, pytest,
Vulture and import-linter remain authoritative. Preserve lock/dependency pins,
public signatures, output formats, recovery/deletion/recency policy, test isolation,
mutation scope/equivalence validity and every configured release gate. No feature
retirement, history consolidation, framework/tool installation or deployment.

Baseline: full suite 2741 passed in 16.81s, coverage 93.39%; raw output
`/tmp/cveta2-cleanup-baseline-20261101.log` (dated results will be retained here).
Static import contracts pass. Two unrelated untracked skill links remain excluded.

## Candidate ledger

| Candidate | Evidence and contrary evidence | Disposition and preserved contract | Acceptance |
| --- | --- | --- | --- |
| Nullable task completion | Nullable boolean mask drops unknown unfinished evidence; object representation does not | fix in separate 002 feature; preserve explicit precedence | partition/whats-new regressions and mutation |
| YAML diagnostics and invalid Retry-After | Reproduced credential source echo and incidental sleep ValueError | fix in separate 003 feature; preserve typed errors/budgets | API/CLI and real decorated retry regressions |
| CSV lexical matrix | 4 columns × 4 tokens use identical write/read path | simplify 16 cases into one test with four per-token tables, preserving isolated numeric-text inference and all column/token/missing/numeric checks | output suite and mutation |
| Per-document pure checks | Language/retired-stack invariants repeat global isolation fixtures per Markdown file; link validation already batches the same tree | simplify into two aggregate checks with per-path diagnostics and identical file/token coverage | documentation suite; report full counts separately from runtime cases |
| Export dimension matrix | 48 file-backed cases invoke the same pure validator twice | simplify to 24 owner-level shape/column/value cases plus two public fail-before-output probes | conversion/review suites and mutation |
| HTTP test server shutdown | serve_forever default polling adds ~0.5s per owned fixture; 3 trials each show ~0.005s at 0.01 polling | simplify polling wait only; preserve lifecycle/requests/assertions | diagnostics/bundle/live suites, durations |
| Hook ordering | uv-lock runs after costly checks; version drift follows full mutation | move prerequisites earlier and set per-hook fail_fast so failure or lock rewrite actually stops later work; remove no gate | real pre-commit in disposable Git repos, valid/failing/rewrite paths |
| Fetch/ignore help and config guide | help describes removed .tasks deletion; guide contradicts numeric-ID inference and output refusal | correct presentation to current baseline/implementation | docs, help/parser and inference tests |
| Materialization final branch | unreachable invalid-mode branch exists, but little payoff and mutation churn | retain: no meaningful simplification justified this session | existing gate retained |
| Facades, recovery/promotion and task manifests | public compatibility/effect safety remains required; suspicious task supersession explicitly tested | retain: few callers are not evidence of no consumers | existing contracts and required tests |
| Mutation caching/profiles | fast positional globs deliberately rerun; tests invalidate full cache for correctness | retain: safe new cache needs separate correctness study | full/fast gates unchanged |
| Portable usage skill | published 13766a1ecb36fdc584cc7588f39ba713155753bc has current guidance; local checkout is stale/dirty | retain published package, no new commands/signatures/defaults | inspect published source; no installation |

## Architecture and ownership

[architecture.json](architecture.json) records the two incoming presentation
modules and existing exhaustive import/effect enforcement. CLI/API behavior,
effect ownership, SDK boundaries and layering stay intact. Testing pure dimension
policy at its domain owner reduces repeated filesystem orchestration and leaves
explicit public boundary probes. No new production module or abstraction is needed.
Bug records own their three runtime modules separately.

Parent owns shared docs/baseline, hooks, evidence, integration, mutation triage and
release. Bounded implementers may independently own (A) domain completion/tests,
(B) config/transport regressions and fixes, and (C) test consolidation/HTTP fixtures.
All are gated on validated plans and must not delegate or commit. Parent integrates,
verifies, then requests fresh independent final review. Preserve others' changes.

## Verification and delivery

Run focused suites, all static/import/effect checks and architecture negative
fixtures, full pytest coverage/durations, docs checks and actual disposable-Git
hook exercises. Compare equivalent suite counts/coverage and timing conditions;
report measurements separately from estimated release savings. Full/fast mutation
and configured live integration remain required. Existing yield/finally HOME,
worker, cache and owned-server teardown remains intact.

Reconcile every owned addition/modification and all retained candidates. Record
checks and independent review in verification-2026-11-01.md, then validate all
architecture records at acceptance. Complete Conventional Commits, merge to main,
evaluate semantic-release and push commits/any generated Git version tag after
checks. Never create a GitHub Release, publish packages or change remotes.
