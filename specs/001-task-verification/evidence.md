# Integrated verification evidence — 2026-11-09

Worktree: `/mnt/wsl/data/nkt/cveta2`, branch
`chore/simplify-hooks-20261109`; starting commit `3044f2b`, two commits ahead
of local `main`. Remote refs were not fetched. Starting working tree was clean.

## Evidence sources

- [Feasibility](../../docs/plans/task-verification-20261109/feasibility.md):
  selection, invalidation, interruption, exit codes and worktree history.
- [Hook validation](../../docs/plans/task-verification-20261109/hooks.md):
  real prek/message validation with mocked Task, staged-input guards, current and
  legacy linked worktree dispatch, backups and rollback.
- [Infrastructure](../../docs/plans/task-verification-20261109/infra.md):
  manual controlled probes, deadline/owned-process cleanup and real availability.

No tooling-only repository tests were added. The shared services and existing
worktrees were preserved. pcboard could not identify the session, so no load
figures were available; serial orchestration and two pytest workers were selected.

## Integration observations

Task command discovery and the actual inline namespace evaluate successfully.
Each command explicitly sets worktree-local environment, testmon, coverage, Ruff
and mypy locations; inherited cache overrides cannot redirect those commands.
The namespace includes ignored downloaded fixture and package assets as well as
tracked/untracked source membership and verification configuration.

The first `check` run passed lock freshness and Ruff lint, then stopped on a Ruff
formatting difference in the feasibility document's Python example. That is an
observed formatting failure, not a passing integrated run. Explicit formatting
and final verification are pending.

Installed semantic-release source confirms it writes version/changelog before
its build command and stages them afterwards. The explicit release-check build
branch therefore stages its owned version/changelog files before invoking the
check; `uv.lock` is already staged by the existing build command. Release execution
itself is not authorized without the separate push/integration decision.

## Completion status

Implementation is awaiting final integrated verification, independent review and
clean-tip acceptance. No merge, release or push has occurred. Deferred or failed
checks remain incomplete until executed successfully; availability is not a live
test result.

## Development results and review corrections

After an explicit `fix`, only the feasibility Markdown example changed; that
mechanical formatting was committed separately (`ebdccb6`). Initial implementation
commit: `4f3cc8c`; Python 3.12 compatibility fix: `bd6ca39`.

`verify` passed lock freshness, Ruff lint/format, all 10 import contracts, mypy
(327 files), vulture, deptry, 2,384 unit tests and source/wheel packaging. First
unit baseline: 19.59 seconds; unchanged repeat: zero tests executed, 1.17 seconds.
Both runs executed static commands and build. Unique build directories were
removed by their owner; existing `dist` contents were not touched.

An initial mypy failure exposed use of Python 3.13's `re.PatternError` on the
supported Python 3.12 floor. Replacing it with `re.error` resolved the failure.

Independent review found and verified fixes for:

1. **Release environment forwarding (P1):** semantic-release builds with a restricted
   environment. `build_command_env` now forwards the explicit selector. Actual
   `RawConfig`, `RuntimeContext` and `build_distributions` with disposable command
   stubs confirmed the check executes and its exit 7 aborts the build.
2. **Timeout classification (P2):** context deadlines and TLS handshake timeouts
   now defer. Controlled original failure paths returned UNAVAILABLE; x509,
   missing context and Unauthorized remained ERROR.
3. **Bootstrap isolation:** both shared dispatch paths and the direct shim override
   inherited `UV_PROJECT_ENVIRONMENT` before uv starts. Disposable new/legacy
   paths selected their own `.venv`; no foreign environment was created.
4. **Release early failure:** `set -e` stops on lock or staging failures. Actual
   build shell with command stubs stopped after exactly one/two commands for
   lock/stage exit 7, raising `BuildDistributionsError`.
5. **Deadline scope:** guidance explicitly bounds availability checks, not the
   entire seeding/test/teardown duration.

These release validations did not create a real release, version bump or tag.
Hook hashes in the earlier hook evidence identify that experiment's revision;
the bootstrap isolation correction was exercised separately as described above.
Final local verification after corrections again passed all stages and all 2,384
units. The config change correctly selected a new testmon baseline.

`mutation -- --base main` completed successfully: no changed cveta2 application
function could be mutated. This is a scoped no-work result, not mutation coverage
of lifecycle/tooling code. Real read-only infrastructure preflight returned
AVAILABLE; live acceptance remains pending on the committed corrected tip.

Post-check independent correction review found no remaining code blockers. Its
README ordering observation was applied: clear the environment override before
`uv sync`, not after it. Final local baseline took 19.88 seconds in pytest.
