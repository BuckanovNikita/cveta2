# Issue tracker: Linear and GitHub PRs

Create every issue for this repository in Linear team `SIP`, project `cveta2`; what
Linear owns is stated in [AGENTS.md](../../AGENTS.md). Resolve an issue by its identifier
or URL. GitHub PRs in `BuckanovNikita/cveta2` own review and delivery. Link issues and PRs
both ways.

## Issues

Search for an existing issue before creating one, and start each new issue from the
[issue template](issue-template.md). An issue records the outcome, scope, compatibility
constraints, a plan where needed, acceptance criteria, selected verification with base and
tip SHAs, dependencies, ownership, authorized stopping points and evidence. Inspect
current source and configuration before relying on claims in older issues.

Use the team lifecycle states Backlog, Todo, In Progress, In Review, Done, Canceled and
Duplicate. Move an issue to In Review when implementation and required verification are
ready. Mark an implementation issue Done only after its changes reach `main` and
acceptance is satisfied or every missing gate is recorded as waived; a verification-only
issue completes on its recorded acceptance outcome.

Readiness labels are separate from state: see [triage labels](triage-labels.md). A ready
label never overrides a blocker.

## Dependencies

Record blocking relations explicitly. Start dependent implementation only when its
prerequisite is implemented and verified on the branch used as its base; merge order still
follows the dependency. A canceled prerequisite requires replanning or removing the
dependent work.

## Evidence

An issue's evidence, kept in the issue and its PR, covers source and environment
identities, commands, the checks actually run and their statuses, exclusions, reuse
reasons and remaining limitations. Waivers and reporting follow
[development procedures](../development.md#order-reuse-and-reporting).

## PR grouping and delivery

Default to one task branch and PR per cohesive feature, including several issues when
appropriate. Link every included issue, map its acceptance criteria to implementation and
evidence, and keep it open until the shared PR merges and its criteria are satisfied.
Draft PRs may hold incomplete work.

Push task branches to the existing SSH remote; merging follows the delivery rule in
[AGENTS.md](../../AGENTS.md). Each human merge into `main` releases automatically when its
commits call for a version ([releases](../development.md#releases)). Do not assume branch
protection, GitHub checks or Linear automation is installed.

Use stacked PRs when separate review units or dependency sequencing help delivery.
Record the grouping and merge order in Linear before implementation; the first PR targets
`main` and each descendant targets its parent branch. Record base and head SHAs, review
incremental diffs and verify the cumulative feature delta against `main`.

Humans merge stacks bottom-up. After each merge, retarget or restack the remaining task
branches, inspect the resulting diffs, reassess evidence and repeat affected verification
and independent review. Use `--force-with-lease` only to rewrite task-owned branches.

## Existing branches

Existing branches keep their owners: an issue does not authorize editing another task's
branch or claiming its acceptance. Keep implementation, prior successful checks and
missing evidence distinct, and never rewrite past records to make unverified work appear
complete.
