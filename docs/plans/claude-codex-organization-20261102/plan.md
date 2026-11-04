# Claude and Codex instruction organization

## Approved outcome

Keep `AGENTS.md` authoritative and expose it to Claude through a regular
`CLAUDE.md` containing `@AGENTS.md`. Preserve the selected project workflow,
resource ownership, generated skills and all unrelated changes. Add only a
concise routing entrypoint where none exists. Global settings and export
reconciliation are owned by the coordinating task outside this repository.

## Architecture

[architecture.json](architecture.json) records inspected documentation-only impact.
No product modules, import boundaries or runtime effects change. The existing
documentation validation assertion is adjusted only where it requires the old
physical alias format. Existing architecture checks remain unchanged.

## Tasks and dependencies

- [x] Inspect instructions, workflow, tracked entrypoints and pre-existing changes.
- [x] Validate the architecture planning record before replacing entrypoints.
- [x] Standardize owned entrypoints and update active references to their format.
- [x] Run relevant documentation checks and inspect the exact task-owned diff.
- [x] Record dated results and validate architecture acceptance.
- [x] Coordinating parent obtains fresh independent review after verification.
- [x] Complete the authorized task-scoped commit and applicable release workflow. The [release follow-up](release-followup-2026-11-02.md) records the successful original publication; its receipt is included in the 2026-11-03 delivery reconciliation.

The entrypoint edits depend on the planning check. Parent integration and final
verification precede independent review. Other repositories are independent
workstreams with exclusive ownership; no child delegation is permitted.

## Acceptance

Root `AGENTS.md` and `CLAUDE.md` are regular files, the adapter imports exactly
the shared root file, relevant links resolve, and documented repository checks
pass. File inspection establishes structure only; actual fresh-session discovery
and cross-host settings verification are coordinated separately and must not be
claimed from byte checks. This task does not modify application behavior.

## Release verification follow-up (2026-11-02)

[The dated follow-up](release-followup-2026-11-02.md) records the exact-main
isolated verification after authorized infrastructure credential repair. The
TLS and live integration blocker is resolved, and exact-tag cleanup is proved.
The native full mutation gate now reports two unaccepted timeouts; publication
remains blocked. Product code and mutation policy are outside this follow-up.

- [x] Recheck original checkout/index and remote; preserve unrelated feature work.
- [x] Verify exact main in an isolated environment and run actual native push gates.
- [x] Prove owned resource cleanup and record the next failing gate accurately.
- [x] Complete publication after the authorized bounded mutant rerun and fully passing native gates.

The authorized single targeted mutant rerun killed both timeouts without policy
changes; the full native push retry then passed all gates, published reviewed
main and proved exact-tag cleanup. The receipt above preserves both attempts.
