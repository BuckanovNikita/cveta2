# Agent instruction refactor (2026-11-04)

Documentation-only maintenance. No product behavior, runtime module or test changes.

## Scope

- `AGENTS.md`: restructured into headed sections (Language, Read before planning or
  editing, Workflow, Project skills, Authorization). All four test-pinned links kept;
  the language rule is merged here from `engineering.md`; the three project skills are
  named with when to use them.
- `.specify/memory/engineering.md`: contents line, language/entry-point duplicate
  removed, duplicated standing-authorization passage replaced by a pointer to
  "Preserve the working tree". The `## Shared infra` block is unchanged.
- `.claude/skills/commit/SKILL.md`: description rewritten with trigger terms (valid YAML),
  full list of accepted commit types, standing-authorization exception stated once.
- `.claude/skills/mutation-testing/`: description rewritten; internals reference fixed
  (stale caption-entry claim, mutmut source citation, full module path), contents line.
- `.claude/skills/running-integration-tests/`: description rewritten, one overlong line
  reflowed; parallel guide gets a contents line.

## Unchanged

`CLAUDE.md`, the constitution, the architecture contract, Spec Kit generated skills and
tooling, and the `.agents/skills/*` discovery symlinks.

## Checks

See `verification-2026-11-04.md`.
