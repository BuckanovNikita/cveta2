# Managed dataset verification — 2026-11-02

## Local checks

- Full regression: uv run pytest -n auto -q — 2775 passed, 8.76 seconds.
- Scoped architecture/docs/migration/mutation-behavior suite — 94 passed, 1.23 seconds.
- uv run ruff check .; uv run ruff format --check .; uv run mypy .; uv run vulture — passed. Four external SDK protocol argument annotations follow the existing narrow Vulture F841/RUF100 convention; no implementation logic is excluded.
- uv run lint-imports — all 10 contracts kept. uv run python scripts/check_architecture.py — passed; forbidden-edge/effect negative fixtures are retained.
- uv build — source archive and wheel built successfully for validation only; no package assets are published.
- Fast mutation profile — zero unexplained survivors.
- Full mutation profile — 8397 total, 8092 killed, 305 justified equivalents, zero unexplained survivors, no timeouts. Initial 67 configuration survivors prompted behavioral assertions; 22 genuinely equivalent exact mutations were independently reviewed. Two command-token mutations were killed by executable-remedy tests rather than allowlisted. Scope/profile/budgets were not weakened.

## Live stands

Run cveta2-codex-20261102-managed-datasets-y7lx: mixed-source cold-start preparation, first ClearML publication and completed-task annotation reuse passed. Broader suite initially passed 35 tests and failed three upload tests at CVAT login HTTP429 before effects. The three original failure paths then passed on a targeted serial rerun (21.65 seconds). This is not reported as one uninterrupted green full-suite run. No production authentication policy was changed.

Lifecycle teardown removed the owned CVAT project/cloud storage, MinIO bucket and ClearML projects; the run tag file was released. No foreign or durable resources were stopped. A subsequent owned run verifies actual new feedback issue creation/deduplication and clean publication before release; its receipt is appended after execution.

## Companion guidance

Canonical cveta2 skill, usage and evaluation cases updated. Initial local companion source 3609778906d3e63d0d160cb7d81510f4bf4849db was pre-existing diverged from current remote 2a1869f. Only task-owned cveta2 guidance was reconciled on a clean remote checkout, preserving newer diagnostics/timing/baseline guidance and unrelated local work. Frontmatter/links/schema/help/API/discovery/Markdown checks passed; final release receipt records the companion commit/tag.

/root/usage_skill_evaluation passed four native guidance application cases in one fresh context (shared override, arbitrary transform/unmapped findings, feedback retry, development near-miss). This is not four independent runtime invocations or OpenCode/DeepSeek runtime acceptance. /root/companion_release_review returned ship after reconciliation, subject to tool publication and final collection checks. No installed copies were changed.

## Ownership

The checkout began clean. Concurrent unrelated docs/plans/claude-codex-organization-20261102/plan.md and release-followup-2026-11-02.md appeared during work and remain excluded, unstaged and intact. Companion clearml-yolo edits and pre-existing local commits/divergence are preserved.

## Companion source commit

Scoped canonical-source commit: 670b0be, containing only the three cveta2 package files and its documentation-only plan/architecture/evidence. Existing local branch divergence and clearml-yolo changes remain intact. The clean release checkout is based on current remote 2a1869f and preserves its newer source guidance. Final collection validation includes 76 Markdown files with zero issues and discovery of all four skills. Collection Git-tag publication follows tool publication.

## Final live feedback and cold start

Run cveta2-codex-20261102-managed-feedback-j0o9: the mixed-source scenario passed in 13.79 seconds. It temporarily reviewed two exact-owned tasks, rejected one traced image, created an actual CVAT issue at the original frame, confirmed its marker, retried with zero duplicate creation, published exactly three files from a null parent, and reused unchanged completed task annotations. Original job states were restored in finally. Native teardown deleted the owned project/storage/bucket; independent exact-prefix helpers then listed zero CVAT projects/tasks/storages, zero MinIO buckets and zero ClearML projects/tasks. No installed/runtime host configuration was changed.

Final parent regression after these test changes: 2775 passed, 6.69 seconds; Ruff and strict mypy passed. The earlier full mutation pass applies to unchanged production/test behavior; native commit/push hooks rerun their required profiles after acceptance-record changes.

## Native convergence and architecture reconciliation

Spec Kit prerequisites resolve feature 004. Compared all FR-001–021 and SC-001–007 with current models/loaders, source adapters/use cases, policies, preparation, feedback/publication, CLI/API, tests and companion guidance. No additional unbuilt functional requirements were found. Existing acceptance/release tasks remain authoritative; no duplicate convergence tasks or competing ledger was created. Fresh independent final review is recorded in review-2026-11-02.md. All owned runtime/test/docs/artifact additions and changes were reconciled, excluding the concurrent instruction-release follow-up files and companion clearml-yolo work. Release remains T019 until actual hook/merge/tag/push completion.

## Personal-workspace release correction

Before any new version was pushed, a direct reproduction showed organization empty string and null were treated inconsistently during credential saves. Three tests captured the failure; validation now canonicalizes both settings boundaries without changing shared files or accepting nonempty overrides. Focused suite103 passed; full suite2778 passed in6.37seconds; Ruff, mypy, Vulture, formatting and architecture checks passed. Independent review78 tests returned ship. Main initially received local-only semantic release14e2913/v0.13.0; that immutable tag remains and the correction is merged through its own branch before a patch release. No package assets or GitHub Release objects are published.
