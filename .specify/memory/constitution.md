# cveta2 Constitution

## Core Principles

### I. Specify behavior before implementation

Every behavior change, including a bug fix, MUST have a current `spec.md`,
`plan.md`, and `tasks.md` under `specs/` before implementation. Spec Kit is the
primary development workflow. Requirements MUST describe the intended outcome,
compatibility boundaries, and verifiable acceptance criteria. Existing code and
documentation are evidence for planning, not an inferred specification of the
entire application. Completed specifications MUST remain living contracts:
later changes reconcile the relevant spec, plan, and tasks together.

### II. Preserve architecture and compatibility

Changes MUST follow the import-linter contracts in `pyproject.toml` and the
flows in [architecture.md](architecture.md). CLI adapters remain thin;
orchestration belongs in
services, which never prompt or exit and raise `Cveta2Error`. Public API
functions remain prompt-free. All `cvat_sdk` imports stay inside `_client/`.
Public CLI, API, configuration, and dataset compatibility MUST be preserved
unless the specification explicitly requests and describes a contract change.
Fetch partitioning MUST preserve deletion precedence for same-task ties and
use `task_id`, not `task_updated_date`, for annotation recency.

### III. Use explicit types and report failures

Python tools MUST run through `uv run`, following the existing project
toolchain. New Python code MUST NOT introduce
`from __future__ import annotations`. Application logging uses `loguru` and
f-strings; configuration and validated models use Pydantic. CLI output follows
its existing contract. Catch specific exceptions at a boundary that can handle
them. Unexpected failures MUST be reported; degraded results require warnings,
and loops that skip failed items MUST summarize them. Do not suppress `BLE001`
or introduce broad application exception handlers. Dynamic attribute access is
limited to opaque third-party SDK boundaries with an explanatory comment.

### IV. Verify the changed behavior

Plans and task lists MUST include the repository checks appropriate to the
change, regardless of optional-test wording in upstream templates. Start with
the nearest meaningful tests and expand when shared behavior, interfaces, or
failures justify it. Bug fixes MUST capture the failing observation, reproduce
it when feasible, and verify the original failure path. When reproduction is
unavailable, distinguish hypotheses, static evidence, and performed checks.
Documentation-only work normally runs `uv run pytest tests/test_docs.py`.
Reported results MUST identify skipped or unavailable checks accurately.
Preserve test environment isolation and cleanup. Mutation scope remains a
ratchet with zero unexplained survivors; use the repository mutation skill for
scope changes or triage. Commits and pushes still require their configured
stage checks; Spec Kit does not replace them.

### V. Preserve ownership, documentation, and release controls

Agents MUST inspect status and diffs before editing, preserve unrelated work,
and stage only task-owned paths when a commit is requested. Do not automatically
stash, reset, revert, or bypass hooks. Shared integration resources MUST use the
existing lifecycle skills, one owned run tag, and exact-tag cleanup on success
and failure; leave other runs and durable resources intact. Do not store
credentials or machine-specific setup in tracked project artifacts.

User-facing messages, README files, contributor documentation, and `docs/`
remain Russian. Agent instructions, architecture and dataset-format documents,
Spec Kit artifacts, and skills remain English. CLI and API changes MUST update
their user documentation. Keep `AGENTS.md` as the shared discovery entry point
and `CLAUDE.md` as its symlink. Detailed operational rules live in
[engineering.md](engineering.md), architecture in
[architecture.md](architecture.md), and output contracts in
[the living dataset reference](../../specs/001-project-documentation/contracts/dataset-format.md).
Retain dated reviews as historical feature evidence, preserving dispositions
without treating old suggestions as a current work queue.
Use Conventional Commits when authorized; `main`
changes only by merge and semantic-release owns versions, tags, and changelog
updates. Never commit, push, publish, release, or change remotes without the
applicable user authorization.

## Project Constraints

cveta2 remains a Python 3.10+ CVAT CLI and API using the existing `uv`, Ruff,
mypy, pytest, import-linter, and release configuration. Spec Kit is development
tooling, not an application dependency. Follow maintained configuration for
changing values; do not duplicate machine paths, credentials, capacities, or
stand setup in specifications. New workflow tooling MUST preserve the existing
quality gates and the commit, mutation, and integration skill contracts.

## Development Workflow and Quality Gates

For each new capability, use the Spec Kit sequence `specify` -> `clarify` ->
`plan` -> `checklist` -> `tasks` -> `analyze` -> `implement` -> `converge`.
Review each stage's artifacts. For an existing capability, select its feature
directory and update the living spec before running the remaining stages.
Unresolved behavior ambiguities, constitution violations, incomplete quality
checklists, and blocking analysis findings MUST be resolved before implementation.
Supporting skills MUST NOT establish a competing spec/plan workflow.

The plan's Constitution Check MUST cover these principles before research and
again after design. Tasks MUST identify acceptance and relevant verification
work. Convergence MUST compare implementation with the current spec, plan, and
tasks; repeat implementation and convergence until no required work remains.
Keep dated verification evidence and limitations with the feature artifacts.
Documentation-only corrections and maintenance without behavior changes may
use the existing lightweight checks without feature artifacts. Enforcement is
through repository guidance, not a new CI or hook gate.

Active feature selection is local checkout state, independent of Git branches.
Before writing artifacts, confirm the selected feature directory. Spec Kit's
bundled four-step workflow does not replace this repository's full sequence.

## Governance

This constitution governs Spec Kit planning and analysis within applicable
user instructions. `AGENTS.md` delegates to Spec Kit memory and contracts;
`CONTRIBUTING.md` and maintained tool configuration supply implementation
evidence. Architecture and dataset contracts remain living shared references
across feature changes. Reviewers MUST check that the change, artifacts, and verification
agree with the constitution and with each other.

Amendments MUST state the changed principle and rationale, update the version
and amendment date, and reconcile affected guidance and active feature
artifacts. Use a MAJOR version for incompatible principle removals or
redefinitions, MINOR for new or expanded principles, and PATCH for
clarifications. The constitution version is independent of the application
and Specify CLI versions. Version 1.0.0 establishes the initial governance;
existing application behavior is not retroactively specified. Version 1.1.0
expands documentation ownership to migrated engineering context, architecture,
dataset contracts, and dated review evidence; it changes no application contract.

**Version**: 1.1.0 | **Ratified**: 2026-09-30 | **Last Amended**: 2026-09-30
