# Infrastructure preflight evidence — 2026-11-09

Scope: `tests/integration/lifecycle.py` and the live fixture's cleanup outcome.
This is manual tooling evidence, not a repository test suite. No stand was
started, stopped, seeded, or mutated during this investigation. All temporary
processes belonged to the experiment; its temporary directory was removed.

## Implementation

`uv run --locked python -m tests.integration.lifecycle check` uses one overall
`CVETA2_INFRA_CHECK_TIMEOUT` deadline (default 60 seconds), including credential
helper subprocesses and their descendants. It checks Kubernetes readiness and
access, registry room, endpoint health, all three service identities, and the
installed registry's `capacity.cveta2_integration_runs` against distinct CVAT
run tags. `INFRA_REGISTRY` is honored. This read-only capacity observation does
not reserve a slot or eliminate cross-worktree races; agents must still obey
the registry capacity before concurrent live runs.

Task-driven setup (`CVETA2_TASK_VERIFICATION=1`) repeats the bounded preflight;
operator `up` without that flag retains the explicit wait workflow. Cleanup
checks the exact tag on all three services, including CVAT cloud storage,
before releasing the local tag file. Leftovers fail the live fixture.

## Executed checks

All commands ran through the repository's `uv run --locked` interpreter.

| Command / manual scenario | Execution count | Observed outcome |
| --- | ---: | --- |
| `python -m tests.integration.lifecycle check` against actual shared infrastructure | 1 | Exit 0, `AVAILABLE`; no run tag or resource created |
| Python heredoc mocking `probe`, then calling `main(['check'])` | 4 | Available → 0; stopped → 3; missing credentials → 1; timeout → 3 |
| Python heredoc mocking `_probe_call` for Kubernetes failure diagnostics | 5 | Connection refused → unavailable; Unauthorized, x509 certificate error, missing context, unexpected error → configuration/error |
| `_probe_call([sys.executable, '-c', ...], monotonic()+0.3)` launching an owned child that spawns a sleeping descendant | 1 | `StandUnavailableError` after 0.302 seconds; descendant absent or terminated zombie, no running descendant |
| `_run_capacity` with a temporary registry and duplicate project/storage rows for one tag | 2 | Full capacity → unavailable; adopted own tag → available without consuming a new slot |
| Task-driven `prepare` with unavailable preflight and mocked `Run.up` | 1 | `UNAVAILABLE: live setup blocked`; `Run.up` was never called |
| `_probe_failure` with captured helper diagnostics | 4 | Connection reset → unavailable; HTTP 401, certificate failure, missing Secret key → error |
| `Run.stop` with mocked cleanup/listing commands | 2 | Empty exact-tag listings → 0 and release; leftover CVAT row → 1 and no release |
| `live_run.__wrapped__` with mocked `finish` returning 1 | 1 | `pytest.fail.Exception`; cleanup failure cannot produce successful pytest teardown |
| `python -m compileall -q tests/integration/lifecycle.py tests/integration/conftest.py` | 1 | Exit 0 |
| Final targeted `ruff check` and `ruff format --check` over both files | 1 each | Exit 0; 2 files already formatted |

The disposable timeout command used `subprocess.Popen` to start a child sleeping
20 seconds, recorded that child's PID in a `TemporaryDirectory`, then slept
20 seconds itself. The preflight killed only that newly created process group;
the experiment checked `/proc/<pid>/stat` for absence or state `Z`. No existing
process was signaled.

Mocked outcomes establish local classification, deadline handling, no setup
mutation after preflight refusal, and cleanup-failure propagation. The actual
read-only check establishes current infrastructure availability only; it is
not a live integration or acceptance test. Full live acceptance and independent
review remain the integrating agent's responsibility.

## Setup-race follow-up

A final manual `uv run --locked python` heredoc exercised three failures after
successful initial preflight: the seed raises `LifecycleError`, then the bounded
read-only recheck reports temporary outage, permanent credential error, or
available infrastructure. All three call `finish` on exactly the prepared run.
Only the outage becomes `UNAVAILABLE: live setup blocked`, with the original
setup exception retained as its cause. Permanent errors and ordinary setup
failures retain the original failure. Exit 0 for the manual assertions; these
are mocks, not injected live outages. Targeted Ruff lint/format checks passed
again after this change.
