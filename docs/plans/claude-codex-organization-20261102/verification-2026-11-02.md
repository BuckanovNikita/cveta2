# Instruction migration checks — 2026-11-02

## Scope and preservation

The task standardizes agent instruction discovery only. Existing application,
service, generated workflow and unrelated source changes are preserved. No runtime
API, database, dependency or deployment changes are made. The implementation checks below preceded commit/release activity; release
outcomes are reported by the coordinating task separately. No deployment or
skill installation is part of this migration.

The existing documentation assertion was updated before changing CLAUDE.md.
The observed failure rejects the previous symlink; the completed docs suite passes.
Constitution 1.5.1 clarifies the adapter format without changing governance principles.
Generated Spec Kit skills and integration manifests are untouched.

## Executed checks

- `uv run --frozen --no-sync pytest tests/test_docs.py::TestTheAgentInstructionsDelegateToSpecKit::test_claude_md_imports_canonical_agents_md -q` — RED: exit 1 while the old symlink existed; assertion rejects the old format.
- `uv run --frozen --no-sync pytest tests/test_docs.py -q` — GREEN: 14 passed.
- `uv run --frozen --no-sync ruff check tests/test_docs.py` — PASS.

Planning and acceptance record validation use the shared architecture validator
with this repository as the explicit root. All root adapter and changed-document
relative links were inspected separately; Git whitespace checks cover owned paths.

## Limits and remaining integration

File checks establish physical instruction discovery structure, not actual loaded
model context. Fresh Claude/Codex sessions, Windows discovery, settings parity,
parent integration, independent final review and authorized commit/release remain
with the coordinating task. Relevant application/runtime suites were not rerun
because no application behavior changed. Missing required release checks must
remain acceptance gaps rather than being inferred from these documentation checks.

## Constitution clarification stage

The installed constitution workflow's template resolver succeeded; the current
constitution retains the scaffold hierarchy and all existing project principles.
No extension hooks are registered. Principle V's title is unchanged and its
entrypoint-format sentence is clarified; version 1.5.0 becomes 1.5.1 with amendment
date 2026-11-02. No sections, placeholders or deferred governance items are added.
The temporary sync-impact report is recorded here rather than retained in governance
content; generated templates and skill files remain unchanged.

## Independent review

The coordinating parent reported fresh `project_review` verdict **SHIP** with no
blocking defects on 2026-11-02. The reviewer validated all twelve project no-impact
records and inspected the documentation evidence across the integrated migration.
No runtime acceptance is inferred from that review. Authorized repository commit
and release gates remain in force; failed gates must be reported separately.
