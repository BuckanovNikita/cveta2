# Live integration acceptance — 2026-10-14

The full serial integration suite passed against the shared CVAT, MinIO and
ClearML stands. No live tests were skipped, and no test assertions or runtime
modules required changes during this acceptance run.

## Ownership and preflight

- Project identity: `cveta2`.
- Minted run tag: `cveta2-codex-20261014-integration-p5hn`, recorded by
  `scripts/integration_up.sh` in the ignored `.run-tag` file.
- The repository integration skill, parallel-run guide and shared infrastructure
  run contract governed setup, execution and exact-tag cleanup.
- `infra.py room` returned **GO**: 81 nonterminated pods against the configured
  limit of 100, three FAT namespaces against four permitted including the owner,
  and zero ClearML task pods against four permitted.
- `infra.py whoami-all --project cveta2` verified all three service identities;
  no missing secrets or authentication failures.
- Preflight service listings showed no active cveta2 run objects. Both the
  ignored `.env` and `.run-tag` files were absent before this run.
- The created `.env` carries only the installed skill locator, with credentials
  consumed directly from the helpers into the shell environment.

## Execution and result

The optional ClearML SDK was installed once with:

```bash
uv sync --dev --extra clearml --locked
```

Subsequent lifecycle commands ran with `INFRA_HARNESS=codex` and
`UV_NO_SYNC=1`, avoiding environment changes during concurrent offline work:

```bash
./scripts/integration_up.sh
./scripts/integration_test.sh tests/integration
./scripts/integration_stop.sh
```

The test wrapper retained `-p tests.env_isolation` and disabled xdist, preserving
configuration/home isolation and the required serial live execution.

**Result: 39 passed, zero failed, zero skipped, 160 warnings in 229.12 seconds.**
The warnings came from ClearML's vendored pyhocon use of deprecated pyparsing
interfaces. ClearML publication, CVAT SDK round trips, fetch and cache refresh,
promotion, issue/job state, throttling recovery, task mutation, interrupted
upload recovery, S3 transfer, and upload/fetch round trips all passed.

## Cleanup acceptance

An exit trap invoked the established stop script on success or failure and
then inspected every service with the complete owned tag. Setup, tests,
cleanup and all three post-cleanup listings returned exit status zero.

- CVAT cleanup removed project 47 and cloud storage 21 belonging to this tag.
- MinIO cleanup removed the owned bucket and its 15 objects.
- ClearML's session teardown removed its test projects; stop found none left.
- `.run-tag` was removed only after successful cleanup.
- No shared stand was deployed, restarted or stopped, and no other run was
  modified.

Exact post-cleanup listings:

```text
CVAT:    0 project(s), 0 task(s), 0 storage(s)
MinIO:   0 bucket(s)
ClearML: 0 project(s), 0 task(s)
```

Each listing used `--project cveta2 ls --prefix
cveta2-codex-20261014-integration-p5hn`. No resources are intentionally retained.
The ignored `.env` remains available for subsequent required integration gates.

## Static and documentation checks

After the live run, canonical integration imports were sorted/formatted without
changing assertions. `uv run --no-sync ruff check tests/integration` passed;
`uv run --no-sync ruff format tests/integration` left all 14 files formatted.
`uv run --no-sync mypy tests/integration` passed for 14 source files.

The first `tests/test_docs.py` run passed 188 checks and failed one language
check against the separate mutation-migration evidence. This integration
record passed its own documentation check; the parent integration workflow
owns resolution and the final complete documentation rerun.
