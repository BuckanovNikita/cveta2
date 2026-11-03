# Implementation Plan: HTTPS docker.internal integration stands

**Feature**: `specs/005-docker-internal-stands` | **Date**: 2026-11-03 | **Spec**: [spec.md](spec.md)

**Process note**: The implementation preceded this plan in this change. The plan records the design of the inspected, already-implemented diff and the checks used to accept it; it does not claim to have guided the coding.

## Summary

Point the live-integration tooling at `https://<name>.k8s.docker.internal`, pass the k8s-infra helpers' CA bundle variables through to every run process by evaluating the helper `env` output (no hard-coded paths), and classify TLS handshake failures separately from unreachable stands in the gate, the stand/seed scripts and the live fixtures. A single standard-library helper, `tests/integration/stand_tls.py`, finds an `ssl.SSLError` in wrapped exception chains and formats the TLS message and remedy.

## Technical Context

**Language/Version**: Python >=3.12,<3.14 (uv); Bash for lifecycle scripts
**Primary Dependencies**: existing cvat-sdk, urllib3, boto3/botocore in integration tooling only; no new dependency
**Storage**: N/A
**Testing**: pytest (xdist, `tests.env_isolation`), offline fakes for helpers/curl/SDK; live tests behind `CVAT_INTEGRATION_HOST`
**Target Platform**: developer WSL machine with the shared docker-desktop stands
**Project Type**: CLI/library; this delta touches development tooling only
**Constraints**: no credential or machine-specific value stored in the repository; certificate verification is never disabled
**Scale/Scope**: 13 modified tracked files, 3 new test/tooling files, feature artifacts

## Constitution Check

PASS before and after design (recorded retroactively, see process note).

- I. Specify before implementation: **deviation, disclosed** — the implementation preceded spec/plan/tasks in this change; the artifacts describe the delta truthfully and no further behavior is added beyond the scoped boundary test (T009).
- II. Architecture and compatibility: runtime `cveta2` modules, public CLI/API/configuration/dataset contracts are untouched; the new helper stays outside the runtime package, enforced by a new scoped boundary test.
- III. Types and failures: specific exception types are caught at script/fixture boundaries (`OSError`, urllib3 `HTTPError`, `BotoCoreError`) and re-raised unchanged when not TLS; dynamic attribute access in `stand_tls.py` is limited to opaque third-party exception attributes and commented.
- IV. Verification: offline tests cover every changed path; full regression and static gates run; the live run is an explicit open item.
- V. Ownership/documentation/release: exact-path staging; Russian contributor guidance and English skill/artifacts updated; no credentials stored; release evaluation follows merge.

## Architecture

Impact class: `modules` (executable tooling and test infrastructure change). Record: [architecture.json](architecture.json).

| Module | Responsibility | Interface | Allowed dependencies | Forbidden | Effects |
| --- | --- | --- | --- | --- | --- |
| `tests/integration/stand_tls.py` (add) | Classify TLS trust failures in wrapped exception chains and render the message/remedy | `find_tls_error(exc) -> ssl.SSLError \| None`, `tls_failure_message(exc, url) -> str \| None`, `StandTlsError(RuntimeError)` (deliberately not `OSError`) | `ssl` only | any `cveta2` runtime module, SDKs (`cvat_sdk`, `urllib3`, `botocore`, `boto3`) | none (pure) |
| `tests/integration/` scripts and fixtures (modify) | Stand verification, seeding, live fixtures | Existing CLIs/exit codes; TLS failures raised as `StandError`/`SeedError`/`StandTlsError` with the TLS message; non-TLS errors re-raised unchanged | `stand_tls`, existing SDKs, `cveta2` public/adapter modules as before | — | network/SDK IO as before |
| `scripts/integration_env.sh`, `integration_gate.sh`, `integration_test.sh` (modify) | Evaluate helper env, gate preflight, run tests | `integration_curl_tls_failure <status>`, `INTEGRATION_TLS_REMEDY` array; exit codes unchanged | k8s-infra helpers, curl | storing credentials/CA paths | process/network as before |
| `cveta2` runtime (unchanged) | — | unchanged | — | importing `tests` or `scripts` tooling | unchanged |

Contracts: the existing import-linter contracts (`pyproject.toml`, root package `cveta2`), `scripts/check_architecture.py` and `tests/test_architecture.py` continue to enforce runtime layering and effect ownership; they do not cover `tests/` or `scripts/`. That boundary lacked enforcement, so a scoped contract `tests/test_integration_tool_boundaries.py` was added in this artifact pass: `stand_tls.py` imports only `ssl`, no runtime module imports `tests`/`scripts`, and parametrized negative fixtures prove forbidden imports (including function-local ones) are rejected.

Corp-skills portable usage skill: inspected `skills/cveta2` at local `/mnt/wsl/data/nkt/corp-skills` HEAD `670b0be`; it describes no stand URLs, integration tooling or TLS setup. No change required.

## Project Structure

```text
specs/005-docker-internal-stands/
├── spec.md, plan.md, tasks.md, architecture.json
├── checklists/requirements.md
└── evidence/{analysis.md, verification-2026-11-03.md}
scripts/integration_env.sh, integration_gate.sh, integration_test.sh
tests/integration/{stand_tls.py, conftest.py, cvat_stand.py, seed_cvat.py, test_e2e.py}
tests/{test_stand_tls.py, test_integration_tool_boundaries.py, test_cvat_stand.py, test_seed_cvat.py, test_integration_env.py, test_clearml_run.py}
CONTRIBUTING.md, .claude/skills/running-integration-tests/SKILL.md
```

## Validation

```bash
uv run ruff format --check . && uv run ruff check . && uv run mypy .
uv run lint-imports && uv run python scripts/check_architecture.py && uv run vulture
uv run pytest -q tests/test_integration_tool_boundaries.py tests/test_architecture.py
uv run pytest -q tests/test_stand_tls.py tests/test_cvat_stand.py tests/test_seed_cvat.py tests/test_integration_env.py tests/test_clearml_run.py
env -u CVAT_INTEGRATION_HOST uv run pytest -q -m "not integration"
uv run pytest tests/test_docs.py
```

Live: `running-integration-tests` skill lifecycle against the HTTPS stands with one owned tag and exact-tag cleanup. Completed results are in [live integration evidence](evidence/integration-2026-11-03.md).

## Documentation and release

`CONTRIBUTING.md` (Russian) and `.claude/skills/running-integration-tests/SKILL.md` describe the HTTPS names, CA variables and TLS troubleshooting. Baseline, `docs/`, README, architecture context and the corp-skills package need no change (no runtime/user-facing behavior). Commit with Conventional Commits through hooks; `main` changes only by merge, where semantic-release evaluates the version.

## Complexity Tracking

| Violation | Why needed | Simpler alternative rejected because |
| --- | --- | --- |
| Artifacts written after implementation | The code change was implemented and reviewed before Spec Kit artifacts existed | Reverting and re-implementing identical code adds no value; the deviation is disclosed instead |

## Release resumption — 2026-11-03

The user authorized dropping the local `docs/lossless-compress` branch and integrating
all other unfinished work, with intent clarification and independent review before
the final gated push. The clarified scope is this HTTPS tooling change plus the
instruction-migration receipt and ledger reconciliation; older branches already
contained in main need no merge. Local main already contains the two HTTPS commits
through fast-forward integration. No runtime, dependency or public interface changes
are planned during this resumption. Preserve the existing feature worktree.

Use T015 for release delivery and append T016 for documentation reconciliation,
parent verification and fresh independent review. The existing architecture record
still covers the implemented tooling and its executable boundaries. The companion
instruction receipt uses its existing documentation-only architecture record.
Release-only additions affect native Markdown records; inspect links, run documentation
tests and validate both records. Commit documentation on a task branch and merge into
main. Semantic-release evaluates the integrated candidate; no new tag is expected
for test/docs-only changes. Push main through every configured gate only after the
independent review passes, then verify remote refs and record the delivery outcome.
