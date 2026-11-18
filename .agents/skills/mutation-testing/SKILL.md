---
name: mutation-testing
description: Use when running cveta2's changed-function mutation report, triaging surviving or unreached mutants, deciding whether a survivor is equivalent, explaining a run with no mutants, or changing the [tool.mutmut] settings.
---

# Triage mutation results

Paths start at the repository root. `docs/development.md#mutation-report` holds the
commands, budget, exit meanings, the reasons a change produces no mutants and the
`[tool.mutmut]` invariants; the module docstring of `scripts/mutation.py` describes how
functions are selected.

1. Run the report over the whole branch:
   `uv run --locked task --exit-code mutation -- --base main`. Without `--base` it covers
   only staged content against `HEAD`.
2. List the functions mutated and those skipped by `--max-functions`, and the counts of
   killed, survived, not-reached and not-run mutants. Act on the exit code as
   `docs/development.md#mutation-report` describes; diagnose exit 2, never report it as a
   result.
3. For each survivor, read the diff and compare it with what a caller can observe:
   - it changes an outcome, boundary, side effect or contract: strengthen or add a
     behavioral test, stage it and rerun;
   - it is equivalent or changes only presentation: leave the code and write the
     reasoning down. There is no allowlist.
   Follow the mutation rules in `docs/development.md#test-conventions`.
4. For functions no unit test reaches, add a unit test that calls them where one can
   observe their behavior, and report any that remain unreached.
5. Record in the Linear issue the base, the functions mutated and any skipped by the
   budget, the killed, survived, not-reached and not-run counts, each survivor's
   classification (test added, equivalent, presentation) and the rerun result. Done when
   every survivor and unreached function has a disposition.

When changing the mutmut settings, keep every invariant listed in
`docs/development.md#mutation-report`.
