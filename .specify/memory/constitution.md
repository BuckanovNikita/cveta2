# cveta2 Constitution

## Core Principles

### I. Specify behavior before implementation

Every new or changed capability MUST have a current `spec.md`, `plan.md`, and
`tasks.md` under `specs/` before implementation. Spec Kit is the primary
development workflow for features. A bug fix or refactor that changes no
capability contract MAY instead use a plain `docs/plans/<task>/plan.md` (or,
when small, only its commit) that records the failing observation, the
reproduction when feasible and the verification of the original failure path. Requirements MUST describe the intended outcome,
compatibility boundaries, and verifiable acceptance criteria. Existing code and
documentation are evidence for planning, not an inferred specification of the
entire application. The current consolidated product contract is
[specs/baseline.md](../../specs/baseline.md). An explicitly authorized consolidation
MUST retain current requirements, deliberate limitations and outstanding obligations,
with immutable decision sources and a verified reachable checkpoint before retiring
historical records. The 2026-11-08 consolidation's checkpoint is the pre-reset commit
`f52c857`; read retired records with `git show f52c857:<path>`. Archived specifications
are evidence, not competing contracts.
Subsequent capability changes MUST use a new or active feature's spec, plan and tasks,
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

Plans and task lists MUST identify applicable development verification, live
acceptance and review. Bug fixes MUST record the failing observation, reproduce
it when feasible, and verify the original failure path; distinguish hypotheses
from performed checks. Tests MUST exercise product behavior, not third-party
tooling or presentation details. Extend existing test modules where practical.

Task owns sequential executable verification; prek owns Git hooks and message
validation. Automatic safe fixes MUST be explicit before staging. Commits MUST
verify fully staged repository inputs, rejecting unstaged tracked and nonignored
untracked files before prek. Direct verification describes the working copy.
Each required command runs once per verification run. Tool-native incremental
checks and affected-unit selection are permitted with conservative invalidation
for inputs they cannot track; Task freshness is not completion evidence.
Interrupted and failed commands establish no successful completion.

Development verification MUST pass on final committed content with verification
skips cleared. Successful applicable checks are reused while their inputs remain
unchanged; do not repeat an equivalent full gate merely to change stages.
Intermediate task commits may explicitly defer the verification hook while
preserving message validation; final completion remains required.

Acceptance MUST run on a clean branch tip: static checks, packaging, randomized
property exploration and full-suite coverage including live tests, without a
preceding duplicate affected-unit stage. Mutation reporting remains required for
code changes; survivors are advisory, but tool errors are unresolved. Mutation,
properties, availability, live acceptance and release operations are never cached.

Live verification MUST begin with bounded read-only preflight. Temporary outage,
timeout or capacity WAIT means deferred verification, not success; configuration,
credentials, TLS and authorization errors are failures requiring diagnosis.
Continue independent local work, retry at a meaningful milestone or after restored
availability, and stop for the user's decision when only blocked verification
remains. Deferred checks block acceptance, merge and release. Explicit operator
waiting remains available. Preserve pytest isolation, live serial execution,
exact-tag cleanup and an honest report of leftovers.

### V. Preserve ownership, documentation, and release controls

Agents MUST inspect status and diffs before editing, preserve unrelated work,
and stage only task-owned paths when a commit is authorized. Do not automatically
stash, reset, revert, or disable all hooks. An explicitly deferred intermediate verification hook is allowed. The standing
release exception requires the explicit release-check task for the version,
changelog and lockfile-only commit, as defined in engineering guidance. Shared integration resources MUST use the
existing lifecycle skills, one owned run tag, and exact-tag cleanup on success
and failure; leave other runs and durable resources intact. Do not store
credentials or machine-specific setup in tracked project artifacts.

Conversation MUST follow the user's requested language (English by default).
CLI output, README files, contributor documentation, and `docs/` human guides
remain Russian; task planning and evidence remain English. Agent instructions,
architecture and dataset-format documents,
Spec Kit artifacts, and skills remain English. CLI and API changes MUST update
their user documentation. Keep `AGENTS.md` as the shared discovery entry point
and `CLAUDE.md` as a regular file importing it with `@AGENTS.md`. Detailed operational rules live in
[engineering.md](engineering.md), architecture in
[architecture.md](architecture.md), and output contracts in
[the living dataset reference](../../docs/dataset-contract.md).
Retain dated reviews as historical feature evidence, preserving dispositions
without treating old suggestions as a current work queue.
Use Conventional Commits when authorized; `main`
changes only by a fast-forward merge of a branch whose tip passed the full
suite, one release at a time, and semantic-release owns versions, tags, and
changelog updates. Local task-owned commits may be autonomous. Pushes require
separate authorization; existing session authorization remains valid within scope.
Publication, releases and remote changes require their applicable authorization.

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
governing process from explicit selection, instructions and active artifacts.
Installed Spec Kit skills/templates remain unchanged.
Required executable behavior checks MUST pass before claiming acceptance.
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
use the existing lightweight checks without feature artifacts; bug fixes and
refactors may use the plain-plan path of principle I. Enforcement is
through repository guidance, not a new CI or hook gate.

Active feature selection is local checkout state, independent of Git branches.
Before writing artifacts, confirm the selected feature directory. Spec Kit's
bundled four-step workflow does not replace this repository's full sequence.

## Governance

This constitution governs Spec Kit planning and analysis within applicable
user instructions. `AGENTS.md` delegates to Spec Kit memory and contracts;
`README.md`, project skills and maintained tool configuration supply implementation
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

Version 1.5.1 clarifies cross-host instruction discovery: a regular Claude import
adapter replaces the symlink so the same shared policy works in regular-file
checkouts. Project workflow, review gates and application contracts are unchanged.

Version 2.0.0 redefines the mutation principle and the gate placement at the
user's request. The zero-survivor ratchet and its equivalent-mutant allowlist are
removed; mutation testing runs on each commit's changed functions in an isolated
workspace and reports survivors without blocking. All quality gates, including
the live integration gate, run at the pre-commit stage; no pre-push stage exists.
Application contracts are unchanged; inactive feature history is not rewritten.

Version 2.0.1 clarifies verification for documentation-only work at the user's
request: the documentation test module is removed, and heavy commit hooks run
only for code and dependency paths. Hooks run through prek. Gate placement and
application contracts are unchanged.

Version 2.1.0 amends principles I, IV and V at the user's request (development
speed plan, `docs/plans/dev-speed-20261106/` at `f52c857`). Spec Kit is required for new or
changed capabilities only; bug fixes and refactors may use a plain plan. Live
tests join the normal suite and a stopped stand is waited for; the commit test
hook runs affected tests, and the full suite with coverage gates the merge.
Mutation testing gains a per-commit budget, and tests must observe behavior
rather than pin defaults or wording for mutants. `main` advances by fast-forward
merge, one release at a time, and the release commit skips the heavy hooks its
already-checked tree does not need. Application contracts are unchanged.

Version 3.0.0 separates routine commit verification from infrastructure-dependent
and advisory expensive checks at the user's request. The default pipeline runs
unit checks; live integration and changed-function mutation are explicit manual
stages. Full-suite coverage before merge and mutation reporting for code changes
remain acceptance requirements. Application behavior and test fixtures are unchanged.

Version 3.0.1 clarifies principle I by naming the reachable checkpoint of the
2026-11-08 specification consolidation and points output contracts at the dataset
contract. Principles and application contracts are unchanged.

Version 3.1.0 permits targeted verification skips for intermediate task commits,
with full default verification after the final commit and separate mechanical
fix commits. Message validation and release acceptance remain required.

Version 3.2.0 removes the lockfile co-staging policy at the user's request.
Intentional lockfile-only dependency updates require no hook skip; lockfile
freshness remains checked. Application contracts are unchanged.

Version 4.0.0 replaces repeated hook pipelines with Task orchestration, explicit
safe fixes and fully staged commit inputs. Tool-native incremental checks remain,
while Task freshness is excluded as completion evidence. Bounded infrastructure
preflight and explicit deferral replace indefinite default waiting; acceptance,
cleanup, independent review and release controls remain required. This amendment
implements the user-approved verification migration and changes no product contract.

**Version**: 4.0.0 | **Ratified**: 2026-09-30 | **Last Amended**: 2026-11-09
