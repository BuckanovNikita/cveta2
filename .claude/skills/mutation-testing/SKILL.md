---
name: mutation-testing
description: Diagnose or change cveta2's mutmut gate. Use for surviving or uncovered mutants, fast/full profile failures, mutation-score interpretation, equivalent-mutant decisions, or edits to only_mutate, profiles, and mutation configuration.
---

# Maintain the cveta2 mutation gate

`scripts/mutation_test.sh` runs mutmut for the current
`[tool.mutmut].only_mutate` scope and uses `scripts/mutation_gate.py` for
the real pass/fail result. Read live `pyproject.toml` and the scripts before
changing configuration; do not rely on a copied module inventory.

## Commands and profiles

```bash
./scripts/mutation_test.sh --profile fast
./scripts/mutation_test.sh --profile full
./scripts/mutation_test.sh
./scripts/mutation_test.sh '<mutant-name-or-glob>'
uv run mutmut show <name>
uv run mutmut browse
```

`fast` is the pre-commit subset. `full` is the pre-push scope and its
profile list is intentionally empty: that produces a bare `mutmut run`, which
can reuse cached verdicts. Replacing the empty list with `"*"` passes a
positional filter and re-executes the whole scope. A run without `--profile`
also covers the full configured scope.

## What pass, score, and profile output mean

`mutmut run` itself exits zero, so it does not decide the gate.
`mutation_test.sh` exports CI stats and textual results, then the gate:

- treats `killed`, `skipped`, and `caught by type check` as benign;
- fails on any other result not justified in
  `[tool.cveta2.mutation.equivalent]`;
- fails when an equivalent entry no longer names a live survivor;
- narrows both survivors and allowlist entries to the selected profile.

The printed mutation score is `killed / total` for the whole configured scope.
It includes whole-scope context even during a filtered profile and is not a
quality threshold. A passing gate means zero unexplained survivors and zero
stale justifications in the selected scope; read the profile's “not killed”
count separately from the whole-scope score.

## Scope decisions

Scope is a ratchet. Add a module to `only_mutate` only with the coverage,
assertions, and justified equivalents that make the gate pass in the same
change. There is no parked measured tier because `mutmut results` walks every
configured file. Evaluate a candidate in an isolated worktree or disposable
copy so temporary scope edits cannot overwrite a shared working tree.

Use two admission stages:

1. Close meaningful line coverage. With `mutate_only_covered_lines` off, an
   uncovered line produces automatic survivors; mutmut's `no tests` result is
   the relevant disqualifier.
2. Triage survivors for assertion quality and genuine equivalence.

Exclude zero-mutable or low-signal presentation/plumbing surfaces only for a
specific, documented reason. Do not preserve static “in/out of scope” lists in
this skill; `only_mutate` is authoritative.

## Triage a survivor

Inspect the exact mutant and the test path that should observe it.

1. Strengthen a behavioral assertion when the mutation changes an outcome,
   boundary, side effect, or contract.
2. If the mutation genuinely cannot change behavior, add the exact mutant name
   to `[tool.cveta2.mutation.equivalent]` with a reason that proves
   equivalence.
3. Use `do_not_mutate_patterns` for a stable class of low-signal presentation
   surfaces, not to hide functional logic.

Never reshape correct production code solely to make mutmut stop generating a
mutant. Do not pin serialized formatting when consumers parse it, or message
wording when only presentation changes. Test the contract the user or caller
observes.

Equivalent names are unstable when a function changes. Re-read every affected
justification after renumbering; stale entries intentionally fail the gate.

## Configuration invariants

Read [mutation-internals.md](mutation-internals.md) before an unkillable mutant,
scope/profile edit, cache surprise, or performance diagnosis. Preserve these
current invariants unless the underlying tool behavior changes and is verified:

- `pytest_add_cli_args` includes `-n 0`; an xdist pool per mutant can hang
  or distort results.
- `cache_invalidation_files` and
  `on_dependency_change = "rerun"` prevent weakened tests from reusing stale
  verdicts.
- `mutate_only_covered_lines` stays off because its coverage pre-pass corrupts
  the later stats run in this environment.
- `mutation_config.py sync-scope` fingerprints mutation-scope fields and
  recreates `mutants/` when they change; mutmut's own fingerprint omits them.
- `PYTEST_DEBUG_TEMPROOT` stays under this checkout's `mutants/` so another
  pytest session cannot remove a shared temp-root link and create a false kill.
- `mutants/` remains generated, gitignored, and excluded from normal analysis.

Adding a new targeted test may require regenerating `mutants/` because mutmut
can retain the old test-to-mutant association. Confirm that diagnosis before
removing the generated workspace; never delete source or test files.

## Completion

For a survivor, report its diff, classification, observing test, and targeted
rerun. For a configuration or scope change, report the changed live settings
and the required fast/full result. Do not claim a mutation gate passed unless
the corresponding script completed and printed no unexplained mutants.
