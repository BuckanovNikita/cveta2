# Tasks: development speed

Plan: [plan.md](plan.md). A task's status changes only after it is verified.
Dated evidence: [verification-2026-11-06.md](verification-2026-11-06.md).

- [x] T0 Plan record, discussion and architecture record (`--phase plan`).
- [x] T1 Phase 1:
  - `prek` runner;
  - delete `tests/test_docs.py` and its references;
  - A1 path filters;
  - A3, which removes `count-lines` and gates `uv build` on `pyproject.toml`;
  - A8 `uv lock --check`, `UV_LOCKED=1` and the lockfile guard.
  - Depends on T0.
- [x] T2 Phase 2:
  - live tests in the normal suite, behind a session fixture with tag
    lifecycle and a wait-and-notify for a stopped stand;
  - `--dist loadgroup` in `addopts`, and a marker that excludes the live tests;
  - pytest-testmon at commit;
  - pytest-randomly;
  - remove the `integration-tests` hook in the same commit.
  - Depends on T1.
- [x] T3 Phase 3: mutation budget (`--budget-seconds`/`--max-functions`), with
  shorter output. Depends on T1.
- [ ] T4 Phase 4:
  - a fast-forward-only merge after the full check on the branch tip;
  - the release commit skips the heavy hooks, as an approved exception;
  - `flock` release lock;
  - constitution and engineering amendments.
  - Depends on T2.
- [ ] T5 Phase 5 test debloat:
  - B8 policy first;
  - B7 analysis;
  - then B1, B3, B4, B5, B6 and B9 by test cluster.
  - Depends on T2.
- [ ] T6 Phase 6:
  - C5 SessionStart status hook (Claude and Codex);
  - C7 Spec Kit only for features.
  - Depends on T4.
- [ ] T7 Phase 7: A7 dmypy (global skill, then the project hook) and D3 deptry.
  Depends on T1.
- [ ] T8 Phase 8 global setup:
  - agent-skills scaffold defaults;
  - global instruction line;
  - k8s-infra contract check;
  - memory;
  - export sync.
  - Depends on T2 and T7.
- [ ] T9 Fresh independent review of the full diff, acceptance validation and
  evidence. The merge and release wait for the owner to end the cleanup.
