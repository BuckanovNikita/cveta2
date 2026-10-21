# cveta2 Constitution

## Core Principles

### I. Specify behavior before implementation

Every behavior change, including a bug fix, MUST have a current `spec.md`,
`plan.md`, and `tasks.md` under `specs/` before implementation. Spec Kit is the
primary development workflow. Requirements MUST describe the intended outcome,
compatibility boundaries, and verifiable acceptance criteria. Existing code and
documentation are evidence for planning, not an inferred specification of the
entire application. The current consolidated product contract is
[specs/baseline.md](../../specs/baseline.md). An explicitly authorized consolidation
MUST retain current requirements, deliberate limitations and outstanding obligations,
with immutable decision sources and a verified reachable checkpoint before retiring
historical records. Archived specifications are evidence, not competing contracts.
Subsequent behavior changes MUST use a new or active feature's spec, plan and tasks,
describe their delta from the baseline and reconcile the baseline on acceptance.
Completed feature history MUST remain recoverable rather than being rewritten.

### II. Preserve architecture and compatibility

Changes MUST follow the import-linter contracts in `pyproject.toml` and the
flows in [architecture.md](architecture.md). CLI adapters remain thin;
orchestration belongs in application use cases, which never prompt or exit and
raise `Cveta2Error`. Domain and application depend only inward and receive
external effects through application-owned ports. Composition constructs outgoing
adapters; incoming interfaces map CLI/API calls. Public facades must not become
dependencies of canonical modules. Public API functions remain prompt-free. All
`cvat_sdk` imports stay inside `adapters/cvat/`.
Before implementation, the shared module-architecture-planning skill MUST record
module responsibilities, interfaces, dependencies, effect ownership and executable
contracts in the native plan and adjacent architecture record, with checks in tasks.
Validate its planning phase before implementation and acceptance phase after diff
reconciliation, checks and applicable review. Documentation-only work MUST record
inspected no-impact reasoning and scoped documentation checks. Resumed gaps MUST
be appended without rewriting completed history; inactive records need no retrofit.
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
and stage only task-owned paths when a commit is authorized. Do not automatically
stash, reset, revert, or bypass hooks. Shared integration resources MUST use the
existing lifecycle skills, one owned run tag, and exact-tag cleanup on success
and failure; leave other runs and durable resources intact. Do not store
credentials or machine-specific setup in tracked project artifacts.

Conversation MUST follow the user's requested language (English by default).
CLI output, README files, contributor documentation, and `docs/` human guides
remain Russian; task planning and evidence remain English. Agent instructions,
architecture and dataset-format documents,
Spec Kit artifacts, and skills remain English. CLI and API changes MUST update
their user documentation. Keep `AGENTS.md` as the shared discovery entry point
and `CLAUDE.md` as its symlink. Detailed operational rules live in
[engineering.md](engineering.md), architecture in
[architecture.md](architecture.md), and output contracts in
[the living dataset reference](../../specs/baseline.md).
Retain dated reviews as historical feature evidence, preserving dispositions
without treating old suggestions as a current work queue.
Use Conventional Commits when authorized; `main`
changes only by merge and semantic-release owns versions, tags, and changelog
updates. Never commit, push, publish, release, or change remotes without the
applicable user authorization.

## Project Constraints

cveta2 remains a Python >=3.12,<3.14 CVAT CLI and API using the existing `uv`, Ruff,
mypy, pytest, import-linter, and release configuration. Spec Kit is development
tooling, not an application dependency. Follow maintained configuration for
changing values; do not duplicate machine paths, credentials, capacities, or
stand setup in specifications. New workflow tooling MUST preserve the existing
quality gates and the commit, mutation, and integration skill contracts.

## Development Workflow and Quality Gates

For each new capability, use the Spec Kit sequence `specify` -> `clarify` ->
`plan` -> `checklist` -> `tasks` -> `analyze` -> `implement` -> `converge`.
Review each stage's artifacts. For an existing active feature, select its directory
and update the living spec before running the remaining stages. For a capability
consolidated into the baseline, create a feature describing only the intended delta.
Unresolved behavior ambiguities, constitution violations, incomplete quality
checklists, and blocking analysis findings MUST be resolved before implementation.
Supporting skills MUST NOT establish a competing spec/plan workflow. Discover the
governing process from explicit selection, instructions and active artifacts. The
shared python-project-workflow skill supplies Python and architecture evidence
within native stages; installed Spec Kit skills/templates remain unchanged.
Unavailable required shared skills or missing/failing documentation/architecture
checks MUST be reported as acceptance gaps; continue independent inspection
without inventing the missing contract or claiming acceptance.
Completion requests MUST progress automatically through authorized stages,
documentation, verification and release without separate stage prompts. Standing
user authorization satisfies project commit/push skill request gates after checks;
explicit stopping points and host Plan Mode/read-only limits take precedence.
Collaboration and checks MUST be proportionate; substantive changes require fresh
independent review after integration and verification, using the native final
review for Python and architecture acceptance. Small low-risk edits need no
manufactured parallel work or unrelated tests.

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

Version 1.2.0 expands principle II with explicit ports, inward dependencies and
effect ownership for the approved reorganization. Supported public behavior and
storage contracts remain unchanged.

Version 1.3.0 expands architecture planning/acceptance and lifecycle governance:
shared skills contribute evidence within native Spec Kit stages, authorized work
progresses without repeated stage/commit/push prompts, explicit stops override
automation, and review/check scope remains proportionate. Conversation language
follows the user while Russian human guides/CLI remain intact. This amendment
changes no application contract; inactive feature history is not rewritten.

Version 1.4.0 narrows the supported interpreter window to Python >=3.12,<3.14,
explicitly removing Python 3.10 and 3.11 support at the user's request.
Development remains on Python 3.12; application interfaces stay unchanged.

Version 1.5.0 expands contract maintenance with explicitly authorized, recoverable
history consolidation and one current baseline. New Spec Kit features describe
deltas from that baseline; application behavior, quality gates and installed
workflow tooling remain unchanged.

**Version**: 1.5.0 | **Ratified**: 2026-09-30 | **Last Amended**: 2026-10-21
