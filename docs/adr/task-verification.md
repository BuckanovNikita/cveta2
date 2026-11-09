# ADR: Task orchestration with tool-native incremental verification and explicit infrastructure deferral

Date: 2026-11-09. Decision: accepted design; rollout evidence belongs in
[the feature](../../specs/001-task-verification/plan.md).

## Context

Duplicated hooks and repeated stages run checks more than necessary. The old unit
hook combines testmon with marker filtering, which prevents affected selection.
Indefinite infrastructure waits stall independent work. Completion still needs
clear evidence, isolated worktrees and successful live acceptance.

## Decision

Task owns sequential commands; prek owns Git hooks and message validation. Use
explicit safe fixes before staging and one serial verification hook. A minimal
Git entry shim rejects unsuitable staged inputs before prek can hide them and
resolves each invoking worktree, retaining legacy behavior and rollback.

Keep Ruff/mypy incremental behavior and testmon Python dependency selection.
Namespace inputs outside testmon's tracking by interpreter, lock/configuration,
static assets and complete relative file membership. Use full units conservatively
where selection cannot reliably represent an input class. Every required static
command still runs once per verification invocation.

Do not use Task freshness as completion evidence. Interrupted commands and path
changes make native freshness an insufficient success record. No custom controller,
snapshot exporter, success-receipt database, shared result cache or CI is introduced.
Mutable tool state stays worktree-local; mutation, property exploration, availability,
live acceptance and release operations are never persistently cached.

Read-only bounded preflight returns AVAILABLE/0, UNAVAILABLE/3 or ERROR/1. Temporary
unavailability defers live verification while allowing independent local work.
Deferral is neither a passing test nor permission to merge or release. Preserve
exact-tag cleanup, clean-tip full-suite acceptance, independent review, fast-forward
integration, semantic-release ownership, the shared release lock and push authorization.

## Consequences

Repeated unchanged unit runs can avoid unaffected tests, but static checks still
execute. Record measured counts and timings rather than promise universal speedups.
Explicit stages and honest deferral make completion reviewable without unsafe
success caching. Contributors must stage complete inputs before commits and stop
concurrent editing during verification. Markdownlint remains separate.
