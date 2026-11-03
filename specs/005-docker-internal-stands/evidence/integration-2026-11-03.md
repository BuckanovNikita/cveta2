# Live integration run against the HTTPS stands (T013, SC-004) — 2026-11-03

## Setup

- **Worktree:** `feat/docker-internal-names` at 9174b14, with the artifact edits of this commit uncommitted. No runtime or test code differs from 9174b14.
- **Stands:** CVAT `https://cvat.k8s.docker.internal`, MinIO `https://s3.k8s.docker.internal`, ClearML `https://api.clearml.k8s.docker.internal` (ClearML server 2.0.0).
- **Trust:** the k8s-infra local CA is installed at `/usr/local/share/ca-certificates/k8s-infra-local-ca.crt`. The helper `env` output exports `SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE`, `AWS_CA_BUNDLE` and `NODE_EXTRA_CA_CERTS`. Their values are not recorded here.
- **Arming:** `tests/integration/.env` was created from `.env.example`. It holds no values.
- **Preflight:** `python3 <k8s-infra>/scripts/infra.py room` exited 0 with verdict GO (pods 57/100, fat namespaces 1/4, clearml task pods 0/4).
- **Run tag:** `infra.py newtag --project cveta2 --slug https-move` minted `cveta2-claude-20261103-https-move-fl1u`. It was exported as `INFRA_RUN_TAG` for every lifecycle command.

## Run

All commands ran from the worktree root with `INFRA_RUN_TAG=cveta2-claude-20261103-https-move-fl1u`:

1. `./scripts/integration_up.sh` started at 20:40:39+03:00 and exited 0.
   - It verified the account and seeded bucket `cveta2-claude-20261103-https-move-fl1u` and cloud storage `<tag> minio`.
   - It seeded project `cveta2-claude-20261103-https-move-fl1u coco8-dev` (id 29) with its tasks in organization `agents`.
2. `./scripts/integration_test.sh tests/integration` ran from 20:41:27 to 20:45:38+03:00 and exited 0.
   - The ClearML `whoami` preflight authenticated identity `cveta2` over HTTPS.
   - pytest collected 38 items: **38 passed, 0 skipped, 0 failed, 0 errors** in 247.98 s. The 480 warnings are third-party deprecation warnings (pyparsing via the ClearML SDK).
   - No `TLS verification of … failed` message appeared.
3. `./scripts/integration_stop.sh` exited 0.
   - It deleted CVAT project 29 and storage 11 (`<tag> minio`) in organization `agents`.
   - It deleted bucket `<tag>` with 15 objects.
   - ClearML reported "nothing to clean"; the tests had removed their own projects.
   - It released `tests/integration/.run-tag`, which is absent afterwards.

## Cleanup proof (same tag, after stop)

| Command (`--project cveta2`) | Result |
| --- | --- |
| `cvat.py cleanup --prefix "$INFRA_RUN_TAG"` | nothing to clean in organization agents (exit 0) |
| `minio.py cleanup --prefix "$INFRA_RUN_TAG"` | nothing to clean (exit 0) |
| `clearml.py cleanup --prefix "$INFRA_RUN_TAG"` | nothing to clean (exit 0) |
| `cvat.py ls --prefix "$INFRA_RUN_TAG"` | organization agents: 0 project(s), 0 task(s), 0 storage(s) |
| `minio.py ls --prefix "$INFRA_RUN_TAG"` | 0 bucket(s) |
| `clearml.py ls --prefix "$INFRA_RUN_TAG"` | 0 project(s), 0 task(s) |
| `tests/integration/cvat_stand.py ls`, lines naming the tag | 0 |

No other tag was touched, and `cveta2-main` was not touched.

## Result

SC-004 is met: the full integration lifecycle passes against the HTTPS docker.internal stands with one owned run tag and exact-tag cleanup.

The pre-push gate runs the suite again when this branch is pushed. That push reuses the same tag (`INFRA_RUN_TAG` exported), and its outcome is reported with the push, not here.
