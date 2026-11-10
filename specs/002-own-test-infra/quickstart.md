# Quickstart: live tests on a session-owned namespace

Target behavior after implementation; validation steps for the tasks.

Prerequisites: `kubectl` with context `docker-desktop`, `uv sync --locked`. No
k8s-infra skill, Helm, local CA or shared stand is needed.

```bash
uv run --locked task --exit-code infra-check   # 0 available, 3 unavailable, 1 error
uv run --locked task --exit-code integration   # creates cveta2-it-<id>, runs the suite, deletes it
```

Keep a session for inspection, then remove it:

```bash
INTEGRATION_KEEP_DATA=1 uv run --locked task --exit-code integration
eval "$(uv run --locked python -m tests.integration.lifecycle env)"   # port-forwards and variables
uv run --locked python -m tests.integration.lifecycle stop             # deletes exactly that namespace
```

Validation scenarios (record outcomes with date in [evidence.md](evidence.md)):

1. Integration task on a reachable cluster: quota exists before the first pod;
   suite passes; namespace and port-forwards are gone afterwards.
2. `infra-check` with a context that cannot create namespaces: exit 1, nothing created.
3. `infra-check` with the API unreachable (an unreachable server URL in a
   throwaway kubeconfig): exit 3 within the deadline.
4. Interrupt a session during seeding: its namespace is deleted.
5. Kept session, then `stop`: only that namespace is deleted; a second `stop`
   reports it already removed.
6. Delete a kept namespace by hand, then start a new session: no repair needed.
7. Two worktrees run sessions at the same time: distinct namespaces and ports.
8. The SC-005 `git grep` is empty outside `specs/`, `docs/plans/` and `CHANGELOG.md`.
