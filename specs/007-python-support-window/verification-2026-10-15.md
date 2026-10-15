# Verification — 2026-10-15

## Scope and workflow

Clean main checkout inspected before work; task branch is `chore/python-312-313`.
Active feature selection confirmed by check-prerequisites with explicit
SPECIFY_FEATURE_DIRECTORY=specs/007-python-support-window. No extension hooks
file exists. Requirements checklist reviewed and pre-implementation analysis found
no blocking gap. Architecture plan validator passed before configuration edits.
Spec Kit stages specify, clarify, plan, checklist, tasks, analyze and implement
were completed for this scoped change; convergence is recorded below.

The user explicitly authorized raising the floor from 3.10 to 3.12 and excluding
3.14+. Existing development pin 3.12 remains. Parent confirmed retaining Ruff's
conservative py310 syntax/lint baseline after py312 exposed unrelated modernization
suggestions. Mypy now targets 3.12. No runtime code, tests, dependency requirements, import
rules or effect ownership were changed.

## Executed checks

| Check | Actual result |
| --- | --- |
| Architecture validator, plan phase | Exit 0 |
| `uv lock` then `uv lock --check` | Exit 0; 137 package records |
| Compare retained lock versions against HEAD with tomllib | No new dependency versions; 147 to 137 records prunes unsupported branches |
| `uv run --frozen --python 3.12 pytest -n 4` | Exit 0; 2435 passed, 80 third-party deprecation warnings, 8.89 s |
| Separate environment: frozen `uv sync --python 3.13`, then `uv run --frozen --python 3.13 pytest -n 4 -q --disable-warnings` | Exit 0; 2435 passed, 10.83 s |
| `uv run --frozen ruff check .` | Exit 0 |
| `uv run --frozen ruff format --check .` | Exit 0; 375 files unchanged |
| `uv run --frozen mypy .` | Exit 0; 243 source files |
| `uv run --frozen vulture` | Exit 0 |
| `uv run --frozen lint-imports` | Exit 0; 10 contracts kept, zero broken |
| `uv run --frozen python scripts/check_architecture.py` | Exit 0 |
| `uv run --frozen pytest tests/test_docs.py tests/test_architecture.py -n 0 -q --disable-warnings` | Exit 0; 252 passed including negative architecture fixtures |
| `uv build` to task-owned temporary output | Exit 0; sdist and wheel built |
| `uv build --wheel` | Exit 0 |
| Isolated wheel install, Python 3.12.13 and 3.13.14 | Exit 0 with pinned runtime requirements exported from frozen lock |
| Wheel public package/API imports, `cveta2 --help` outside checkout, preset data | Exit 0 on both supported interpreters; imported paths verified inside isolated environments |
| Wheel Requires-Python via importlib.metadata/packaging | `<3.14,>=3.12`; includes 3.12/3.13 and excludes 3.11/3.14 |
| Actual Python 3.11.15 wheel install using uv | Exit 1 as expected: current Python does not satisfy package metadata |
| Actual Python 3.14.4 pip install dry run, ignore installed/no deps | Exit 1 as expected: requires a different Python |
| Final `uv run --frozen pytest tests/test_docs.py -n 0 -q --disable-warnings` | Exit 0; 209 passed in 0.23 s |
| `git diff --check` | Exit 0 |

The Python 3.12 environment already had optional ClearML installed, and it was
preserved. The new frozen Python 3.13 environment and isolated wheel installs use
the base package without the optional extra. No live integration services were
contacted; offline checks do not establish live CVAT/MinIO/ClearML outcomes.

## Installer observation

uv 0.11.32 accepted a direct wheel `--no-deps` install on Python 3.14.4 despite
correct upper-bound metadata; pip 26.2.1 rejected it. A target-version uv dry run
showed the same upper-bound behavior. This is a recorded installer limitation;
the package metadata and maintained supported window remain authoritative.
No runtime guard or workaround was introduced outside the requested scope.

## Documentation and final reconciliation

Reviewed complete owned diff: pyproject.toml, uv.lock, README.md, CONTRIBUTING.md,
AGENTS.md, current engineering/constitution guidance and this feature directory.
No unrelated changes existed. Historical feature/planning evidence is preserved.
No application modules, import contracts, scripts, tests or package version changed.
README/contributor guidance distinguishes runtime range, dev pin and lint baseline.
Current memory constraints and constitution amendment are reconciled. Dataset/API/
CLI contracts need no changes because behavior/signatures/formats stay unchanged.

Portable source inspected at corp-skills commit
755e9860cc8dd46431accd260890cc653a292326. Parent owns changing
skills/cveta2/references/usage.md (old Python 3.10 prerequisite) and validating the
package, applicable evaluation cases and source release. No installed copy edited.

## Convergence and remaining gates

FR-001 through FR-004 and SC-001 through SC-004 match current implementation and
executed evidence. FR-005 repository guidance is updated; companion skill remains
parent-owned work. Independent final review, architecture acceptance and native
commit/merge/release/push gates are pending by the bounded-agent stopping point.
No acceptance/release claim is made. No commit, version bump, tag or push occurred.

Release procedure: exact-path staging and Conventional Commit with breaking-change
footer for the raised floor; configured commit hooks must run. Main changes only
by merge. From main run semantic-release version --print, then version --no-push
--no-vcs-release; it owns version, changelog, lock version and annotated Git tag.
Push the intended branch/tag together through full mutation/version/live integration
hooks as configured, then verify remote refs. No GitHub Releases/assets/publication.

Final rebuilt wheel SHA-256: `ccd4813949eb3d50c914101987ac868995bfaa49c88bc89e9f14e1b339ce30d7`.
Final sdist metadata and retained Ruff baseline inspected successfully.

## Integrated acceptance — 2026-10-15

Parent rechecked the final integrated scope and ran the full offline suite:
2437 passed in 7.35 s. Two additional documentation-link parameter cases arise
from the added feature documents; application/test source remains unchanged.
Fresh independent reviewer `/root/python_window_review` (GPT-6.1 Sol, high)
returned **ship**, no findings. Review independently confirmed the lock introduces
no new package versions or dependency-source changes, checked planning records and
whitespace, and accepted architecture responsibilities/contracts/effect ownership.
The complete task-owned diff includes the seven maintained tracked paths plus this
feature directory, with no runtime modules, tests or checker changes. Unrelated
canonical-root untracked skill links and bugs/ are excluded and preserved.

Parent corrected the companion portable skill prerequisites and evaluation cases;
quick_validate, full Markdown lint, discovery, packaged links and fresh-context
native-agent evaluation pass. That evaluation accepted Python 3.12/3.13 and rejected
3.11/3.14, including older-tag metadata checks. Companion source publication remains
parent-owned and follows the app release. No installed copy was changed here.

Architecture acceptance validator runs after this reconciliation. Native delivery
is now authorized; exact-path commit/hooks, canonical-main merge, semantic release
and branch/specific-tag push follow. Earlier pending/stop statements above describe
the initial bounded handoff, superseded by this integrated acceptance stage.

## Native delivery — 2026-10-15

- Contributor `7f91109ddd36e85ff7912fddafb7136d6700959b`,
  `feat!: support only Python 3.12 and 3.13`, passed all configured commit hooks:
  Ruff format/lint, import-linter, effect checker, mypy, Vulture, coverage pytest,
  fast mutation, build, lock and Conventional Commit validation.
- Canonical-main merge `9ba6016` used the required native merge route.
- Native semantic-release selected 0.10.0 for the intentional compatibility break;
  generated diff contained CHANGELOG.md and only project/lock version updates.
  No dependency pin/source change occurred during release generation.
- The initial canonical release commit failed mypy because preserved, unrelated
  untracked bugs/ reproduction scripts have duplicate module names. No tag or
  release commit resulted from that failed attempt. No check was bypassed.
- A clean task-owned clone at the same merged commit ran the unmodified native
  semantic-release command with all normal hooks. Release commit
  `7b23114ed28da9bcd8a450452bc21ccc2fcbf546`, `chore(release): 0.10.0`, and
  annotated Git tag v0.10.0 were created successfully with
  `semantic-release version --no-push --no-vcs-release`.
- Fetched the exact release branch/tag into the canonical checkout. Verified
  CHANGELOG.md, pyproject.toml and uv.lock worktree and index bytes exactly matched
  the release tree, then merged v0.10.0 with --ff-only. This reconciled the staged
  generated files without reset, restore, revert, stash or unrelated file edits.
- Canonical frozen sync explicitly retained the ClearML extra. Installed metadata
  reports cveta2 0.10.0 and ClearML 2.1.3; version drift check passed.
- Atomic `git push --atomic origin main refs/tags/v0.10.0` passed full mutation,
  version drift and armed live integration gates. Live tests/integration:
  39 passed, 160 third-party deprecation warnings, 224.60 s.
- Remote main verified as `7b23114ed28da9bcd8a450452bc21ccc2fcbf546`; annotated
  v0.10.0 object `63903c212ebdd582b6039a1ce5770b61f07dff97` peels to that commit.
  No GitHub Release, package publication or uploaded release asset was created.

The live gate retained its designated durable cveta2-main CVAT project/cloud
storage and MinIO bucket for inspection, as native policy requires. ClearML test
projects were removed by teardown. No other run or shared service was changed.
Canonical unrelated untracked .claude skill links and bugs/ remain untouched.
The clean release clone, temporary test environments and build artifacts were
removed after importing/validating the release. Transient task logs are cleaned
once final delivery verification is complete.

A supplementary optional-SDK import smoke read pre-existing localhost ClearML
configuration and retried authentication; only that task-owned smoke process was
stopped. Installation was then verified through importlib.metadata. This did not
change user configuration or services; the successful live gate used the normal
Secret-derived stand environment.

## Documentation-only closure

T012 delivery is complete. This follow-up closes the feature status and task
ledger and records the actual checks and publication. The architecture scope now
includes semantic-release-owned CHANGELOG.md alongside configuration/version
updates; runtime import/effect boundaries remain unchanged. No new application
behavior or executable contracts change, so existing independent review and
negative architecture evidence remain applicable. Documentation and architecture
acceptance checks run before committing the closure. The subsequent docs-only
merge evaluates release normally and does not force another version.

Parent prepared and validated companion corp-skills v0.2.2; its publication follows
the verified application refs and is reported by the parent.

Closure validation: documentation pytest 209 passed in 0.19 s; architecture
acceptance validator and git diff --check exited 0.
