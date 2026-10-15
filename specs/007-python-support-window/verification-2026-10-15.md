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
