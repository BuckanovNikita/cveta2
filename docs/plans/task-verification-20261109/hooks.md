# Git hook rollout experiment — 2026-11-09

Manual experiments copied the production `scripts/install-hooks.sh`,
`scripts/git-hook.sh` and `.pre-commit-config.yaml` into a disposable Git
repository with a linked legacy worktree. No actual project hook installation,
configuration, index or branch was changed. The driver ran through
`uv run --locked python`; each fixture operation was a real Git command.

A temporary `uv` wrapper logged its working directory and arguments. For
`uv run --locked prek ...` it executed the project's actual prek 0.5.10 binary.
For `uv run --locked task --exit-code verify` it returned a configured status,
without running project verification. Thus this experiment validates Git/prek
routing and real Conventional Commit validation; it does not establish that
Task's production checks pass. The production remote Conventional Commit hook
was executed by prek, not replaced with a stub.

## Input guards and verification selection

Each guarded case used `git commit [--allow-empty] -m 'test: ...'`; the unborn
case started before any commit existed. Input edits and staging happened before
invocation. The `uv` log established whether rejection preceded prek.

| Case | Git exit | Calls reached | Observation |
|---|---:|---|---|
| Unborn repository, nonignored untracked inputs | 1 | none | Rejected before prek |
| All unborn inputs staged | 0 | prek, verify, commit-msg | Initial commit accepted |
| Unstaged tracked modification | 1 | none | Rejected before prek |
| Partially staged tracked modification | 1 | none | Rejected before prek |
| Staged change plus nonignored untracked file | 1 | none | Rejected before prek |
| Staged change plus ignored untracked file | 0 | prek, verify, commit-msg | Accepted |
| Staged change, mocked Task exit 7 | 1 | prek, verify | prek reports hook exit 7; no commit-msg |
| Staged change, invalid message `invalid subject` | 1 | prek, verify, commit-msg | Real Conventional Commit hook rejects |
| Same staged change, `test: valid subject` | 0 | prek, verify, commit-msg | Accepted |
| Unstaged tracked deletion | 1 | none | Rejected before prek |
| Staged deletion | 0 | prek, verify, commit-msg | Always-selected verify runs |
| Empty commit on clean new worktree | 0 | prek, verify, commit-msg | Always-selected verify runs |

The shim's direct invocation with a mocked prek returning 7 returned exactly 7:

```text
bash scripts/git-hook.sh pre-commit <fixture-hooks-directory>
```

Real prek aggregates a failed verify hook into a nonzero status; Git reports
failed commits as exit 1. Infrastructure-specific statuses must therefore be
interpreted at the direct Task boundary, as documented, rather than inferred
from `git commit`'s status. No failing command was suppressed.

## Shared hooks and legacy worktree

`bash scripts/install-hooks.sh` installed the shared dispatchers. A subsequent
`git worktree add -b legacy <fixture-legacy-path>` created a linked worktree
using the same `.git/hooks`. In that worktree, the Taskfile and new scripts were
removed and its prek configuration replaced with a small local legacy hook.
Its commit successfully executed that legacy hook through actual prek. The log
showed both hook invocations executing from the legacy worktree while using
the common hooks directory; no Task invocation occurred.

Returning to the new worktree and making an empty Conventional Commit executed
its Task verify entry and its Conventional Commit hook. This proves dispatch
resolves the invoking worktree at runtime, rather than retaining the install
worktree's path or configuration. The legacy fixture deliberately omitted a
message validator; the dispatcher preserved that older configuration instead
of imposing the new worktree's configuration.

## Backup and rollback

Before installation, both hook files contained identifiable executable fixture
hooks returning 23. Installation saved byte-identical copies with executable
modes in the reported unique `cveta2-backup.*` directory. Restoring those two
files with `shutil.copy2` made the next Git commit fail through the original
hook, before any uv call. A separate fresh repository with neither hook present
received `pre-commit.absent` and `commit-msg.absent` markers, so rollback can
restore absence instead of inventing prior contents.

## Tested artifacts

SHA-256 hashes below matched the production files when the experiment finished:

```text
scripts/install-hooks.sh
  a317e967cc4ef89b56773b9a783b48736fd4c9da830e137086234cf07a12f29e
scripts/git-hook.sh
  9d5d493a8fd279c24d0e8f600dce44ed65fadfff316d471aba60f9a0252460a4
.pre-commit-config.yaml
  227f4828277f0fb78947133dd3023a12505f446f32602d2fe17318c2fc354602
```

These checks establish the staging gate, serial always-selected hook routing,
message validation, worktree compatibility, and rollback behavior. Production
Task execution, live acceptance, and actual shared-hook installation remain
separate validation stages.

All task-owned fixture repositories, linked worktrees, logs and drivers were
removed after recording results. The earlier parent-owned staging-guard
fixture was also removed as authorized. No process or service remains.
