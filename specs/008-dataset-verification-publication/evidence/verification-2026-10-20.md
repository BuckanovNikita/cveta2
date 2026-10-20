# Integrated verification — 2026-10-20

Inspected base: `39bc958d20cc21a85beeaf238e411d815c66e678`.
Feature: `008-dataset-verification-publication`. Tests below exercised the
integrated feature worktree before release, with Python 3.12.13.

## Local gates

| Executed check | Observed result |
| --- | --- |
| `uv run --no-sync pytest -n 6 --cov --cov-report=term-missing` | 2,745 passed; 93.11% coverage, exceeding the 90% gate |
| `uv run --no-sync ruff check .` | Passed |
| `uv run --no-sync ruff format --check .` | Passed, 426 files formatted |
| `uv run --no-sync mypy .` | Passed, 282 source files |
| `uv run --no-sync vulture` | Passed |
| `uv run --no-sync lint-imports` | All 10 contracts kept |
| `uv run --no-sync python scripts/check_architecture.py` | Passed |
| Architecture negative dependency/effect fixtures | Passed within the full suite |
| Documentation contract/link tests | Passed within the full suite; preceding focused run: 232 passed |
| `uv build` and `uv lock --check` | Wheel and sdist built; dependency lock consistent |
| `git diff --check` | Passed |

An earlier complete local attempt had two collection errors from test imports of
the renamed internal CVAT upload composition function. Those imports were
corrected before the successful run above. Initial strict typing errors in ported
tests were also corrected, without weakening configuration. The internal rename
separates existing CVAT upload from the new public ClearML upload_dataset.

The installed wheel was tested outside the checkout in isolated Python 3.12.13
and 3.13.14 environments without ClearML. Both successfully imported public
interfaces, preserved literal `001`, validated a DataFrame and CSV, produced
report-only output without clean.csv, and wrote clean.csv only with explicit
cleanup into a new directory. Original CSV bytes remained unchanged. Expected
warnings identified missing dimensions in the synthetic smoke fixture.
The optional ClearML dependency was exercised in the live checks below.

## Live checks and ownership

The standard integration lifecycle was used after infrastructure capacity
preflight. Owned run: `cveta2-codex-20261020-integration-0roe`.

- `INFRA_HARNESS=codex ./scripts/integration_up.sh` succeeded.
- Targeted `integration_test.sh tests/integration/test_clearml.py`: two passed.
- Full `integration_test.sh tests/integration`: 37 passed in 240.68 seconds.
- 380 warnings came from ClearML's Pyparsing deprecations; no test failed.

Real finalized parent and child each contained exactly dataset.csv, dataset.yaml
and tasks.yaml. Local source evidence and parent content stayed unchanged.
Changed payload and newer-parent scenarios created no child. Existing CVAT/S3
fetch, upload, remediation, cache and lifecycle scenarios passed.

An initial full-live collection attempt caught the same internal composition
rename in integration imports. The corrected complete run above is the acceptance
result; the failed collection was not counted as passing.

`integration_stop.sh` deleted the owned CVAT project 74 and cloud storage 30,
and the owned MinIO bucket with 15 objects. ClearML had no remaining owned
objects. Follow-up listings found zero matching MinIO buckets, zero ClearML
projects/tasks; CVAT listing and exact-tag cleanup dry-run found no owned
project, task or cloud storage. The pre-existing durable main objects were
preserved. Temporary media, HTTP fixture server and prepared-stage files were
fixture/context managed.

## Portable skill

Canonical source and executable example checks are in
[documentation-2026-10-20.md](documentation-2026-10-20.md). Parent reran collection
discovery, full Markdown lint and whitespace checks: all passed (47 Markdown
files at that checkpoint). No installation occurred.

A fresh native agent requested as gpt-6.1-sol with medium effort first read only
the skill name/description. It selected cveta2 for CSV inspection and reviewed
publication, and excluded training/accuracy evaluation and repository development.
After reading the full package, it proposed correct commands and failure handling
for report-only verification, explicit cleanup, preparation, missing choices,
reviewed publication, edited payload/new parent, legacy parent, uncertain child
failure and removed controls. Both actual CLI help commands passed.

These are observed native-agent routing and proposed-action results. They are not
remote execution or a controlled before/after benchmark, and establish no
OpenCode/DeepSeek runtime performance. Local artifact behavior and remote
publication were tested separately above.

## Remaining delivery checks

Full mutation gate, fresh final review, architecture acceptance/convergence and
release hooks are recorded in subsequent acceptance/delivery evidence. They are
not implied by the checks above. An optional default Markdown lint of established
cveta2 guides failed on existing style conventions; the required repository
documentation checks passed, as detailed in the documentation evidence.
