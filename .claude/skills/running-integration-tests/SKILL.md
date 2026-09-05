---
name: running-integration-tests
description: Run or troubleshoot cveta2 integration tests against the shared CVAT, MinIO and ClearML stands of the docker-desktop cluster. Use for integration setup, targeted or full live tests, run-tag ownership and cleanup, pre-push integration failures, or concurrent-run isolation.
---

# Run cveta2 integration tests

The integration tests run against the shared stands of the local Kubernetes
cluster: CVAT, MinIO and ClearML, all owned by the `k8s-infra` skill. Nothing
runs on this host, so there are no containers to start and no ports to pick.
Every run acts as project `cveta2` of the skill's registry under one **run tag**
(the `## Shared infra` block in `AGENTS.md`, and the skill's
`references/run-contract.md`), and the repository's lifecycle scripts do the
minting, the credential lookup, the seeding and the cleanup. These commands
mutate shared state: operate only the current run's exact tag, never another
tag, never a stand.

## Arm the machine

`tests/integration/.env` is gitignored, holds no credentials and is required by
every lifecycle script; its presence also arms the pre-push gate. Create it
with `cp tests/integration/.env.example tests/integration/.env`. The only value
it may carry is `K8S_INFRA_SKILL_DIR`, for a skill checkout that is not
installed under `~/.agents/skills` or `~/.claude/skills`.

Credentials never live in a file: `scripts/integration_env.sh` evaluates
`cvat.py`, `minio.py` and `clearml.py --project cveta2 env` from the skill and
maps the Secret's keys onto the variables the tests read (`CVAT_INTEGRATION_*`,
`MINIO_*`, `CLEARML_*`). A missing Secret key is an error, never a default.
Before the first run, `python3 <skill-dir>/scripts/infra.py room` must answer
GO (exit status 3 is WAIT: come back later, it is not an error).

## The run tag owns everything

`scripts/integration_env.sh` resolves one tag for up, test, stop and the gate:

1. `INFRA_RUN_TAG`, when exported: this is how a shell adopts a run that was
   started elsewhere (another shell, a killed gate), and the only way to run
   under an explicit tag. Never set `INTEGRATION_RUN_TAG` yourself; the script
   refuses a shell value that differs from the derived tag.
2. On `main` (or when pre-commit pushes `refs/heads/main`): the durable slot
   `cveta2-main`, a registry durable name that the janitor never sweeps and that
   the next main run replaces.
3. `tests/integration/.run-tag`: the file `integration_up.sh` writes when it
   mints a tag and `integration_stop.sh` deletes on full success.
4. Nothing: `integration_up.sh` mints
   `infra.py newtag --project cveta2 --slug integration`; test and stop refuse.

The tag names the run's objects on every stand: CVAT project `<tag> coco8-dev`
and cloud storage `<tag> minio` inside the organization from the Secret
(`CVAT_ORG`), MinIO bucket `<tag>`, and ClearML projects `<tag> <what>` that the
tests create and remove themselves at session end. An existing `.run-tag` file
means a run is active: stop it, or export `INFRA_RUN_TAG` to adopt it; up and
the gate refuse to mint over it.

## Run the requested scope

```bash
./scripts/integration_up.sh
./scripts/integration_test.sh tests/integration
./scripts/integration_stop.sh
```

Setup verifies the `cveta2` account and its organization membership
(`cvat_stand.py verify`; it registers nothing), removes this tag's previous
CVAT objects and bucket, downloads the coco8 images once, then seeds the bucket,
the cloud storage, the project and its tasks. Pass pytest paths and selectors
through `integration_test.sh` for a targeted run:

```bash
./scripts/integration_test.sh tests/integration/test_upload.py -k upload
```

Do not add `-n auto`. The wrapper replaces pytest `addopts` to disable xdist
while retaining `tests.env_isolation`; concurrent requests otherwise hit the
CVAT stand's anonymous throttle. It runs pytest as `uv run --extra clearml` so
the ClearML SDK is present (a plain `uv sync` removes it again). The registered
`integration` marker and `CVAT_INTEGRATION_HOST` control live collection.

The ClearML stand is not optional: `integration_test.sh` and the gate run
`clearml.py --project cveta2 whoami` first and fail when the identity does not
authenticate. On an armed machine nothing skips; a stand that is down is
diagnosed with the `k8s-infra` skill, never worked around.

A seeded project is single-use for a full run because tests create fixed task
names. Run `integration_up.sh` again before a second full suite. Test fixtures
and `finally` blocks close clients and remove test-owned objects; do not bypass
that teardown.

## Inspect a run

Everything is read through the identity's own view, never as an administrator:

```bash
source scripts/integration_env.sh
uv run python tests/integration/cvat_stand.py ls
python3 "$INTEGRATION_SKILL_DIR/scripts/cvat.py"    --project cveta2 ls --prefix "$INTEGRATION_RUN_TAG"
python3 "$INTEGRATION_SKILL_DIR/scripts/minio.py"   --project cveta2 ls --prefix "$INTEGRATION_RUN_TAG"
python3 "$INTEGRATION_SKILL_DIR/scripts/clearml.py" --project cveta2 ls --prefix "$INTEGRATION_RUN_TAG"
```

`cvat_stand.py ls` shows the projects, tasks and cloud storages the `cveta2`
user owns in the organization; the helpers' `ls` prints a count line and one
row per object, so an empty listing after cleanup is the proof it worked. In a
browser, the CVAT UI (`CVAT_INTEGRATION_HOST`) signs in as the `cveta2` user
with the password from the Secret, and the MinIO console (`MINIO_CONSOLE`) with
the project's key; read both from the environment, never print or paste them.

## Cleanup boundary

`integration_stop.sh` removes the current tag's CVAT project and cloud storage
(`cvat_stand.py cleanup --tag`, which matches `"<tag> "` with the trailing
space so a short tag never matches a longer one), then bucket `<tag>`
(`minio.py cleanup --prefix`), then any `<tag> ...` ClearML project a killed
session left (`clearml.py cleanup --prefix`). It releases `.run-tag` only when
every stand succeeded; on a failure it prints the retry command for that stand
and the same tag. Never broaden a selector or a prefix. Stop an integration run
through `integration_stop.sh`, not through the skill's `cvat.py cleanup` line
of the `## Shared infra` block: that helper removes projects and tasks only and
would leave the `<tag> minio` cloud storage behind.

`cleanup --stale` is the janitor's: for anyone else it degrades to the
`--dry-run` listing, which is how orphans of dead runs are inventoried and
reported. Never delete another tag's objects, never touch `cveta2-main` unless
the run is the main run, and report anything intentionally kept by its full
tag.

## Pre-push gate

`scripts/integration_gate.sh` is armed only when `tests/integration/.env`
exists. Once armed it preflights the CVAT stand and the ClearML identity, checks
that no other run is active, and only then arms its teardown trap, runs setup
and `tests/integration`, and decides what stays:

- on `main` the run is the `cveta2-main` slot and stays for inspection (nothing
  stays on ClearML: the tests remove their projects);
- any other branch is stopped fully;
- `INTEGRATION_KEEP_DATA=1` keeps whatever the branch (a kept branch run is an
  ordinary tag the janitor sweeps after the registry's `[contract].stale_hours`;
  its `.run-tag` stays, so the next gate refuses until `integration_stop.sh`);
  `INTEGRATION_KEEP_DATA=0` stops whatever the branch;
- `--keep-stack` keeps only a failed run, for triage.

A preflight failure fails the push with a diagnose-only message: the scripts
never deploy or restart a stand. `SKIP=integration-tests git push` is an
explicit one-push bypass, not a default recovery action.

## Concurrency

Isolation is the tag: two runs with different tags never touch each other's
objects. The registry caps concurrent cveta2 suites at
`[capacity].cveta2_integration_runs` (CVAT's anonymous throttle sees one client
IP for every run on this machine); read
[parallel-agents-guide.md](parallel-agents-guide.md) before starting a run
while another may be active.

## Completion evidence

Report the run tag, the test selector, the pytest result, and whether the run
was stopped or kept (by tag). If setup or cleanup fails, name which owned
resources may remain and the exact same-tag recovery command.
