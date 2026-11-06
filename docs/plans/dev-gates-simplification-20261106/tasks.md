# Tasks: development gates simplification

Plan: [plan.md](plan.md). Status is updated only after verification;
evidence is in [verification-2026-11-06.md](verification-2026-11-06.md).

- [x] T1 Validate the architecture record (`--phase plan`).
- [x] T2 Rewrite `scripts/mutation.py` (change-scoped, advisory, per-run workspace) and `tests/test_mutation_tool.py`. Depends on T1.
- [x] T3 Strip the ratchet configuration from `pyproject.toml`. Depends on T2.
- [x] T4 `tests/integration/lifecycle.py`: arm on the installed skill, `room` preflight, no push-branch detection; update `tests/test_integration_lifecycle.py`; delete `.env.example`. Depends on T1.
- [x] T5 `.pre-commit-config.yaml`: everything in pre-commit, `fail_fast`, file filters, no pre-push or version-drift. Depends on T2, T4.
- [x] T6 Amend the constitution and `engineering.md`; slim the three project skills; update `AGENTS.md`, `scripts/README.md`. Depends on T5.
- [x] T7 Remove `mutants/`, uninstall the local pre-push hook, update agent memory. Depends on T5.
- [x] T8 Static checks, targeted tests, mutation end-to-end checks (survivor reported, nothing to mutate, timing). Depends on T2-T6.
- [x] T9 Fresh independent review of the full diff; resolve findings. Depends on T8.
- [x] T10 Record evidence; `--phase acceptance`; commit through the full pre-commit gate including live integration; push; confirm with `git ls-remote`. Depends on T9.
