# cveta2 agent entry point

cveta2 is a Python >=3.12,<3.14 CVAT CLI and API. Run Python tools through `uv run`.
`CLAUDE.md` imports this shared entry point with `@AGENTS.md`.

## Read before work

- Read [engineering policy](docs/agents/engineering.md) before planning, editing,
  verification or commits, and [Linear/GitHub delivery](docs/agents/issue-tracker.md)
  before planning or delivering repository changes.
- Consult the [product contract index](docs/agents/contracts.md) before changing
  behavior, configuration, API return values or serialized formats.
- Read [architecture](docs/agents/architecture.md) before changing module flow,
  project resolution, fetch/upload or conversion behavior.
- Use [domain documentation](docs/agents/domain.md) and [GLOSSARY.md](GLOSSARY.md)
  for dataset-preparation terminology; [triage guidance](docs/agents/triage-labels.md)
  owns readiness labels.

Linear owns current product requirements, proposals, plans and task status; repository
policy owns engineering safeguards. Spec Kit is temporarily disabled. Preserve
`specs/`, `.specify/` and archived tooling unchanged and outside active discovery.
Reactivation requires explicit user instruction. Historical workflow instructions
are inactive; historical product requirements remain preserved through the migration.
The approved migration branch uses the new workflow; repository-wide authority changes
only after human merge and accepted migration, with Linear drafts activated then.

## Language and ownership

Keep README, human usage guides and CLI output Russian. Agent instructions, skills,
architecture, plans and evidence are English. Keep this entry point concise and link
procedures. Edit maintained sources, preserve unrelated work and local overrides,
and keep machine-specific settings out of portable policy.

## Delivery and completion

Agents may commit task-owned changes, push task branches and open GitHub PRs. Humans
merge into `main`; agents do not deliver through local main merges or main pushes.
Explicit session restrictions and host read-only modes take precedence. Code releases
are suspended pending separately authorized PR-based release tooling.

Use [verification-workflow](.agents/skills/verification-workflow/SKILL.md) before
verification or completion claims. Task owns commands; prek owns hooks and message
validation. Preserve required gates and report executed evidence accurately. Deferred
live verification blocks acceptance and merge readiness; continue independent work
and ask for the user's decision when only blocked verification remains.

Delegate independent substantial work with bounded ownership and acceptance evidence;
keep dependencies ordered and inspect integrated results. Behavior, interface,
dependency, security and operational-policy changes require fresh independent review
after integrated verification. Wording edits may be self-reviewed. Review documentation
consistency proportionately without introducing a documentation checker.

## Situational skills

Authored sources live in `.agents/skills/`; Claude symlinks use those same sources.

- `mutation-testing`: changed-function mutation execution and survivor triage.
- `running-integration-tests`: live CVAT, MinIO and ClearML sessions, preflight,
  namespace ownership, kept sessions and cleanup.
- `release`: suspended release route and requirements for its replacement.

For requirement rewrites, compare original meaning, conditions and scenario exceptions
against their new authoritative homes; preserve compatibility and immutable provenance.
Separate approved policy changes from wording changes. Independent review must compare
meaning against the original source, not just judge the resulting prose.
