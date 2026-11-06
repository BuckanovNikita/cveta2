# cveta2 agent entry point

cveta2 is a Python >=3.12,<3.14 CVAT CLI and API. Run Python tools through `uv run`.

This file is the shared discovery entry point for Codex and Claude; `CLAUDE.md` is a
regular file importing it with `@AGENTS.md`. Keep detailed rules in the canonical
sources below rather than duplicating them here.

## Language

- Follow the user's conversation language (English by default); repository language
  conventions do not override it.
- Human guides and CLI output remain Russian. Agent instructions, skills, Spec Kit
  memory and feature artifacts, and the dataset contract are English.

## Read before planning or editing

1. [Spec Kit constitution](.specify/memory/constitution.md) for project principles.
2. [Engineering guidance](.specify/memory/engineering.md) for the required
   workflow, verification, working-tree ownership, integration, and release rules.
3. [Architecture context](.specify/memory/architecture.md) when changing module
   flow, project resolution, fetch/upload, or conversion behavior.
4. [Current specification and dataset contract](specs/baseline.md) for preserved
   behavior, acceptance criteria and immutable historical decisions.

Human usage is in [README.md](README.md); setup commands are in
[engineering guidance](.specify/memory/engineering.md); release commands are in the
`release` skill.

## Workflow

- Use `$speckit-<step>` in Codex and `/speckit-<step>` in Claude. Follow the full
  sequence in engineering guidance; select the active feature explicitly before
  writing artifacts.
- New features describe deltas from the baseline; archived features are historical
  evidence.
- Use the shared `python-project-workflow` and `module-architecture-planning` skills
  within the selected native stages for Python conventions and architecture evidence.
- Inspect instructions, current artifacts, configuration and diffs before choosing checks.

## Project skills

These skills hold situational procedures within the Spec Kit workflow; commit and
hook rules are in engineering guidance. Sources live in `.agents/skills/` and
`.claude/skills/` symlinks to them; the generated `speckit-*` skills are per-host
copies (see engineering guidance, "Project skills").

- `mutation-testing` — run and triage the changed-function mutation check.
- `running-integration-tests` — live CVAT/MinIO/ClearML runs, run tags, cleanup and
  the pre-commit integration gate.
- `release` — the semantic-release procedure on `main` and its failure recovery.

## Authorization

- Continue authorized stages through verification, documentation and the project
  release workflow without requiring a separate user prompt for each stage.
- Standing user authorization covers the required commits, release and commit/tag
  pushes in engineering guidance; explicit stopping points and host Plan
  Mode/read-only limits take precedence.
