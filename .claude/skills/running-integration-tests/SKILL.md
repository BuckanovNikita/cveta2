---
name: running-integration-tests
description: Run or troubleshoot cveta2 integration tests against the local cluster CVAT stand and per-run MinIO/ClearML stack. Use for integration setup, targeted or full live tests, lifecycle cleanup, pre-push integration failures, or concurrent-run isolation.
---

# Run cveta2 integration tests

Use the repository lifecycle scripts for the persistent CVAT stand at
`http://cvat.k8s.localhost` and the per-run MinIO/ClearML Compose stack.
These commands mutate external test state. Operate only the current run's exact
tag and ports; never stop the shared CVAT stand or delete another run's data.

## Choose and record run ownership

Every command must use the same environment. `scripts/integration_env.sh`
derives `INTEGRATION_RUN_TAG` from `INTEGRATION_USER` and branch unless it is
set explicitly. The tag owns:

- Compose project `<tag>-cveta2`, its containers, volumes, and ports.
- CVAT project `<tag> coco8-dev`, its tasks, and cloud storage
  `<tag> minio` inside `CVAT_INTEGRATION_ORG`.

For automated or concurrent work, set a unique
`INTEGRATION_RUN_TAG` and unique ports before setup; record them so test and
stop commands reuse them. Do not adopt a tag already in use. Read
[parallel-agents-guide.md](parallel-agents-guide.md) when another run may be
active or a port is occupied.

The default ports are MinIO 9989/9990 and ClearML 8880–8882. Override with
`MINIO_PORT`, `MINIO_CONSOLE_PORT`, `CLEARML_API_PORT`,
`CLEARML_FILES_PORT`, and `CLEARML_WEB_PORT`.

## Credentials and CVAT identity

The lifecycle requires Docker with Compose v2, `uv`, `curl`, and `unzip`, and
the cluster CVAT stand must be reachable. Diagnose or deploy that stand through
the `k8s-infra` skill; these scripts never start or stop CVAT itself.

`tests/integration/.env` is gitignored and required by every lifecycle script.
Create it from `.env.example` and supply a non-placeholder
`CVAT_INTEGRATION_PASSWORD`. It defines the host, integration username,
password, organization, and MinIO bucket. Its presence also arms the pre-push
integration gate.

`cvat_stand.py bootstrap` logs in without an organization header until the
organization exists. On an HTTP 400/401/403 login rejection it registers the
integration account and retries once. It then verifies membership in
`CVAT_INTEGRATION_ORG`, creating the organization when the account can do so.
It fails on a wrong password or an organization slug owned by another account;
do not work around those identity errors by switching organizations or using an
admin account. Tests authenticate as the integration account and set the
organization slug after login. Admin is for inspection only.

## Run the requested scope

Setup recreates the current tag's Compose state and CVAT objects before seeding:

```bash
./scripts/integration_up.sh
./scripts/integration_test.sh tests/integration
./scripts/integration_stop.sh
```

Pass pytest paths and selectors through `integration_test.sh` for a targeted
run, for example:

```bash
./scripts/integration_test.sh tests/integration/test_upload.py -k upload
```

Do not add `-n auto`. The wrapper deliberately replaces pytest `addopts` to
disable xdist while retaining `tests.env_isolation`; concurrent CVAT requests
otherwise hit the shared stand's rate limit and can corrupt test assumptions.
The registered `integration` marker and `CVAT_INTEGRATION_HOST` control live
test collection. ClearML tests skip when its health endpoint is unavailable.

A seeded project is single-use for a full run because tests create fixed task
names. Run `integration_up.sh` again before a second full suite. Test fixtures
and `finally` blocks close clients and remove test-owned objects where defined;
do not bypass that teardown. Run-level cleanup removes the remaining exact-tag
project and storage.

## Cleanup boundary

After manual tests, run `integration_stop.sh` with the same tag and ports. It
removes the current tag's Compose project and volumes first, then exact-tag CVAT
objects. The CVAT selector is `"<tag> "` including the trailing space, so a
short tag cannot match a longer one. If CVAT cleanup fails, report the retry
command for that same tag; do not broaden the selector.

Never use `cleanup --stale` to remove objects as routine test teardown. A
stale dry-run may inventory candidates, but deletion requires explicit user
authorization and independent ownership verification for every listed object.
Do not remove the deliberately retained main run without that authorization.

## Pre-push gate

`scripts/integration_gate.sh` is armed only when
`tests/integration/.env` exists. Once armed, missing Docker, an unavailable
CVAT stand, or occupied ports fail the gate. It runs setup, only
`tests/integration`, then:

- keeps the main run for inspection;
- stops an ordinary branch run;
- honors `INTEGRATION_KEEP_DATA=1/0`;
- keeps a failed run only with `--keep-stack`.

The teardown trap is armed after preflight, so a skipped or unprepared gate does
not delete anything. `SKIP=integration-tests git push` is an explicit
one-push bypass, not a default recovery action.

## Completion evidence

Report the run tag, ports, test selector, pytest result, and cleanup/keep state.
If setup or cleanup fails, name which owned resources may remain and the exact
same-tag recovery command.
