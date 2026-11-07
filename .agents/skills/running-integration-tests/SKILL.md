---
name: running-integration-tests
description: Runs and troubleshoots cveta2's live tests against the shared CVAT, MinIO and ClearML stands of the docker-desktop cluster. They run through the manual integration-tests hook or an explicit full pytest run (tests/integration, session fixture over tests/integration/lifecycle.py). Use for targeted or full live runs, stopped-stand waits, live test failures, run-tag ownership and cleanup, TLS trust failures, or concurrent runs.
---

# Run cveta2 live tests

Live tests run on the shared stands owned by the `k8s-infra` skill (read its
`references/run-contract.md` before touching a stand). Nothing runs on this
host. Credentials come from the project Secrets through the skill, never from a
file.

The live tests are ordinary pytest tests under `tests/integration`. The default
prek pipeline excludes this directory; invoke live checks explicitly. The full
suite with coverage, including live tests, remains required before merging.
`tests/conftest.py` marks them `integration` and puts them in the `live` xdist
group, so under the default `-n auto --dist loadgroup` one worker runs them
serially; unit tests stay parallel. The autouse session fixture `live_run`
(`tests/integration/conftest.py`) does the following:

1. Waits for the stands (see below).
2. Mints or adopts the run tag, then seeds the run through
   `tests/integration/lifecycle.py`.
3. Keeps or stops the run after the last live test.

```bash
uv run prek run acceptance-tests --hook-stage manual --all-files  # full suite with coverage
uv run pytest tests/integration/test_upload.py -k upload
uv run pytest -m "not integration"             # unit tests only
uv run prek run integration-tests --hook-stage manual --all-files
```

`L` below is `uv run python -m tests.integration.lifecycle`, for manual work:

```bash
L up              # wait for the stands, mint a tag, seed; prints the tag
L stop            # remove the run, release the tag (also the crash cleanup)
eval "$(L env)"   # the run's variables, for manual tools
```

## Stopped stands: notify and wait

The owner stops the stands at times. A stopped stand is not a failure:

- **What counts as stopped.**
  - The cluster does not answer.
  - `infra.py room` answers WAIT or fails.
  - The CVAT, MinIO or ClearML endpoint does not answer.
- **What happens.** The fixture (and `L up`) prints one notice, then polls with
  backoff from 15 s up to 60 s. It prints a heartbeat every 5 minutes and
  continues once the stands answer.
- **Limits.**
  - The wait is unlimited unless `CVETA2_STAND_WAIT_TIMEOUT` (seconds) is set.
  - Ctrl-C stops it; nothing has been created yet.
- **Agents.**
  - Start a commit or test run that touches live-affected code with
    `run_in_background`, so a long wait is not killed by a tool timeout.
  - Tell the user the run is waiting for the stands to be restored.
  - Never restart a stand, skip the tests, or bypass the hook.

These fail at once instead:

- a missing Secret key;
- an untrusted certificate (a TLS trust problem, not a stopped stand; never
  switch to plain HTTP or disable verification);
- a ClearML identity that the stand refuses.

## Rules

Safety rules for the stands are in engineering guidance § "Shared infra" and in
k8s-infra `references/run-contract.md`; follow them. They cover owning only your
own tag, exact-tag cleanup, running `cleanup --stale` only with `--dry-run`, and
never acting on another run. In addition, for this suite:

- **One run, one tag.**
  - The fixture or `L up` mints the tag (`infra.py newtag`) and writes the
    gitignored `tests/integration/.run-tag`.
  - Export `INFRA_RUN_TAG=<tag>` to adopt a run started elsewhere.
  - On `main` the run is the durable slot `cveta2-main`; never touch it from a
    branch.
- **Keep or stop.**
  - A branch run is stopped after the session. The `main` slot is kept.
  - `INTEGRATION_KEEP_DATA=1` keeps any run, and `=0` stops `main`'s.
  - A kept run stays until `L stop`.
- **Stop proof.** `L stop` removes the CVAT project and cloud storage, the MinIO
  bucket and leftover ClearML projects. It releases the tag only when every stand
  succeeded. An empty `ls --prefix <tag>` listing is the proof.
- **An active `.run-tag` blocks the next fresh run** in this checkout. After a
  crash, run `L stop`, or adopt the tag with `INFRA_RUN_TAG`.
- **Parallelism.** Do not split the `live` group across workers, and keep
  `--dist loadgroup`: CVAT throttles one client IP, and each worker would
  otherwise prepare its own run.
- This suite never deploys or restarts a stand. Diagnose a broken stand with the
  `k8s-infra` skill.

## Concurrency

Different tags never share objects. The registry's
`[capacity].cveta2_integration_runs` caps concurrent cveta2 suites, but nothing
enforces it, because `room` checks only the stands' own load. Every session that
runs selected live tests starts a run. Before running from several worktrees or
agents at once, count the active runs (`cvat.py --project cveta2 ls`) and
serialize the runs beyond the cap.

## Completion evidence

Report the run tag, the selector, the pytest result, and whether the run was
stopped or kept (by tag). After a failed setup or cleanup, name what may remain
and the exact same-tag `L stop` retry.
