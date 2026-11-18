---
name: running-integration-tests
description: Use when running cveta2 live tests (integration or acceptance), handling blocked setup, unavailable infrastructure, live assertion failures or cluster access errors, keeping or inspecting a session, cleaning up leftovers, or waiting for the cluster on request.
---

# Run cveta2 live tests

Paths start at the repository root. Before the first run, read the rules in
`docs/development.md#live-tests` and the module docstring of
`tests/integration/lifecycle.py` (setup, teardown, ownership, command exits and the
session environment). `L` below abbreviates
`uv run --locked python -m tests.integration.lifecycle`.

1. Run the preflight: `uv run --locked task --exit-code infra-check`. Classify the exit
   by `docs/development.md#deferral-of-live-checks`. On UNAVAILABLE, defer the live checks
   and stop here; on ERROR, diagnose the tool, context or permission.
2. Run the selected stage: `uv run --locked task --exit-code integration`, or
   `acceptance` on the clean committed tip. Both recheck availability during setup. For a
   focused selector, run `infra-check` first, then pytest on the selector with
   `CVETA2_TASK_VERIFICATION=1` and `--dist loadgroup` as `Taskfile.yml` does; a focused
   run establishes only what it selected and is never acceptance.
3. Classify the outcome by `docs/development.md#deferral-of-live-checks` and repair
   ordinary failures within scope. A first
   pull of the CVAT server image may exceed the cold-start deadline: pull it once or raise
   `CVETA2_SESSION_READY_TIMEOUT`.
4. To inspect a session, either set `INTEGRATION_KEEP_DATA=1` for the pytest run or,
   after an AVAILABLE `infra-check`, use `L up` (it waits for an unavailable cluster, so
   set `CVETA2_STAND_WAIT_TIMEOUT` unless the user asked to wait), then
   `eval "$(L env)"` (never print its output: it holds credentials). Stop a kept session
   in this checkout before starting another kept one, and remove it with
   `L stop <namespace>` when done.
5. Wait for an unavailable cluster only when the user asked for it: `L up` waits, bounded
   by `CVETA2_STAND_WAIT_TIMEOUT` when set. Keep the waiting process observable, report
   its state and keep its interruption cleanup. Task-driven runs never wait indefinitely.
6. After a failed or interrupted run, prove cleanup: no namespace of the run in
   `kubectl --context docker-desktop get ns`, and no
   `kubectl --context docker-desktop -n <namespace> port-forward` process left. Report
   anything left by name with the `L stop <namespace>` retry. Done when cleanup is proven
   or each leftover is reported.
7. Record in the Linear issue the session namespace, the selector, the pytest result,
   whether the namespace was deleted or kept (by name), and passed tests, actual
   failures, deferred checks and incomplete cleanup as separate items.
