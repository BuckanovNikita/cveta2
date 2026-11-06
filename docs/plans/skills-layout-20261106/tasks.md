# Tasks: project skills layout

Plan: [plan.md](plan.md). Status is updated only after verification;
evidence is in [verification-2026-11-06.md](verification-2026-11-06.md).

- [x] T1 Validate the no-impact architecture record (`--phase plan`).
- [x] T2 Move authored skills to `.agents/skills`, symlink them from `.claude/skills`, fix `.gitignore`. Depends on T1.
- [x] T3 Fold `commit` into engineering guidance; delete it; add `release`; slim `running-integration-tests`; update `AGENTS.md`. Depends on T2.
- [x] T4 Regenerate the Spec Kit skills with the installed `specify`. Depends on T1.
- [x] T5 Layout tests in `tests/test_docs.py`, with negative checks. Depends on T2-T4.
- [x] T6 Checks, fresh independent review, evidence, `--phase acceptance`, commit and push the branch. Depends on T5.
