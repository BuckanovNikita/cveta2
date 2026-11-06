---
name: running-integration-tests
description: Runs and troubleshoots cveta2 integration tests against the shared CVAT, MinIO and ClearML stands of the docker-desktop cluster through the repository lifecycle tool (tests/integration/lifecycle.py). Use for targeted or full live tests, the pre-commit integration gate failing, run-tag ownership and cleanup, TLS trust failures, or concurrent runs.
---

# Run cveta2 integration tests

Live tests run on the shared stands owned by the `k8s-infra` skill (read its
`references/run-contract.md` before touching a stand). Nothing runs on this
host. A machine is armed when that skill is installed (`~/.agents/skills`,
`~/.claude/skills`, or `K8S_INFRA_SKILL_DIR`); credentials come from the
project Secrets through the skill, never from a file.

`L` below is `uv run python -m tests.integration.lifecycle`.

```bash
L gate                                   # all of it: preflight, up, tests, stop
L up                                     # mint a tag and seed the run
L test tests/integration/test_upload.py -k upload
L stop                                   # remove the run, release the tag
eval "$(L env)"                          # the run's variables, for manual tools
```

The tool's errors name the failing stand and the retry command; read them before
anything else. The module docstring documents tag precedence and every exported
variable.

## Rules

- One run, one tag. `up` mints it (`infra.py newtag`) and writes the gitignored
  `tests/integration/.run-tag`; `test`, `stop` and the gate read it. Export
  `INFRA_RUN_TAG=<tag>` to adopt a run started elsewhere. On `main` the run is
  the durable slot `cveta2-main`.
- Operate only your own tag. Never broaden a cleanup selector, never touch
  another tag or `cveta2-main` from a branch, and never run `cleanup --stale`
  without `--dry-run`.
- Stop every run with `L stop`; it removes the CVAT project and cloud storage,
  the MinIO bucket and leftover ClearML projects, and releases the tag only when
  every stand succeeded. An empty `ls --prefix <tag>` listing is the proof.
- Do not add `-n auto`: `L test` runs pytest serially because CVAT throttles one
  client IP. A seeded project is single-use for a full run; `up` again first.
- A failed TLS handshake is a trust problem (the k8s-infra local CA), not a stand
  that is down. Never switch to plain HTTP or disable verification.
- A stand that is down is diagnosed with the `k8s-infra` skill; this tool never
  deploys or restarts one.

## Pre-commit gate

The `integration-tests` hook runs `L gate` on commits that touch `cveta2/`,
`tests/integration/`, `pyproject.toml` or `uv.lock`, and skips with a notice on
a machine without the skill. It fails the commit when `infra.py room` answers
WAIT (retry later), a stand does not answer or authenticate, or a `.run-tag`
names an active run in this checkout (`L stop` it, or commit from another
worktree). Branch runs are stopped; the `main` run stays in its slot.
`INTEGRATION_KEEP_DATA=1` keeps any run and `--keep-stack` keeps a failed one,
both until `L stop`. `SKIP=integration-tests git commit` is a one-commit bypass
for the user's explicit request, not a recovery step.

## Concurrency

Different tags never share objects. The registry's
`[capacity].cveta2_integration_runs` caps concurrent cveta2 suites (CVAT
throttles the one client IP every run shares), but nothing enforces it: `room`
checks only the stands' own load. Every armed worktree whose commit touches the
gated paths starts a suite, so before committing from several worktrees or
agents at once, count the active runs (`cvat.py --project cveta2 ls`) and
serialize the commits beyond the cap. One checkout holds one `.run-tag`.

## Completion evidence

Report the run tag, the selector, the pytest result, and whether the run was
stopped or kept (by tag). After a failed setup or cleanup, name what may remain
and the exact same-tag `L stop` retry.
