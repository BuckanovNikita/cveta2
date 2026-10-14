# Implementation verification — 2026-10-14

The isolated implementation branch is `refactor/clean-architecture`, based on
`09ded060040d87c7f13bf773349abfa1f16ffe30`. Original checkout changes were preserved.
The existing baseline passed 2,314 offline tests before implementation.

## Parent checks

Commands used the locked development environment with `UV_NO_SYNC=1` while the
live and mutation workflows shared the interpreter. Results below are observed
command exits, not planned checks.

| Check | Result |
|---|---|
| `uv run pytest --cov --cov-report=term-missing` | Exit 0; 2,421 passed, 80 warnings; 92.92% coverage against the 90% gate after mutation-driven regression additions |
| `uv run ruff check .` | Exit 0 |
| `uv run ruff format --check .` | Exit 0; 366 files formatted |
| `uv run mypy .` | Exit 0; 243 source files |
| `uv run vulture` | Exit 0 |
| `uv run lint-imports` | Exit 0; 10 kept, zero broken; 178 files and 760 dependencies analyzed |
| `uv run python scripts/check_architecture.py` | Exit 0; no forbidden known effects or facade imports |
| `uv run pytest tests/test_client_architecture.py tests/test_architecture.py` | Exit 0; 51 passed after compatibility corrections |
| `uv run pytest tests/test_docs.py` | Exit 0; 191 passed at the documentation reconciliation checkpoint |
| `uv build` with an isolated output directory | Exit 0; source distribution and wheel built |
| Python 3.10 import smoke in a separate locked runtime environment | Exit 0; Python 3.10.20 imported 134 modules and verified public type identities |
| `git diff --check` | Exit 0 |

The architecture guard is a targeted static rule set. It detects known prohibited
imports and effects, including aliases and typed path operations; it is not a
general Python effect proof. Isolated-import tests also block SDK loading at
runtime. The new contract tests reject outward edges, adapter-to-orchestration
edges, SDK escape, local/type-only SDK imports, cycles, unclassified modules,
facade imports, filesystem, environment, network and execution effects.

## Compatibility review corrections

The interim independent review checked supported export names and client method
parameters against the baseline. It found two reproducible regressions: a mutable
public configuration no longer updated client host/default-organization properties,
and lazy root exports disappeared from `dir(cveta2)`.

Two regression checks failed before the corrections. The outer client now reads
those public properties from its retained configuration; owned session creation
uses the same live values. The lazy package implements `__dir__` without loading
SDKs. The two original failure paths then passed, together with the 51-test
architecture/client suite and the complete offline suite above.

Parent inspection also restored the public `python -m cveta2.cli` entrypoint guard
and retained public subprocess checks. Invocation-time worker and fetch-failure
configuration remains resolved at the outer composition boundary. Regression
tests verify late environment and worker changes.

## Separate acceptance records

- [Mutation scope and equivalents](mutation-migration-2026-10-14.md).
- [Full live integration and exact-tag cleanup](integration-2026-10-14.md):
  39 passed, zero skipped or failed.

## Final gates and review

The final full mutation gate exited zero after checking all 7,996 mutations:
7,764 killed and 232 individually justified equivalents. There were no unexplained
survivors, stale entries, uncovered/not-checked mutations or timeouts. The
independent reviewer accepted the source and final test/equivalence delta;
see [the review record](review-2026-10-14.md).

`UV_NO_SYNC=1 uv run pre-commit run --all-files` exited zero on the stable final
checkout. All configured commit-stage hooks passed: Ruff formatting/checks,
import-linter, effect ownership, mypy, vulture, coverage, fast mutation, line count,
build and lockfile resolution. The fast profile checked 749 mutants, with 728
killed and 21 justified equivalents. No hook was skipped or bypassed.

An earlier invocation passed every individual check but returned nonzero because
acceptance evidence was edited while its mutation hook ran. All writers were
stopped before the successful complete rerun. No runtime or test correction was
needed for that pipeline failure. The hook installation was refreshed because
its interpreter path referenced a checkout that no longer exists.

## Architecture acceptance and source convergence

The shared architecture validator exited zero with `--phase acceptance`, using
this feature's `architecture.json` and the explicit repository root. Every
declared check has passing dated evidence and the review is accepted. The parent
reconciled canonical module ownership, removed paths, the effect checker,
configuration, tests and documentation with the complete task-owned diff.

Source convergence inspected 10 functional requirements, four success criteria,
10 user-story acceptance scenarios, nine architectural/verification decisions,
five constitution principles and all 18 task descriptions. It found zero missing,
partial, contradictory or unrequested buildable changes; no source remediation
task was appended. The convergence pass left `tasks.md` byte-for-byte unchanged
(SHA-256 `e0c00bfa896ec53af5f647c3df216e1080b6370d10146d49869ce388e16eabf4`).
There are no extension hooks. The normal implementation ledger is updated after
this read-only assessment. T018 remains the separately tracked downstream release
stage; source convergence does not claim that publication has already happened.
