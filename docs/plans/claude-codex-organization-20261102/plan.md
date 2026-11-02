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
- [ ] Complete the authorized task-scoped commit and applicable release workflow.

The entrypoint edits depend on the planning check. Parent integration and final
verification precede independent review. Other repositories are independent
workstreams with exclusive ownership; no child delegation is permitted.

## Acceptance

Root `AGENTS.md` and `CLAUDE.md` are regular files, the adapter imports exactly
the shared root file, relevant links resolve, and documented repository checks
pass. File inspection establishes structure only; actual fresh-session discovery
and cross-host settings verification are coordinated separately and must not be
claimed from byte checks. This task does not modify application behavior.
