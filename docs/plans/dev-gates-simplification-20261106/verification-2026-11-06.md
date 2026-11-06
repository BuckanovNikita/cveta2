# Verification: development gates simplification (2026-11-06)

Plan: [plan.md](plan.md). Base: `45d16e7` on branch `project-cleunap`.

## Static checks

- `uv run ruff format --check .`: 465 files already formatted.
- `uv run ruff check .`: all checks passed.
- `uv run mypy .`: no issues in 342 source files.
- `uv run vulture`: clean.
- `uv run lint-imports`: 10 contracts kept, 0 broken.

## Targeted tests

- `uv run pytest -n 0 tests/test_architecture.py tests/test_integration_tool_boundaries.py tests/test_integration_lifecycle.py tests/test_mutation_tool.py tests/test_docs.py`:
  165 passed. The only failure was the dead link from `tasks.md` to this file,
  which did not exist yet.
- `tests/test_mutation_tool.py` (16 tests) covers:
  - mapping changed lines to functions and methods;
  - skipping decorated functions and classes;
  - the two spellings for `__init__` modules;
  - reading the staged diff only;
  - narrowing the workspace `pyproject.toml`, and refusing a checked-in
    `only_mutate`;
  - dropping stand and `GIT_*` variables;
  - a private workspace built from the index and removed afterwards;
  - survivors reported with diffs, and exact function names only;
  - `--strict`;
  - "no mutants" and a mutmut failure;
  - explicit files with `--keep`;
  - refusal of a file outside the package.
- `tests/test_integration_lifecycle.py` (67 tests) covers:
  - the gate skips without the k8s-infra skill;
  - a skill directory without the run contract fails;
  - `room` WAIT and a `room` failure fail before anything is touched;
  - the branch is read from git `HEAD` (`main` gives the durable slot);
  - every previous tag, teardown, TLS and interrupt case.

## Full suite

`uv run pytest -n auto --cov --cov-report=term`: 2825 passed. Total coverage is
91.86%, above the 90% threshold. The only failure was the same dead link.

## Mutation tool end to end (real mutmut 3.7.0)

Probe: I temporarily staged an untested branch in
`cveta2/domain/paths.py::build_s3_key`, together with the new `pyproject.toml`
(the workspace is built from the index). Then I restored both files.

| Run | Result |
|---|---|
| First version, `__mutmut_*` filters | 10 mutants, 5 killed, 5 survivors (all in the probe branch, diffs printed), exit 0, workspace removed. 86 s. |
| Phase timing of that version | generation 0.2 s, stats pass 35 s, clean run 36 s, mutants 3 s |
| After `--ignore` of the non-executing suites | 66 s |
| After the filter fix (`<function>*`) | 39 s in total. The clean run fell from 28 s to about 3 s. |

The filter fix addresses a mutmut 3.7 behaviour:
- `tests_for_mutant_names` matches the run filter against mangled function
  names, which have no `__mutmut_` suffix.
- A `__mutmut_*` glob therefore selects no tests, and the clean run silently
  executes the whole suite.
- I measured this with a kept workspace: the 275 mapped tests take about 4 s
  on their own, but 26 to 28 s inside mutmut.

What remains is mutmut's stats pass, about 28 s: the whole unit suite run
serially. That cost is fixed while nothing is shared between runs.

A run with no changed `cveta2` function prints "nothing to do" without starting
mutmut (tested). A run whose filters match no mutant is reported as
"produce no mutants" and passes (tested with the fake mutmut).

## Local machine

- `uv run pre-commit uninstall -t pre-push`: removed. `commit-msg` and
  `pre-commit` remain.
- Removed the generated `mutants/` directory (3.8 GB; 3.7 GB of it was leaked
  `.pytest-temproot` directories).
- This machine's untracked `tests/integration/.env` is no longer read. It still
  holds stale values from the retired local stack, including a plaintext CVAT password. I left
  it in place for the owner to delete.

## Independent review

A fresh general-purpose subagent reviewed the whole uncommitted diff, read-only,
including real mutmut 3.7.0 runs in a throwaway repository. The parent resolved
every finding:

| # | Finding | Resolution |
|---|---|---|
| 1 (high) | A change that no unit test reaches made mutmut stop ("could not find any test case"). The hook then exited 2 and blocked the commit. | The tool reports it, exits 0, and exits 1 under `--strict`. Tested. |
| 2 | Deletion-only hunks (`+N,0`) were never mapped. | Both sides of the gap are marked. Tested. |
| 3 | User diff configuration (`noprefix`, `mnemonicPrefix`, quoting, external diff) could hide changes. | The format is pinned (`--src-prefix/--dst-prefix`, `--no-ext-diff`, `--no-textconv`, `core.quotePath=false`). An unexpected header is now an error. Tested. |
| 4 | `specs/baseline.md` still described profiles. | Reconciled. |
| 5 | Release-commit hook recovery was undocumented. | Documented in `engineering.md`. |
| 6 | The concurrency cap was overstated. | The skill now states that `room` does not enforce `cveta2_integration_runs`. Recorded as an accepted loss. |
| 7 | A path outside the repository gave a traceback. | It is now a tool error. Tested. |
| 8 | "All killed" was printed when nothing was selected. | It now says "produce no mutants". Tested. |
| 9 | The rebase remedy did not cover mutation, and `--base` diffed against the tip. | The remedy now mentions `scripts/mutation.py --base <upstream>`, and `--base` uses `--merge-base`. Tested. |
| 10 | A commit that only deletes files runs no filtered hook. | Accepted, and recorded in the plan and the commit skill. |
| 11 | Stale wording and other nits. | Fixed: "push" wording, docstring wraps, `--keep` hint, README timing and exit codes, blank lines and the redundant per-hook `fail_fast`. A failing Secret lookup in the gate now carries the SKIP hint (tested). The MEMORY.md finding was already resolved. |
| 12 | The architecture scope was incomplete. | `tests/env_isolation.py` and `.gitignore` were added. |

Test gaps added:
- a non-default `GIT_INDEX_FILE` is honoured;
- `CLEARML_`, `INTEGRATION_` and `GIT_` variables are stripped from the child;
- pytest sessions see no `GIT_*` variables;
- the passing gate calls `room`.

## Re-verification after the fixes

- ruff format and check, mypy (342 files), vulture and lint-imports (10 kept):
  all clean.
- `uv run pytest -n auto --cov`: 2835 passed, coverage 91.86%.
- `uv run pre-commit validate-config`: valid.
- The real mutmut probe again found 10 mutants in `build_s3_key`: 5 killed and
  5 survivors in the probe branch. It took 37.5 s, and no workspace was left
  behind.

## Commit gate

Recorded after the commit, in a follow-up documentation commit (its paths start
neither the mutation hook nor the live gate).
