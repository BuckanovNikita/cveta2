# cveta2 agent entry point

cveta2 is a Python >=3.12,<3.14 CVAT CLI and API. Run Python tools through `uv run`.

This file is the shared discovery entry point for Codex and Claude; `CLAUDE.md` is a
regular file importing it with `@AGENTS.md`. Keep detailed rules in the canonical
sources below rather than duplicating them here.

## Language

- Human guides and CLI output remain Russian. Agent instructions, skills, Spec Kit
  memory and feature artifacts, and the dataset contract are English.

## Read before planning or editing

1. [Spec Kit constitution](.specify/memory/constitution.md) for project principles.
2. [Engineering guidance](.specify/memory/engineering.md) for the required
   workflow, verification, working-tree ownership, integration, and release rules.
3. [Architecture context](.specify/memory/architecture.md) when changing module
   flow, project resolution, fetch/upload, or conversion behavior.
4. [Functional specification](specs/baseline.md) for preserved behavior and
   compatibility obligations of any workflow you change.
5. [Dataset contract](docs/dataset-contract.md) when changing CSV columns, API
   return values or serialized file formats.
6. [Glossary](GLOSSARY.md) for dataset-preparation terms (standalone and managed
   preparation, source evidence, prepared bundle, parent dataset).

Human usage is in [README.md](README.md); setup commands are in
[engineering guidance](.specify/memory/engineering.md); release commands are in the
`release` skill.

Release only Git version tags; do not create GitHub Releases or publish release
assets or packages. Follow the release policy in the engineering guidance.

## Workflow

- Use `$speckit-<step>` in Codex and `/speckit-<step>` in Claude. Follow the full
  sequence in engineering guidance; select the active feature explicitly before
  writing artifacts.
- New features describe deltas from the baseline; product requirements contain no
  implementation status.
- Apply the Python conventions in the constitution within the selected native stages.

## Project skills

These skills hold situational procedures within the Spec Kit workflow; commit and
hook rules are in engineering guidance. Sources live in `.agents/skills/` and
`.claude/skills/` symlinks to them; the generated `speckit-*` skills are per-host
copies (see engineering guidance, "Project skills").

- `mutation-testing` — run and triage the changed-function mutation check.
- `running-integration-tests` — explicitly invoked live CVAT/MinIO/ClearML tests,
  run tags, cleanup and the stopped-stand wait.
- `release` — the semantic-release procedure on `main` and its failure recovery.

## Authorization

- Continue authorized stages through verification, documentation and the project
  release workflow without requiring a separate user prompt for each stage.
- Explicit stopping points and host Plan Mode/read-only limits take precedence.

## Project execution policy

Use Spec Kit for new capabilities or documented behavior changes; routine fixes,
docs and small refactors proceed directly, updating existing task artifacts as needed.
Behavior, interface, dependency, security and operational-policy changes require
independent review after integration and verification; wording edits may be self-reviewed.
Documentation checks are limited to native Spec Kit or OpenSpec checks. Local commits
may be autonomous; pushes require separate authorization, including existing session authorization.

## Split commits and final verification

Intermediate task commits may skip explicitly named verification hooks with `SKIP`;
keep commit-message validation enabled. After the last commit, clear `SKIP` and run
`prek run --all-files` through the project environment. Keep applicable manual and
release gates. Inspect auto-fixes and commit mechanical changes separately, then
repeat affected verification until the final committed content passes without changes.
Reuse successful checks while their inputs remain unchanged; do not repeat full
verification before every intermediate commit.

## Specification rewrites

Compare the original behavior, conditions and exceptions with their new authoritative
homes, including requirements embedded in scenarios. Separate approved policy changes
from wording changes; resolve overloaded terms before editing. Retain compatibility
obligations, remove historical status claims, and have the reviewer compare meaning
against the original source rather than judge length or wording alone.
