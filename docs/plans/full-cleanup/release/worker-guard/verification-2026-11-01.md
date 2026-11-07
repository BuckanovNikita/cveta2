# Worker guard verification: 2026-11-01

## Failure and diagnosis

The first atomic push of main/v0.12.1 passed version drift and then blocked on
two worker-configuration mutants. The whole owned push process group was
interrupted (exit 130); all its descendants stopped. Remote inspection confirmed
main still at `a6b77f204790120650460f37dbacf32bd2e4ea6c`, with no v0.12.1 tag.
This interrupted gate is not successful verification.

Mutant 6 replaces the S3 count floor with two; mutant 11 does the same for CVAT.
The sequential-transfer fixture associates 2653 tests with this function. Cached
sorting put the real count-floor assertion at index 672 and the grimp type-only
import probe at index 530. Both stopped children last wrote that probe's package
files and had one sleeping thread in a futex wait. Precise original-process stacks
were unavailable. Native reviewer `/root/mutation_hang_review` independently
confirmed the ordering and favored prioritizing the existing assertion.

A separate bounded reproduction built a tiny grimp graph, forked and rebuilt it
in the child. The parent succeeded; the child timed out after three seconds with
a faulthandler stack at `grimp.application.scanning.scan_imports`, matching the
suspected inherited scanner/thread-pool problem. Its temporary package was removed
normally. No signal was sent to an individual mutation child to manufacture a
kill. This reproduces the scanner's fork hazard, not a product transfer failure.

## Implemented change and focused checks

The existing worker-floor test now precedes the CSV EOF guard; all other selected
tests retain their relative order. There are no new tests, imports, fixture-state
assertions, runtime changes, mutation exclusions or equivalent entries.

- Architecture record planning validation passed before changing source.
- A real pytest collection probe passed three selected-input arrangements,
  including reversed guards and no guards: unchanged membership, guard priority
  and stable non-guard order. The probe overrides collection addopts while
  retaining `tests.env_isolation`; ordinary defaults combine verbose/quiet output
  into a module summary rather than the node listing needed by this probe.
- Ordinary suite: **2666 passed in 9.72 seconds**.
- Architecture/negative fixtures and documentation: **70 passed in 3.58 seconds**.
- Ruff check/format, strict mypy, Vulture, 10 import contracts and effect ownership
  checker passed.
- Exact targeted mutation execution rejected both original cases: **2 killed,
  0 timeouts/survivors** at 1.83 mutations/second. The script's subsequent full-scope
  gate correctly exited 1 because all other verdicts had been invalidated and
  were not checked in this targeted run. This is not a passing full gate; the
  separate full-profile execution remains required.
- Rebuilt wheel SHA-256 remains
  `965460ae89a7a853a82d915599bc60431d5e663159d3b769784ef91c694c1102`, byte-identical
  to the actual generated v0.12.1 wheel and the rehearsal wheel smoke-tested on
  both supported Python versions. The release tag/runtime need no rewrite.

## Remaining acceptance

Full mutation verdicts, fresh independent review, architecture acceptance, normal
commit/main merge and actual push gates/delivery are pending. Final results will
be appended here; the parent release ledger owns final delivery.

## Full profile and architecture correction

The separate full profile completed successfully: **8118 total, 7835 killed,
283 existing justified equivalents, 0 unexplained survivors, 0 unchecked,
0 no-tests and 0 timeouts**. The original two worker-floor mutants were killed.
No mutation configuration, scope, profile or justification was changed.

Fresh independent reviewer `/root/worker_guard_final_review` returned fix-first
for an architecture-evidence gap: production graph/effect checks do not scan the
test collection hook or forbid production-to-tests imports. The change itself,
collection probes, personal-link preservation and immutable release approach were
accepted. Removed that unimplemented dependency claim from this task's record;
no production dependency change was part of this maintenance.

The scoped executable contract now extracts only the collection hook and applies
the existing pure-module import/effect policy. This is a task acceptance check,
not a claim that the normal production checker automatically scans test fixtures.
It passed for the real hook and rejected network import, SDK import and file-read
negative cases. Other fixtures retain their existing temporary-file/environment
ownership. The exact reproducer for the record's command is:

```python
import ast
from pathlib import Path

from scripts.check_architecture import inspect_source

source = Path("tests/conftest.py").read_text()
hook = next(
    node
    for node in ast.parse(source).body
    if isinstance(node, ast.FunctionDef) and node.name == "pytest_collection_modifyitems"
)
actual = ast.get_source_segment(source, hook)
assert actual is not None
policy = "cveta2.domain.collection_contract"
assert inspect_source(actual, policy) == []
for forbidden in [
    "import socket",
    'from pathlib import Path\nPath("unexpected").read_text()',
    "import cvat_sdk",
]:
    assert inspect_source(forbidden, policy), forbidden
```

The policy label applies the maintained pure-policy rules to this extracted
function; it does not describe the function's actual package location. Exact
personal-link ignore matches and both unchanged relative symlink targets were
verified. The subsequent full-profile cache probe and fresh review of this
correction remain required before final acceptance.

The subsequent ordinary `--profile full` execution completed successfully with
all 8118 cached verdicts, **0.00 mutations/second**, no invalidation notice and no
unexplained mutants or timeouts. Clean-suite/forced-failure safeguards still ran.
Both personal symlinks remain in place; only their exact ignore status changed.
Documentation recheck passed 14 tests in 2.48 seconds; scoped import/effect probe,
architecture plan validation and whitespace checks passed after the correction.
Fresh review of this final corrected record is the remaining source-acceptance
step. Delivery remains open until the actual gated push succeeds.

## Fresh independent acceptance

Native `/root/worker_contract_acceptance` returned **ship**, no findings, after
the architecture correction and parent full/cached verification. Independent
checks passed: 201 concurrency/dataset-review/documentation tests, 56 architecture
tests, 10 import contracts, effect checker, real-hook purity plus three negative
probes, three actual collection permutations, architecture planning validation,
whitespace and exact personal-link preservation. The reviewer confirmed that the
scoped architecture mapping and its enforcement limits are truthful. Parent
reconciled every task-owned path against this record; runtime/package source and
mutation policy remain unchanged. Requested model/effort inherited the parent;
actual runtime settings are not exposed. Architecture acceptance validation is
the final structural check before committing. Publication remains a separate
pending workflow action.
