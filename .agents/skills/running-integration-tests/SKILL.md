---
name: running-integration-tests
description: Run cveta2 live tests through Task with bounded preflight, explicit infrastructure deferral, run-tag ownership and exact-tag cleanup. Use for integration or acceptance runs, blocked setup, assertion failures, TLS/access errors, cleanup leftovers or explicitly requested operator waiting.
---

# Run cveta2 live tests

Live tests run on the shared stands owned by the `k8s-infra` skill (read its
`references/run-contract.md` before touching a stand). Nothing runs on this
host. Credentials come from the project Secrets through the skill, never from a
file.

The live tests are ordinary pytest tests under `tests/integration`. Development
verification excludes this directory; invoke live checks explicitly. The full
suite with coverage, including live tests, remains required before merging.
`tests/conftest.py` marks them `integration` and puts them in the `live` xdist
group, so under the configured `--dist loadgroup` one worker runs them
serially; unit tests stay parallel. The autouse session fixture `live_run`
(`tests/integration/conftest.py`) does the following:

1. Rechecks availability with bounded startup in Task-driven runs (see below).
2. Mints or adopts the run tag, then seeds the run through
   `tests/integration/lifecycle.py`.
3. Keeps or stops the run after the last live test.

```bash
uv run --locked task --exit-code infra-check
uv run --locked task --exit-code integration
uv run --locked task --exit-code acceptance  # clean-tip full coverage, including live tests
uv run --locked task --exit-code test        # affected units, integration directory excluded
```

`L` below abbreviates `uv run --locked python -m tests.integration.lifecycle`,
for manual lifecycle operations after reading this skill:

```bash
L check           # read-only bounded availability, no tag or resources
L up              # operator lifecycle: prepare, mint a tag and seed
L stop            # remove the run, release the tag (also the crash cleanup)
eval "$(L env)"   # the run's variables, for manual tools
```

The k8s-infra helpers are not on `PATH`. After `eval "$(L env)"`, `infra.py` and
`cvat.py` below mean `uv run --locked python "$INTEGRATION_SKILL_DIR/scripts/<name>"`.
`INTEGRATION_SKILL_DIR` is `K8S_INFRA_SKILL_DIR` when set, else the installed
k8s-infra skill under `~/.agents/skills` or `~/.claude/skills`.

## Bounded preflight and deferral

`infra-check` checks cluster access, registry capacity and the required CVAT,
MinIO and ClearML services. `CVETA2_INFRA_CHECK_TIMEOUT` bounds the overall
read-only check (60 seconds by default). It creates no run tag or service data.
Task uses `--exit-code` to retain these results:

| Result | Exit | Action |
| --- | --- | --- |
| AVAILABLE | 0 | Live verification may start; setup rechecks availability. |
| UNAVAILABLE | 3 | Temporary outage, timeout or capacity WAIT: defer live verification. |
| ERROR | 1 | Diagnose prerequisites, credentials, authorization, TLS or unexpected failure. |

Every Task-driven live run performs preflight and bounds startup. An availability
result is not a test result. Loss of availability during setup is blocked setup;
assertion failures are test failures. Missing Secret keys, untrusted certificates
and refused identities are errors: do not default credentials, disable TLS or
switch to HTTP. Use the installed infrastructure skill to diagnose them.

When unavailable, report the reason and required checks left deferred. Continue
independent implementation, documentation, review and local verification. Retry
at a meaningful milestone or after restored availability, without continuous
polling. When only blocked checks remain, stop and ask for the user's decision.
Deferred live verification blocks acceptance, merge and release.

Explicit operator waiting remains available through lifecycle `up` and
`CVETA2_STAND_WAIT_TIMEOUT`; use it only when waiting was requested. Keep the
waiting process observable, report its state and retain interruption cleanup.
Task verification must not silently revert to indefinite waiting. Never restart,
stop or otherwise modify shared stands merely to make verification pass.

For a focused live selector, first run `infra-check`, then invoke pytest with
bounded startup configured as in `Taskfile.yml`, preserving environment isolation
and `--dist loadgroup`. Do not use an unbounded ad hoc command as acceptance.

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
`[capacity].cveta2_integration_runs` caps concurrent cveta2 suites; preflight must enforce that
capacity in addition to the stand load checked by `room`. Every session that
runs selected live tests starts a run. Before running from several worktrees or
agents at once, count the active runs
(`uv run --locked python "$INTEGRATION_SKILL_DIR/scripts/cvat.py" --project cveta2 ls`) and
serialize the runs beyond the cap.

## Completion evidence

Report the run tag, the selector, the pytest result, and whether the run was
stopped or kept (by tag). Distinguish passed tests, actual failures, deferred verification and
incomplete cleanup. After a failed or interrupted setup, clean owned resources
with the exact run tag; report what may remain and the same-tag `L stop` retry.
Never clear ownership evidence while cleanup is incomplete. A successful preflight
without executed live tests is not acceptance.
