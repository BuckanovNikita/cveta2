# Backlog migration evidence — 2026-11-17

This is a dated source-to-Linear mapping, not an active status ledger. Subsequent
requirements, discussion and status belong in Linear. The migration is part of
SIP-66; the project is cveta2 under team SIP. Existing branch/worktree owners
retain their work. No human or agent assignee was inferred.

## Sources and preservation

- Reviewed main: `63cd25522f29c566a25840a944f6486e7d3451ed`.
- Expanded review and remediation plan: `af7c8c1842d27088869ff50086e4106a125c61d1`,
  `docs/plans/code-review-20261117/review.md` and `plan.md`, retained on the
  existing integration branch. The parent issue contains the complete original
  plan; batch/decision issues contain verbatim relevant finding sections and
  ownership rows or explicit finding IDs.
- Carried review: untracked `docs/plans/code-review-20261115/review.md` in the
  original checkout, SHA-256
  `e05e3abc504da97e0bf15474e07d505b283e7d36ad5bc7acbbab3af1a16f7117`.
  Its R01–R09 finding sections were copied into the corresponding Linear issues;
  the original file was neither staged nor changed.
- Feature evidence: `specs/001-task-verification/evidence.md` and
  `specs/002-own-test-infra/{tasks,evidence}.md` at reviewed main. Relevant
  original evidence excerpts are included in SIP-90 and SIP-91.
- Quoted source directions to use Spec Kit or local release integration are
  historical context. The approved workflow migration governs subsequent work.

Initial duplicate discovery found only SIP-66 and SIP-67. The migration created
24 records: one review integration parent, eight batch children, twelve held
decisions, one README integration issue and two historical evidence follow-ups.

## Mapping

| Source identity / branch | Linear | Findings or outcome |
| --- | --- | --- |
| review integration | [SIP-68](https://linear.app/sip-ds-team/issue/SIP-68/integrate-and-accept-the-2026-11-17-review-remediation) | Integrate and accept the 2026-11-17 review remediation |
| fix/cr-export | [SIP-69](https://linear.app/sip-ds-team/issue/SIP-69/review-remediation-export) | R02 N01 N09 N34 N18f |
| fix/cr-upload | [SIP-70](https://linear.app/sip-ds-team/issue/SIP-70/review-remediation-upload-and-s3) | R03 R06 R08 N05 N23 N25 N18g N18i N40 |
| fix/cr-cvat | [SIP-71](https://linear.app/sip-ds-team/issue/SIP-71/review-remediation-cvat-client) | N03 N19 N26 N27 N28 N18b N18c N42 |
| fix/cr-cache | [SIP-72](https://linear.app/sip-ds-team/issue/SIP-72/review-remediation-cache-and-fetch) | N06 N07 N18h |
| fix/cr-config | [SIP-73](https://linear.app/sip-ds-team/issue/SIP-73/review-remediation-configuration) | N02 N04 N11 N12 N13 R07 N31 N32 N33 N18d N18e N06 |
| fix/cr-bundle | [SIP-74](https://linear.app/sip-ds-team/issue/SIP-74/review-remediation-verification-and-bundle) | N08 N14 N35 N41 N18j |
| fix/cr-managed | [SIP-75](https://linear.app/sip-ds-team/issue/SIP-75/review-remediation-managed-datasets) | R04 R05 N15 N16 N37 |
| fix/cr-tooling | [SIP-76](https://linear.app/sip-ds-team/issue/SIP-76/review-remediation-tooling) | N17 N21 N22 R09 N38 N39 N43 N44 N45 N46 |
| R01 | [SIP-77](https://linear.app/sip-ds-team/issue/SIP-77/r01-decide-yolo-export-ownership-tracking) | R01: Decide YOLO export ownership tracking |
| N10 | [SIP-78](https://linear.app/sip-ds-team/issue/SIP-78/n10-decide-reject-versus-clip-for-out-of-bounds-boxes) | N10: Decide reject versus clip for out-of-bounds boxes |
| N20 | [SIP-79](https://linear.app/sip-ds-team/issue/SIP-79/n20-decide-exif-orientation-for-yolo-import) | N20: Decide EXIF orientation for YOLO import |
| N18a | [SIP-80](https://linear.app/sip-ds-team/issue/SIP-80/n18a-decide-the-public-s3-error-boundary) | N18a: Decide the public S3 error boundary |
| N24 | [SIP-81](https://linear.app/sip-ds-team/issue/SIP-81/n24-specify-an-uncertain-annotation-write-checkpoint) | N24: Specify an uncertain annotation-write checkpoint |
| N29 | [SIP-82](https://linear.app/sip-ds-team/issue/SIP-82/n29-validate-and-decide-annotation-cache-job-freshness) | N29: Validate and decide annotation-cache job freshness |
| N30 | [SIP-83](https://linear.app/sip-ds-team/issue/SIP-83/n30-decide-cvat-host-scoping-for-annotation-cache) | N30: Decide CVAT-host scoping for annotation cache |
| N36 | [SIP-84](https://linear.app/sip-ds-team/issue/SIP-84/n36-decide-supported-heic-and-heif-decoding) | N36: Decide supported HEIC and HEIF decoding |
| Q1 | [SIP-85](https://linear.app/sip-ds-team/issue/SIP-85/q1-decide-unfinished-task-deletion-precedence) | Q1: Decide unfinished-task deletion precedence |
| Q2 | [SIP-86](https://linear.app/sip-ds-team/issue/SIP-86/q2-decide-feedback-behavior-for-overlapping-jobs) | Q2: Decide feedback behavior for overlapping jobs |
| Q3 | [SIP-87](https://linear.app/sip-ds-team/issue/SIP-87/q3-decide-managed-class-change-approval) | Q3: Decide managed class-change approval |
| Q4 | [SIP-88](https://linear.app/sip-ds-team/issue/SIP-88/q4-define-semantically-relevant-managed-fingerprints) | Q4: Define semantically relevant managed fingerprints |
| docs/readme-rewrite | [SIP-89](https://linear.app/sip-ds-team/issue/SIP-89/integrate-revised-russian-readme) | Integrate revised Russian README |
| 001-T016-evidence | [SIP-90](https://linear.app/sip-ds-team/issue/SIP-90/recover-final-acceptance-evidence-after-the-task-dispatcher-correction) | Recover final acceptance evidence after the Task dispatcher correction |
| 002-T025-T026 | [SIP-91](https://linear.app/sip-ds-team/issue/SIP-91/complete-independent-review-and-obligation-reconciliation-for-session) | Complete independent review and obligation reconciliation for session-owned infrastructure |

## Observed branch tips

These are immutable observation identities, not acceptance claims. Branches may
advance independently after this inventory.

| Existing branch | Observed tip |
| --- | --- |
| `fix/cr-export` | `0e48400a1f7af264bb6e8109a5a5489d3fead0d4` |
| `fix/cr-upload` | `ecc2cf05e5fd5d49491b7c62f21250c28ee7c2f6` |
| `fix/cr-cvat` | `77a0790ee542d449be8b23ba070b0c4397ea9279` |
| `fix/cr-cache` | `2c9952d1fc4706427598581abf23a529da604ee5` |
| `fix/cr-config` | `2e7322b18470128aeb3bf25dc8862150307719ea` |
| `fix/cr-bundle` | `cf77819564b943743c7987cb17ca3c5504d82ccf` |
| `fix/cr-managed` | `c17444964508299aa4e1bba76a374a2770f5c47e` |
| `fix/cr-tooling` | `e0b4dc1d8d5221465a205244aac8091bb73d33b7` |
| `docs/readme-rewrite` | `f533cf61dc6fef0ac253a1017cf415c25c160890` |

## State and dependencies at migration

- SIP-68 and its eight children, plus SIP-89, were created In Progress because
  unmerged implementation commits exist. No issue was marked Done or In Review.
- SIP-68 is blocked by SIP-69 through SIP-76. Individual batch integration must
  reconcile shared files and cumulative verification before human PR merge.
- SIP-72 and SIP-73 are related for N06: configuration owns load-time validation;
  cache owns graceful degradation. SIP-69 and SIP-70 are related because export
  owns image lookup used by upload R03. These are coordination relationships,
  not invented hard execution blockers.
- SIP-77 through SIP-88 are Backlog with needs-triage and related to SIP-68.
  They are explicit policy decisions, not blanket blockers for direct fixes.
- SIP-90 and SIP-91 are Backlog with needs-triage. They track missing historical
  evidence/review, not unfinished implementation or failed live acceptance.
- Named assignees were left unset; existing session ownership was preserved.

## Evidence limits

This migration inspected source records and local commit history; it did not
rerun product reproductions, live services, mutation or acceptance for these
branches. Recorded branch commits establish activity, not passing verification.
The historical 002 acceptance at `739c964` remains historical evidence. New
verification/review must identify the inputs it actually checks.

Two Linear mutations transiently returned upstream-unavailable errors. Creation
was retried only after duplicate discovery; the relationship update was retried.
All intended issue creations and dependency updates then returned success.
