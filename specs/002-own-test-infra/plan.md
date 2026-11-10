# Implementation Plan: Session-owned live-test infrastructure

**Branch**: `feat/own-test-infra` | **Date**: 2026-11-10 | **Spec**: [spec.md](spec.md)

**Input**: [spec.md](spec.md), the k8s-infra plan
`docs/plans/2026-11-09-managed-infrastructure-reset.md` (phase P5, "Rules for
every project", the cveta2 block), and the measurements in
[evidence.md](evidence.md).

## Summary

Replace the shared-stand run model of the live tests with one Kubernetes
namespace per session that the session creates, fills from manifests in this
repository, seeds, reaches through loopback port-forwards and deletes. The test
modules and their assertions stay; `tests/integration/lifecycle.py` is rewritten
around the namespace, the manifests are new, and the governing policy and
guidance move from "one owned run tag" to "one owned session namespace". The
measured minimal service set ([research.md](research.md), R2 and R4) passed the
whole live suite.

## Technical Context

**Language/Version**: Python >=3.12,<3.14; the lifecycle tool stays standard-library only.
**Primary Dependencies**: `kubectl` with the `docker-desktop` context. Helm is no longer a prerequisite. No new Python dependency.
**Storage**: `emptyDir`; one `hostpath` claim for CVAT's shared data directory.
**Testing**: the existing live suite (`tests/integration`, serial `live` group) is the acceptance test; the unit suite stays as is. No test of the lifecycle tool or manifest text (constitution IV; feature 001 precedent): its behavior is validated by recorded manual experiments.
**Target Platform**: Docker Desktop Kubernetes on WSL2, single node.
**Project Type**: CLI/library; this feature touches test infrastructure and development policy only.
**Performance Goals**: session ready to seed within the cold-start deadline (SC-003); measured about 70 s with cached images.
**Constraints**: plan rules 1-9 and the two interim rules; no shared stand, k8s-infra helper or registry; credentials never stored or printed; quota before workloads.
**Scale/Scope**: one session per live run; several concurrent sessions bounded only by the node.

## Constitution Check

*Gate before research and after design.*

| Principle | Status |
|---|---|
| I. Specification ownership | Pass. Product baseline, dataset contract and public interfaces unchanged; this feature records its own dated evidence. |
| II-III. Architecture and Python conventions | Pass. No product module changes. The lifecycle tool keeps catching specific exceptions and never swallows failures. |
| IV. Verify the changed behavior | Pass with design note. Live verification keeps bounded read-only preflight and the 0/3/1 outcomes; the meaning of UNAVAILABLE changes from "capacity WAIT or stand down" to "cluster down or node cannot admit the quota" (spec, Clarifications). Tests stay product tests; tooling is validated by recorded experiments. |
| V. Ownership, documentation, release | **Conflict, resolved by amendment before implementation.** V requires that "shared integration resources MUST use the existing lifecycle skills, one owned run tag, and exact-tag cleanup". After this feature there are no shared integration resources; the rule becomes "each live session owns one namespace, created with a quota and removed by exact name on success, failure and interruption; never act on another session's namespace". The amendment (minor version) is task T001 and gates every other implementation task. The "Project Constraints" ban on duplicating capacities and stand setup in specifications is respected: numbers live in the manifests and dated evidence. |

Post-design re-check: the design adds no new service, controller, CI job or
dependency; it removes the k8s-infra coupling. No unresolved violation once
T001 lands.

## Behavior mapping (current → new)

| Current behavior | New home or disposition |
|---|---|
| `check` 0/3/1 within `CVETA2_INFRA_CHECK_TIMEOUT` | Retained (FR-014); checks change per research R9 |
| UNAVAILABLE on capacity WAIT (`infra.py room`, registry cap) | Removed with the registry; replaced by node admission of the session quota |
| Explicit operator wait (`CVETA2_STAND_WAIT_TIMEOUT`) | Retained for an unavailable cluster |
| Run tag minted by `infra.py newtag`; `INFRA_RUN_TAG` adoption | Removed; the session namespace is the tag (R7) |
| Durable `cveta2-main` slot, kept by default on `main` | Removed; every session is stopped unless `INTEGRATION_KEEP_DATA=1` |
| `INTEGRATION_KEEP_DATA=1/0` | `=1` retained; `=0` is the default everywhere |
| `.run-tag` blocks a second fresh run in a checkout | Replaced by `.session` for kept sessions only; concurrent fixture sessions are allowed (FR-019) |
| Credentials from k8s-infra project Secrets | Generated per session (FR-009, FR-010) |
| CVAT identity check `cvat_stand.py verify` | Retained as a post-bootstrap check |
| Exact-tag cleanup in CVAT, MinIO, ClearML + listing proof | Replaced by namespace deletion and absence proof (FR-016); object-level cleanup inside a session is unnecessary |
| TLS trust classification (`stand_tls.py`) | Removed: loopback HTTP has no certificate |
| Stale-run sweeping by the k8s-infra janitor | Platform sweeper deletes any project namespace at 48 h; `stop <namespace>` for manual cleanup |
| Live tests serial, `--dist loadgroup`, env isolation, hidden live variables | Retained (FR-021) |
| Deferral blocks acceptance, merge and release | Retained |

## Project Structure

### Documentation (this feature)

```text
specs/002-own-test-infra/
├── spec.md, plan.md, research.md, data-model.md, quickstart.md
├── contracts/lifecycle-cli.md, contracts/environment.md
├── checklists/requirements.md, checklists/live-infrastructure.md
├── tasks.md
└── evidence.md          # dated measurements and later verification
```

### Source and policy (repository root)

```text
tests/integration/k8s/          # new: quota.yaml, cvat.yaml, minio.yaml, clearml.yaml
tests/integration/lifecycle.py  # rewritten around the session namespace
tests/integration/conftest.py   # live_run fixture: prepare/finish, docstring, no TLS path
tests/integration/{cvat_stand,seed_cvat,clearml_run}.py  # docstrings, no helper references
tests/integration/stand_tls.py  # removed
tests/integration/test_*.py     # docstrings and the default host in test_e2e only
tests/env_isolation.py          # comment on the real environment
scripts/mutation.py, scripts/session_status.sh, scripts/README.md, .gitignore
Taskfile.yml                    # only if a task text names the stands
.specify/memory/constitution.md # amendment (T001)
.specify/memory/engineering.md  # "Integration tests" and "Shared infra" sections, setup prerequisites
.agents/skills/running-integration-tests/SKILL.md, .agents/skills/verification-workflow/SKILL.md
AGENTS.md, README.md (Russian)
```

## Phases and ownership

1. **Policy gate** (T001). Constitution amendment and its sync report; nothing
   else starts before it.
2. **Manifests** (T002-T005). Derived from the measurement builder's output,
   cleaned to plain YAML with pinned images, resources inside the quota,
   no Ingress, the one `hostpath` claim, the file server's wait on the API
   server, Elasticsearch host schemes. Parallel per file.
3. **Lifecycle** (T006-T011). Sequential: session naming and state, deploy and
   readiness, bootstrap, port-forwards and environment, teardown, preflight and
   CLI. Then the fixture and helper docstrings (T012-T014).
4. **Retirement and guidance** (T015-T019). Parallel with phase 3 once T001 is
   in: engineering guidance, skills, AGENTS.md, README, scripts, `.gitignore`.
5. **Verification** (T020-T026). Stop editing; record the manual experiments
   (preflight outcomes, interruption, kept session, vanished namespace,
   concurrent sessions), the full live suite through Task, cleanup proof,
   `git grep` for retired names, development verification with `SKIP` cleared,
   mutation report, fresh independent review, convergence and baseline note.

## Verification

- Development: `uv run --locked task --exit-code verify` on the final commit.
- Live: `uv run --locked task --exit-code infra-check`, then
  `uv run --locked task --exit-code integration`; acceptance on the clean tip.
- Manual experiments as listed in phase 5, recorded with date in evidence.md.
- Cleanup proof: no `cveta2-it-*` namespace of the run and no session
  port-forward process after each experiment.
- Independent review after integration and verification (behavior and
  operational-policy change).

## Complexity Tracking

| Item | Why needed | Simpler alternative rejected because |
|---|---|---|
| One `hostpath` claim | CVAT server and workers share files across pods | `emptyDir` is per pod; a merged multi-container pod is unmeasured (R3) |
| Plain manifests derived from the upstream chart | Small reviewed component set without Helm | Running the chart needs Helm and carries unused subcharts (R1) |
