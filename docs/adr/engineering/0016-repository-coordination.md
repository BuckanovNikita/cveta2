# Track work in Linear and make concurrent sessions visible

## Tracking work

In team SIP and project cveta2, readiness maps to a Linear status. Todo means agent-ready, Triage handles unresolved reports, and a human-ready item also carries its designated label. Use native relations for blockers and parent issues. The issue identifier at the end of a PR title associates the merge with the issue. [Tracker conventions](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/docs/agents/issue-tracker.md) · [Triage mapping](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/docs/agents/triage-labels.md)

## Concurrent sessions

The session-start script reports the current branch against local main, pending changes, other worktrees, unmerged branches and a kept live session. This identifies concurrent work before staging files or stopping the stand. Hook installation is machine-specific. [Status script](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/scripts/session_status.sh)

## Domain decisions

Use the project vocabulary and flag a proposed change that conflicts with a recorded decision. The original rationale for the tracker status mapping is unknown. [Domain documentation guide](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/docs/agents/domain.md)
