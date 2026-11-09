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

## Initial implementation checkpoint

At that checkpoint, implementation was awaiting final integrated verification, independent review and
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


## Live acceptance and cleanup

On clean corrected commit `f2e8cc2`, with `INFRA_HARNESS=codex`,
`env -u SKIP -u UV_PROJECT_ENVIRONMENT uv run --locked task --exit-code acceptance`
returned 0. Static checks and temporary packaging passed; randomized properties
ran 2,384 tests (28.69 seconds). Preflight returned AVAILABLE. Full coverage ran
2,422 tests, including all 38 live tests, in 287.64 seconds: all passed,
480 warnings, total coverage 92.23% against the 90% gate. The final clean-tip
guard passed.

Owned run: `cveta2-codex-20261109-integration-vttf`. Fixture cleanup succeeded.
An additional read-only exact-tag listing returned exit 0 and zero object rows
for each of CVAT, MinIO and ClearML. The `.run-tag` file was absent. No shared
stand was restarted, stopped or reconfigured; no cleanup leftovers remain.

A controlled real preflight with `CVETA2_INFRA_CHECK_TIMEOUT=0.001` subsequently
returned UNAVAILABLE during kubectl and Task preserved exit 3. This deliberately
insufficient deadline tests deferral; it is not evidence that services stopped.
Independent local work continued: actual `release-check` on the clean eligible
(no-change) tree returned 0, exercising its static checks and temporary build.
With the final evidence files staged, `release-check` rejected the nonrelease
path before static commands and preserved exit 1. No release, version bump,
Git tag, merge or push was performed.

## Convergence and retained state

Native Spec Kit convergence checked 12 functional requirements, 4 success
criteria, all 11 user-story scenarios, the plan's orchestration/isolation/
deferral/release decisions, and the five constitutional principles. There were
no remaining implementation gaps or actionable convergence tasks. Independent
review corrections and observed verification satisfy the completed task list.
Final-tip acceptance will be reported in-session after this evidence-only commit;
these recorded live results specifically identify the tested commit above.

The original hook installation remains in the task-owned rollback directory
`.git/hooks/cveta2-backup.wpMHKi`; the intermediate dispatcher backup is
`.git/hooks/cveta2-backup.lz9jdH`. These are intentionally retained for rollback.
Tool-native worktree caches and coverage output remain local as designed.
Disposable experiments and owned child processes were cleaned. Application
sources, glossary, CLAUDE adapter and generated Spec Kit skills/templates were
unchanged. Remote refs were not fetched; integration/publication still requires
separate authorization.

## Late deletion-boundary convergence correction

The evidence-only tip `31fcc31` also passed clean-tip acceptance: randomized
properties 2,384 passed in 31.42 seconds; full live coverage 2,422 passed in
284.16 seconds, 92.23% coverage, 480 warnings. Run
`cveta2-codex-20261109-integration-3wkz` completed teardown, removed its ownership
file, and left a clean tree.

A further bounded independent experiment found a concrete FR-004 gap: deleting
either tracked workflow file made the shared dispatcher choose legacy fallback.
Actual prek then stashed the deletion instead of rejecting it. Convergence added
T016. The dispatcher now recognizes migration markers in HEAD or the index even
when working files are absent, and refuses incomplete workflow files before uv.
It does not execute shell content from the index.

`bash -n` passed for both scripts. Disposable actual-prek rechecks established:
missing tracked shim, missing tracked Taskfile, and an unborn index-only marker
all exit 1 before uv/prek with no stash. A genuine linked legacy worktree without
markers still runs its own configuration. Fresh independent correction review
found no remaining blocker. These fixtures were cleaned; no repository tooling
self-tests were added. The corrected dispatcher was installed; its previous
version is retained in `.git/hooks/cveta2-backup.yJigZd`. Removing the complete
workflow deliberately requires an explicit hook migration or rollback.

T016 is complete and the native convergence inventory has no further unbuilt
work. A final clean-tip acceptance run follows this correction commit and is
reported in-session, without changing committed inputs during verification.
