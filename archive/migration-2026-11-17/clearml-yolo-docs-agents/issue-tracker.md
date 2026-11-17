# Issue tracker: Linear and GitHub PRs

Use Linear team `SIP`, project `clearml-yolo`, for active requirements, implementation
plans, acceptance criteria, dependencies, ownership, discussion and status. Resolve an
issue by its Linear identifier or URL. GitHub PRs in `BuckanovNikita/clearml-yolo` own
implementation review and delivery. Link issues, PRs and evidence in both directions.

## Planning and acceptance

Each issue records the outcome, scope, implementation plan where needed, blockers,
compatibility constraints, acceptance criteria and selected verification. Discover
current source and configuration before relying on historical claims. Transfer needed
requirements from archived sources into Linear with provenance; Spec Kit remains archived.

Use the team's lifecycle states: Backlog, Todo, In Progress, In Review, Done, Canceled,
and Duplicate. Readiness labels follow [triage guidance](triage-labels.md). A ready label
does not override dependencies. Start dependent implementation only when its prerequisite
is implemented and verified on the branch used as its base; merge dependencies remain.
Move to In Review when implementation and required verification are ready for review.

Record evidence with source/environment identities, actual checks and outcomes, exclusions,
reuse reasons and remaining limitations. Link dated repository evidence when needed.
Mark an issue Done only after its changes reach `master` and its acceptance criteria are
satisfied. Verification-only work completes on its recorded acceptance outcome.

## PR grouping and authorization

Default to one branch and PR for a cohesive feature, including multiple tickets when
appropriate. Link every included issue and map its acceptance criteria to implementation
and evidence. Keep those issues open until the shared PR merges and criteria are met.
Use stacked PRs when separate review units or dependency sequencing benefit delivery;
record the grouping in Linear before implementation. Routine grouping needs no approval.

Agents may push task branches and create PRs. Humans merge PRs. Use Conventional Commits,
the existing SSH remote, and task-owned branches; never deliver by merging locally into
`master` or pushing `master`. Explicit session restrictions take precedence. Code release
publication has separate authorization and remains suspended pending replacement tooling.

For stacks, the first PR targets `master`; descendants target their parent branches.
Link parent PRs and merge order. Review incremental diffs and verify the cumulative
feature delta against `master`, recording base/head SHAs. Draft PRs may contain incomplete
work; required deferred verification blocks merge readiness. Independent review follows
integrated verification for behavior, interface, dependency, security and policy changes.

Humans merge stacks bottom-up. Retarget or restack remaining branches after each merge,
inspect the resulting diffs, reassess evidence applicability, and repeat affected checks
and independent review. Use force-with-lease only for task-owned branch rewrites. A canceled
prerequisite requires replanning or removing dependent work, never silently bypassing it.
Do not assume GitHub checks, branch protection or Linear automation is configured.

## Migration and archive

Local `.scratch/*/issues/*.md` tickets are superseded by Linear. Reconcile their status
against acceptance evidence; migrate active work with requirements, relevant discussion
and blocking edges. Record the original path as migration identity, check for an existing
issue before creation, and maintain a dated mapping. Preserve completed historical tickets
and historical prerequisite context without inventing active blockers. Preserve original
files; stop updating their ticket status after migration. Archived Spec Kit artifacts are
read-only historical sources, never a parallel active tracker.
