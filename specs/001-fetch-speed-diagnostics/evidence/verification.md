# Verification evidence — 2026-10-28

Base: `13ffec2` (v0.11.1). Branch: `feat/fetch-speed-diagnostics`.
Prior-agent report of 202 tests is planning evidence only.

## Reproduced failures

- Direct-image regressions: 3 failed before implementation. Canonical images
  issued HEAD; denied GET test could be reported as missing.
- Actual SDK/local HTTP reproduction: exhausted HTTP 500 became status 0.
- Application baseline: full fetch lists twice; ordinary fetch deletes an
  existing `.tasks` sentinel; 40 rows/2 images produce 82 Path.resolve calls;
  dataframe 40 rows/1 destination resolves 40 times; cache-disabled runs omit totals.

## Checks executed during implementation

- Architecture plan validator: exit 0.
- `uv run lint-imports`: 10 contracts kept, 0 broken.
- `uv run python scripts/check_architecture.py`: exit 0.
- `uv run pytest -n 0 -q tests/test_architecture.py`: 56 passed.
- `uv run pytest -n 0 -q tests/test_docs.py`: 65 passed.
- Image/S3 focused run: 146 passed; additional disappearance/body-category
  regressions then passed (18 tests in test_image_download_failures.py).
- S3 scoped Ruff and mypy: pass after formatting/type fixes.

These are intermediate checks. Full-suite, final architecture/docs, mutation,
packaging, serial live integration and independent review remain pending.

## Ownership

Existing `.claude/skills/ai-stage-gate` and `ml-system-design-review` untracked
links remain untouched. Companion clearml-yolo work is outside this task.
Native subagents inherit parent model/effort; realized runtime settings are not
exposed by the orchestration tools. Diagnostics, application and benchmark scopes
are disjoint; no bounded child delegates further.

## Integrated parent verification

- `uv run pytest -n auto --cov --cov-report=term-missing`: 2,725 passed,
  93.40% coverage (90% required), 15.15 seconds. Earlier full run exposed old
  internal-helper test expectations; corrected assertions now cover the inventory
  tuple and canonical missing GETs without changing output expectations.
- Diagnostics scoped suite: 189 passed, including 32 controlled HTTP tests;
  bootstrap advisory503/login401, pagination/comments, status exhaustion,
  per-request retry overrides, warm injected pools, concurrent context, redaction
  and exhausted connection errors included.
- Whole mypy: 308 files passed; Ruff/Vulture/format checks passed before final
  new diagnostics tests and are being rerun with the final snapshot.
- Final architecture/docs suite: 125 passed; import-linter 10 contracts kept;
  effect checker exit 0. New public fields are covered by doc introspection.
- `uv lock --check`: passed. Wheel and source archive built; wheel installed
  independently outside checkout, CLI help/imports/facade identity/keyword-only
  error parameter and bundled preset passed. Dependencies resolved independently
  in this isolated package smoke; it is not the locked-runtime regression suite.
- Serial live gate: `INFRA_HARNESS=codex INTEGRATION_KEEP_DATA=0
  ./scripts/integration_gate.sh`: 37 passed, 380 warnings, 211.79 seconds.
  Tag `cveta2-codex-20261028-integration-txi0` cleaned; exact-tag CVAT listing found
  0 projects/tasks/storages, MinIO 0 buckets, ClearML 0 projects/tasks. No shared
  stand restarted, changed or removed.
- Full mutation gate started after regenerating test-to-mutant associations.
  Prior generated workspace was moved into ignored local storage, not discarded.

See [benchmark](benchmark.md) for measured workload effects and limitations.

## Final integrated verification and review

After the first independent review found echoed Cookie values in bounded error
summaries and correlation IDs, the transport sanitizer was corrected to collect
transient cookie components, authorization/token headers and omitted query values.
Nine parameterized actual-SDK regressions cover echoes; only sanitized values are
retained. Original exception causes remain available and can contain raw SDK data.

- Full pytest with coverage: 2,741 passed, 93.39% coverage, 14.86 seconds.
- Whole mypy: 309 source files passed. Ruff check, formatting (369 files), Vulture
  and uv lock check passed.
- Parent image regressions: 77 passed. Documentation after cache-claim
  clarification: 69 passed. Import contracts: 10 kept; effect checker passed.
- Wheel and source archive rebuilt after the privacy fix. Installed wheel checked
  outside the checkout: CLI help, facade identity, three-positional-argument error
  construction, keyword-only diagnostics, frozen value and bundled preset passed.
  This smoke independently resolved dependencies, including cvat-sdk 2.80.0; the
  locked environment remains the source of regression results.
- Full mutation: 8,105 assessed, 7,822 killed and 283 justified equivalents;
  zero unexplained survivors, no-tests, timeouts or stale equivalents. Scope and
  profiles unchanged. Added assertions cover original ClientError preservation,
  accumulating body/missing/fallback failures, full canonical fallback precedence,
  nonzero-start elapsed clocks, injected degraded-cache totals and explicit
  task-output cleanup. Removed obsolete probe entries and the incorrect old
  full-key lookup equivalence; inspected every new equivalent's exact diff.

Fresh independent review by `/root/acceptance_review` (requested gpt-6.1-sol, high;
runtime settings unobservable) returned **ship**, no remaining blockers. Its
independent checks: 81 focused regressions, 125 architecture/docs tests, 10 import
contracts, effect checker and whitespace checks passed. It also validated the
reconciled companion skill, no-impact architecture record and all 64 Markdown
files, returning **ship**. No child delegated further.

Review corrected the zero-S3 wording: it applies to expected canonical cache
destinations. A stale frame resolved by basename fallback still needs key
rediscovery, but cached alternate bytes are reused. Spec clarification, baseline,
architecture and Russian/companion guides now state this existing limitation.
Benchmark fixtures already separated warm canonical-cache and fallback workloads.

The initial serial live gate passed before the final privacy-only sanitizer
correction. The configured pre-push gate will rerun serial integration on the
released snapshot; it remains a required delivery check.

## Companion preparation

The companion update was reconciled from original source `44426a6` into published
corp-skills `a9dea49470344d6fbfbc3a9e0381d169b1ac1a81` (v0.5.0) in an isolated
checkout, preserving unrelated clearml-yolo work. Changed paths are
`skills/cveta2/SKILL.md`, `skills/cveta2/references/usage.md`,
`skills/cveta2/references/evaluation.md` and dated verification/architecture evidence.
Package/frontmatter/duplicate-YAML/local links, four-skill discovery without
installation, documented synthetic Python example, architecture plan/acceptance,
64-file Markdown lint and whitespace checks passed. Added benchmark-overclaim
evaluation and clarified known-destination cache versus fallback rediscovery.
Prior fresh usage evaluation covered five scenarios; no external target-model
runtime or routing performance was measured. Final version pin and companion
commit/tag follow the actual application release and will be recorded below.

## Convergence and architecture acceptance

Spec Kit convergence inspected the current spec/plan/tasks and implementation:
11 functional requirements, 6 success criteria, 12 user-story scenarios, 4 edge
cases, the module/effect/retry/cache design decisions and 5 constitution principles.
No missing, partial, contradictory or unrequested buildable implementation work
remains. The existing companion commit and release tasks remain delivery steps,
not newly discovered implementation gaps; no convergence section/tasks appended.
The architecture acceptance validator exited 0 after reconciling all owned source,
tests, docs, benchmark and mutation-equivalence changes with executed contracts
and the fresh ship review. Task ownership excludes the two pre-existing untracked
skill links and unrelated companion work.

Fast mutation profile: passed, 21 justified survivors and zero unexplained mutants;
whole-scope score from this filtered run is not a whole-scope acceptance claim.

## Release delivery — 2026-10-29

- Feature commit `bc03d408` passed all configured commit hooks: formatting, lint,
  import/effect checks, whole mypy/Vulture, full coverage suite, fast mutation,
  packaging, lock and Conventional Commit validation. Main received it only by
  merge (`9159407`).
- Semantic-release selected and created v0.12.0, release commit
  `a6b77f204790120650460f37dbacf32bd2e4ea6c`. Version, changelog and lock metadata
  were generated by the established release command, not edited manually.
- Atomic push of main and v0.12.0 passed full mutation, version drift and serial
  live integration. Live result: 37 passed, 380 dependency warnings, 212.69 seconds.
  Run tag `cveta2-codex-20261028-fetch-release-hn2c` was minted by the maintained
  infrastructure helper; exact-tag cleanup verified 0 CVAT projects/tasks/storages,
  0 MinIO buckets and 0 ClearML projects/tasks. Existing durable main data remained
  intact. The tag date uses UTC; this delivery receipt uses local date.
- Read-back of remote main and peeled v0.12.0 both matched
  `a6b77f204790120650460f37dbacf32bd2e4ea6c`; annotated tag object is
  `91be8adb42b7d64c2458cb187595126abdb0f6ea`. No GitHub Release object, release
  asset, package publication, deployment or installed-skill update was created.

Implementation target reconciliation: existing S3 utility/retry helpers were
reused unchanged; focused image failure regressions live in the new
`tests/test_image_download_failures.py` and existing downloader/audit tests. This
fulfills T003/T005 without unnecessary edits to `adapters/s3/utils.py` or its tests.
The retained explicit task-cleanup adapter is tested independently although
ordinary fetch no longer invokes it. Final receipt changes affect only feature
status, task completion and dated evidence; no runtime or architecture contracts.

Companion source is published as corp-skills v0.6.0, commit
`13766a1ecb36fdc584cc7588f39ba713155753bc`; remote main and peeled tag match.
Annotated tag object: `539c80dc2820e426ae18657830db39ff22af0400`. The release
contains the three cveta2 skill/reference paths, two dated verification/architecture
files, VERSION and CHANGELOG. Guidance now pins introduction to cveta2 v0.12.0.
All package/example/Markdown checks and independent ship review passed on the
reconciled source; the final version pin was checked before commit. Source
publication used the established Git-only workflow, with no installed copies
updated. Five superseded task files in the original dirty checkout were removed
only after exact ownership checks; all ten unrelated changed/untracked file
contents and modes were preserved. The original branch was not advanced over
unrelated work.

Final convergence: all 21 native tasks are complete; no remaining implementation
or delivery findings. This receipt closes the recorded delivery state after
verified publication and does not change the released runtime.
