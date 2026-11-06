# Tasks: scripts/ simplification

Plan: [plan.md](plan.md). Status is updated only after verification;
evidence is in [verification-2026-11-06.md](verification-2026-11-06.md).

- [x] T1 Validate architecture record (`--phase plan`).
- [x] T2 Tier 1: conventional-pre-commit hook; inline version-drift entry; remove both scripts.
- [x] T3 Tier 1: move the effect checker to `tests/architecture_effects.py`; drop the hook. Depends on T1.
- [x] T4 Tier 1: delete the upload/export tools; move `clone_project_to_s3.py` into `tests/integration/` and reuse the package's storage parsing.
- [x] T5 Tier 1 documentation and reference sweep; commit.
- [x] T6 Tier 2: `scripts/mutation.py` and `tests/test_mutation_tool.py`; remove the three old files; update hooks, docs and the skill; commit.
- [x] T7 Tier 3: `tests/integration/lifecycle.py`, the ported `tests/test_integration_lifecycle.py` and the boundary contract; remove the five shell scripts.
- [x] T8 Tier 3 documentation (CONTRIBUTING, engineering memory, integration skill, `.env.example`, docstrings); commit.
- [x] T9 Live check: up → targeted test → stop with exact-tag cleanup proof. Depends on T7.
- [ ] T10 Fresh independent review of the full diff; resolve findings.
- [ ] T11 Record evidence; validate with `--phase acceptance`; push through the gates; confirm with `git ls-remote`.
