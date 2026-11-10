# Tasks: Session-owned live-test infrastructure

Input: [spec.md](spec.md), [plan.md](plan.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/](contracts/), [evidence.md](evidence.md).
The live suite is the acceptance test; the lifecycle tool and manifests are
validated by recorded manual experiments, not by new repository tests of tooling
or manifest text. `[P]` marks tasks on different files with no open dependency.

## Phase 0: Specification and measurement (this step)

- [x] T000 Select specs/002-own-test-infra; write spec with clarifications, plan, research, data model, contracts, quickstart, quality checklists and analysis; measure the minimal service set, cold start and quota in throwaway `cveta2-it-*` namespaces and record dated evidence.

## Phase 1: Policy gate

- [x] T001 Amend principle V (and the IV wording on exact-tag cleanup) in .specify/memory/constitution.md: each live session owns one namespace with a quota and removes it by exact name; record the amendment rationale and version. Blocks every later task.

## Phase 2: Foundational manifests

Independent check: `kubectl apply --dry-run=server` into a throwaway `cveta2-it-*` namespace succeeds; no Ingress, NodePort, host port, `local-path` or unnamed storage class.

- [x] T002 [P] Add tests/integration/k8s/quota.yaml: ResourceQuota and LimitRange sized from evidence.md with headroom (FR-003).
- [x] T003 [P] Add tests/integration/k8s/cvat.yaml: server, import and chunks workers, initializer Job, OPA, Redis, kvrocks on emptyDir, PostgreSQL 15 on emptyDir, one `hostpath` claim for /home/django/data, smokescreen private ranges, pinned v2.59.1 images and a pinned `busybox` for the permission-fix init container, header naming the source chart version (FR-004, FR-006, FR-008).
- [x] T004 [P] Add tests/integration/k8s/minio.yaml: pinned MinIO on emptyDir with readiness probe (FR-004).
- [x] T005 [P] Add tests/integration/k8s/clearml.yaml: API server, file server waiting for the API, MongoDB, Elasticsearch 7.17.28 with explicit host schemes, Redis, all emptyDir, pinned images (FR-007).

## Phase 3: US1 — Run on session-owned services (P1)

Independent check: `task integration` passes the full suite and leaves no namespace or port-forward.

- [x] T006 [US1] In tests/integration/lifecycle.py, replace run-tag resolution with session naming (`cveta2-it-<UTC>-<hex>`), `.session` for kept sessions, and removal of the main slot, `INFRA_RUN_TAG`, skill lookup and registry reads (FR-002, FR-012, FR-017).
- [x] T007 [US1] Implement namespace creation with label, quota first, generated credential Secrets, manifest apply and bounded readiness wait in tests/integration/lifecycle.py (FR-001, FR-003, FR-009, FR-010, FR-015).
- [x] T008 [US1] Implement CVAT user and organization bootstrap through the public API and the ClearML key pair from the session Secret; keep `cvat_stand.py verify` as the post-bootstrap identity check (FR-009).
- [x] T009 [US1] Implement loopback port-forwards with kubectl-chosen ports and the environment of contracts/environment.md, including the AWS names; keep `CVETA2_LIVE_EXPORTED` (FR-005, FR-011).
- [x] T010 [US1] Implement teardown: delete exactly the session namespace, bounded wait, stop port-forwards, report incomplete cleanup with the retry command; keep on `INTEGRATION_KEEP_DATA=1` (FR-016, FR-018).
- [x] T011 [US1] Update tests/integration/conftest.py (live_run, docstrings, default host, drop the TLS path), remove tests/integration/stand_tls.py and its imports in cvat_stand.py and seed_cvat.py, and update docstrings of seed_cvat.py, cvat_stand.py, clearml_run.py and test modules that name the shared stands (FR-012, FR-013).

## Phase 4: US2 — Honest deferral (P2)

Independent check: the three preflight outcomes within the deadline; blocked setup leaves nothing.

- [x] T012 [US2] Rewrite `check`/`probe` in tests/integration/lifecycle.py per research R9 (kubectl present, `/readyz`, namespace create/delete permission, node admission of the quota requests) with the 0/3/1 outcomes; keep `CVETA2_STAND_WAIT_TIMEOUT` operator waiting (FR-014).
- [x] T013 [US2] Report readiness timeout as blocked setup and tear the namespace down (FR-015).

## Phase 5: US3 — Recovery and concurrency (P3)

- [x] T014 [US3] `stop [<namespace>]`: refuse names without the prefix, treat an absent namespace as removed, never touch another session automatically; `up` discards a `.session` whose namespace vanished (FR-016-FR-019).

## Phase 6: Retirement and guidance

Can start after T001, in parallel with Phases 3-5 (different files).

- [x] T015 [P] Rewrite "Integration tests" and "Shared infra" in .specify/memory/engineering.md and its setup prerequisites (no k8s-infra skill; kubectl only) (FR-022).
- [x] T016 [P] Rewrite .agents/skills/running-integration-tests/SKILL.md for sessions, keep/stop, cleanup proof and concurrency; adjust .agents/skills/verification-workflow/SKILL.md wording (FR-022).
- [x] T017 [P] Update AGENTS.md project-skill line and the Russian README.md live-test paragraph (FR-022).
- [x] T018 [P] Update scripts/mutation.py `STAND_NAMES`, scripts/session_status.sh, scripts/README.md and .gitignore (`.run-tag` → `.session`) (FR-013).
- [x] T019 [P] Update tests/env_isolation.py and tests/conftest.py comments that name the skill lookup or the stands, and the `integration` marker description in pyproject.toml (FR-013, FR-022).

## Phase 7: Verification and convergence

- [x] T020 Stop editing. Run `infra-check` and `integration` through Task; record the run, namespace, timings and cleanup proof in evidence.md; confirm the serial `live` group and environment isolation held and the session finished far inside 48 hours (SC-001-SC-004, FR-020, FR-021).
- [x] T021 Record the quickstart experiments 2-7 with date and outcome in evidence.md (SC-006, US2, US3).
- [x] T022 Run the SC-005 `git grep`; record the empty result (SC-005, FR-013).
- [x] T023 Run development verification with `SKIP` cleared on the final commit; inspect and commit mechanical fixes separately.
- [x] T024 Run the mutation report for changed functions and triage per the mutation skill.
- [ ] T025 Fresh independent review of the integrated branch (behavior and operational policy); resolve findings and rerun affected checks.
- [ ] T026 Converge spec, plan and tasks with the result; clean-tip acceptance; merge and release follow the release skill and need their authorizations.

## Dependencies

T001 → everything. T002-T005 → T007. T006 → T007 → T008 → T009 → T010 → T011.
T012-T014 after T010. T015-T019 after T001. T020-T026 after all implementation.
