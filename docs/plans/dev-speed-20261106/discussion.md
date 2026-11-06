# Development speed: open discussion

Date: 2026-11-06. These items from the [development speed plan](plan.md) are
undecided. A later session continues the discussion with the owner. Nothing here
is approved.

## C1: one git worktree per session

**Today.** Parallel sessions share one checkout. Engineering guidance even
prescribes "unique temporary message files when several writers share the
checkout".

**How it would help.**

- **Lost or mixed edits.** While a long commit hook runs, pre-commit/prek keeps
  every unstaged change stashed. The live tests take minutes. If another session
  edits a file during that time, its edit conflicts with the restore, or gets
  mixed into the wrong state.
- **Cross-staging.** `git add` and `git commit` act on one shared index. One
  session can commit another session's half-done files, or a hook (ruff format,
  `uv lock`) can rewrite them.
- **Shared caches.** `.testmondata`, the mypy/dmypy state and `.pytest_cache`
  are shared too. Concurrent runs corrupt them or trigger needless reruns.
- With a worktree per session (`claude --worktree` or EnterWorktree, or Codex
  worktrees), each session has its own index, stash, venv and caches. Sessions
  meet only at merge time, through git.

**Costs.**

- A `.venv` per worktree. uv hard-links packages, so the disk cost is modest,
  but first-time setup takes about a minute.
- Live runs happen at the same time when several worktrees commit
  live-affecting code. The registry capacity applies.
- Each session must start on a branch and later merge, which interacts with C3.

**Open question.** After A5 and A6, the live tests run only when affected and
the stash is held for less time. Is the residual risk worth requiring
worktrees, or is it enough to recommend them for long tasks?

## C2: evidence outside the repository

**Today.** About 50 of the 113 commits since 2026-09-01 are bookkeeping:
"record", "merge", "reconcile" or "close" evidence, receipts and acceptance.
They create merge chains and documentation conflicts between sessions.

**Owner's concern.** Moving evidence out of the repository may lose context.

**Middle options.**

- **(a)** The evidence file is written in the same commit as the change, never
  as a follow-up "record evidence" commit. Results that only exist after the
  commit (for example hook output) go into the commit message body.
- **(b)** Commit trailers carry the check results, for example
  `Checks: pytest 2835 passed; live 38 passed`, and the plan directory keeps
  only decisions.
- **(c)** One rolling `verification.md` per task, amended in place until
  acceptance, instead of new dated files.
- **(d)** `git notes` for post-commit receipts. Notes are not pushed by default
  and are easy to lose, so this is probably not suitable.

This needs constitution and global-instruction wording ("keep dated
evidence") reconciled with whichever option is chosen.

## C3: short-lived branches rebased onto `main`

It pairs with A2, which uses fast-forward merges. To decide:

- the maximum branch lifetime;
- one open branch per session;
- whether long cleanups like `project-cleunap` get split into mergeable slices.

After a rebase the hooks must be rerun (`prek run --all-files`), as already
documented.

## C6: split the instruction layers into granular files

The owner prefers splitting over merging. Today the large files are
`engineering.md` (382 lines), `constitution.md` (195), `architecture.md` (347)
and `specs/baseline.md` (778).

The idea is small topic files that parallel sessions can edit without
conflicts, each loaded only when relevant. Possible topics:

- working tree;
- Spec Kit workflow;
- architecture rules;
- conventions;
- verification;
- hooks;
- releases;
- integration and infra;
- configuration.

To decide:

- the file boundaries;
- whether `AGENTS.md` links to all of them or only to an index;
- whether the generated `speckit-*` skills reference specific paths in
  `.specify/memory/` (`constitution.md` must stay where Spec Kit expects it);
- how to keep links stable now that the `test_docs.py` link check is gone.

## D4: faster type checker

The candidates are basedpyright, Astral's `ty` and Meta's `pyrefly`, either
alongside strict mypy or replacing it. To decide:

- the strictness and semantics gap against `mypy --strict`, including the
  pandas-stubs and pydantic plugins;
- whether A7 (dmypy) already removes the speed problem;
- the maintenance cost of two checkers.

## Rejected (do not propose again)

- **A9:** GitHub Actions CI.
- **C8:** `merge=union` drivers and `rerere`.
- **D2:** `pytest-timeout`.
