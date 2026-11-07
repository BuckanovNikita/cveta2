---
name: mutation-testing
description: Runs and triages cveta2's changed-function mutation check (scripts/mutation.py, [tool.mutmut] in pyproject.toml). Use for surviving mutants reported by the manual mutmut hook, hardening tests of a function, deciding whether a survivor is equivalent, a run that produces no mutants, or edits to the mutmut settings.
---

# Changed-function mutation testing

`scripts/mutation.py` maps the staged diff to the top-level functions and methods
it touches, exports the index into a fresh temporary workspace, and runs mutmut
there on those functions only. It reports survivors (the first five with diffs)
and passes; nothing is cached or shared between runs. The hook runs within a
budget: at most 8 changed functions (`--max-functions`) and 120 s of mutmut
(`--budget-seconds`); unjudged mutants count as "not run", and mutants no unit
test reaches as "not reached by tests", never as survivors. Read the script's
docstring for the mechanics.

```bash
uv run prek run mutmut --hook-stage manual --all-files  # staged change vs HEAD
uv run python scripts/mutation.py --base main       # the whole branch
uv run python scripts/mutation.py cveta2/domain/merge.py   # every function of a file
uv run python scripts/mutation.py --keep --strict   # keep workspace; exit 1 on survivors
uv run python scripts/mutation.py --budget-seconds 0 --max-functions 0  # no budget
```

With `--keep`, `cd` into the printed workspace and use
`<repo>/.venv/bin/mutmut show <name>` or `browse`.

## Triage a survivor

Survivors are information, not a gate. Triage only behavioural ones; do not add
tests that exist only to kill a mutant of a default argument, a message's
wording or another presentation detail.

1. Read the diff. If the mutation changes an outcome, boundary, side effect or
   contract a caller can observe, strengthen or add a behavioural test, stage
   it, and rerun.
2. If it cannot change observable behaviour (equivalent), or only changes
   presentation, leave it and say so in the report. There is no allowlist.
3. Never reshape correct production code only to stop a mutant, and do not pin
   message wording or serialized formatting a consumer parses anyway.

## Why a change produces no mutants

mutmut mutates only code inside undecorated top-level functions and methods (a
single bare `@staticmethod`/`@classmethod` is allowed), never f-strings, module
constants or docstrings, and skips lines matching `do_not_mutate_patterns`
(logging, progress bars, argparse help). "No mutants" is a pass. "No unit test
exercises the changed functions" (e.g. code only `tests/integration` reaches)
also passes, but is a prompt to add a unit test.

## Settings invariants

- `pytest_add_cli_args` keeps `-n 0` (mutmut forks per mutant; xdist would spawn
  a pool each time) and the `--ignore` list of suites that never execute
  package code.
- `mutate_only_covered_lines` stays off (its coverage pass breaks numpy import).
- Do not set `only_mutate`: the script derives it and refuses a checked-in one.
- `do_not_mutate_patterns` is for stable presentation surfaces, not logic.

## Completion

Report the functions mutated (and any skipped by the budget), the
killed/survived/not-reached/not-run counts, each survivor's
classification (test added, equivalent, presentation) and the rerun result.
