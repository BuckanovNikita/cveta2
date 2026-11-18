# Linear requirements and GitHub delivery

Use Linear team `SIP`, project `cveta2`, and GitHub repository
`BuckanovNikita/cveta2`. Resolve records by identifier or URL and link issues, PRs
and evidence in both directions. The [contract index](contracts.md) locates current
product requirement documents. [Engineering policy](engineering.md) stays in Git.

## Authority and cutover

Linear project documents own the current product contract after the migration PR is
human-merged and its acceptance criteria are satisfied. Until then the new documents
are explicitly migration drafts; frozen repository originals retain historical
provenance and supply the migration comparison baseline. The approved migration itself
uses this workflow. Record the merged commit, review and contract activation in the
migration issue; activate all contract documents and reconcile issue status together.
Do not mark the migration complete merely because drafts or a PR exist.

Proposed requirements stay in issues until their implementation is merged and accepted.
Then update the relevant current contract and index with source commit links. Preserve
source mappings and conditions/limitations when transferring requirements. Repository
usage guides remain maintained explanations; superseded normative files are frozen
references, not another current requirement authority.

If Linear is unavailable, investigate and implement in isolation against an identified,
previously verified contract snapshot. Record snapshot identity and deferred updates;
defer requirement decisions and merge readiness until Linear can be reconciled. Never
silently substitute stale repository requirements for current Linear authority.

## Planning and acceptance

Issues record outcomes, scope, compatibility, implementation plans where needed,
acceptance criteria, selected verification, dependencies, ownership and stopping points.
Inspect current source and evidence before adopting historical claims. Use team lifecycle
states Backlog, Todo, In Progress, In Review, Done, Canceled and Duplicate, with separate
[readiness labels](triage-labels.md). A ready label never overrides a blocker.

Start dependent implementation only once its prerequisite is implemented and verified
on the branch used as the base; merge dependencies remain explicit. Record actual
checks, source/environment identities, exclusions, reuse reasons and limitations.
Report required checks as passed, failed, deferred, waived or error; only a user
waiver may remove a required gate, and it is never a passing result. A waiver is
either stated by the user or given by a human merge of a PR whose description lists
that gate as not run; record the latter as waived by merge. Until then the agent
reports such a PR as not merge-ready. Documentation-only changes need development
verification only, as [engineering policy](engineering.md#acceptance-and-deferral) defines.

Move to In Review when implementation and required verification are ready. Draft PRs may
contain incomplete work; required deferred verification blocks merge readiness. Mark
implementation issues Done only after changes reach `main` and acceptance is satisfied.
Verification-only tasks complete on their recorded acceptance outcome.

## Branches and PRs

Default to one task branch and PR per cohesive feature, including multiple issues when
appropriate. Link every issue and map acceptance criteria to implementation/evidence.
Keep included issues open until the shared PR merges and their criteria are satisfied.
Agents may push task branches using the existing SSH remote and create PRs. Humans
merge; agents must not merge locally into `main` or push `main`. Code release publication
remains suspended and separately authorized. Explicit session restrictions prevail.

Use stacked PRs when separate review units or dependency sequencing help delivery.
Record grouping and merge order in Linear before implementation; the first PR targets
`main`, descendants target their parent branches. Record base/head SHAs, review
incremental diffs, and verify the cumulative feature delta against `main`.

After humans merge bottom-up, retarget or restack remaining task branches, inspect the
diff, reassess evidence and repeat affected verification and independent review. Use
force-with-lease only for task-owned rewrites. A canceled prerequisite requires replanning
or removal of dependent work. Do not assume branch protection, GitHub checks or Linear
automation is installed. Follow engineering policy for commits, checks and review.

## Migrating existing work

Search for existing issues before creation. Reconcile outstanding tasks and findings
against implementation and dated evidence; unchecked historical tasks are not proof of
unfinished implementation. Preserve original paths/commits as migration identity and
maintain a dated mapping. Transfer actionable requirements, discussion and dependencies;
preserve completed history without inventing active blockers.

Existing branches retain their owners. Migration records do not authorize editing
another task's branch or claiming its acceptance. New delivery rules apply when those
branches are integrated. Track unresolved historical evidence in separate follow-ups;
keep implementation, prior successful checks and missing evidence distinct. Archived
Spec Kit artifacts remain unchanged and receive no further task-status updates.
