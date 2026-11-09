# Design decisions

The user-approved plan resolves the design choices. Feasibility evidence belongs
in [the dated experiment record](../../docs/plans/task-verification-20261109/feasibility.md)
and must be observed before production hooks change.

- Use Task for sequential orchestration and prek for hooks/message validation.
  Avoid duplicate command definitions and repeated stages.
- Retain tool-native incremental state. Do not use Task freshness because interrupted
  commands and path changes are not a trustworthy success record.
- Remove the marker filter from affected-unit runs; exclude the integration directory.
  Namespace untracked inputs conservatively, falling back to full units if necessary.
- Keep mutation advisory and uncached; no completion receipts or shared result cache.
- Use bounded preflight and explicit deferral. Indefinite default waits block useful
  independent work; pretending unavailable tests passed would weaken acceptance.
- Preserve existing worktree hook behavior and rollback installation. Shared mutable
  verification state and a shared heavy-job lock are rejected.
