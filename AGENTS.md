# cveta2 agent instructions

cveta2 is a Python >=3.12,<3.14 CLI and API for CVAT annotation projects: it fetches
bounding-box annotations, partitions them by task completion state, downloads images from
S3, converts, uploads and publishes datasets, and manages project labels. Run Python
tools through `uv run`. The Russian [README](README.md) describes usage.

## Rules

- Deliver every change through a Linear issue in team `SIP`, project `cveta2`, a task
  branch and a GitHub PR. Agents commit task-owned changes, push task branches and open
  PRs; humans merge into `main`, and a merge releases automatically when its commits call
  for a version. Never push `main`, merge locally into `main`, create tags or release
  locally; an implementation request authorizes no release action. Explicit session
  restrictions and host read-only modes take precedence.
- Inspect existing and staged changes before editing. Treat them as user work: stage only
  task-owned paths, never stash, reset or discard other work, and preserve local
  overrides.
- Use Conventional Commits; the commit type decides the release
  ([commit procedure](docs/development.md#commit-procedure)).
- The repository owns product behavior: the files in `docs/feature/` describe it as it is.
  A PR that changes behavior updates the affected feature file and the affected section
  of the Russian guides (`docs/cli.md`, `docs/configuration.md`, `docs/python-api.md`,
  `docs/images-and-cache.md`) in the same change.
- Linear owns issues, plans, acceptance criteria, discussion, status and evidence.
  Evidence (counts, timings, results, identities) lives only in the Linear issue and the
  PR; the repository holds no dated evidence, plans or ADRs, and documentation states
  current behavior only.
- Resolve material requirement ambiguities before implementing. A bug fix records the
  failing observation, a reproduction where feasible and verification of the original
  failure path. Before completion, compare the final diff, the executed checks and the
  review with the acceptance criteria. Continue authorized implementation, documentation
  and verification without asking at each stage, but stop at every stopping point
  recorded in the issue.
- Report each required check as passed, failed, deferred, waived or error. A deferred
  required check blocks acceptance, merge readiness and release; only the user waives a
  check, by stating it or by a human merge of a PR whose description lists that gate as
  not run (recorded as waived by merge). A waiver is never a pass.
- Behavior, interface, dependency, security and operational-policy changes get a fresh
  independent review after integrated verification; wording edits may be self-reviewed.
- Delegate independent substantial work with bounded ownership and acceptance evidence,
  keep dependent work ordered, and inspect the integrated result.
- `README.md`, the human usage guides in `docs/` and CLI output are Russian; agent
  instructions, skills, architecture and other documentation are English.
- Edit maintained sources, not generated or installed copies, and keep machine-specific
  settings out of portable guidance.
- When rewriting requirements or behavior documentation, compare the original behavior,
  conditions, limitations and exceptions, including scenario exceptions, with every new
  home and preserve compatibility; keep approved policy changes separate from wording
  changes, and have the reviewer compare meaning against
  the original rather than judge the resulting prose.

## Read when relevant

| Trigger | Read |
| --- | --- |
| Change behavior, configuration, API return values or serialized formats | The affected file in `docs/feature/` and its Russian guide section |
| Write or edit Python code or tests | [Code conventions](docs/architecture.md#code-conventions) and [test conventions](docs/development.md#test-conventions) |
| Change module structure, imports or effects | [Architecture](docs/architecture.md) |
| Set up a worktree, verify, commit or release | [Development procedures](docs/development.md); read its commit procedure before every commit |
| Change Task stages, hooks, preflight, Kubernetes manifests or the live-session lifecycle | [Development procedures](docs/development.md) and the module docstring of [lifecycle.py](tests/integration/lifecycle.py) |
| Plan or deliver issues and PRs | [Issue tracker](docs/agents/issue-tracker.md) and [issue template](docs/agents/issue-template.md) |
| Select checks, report verification | [verification-workflow](.agents/skills/verification-workflow/SKILL.md) |
| Run live tests, manage or clean up a session | [running-integration-tests](.agents/skills/running-integration-tests/SKILL.md) |
| Triage mutation survivors or change mutation settings | [mutation-testing](.agents/skills/mutation-testing/SKILL.md) |
| Prepare merge readiness, inspect or recover a release | [release](.agents/skills/release/SKILL.md) |

`scripts/session_status.sh` runs at Claude and Codex session start and reports the branch
against `main`, uncommitted paths, other worktrees, unmerged branches and a kept live
session. Changes it lists may belong to another session.

## Instruction files

`AGENTS.md` is the shared instruction source and holds the rules that apply to every task;
procedures live in `docs/development.md` and the project skills. `CLAUDE.md` stays a
regular file containing `@AGENTS.md`. Author each project skill in
`.agents/skills/<name>/`; `.claude/skills/<name>` is a relative symlink to
`../../.agents/skills/<name>`, so both hosts read one copy. Add each new skill to the
`.agents/skills` exceptions in `.gitignore`.

## Agent skills

### Issue tracker

For ticket operations, use the [Linear conventions](docs/agents/issue-tracker.md).

### Triage labels

For ticket triage, use the [readiness labels](docs/agents/triage-labels.md).

### Domain docs

Before domain exploration, follow the [domain documentation guidance](docs/agents/domain.md).
