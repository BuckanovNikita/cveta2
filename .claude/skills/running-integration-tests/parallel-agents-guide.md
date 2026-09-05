# Concurrent integration runs

Read this reference when another developer, agent or pre-push gate may be
running the integration tests against the shared stands at the same time.

## Isolation model

Isolation is the run tag, nothing else. Every object a run creates carries its
tag (CVAT project `<tag> coco8-dev` and cloud storage `<tag> minio`, MinIO
bucket `<tag>`, ClearML projects `<tag> <what>`), every cleanup selects by that
exact tag, and the tag is minted by the skill with a nonce
(`infra.py newtag --project cveta2 --slug integration`), so two runs started on
the same day from the same branch still get different tags. Nothing runs on
this host: there are no ports, containers or volumes to keep apart.

What is still shared:

- the stands themselves, and CVAT's anonymous throttle, which sees one client
  IP for every run on this machine. The registry caps concurrent cveta2 suites
  at `[capacity].cveta2_integration_runs` in the skill's `projects.toml`; read
  the value there, and run `python3 <skill-dir>/scripts/infra.py room` before a
  run (exit status 3 is WAIT);
- the durable slot `cveta2-main`: a run on `main` (a checkout on `main`, or a
  push of `refs/heads/main`) without an exported `INFRA_RUN_TAG` is that one
  slot, so two such runs at once replace each other. Run branch work from a
  branch, and only one main run at a time;
- one checkout's `tests/integration/.run-tag` file, which names the run active
  in that checkout. `integration_up.sh` and the gate refuse to mint while it
  exists; a second run from the same checkout needs another worktree or must
  adopt the tag (below).

## Start an isolated run

The default path is already isolated: `integration_up.sh` mints a fresh tag and
records it, and test and stop read the record.

```bash
./scripts/integration_up.sh
./scripts/integration_test.sh tests/integration/<target>.py
./scripts/integration_stop.sh
```

To run under a tag you chose (a `--keep` tag, a slug that names the work), mint
it through the skill and export it before the first script; every script in
that shell then acts on it and nothing is written to `.run-tag`:

```bash
INFRA_RUN_TAG=$(python3 <skill-dir>/scripts/infra.py newtag --project cveta2 --slug <what>) && export INFRA_RUN_TAG
./scripts/integration_up.sh
./scripts/integration_test.sh tests/integration/<target>.py
./scripts/integration_stop.sh
```

Never hand-write a tag and never set `INTEGRATION_RUN_TAG`: the scripts derive
it and refuse a conflicting shell value. Not Claude Code? Export
`INFRA_HARNESS=codex|ci|human` first, so the tag records who ran it.

## Adopt a run started elsewhere

A run's tag is its only handle. To test or stop a run that another shell or a
killed gate started, export its tag and use the same scripts:

```bash
export INFRA_RUN_TAG=<tag>          # from .run-tag, the gate log, or `ls` below
./scripts/integration_test.sh tests/integration/<target>.py
./scripts/integration_stop.sh
```

Adopt only a tag you own or were handed: adopting a live run of somebody else
and stopping it deletes their objects. When in doubt, list first.

## Diagnose collisions

```bash
source scripts/integration_env.sh
cat tests/integration/.run-tag                               # the run active in this checkout
uv run python tests/integration/cvat_stand.py ls             # what the cveta2 user owns on CVAT
python3 "$INTEGRATION_SKILL_DIR/scripts/cvat.py"    --project cveta2 ls
python3 "$INTEGRATION_SKILL_DIR/scripts/minio.py"   --project cveta2 ls
python3 "$INTEGRATION_SKILL_DIR/scripts/clearml.py" --project cveta2 ls
```

Every cveta2 run tag reads as `cveta2-<harness>-<yyyymmdd>-integration-<nonce>`
(or the slug the run chose), so the listings say who started what and when.
A `Duplicate base task name` failure or a project that vanished mid-run means
two runs share one tag: only the main slot and an adopted tag can do that.
Choose a fresh tag; never stop a tag you did not start.

## Cleanup after failure

Clean only the tag recorded for the current run; `integration_stop.sh` prints
the exact same-tag retry command for the stand that failed:

```bash
INFRA_RUN_TAG=<owned-tag> ./scripts/integration_stop.sh
```

If only one stand needs retrying, use the command the script printed:
`cvat_stand.py cleanup --tag <owned-tag>` for CVAT, or the skill's
`minio.py` / `clearml.py --project cveta2 cleanup --prefix <owned-tag>`. Never
substitute a shorter prefix: the helpers refuse one that does not reach
`cveta2-<harness>-<yyyymmdd>-`, and `cvat_stand.py` matches the tag followed by
a space.

Orphans of dead runs are inventoried with the skill's
`cleanup --stale --dry-run` on each stand; for anyone but the janitor
`cleanup --stale` is that listing whatever the flags say. Report what it shows
and leave the deletion to the janitor or the human. The retained
`cveta2-main` slot is a durable name of the registry: the listing never shows
it, and it is never an orphan.
