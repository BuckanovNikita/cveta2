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

Human setup and invocation examples are in [CONTRIBUTING.md](CONTRIBUTING.md).

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

These skills remain applicable within the Spec Kit workflow:

- `commit` — stage exact paths, write Conventional Commits, handle hook rewrites,
  and run gated pushes.
- `mutation-testing` — mutmut gate failures, survivors, equivalents, scope and profiles.
- `running-integration-tests` — live CVAT/MinIO/ClearML runs, run tags, cleanup and
  the pre-push integration gate.

## Authorization

- Continue authorized stages through verification, documentation and the project
  release workflow without requiring a separate user prompt for each stage.
- Standing user authorization satisfies commit/push request gates in project skills;
  explicit stopping points and host Plan Mode/read-only limits take precedence.
