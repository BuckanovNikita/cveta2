# Contract: `python -m tests.integration.lifecycle`

Standard library only, as today. Every cluster call uses
`kubectl --context docker-desktop`. Output lines keep the `==> ` and `ERROR:`
shapes; nothing prints a credential.

| Command | Behavior | Exit |
|---|---|---|
| `check` | Read-only preflight within `CVETA2_INFRA_CHECK_TIMEOUT` (default 60 s): kubectl present, cluster ready, namespace create/delete allowed, node can admit the session quota. Creates nothing. | 0 AVAILABLE, 3 UNAVAILABLE, 1 ERROR |
| `up` | Preflight, create a session, deploy, wait (cold-start deadline), bootstrap, seed; keep it and record it in `tests/integration/.session`. Refuses while `.session` names a namespace that still exists. | 0, 3 blocked setup, 1 error |
| `env` | For the recorded (or given) session: read its credentials from its Secrets, start port-forwards, print `export NAME=<quoted>` lines for the names in [environment.md](environment.md). Refuses a terminal. | 0, 1 |
| `stop [<namespace>]` | Delete exactly the given or recorded `cveta2-it-*` namespace and wait until it is gone; stop this checkout's port-forwards for it; remove `.session` when it names it. An absent namespace is success. A name without the prefix is refused. | 0, 1 incomplete cleanup |

Session fixture (`tests/integration/conftest.py::live_run`): `prepare` performs
`up` without recording `.session`; `finish` stops the session unless
`INTEGRATION_KEEP_DATA=1`, in which case it records `.session` and prints the
exact `stop` command. A teardown failure fails the session with the namespace
name and the retry command, as today.

Removed: `INFRA_RUN_TAG` adoption, the `cveta2-main` slot and its keep-on-main
default, run-tag minting, `infra.py room`, registry capacity, k8s-infra skill
lookup, k8s-infra helper calls, `.run-tag`, TLS trust classification.
Retained: `CVETA2_TASK_VERIFICATION=1` bounded setup, `CVETA2_STAND_WAIT_TIMEOUT`
for explicit operator waiting on an unavailable cluster, the `UNAVAILABLE:` and
`ERROR:` reporting, waiting for an interrupted child before teardown.
