# Implementation Plan: Python support window

## Technical context and clarification

cveta2 0.9.1 uses Hatchling, uv, Ruff, strict mypy, pytest and import-linter.
Inspected clean main checkout, metadata >=3.10, Ruff py310, mypy 3.11,
.python-version 3.12, hooks and current docs. No CI matrix exists.
The requested floor change is deliberate; no behavior redesign is needed.
Ruff retains its conservative py310 syntax/lint baseline: changing it to py312
produced unrelated modernization suggestions. Parent confirmed retaining the
baseline; interpreter metadata and mypy express the supported runtime minimum.

## Constitution Check

Spec precedes implementation. Existing inward import/effect contracts remain
mandatory. No new Python source or future annotations are introduced. Metadata,
locking, dual-interpreter regression/packaging and docs checks establish evidence.
The support-window constraint in the constitution is amended explicitly to reflect
the user-authorized compatibility change; historical feature evidence stays intact.
No release/version/changelog edits belong to this bounded implementation.
Post-design check: same constraints apply; no unresolved design decision.

## Architecture

[Architecture record](architecture.json) records the packaging/tool configuration
module and existing import/effect contracts. Dependencies/effect ownership stay in
current layers; metadata controls interpreter installation and analysis. No import
or runtime code changes are planned, so existing negative architecture tests suffice.
Validate planning record before editing configuration and reconcile the final diff.

## Workflow and ownership

Spec Kit specify/clarify/plan/checklist/tasks/analyze/implement/converge are handled
in order in this scoped feature. Existing source and completed history are preserved.
The bounded agent owns this repository; parent owns companion corp-skills edits,
post-integration independent review, acceptance and later commits/release.
Useful parallel work is parent-owned companion skill documentation; dual-version
checks use independent environments. Artifact/config edits are sequential.

## Documentation

Update README.md, CONTRIBUTING.md, AGENTS.md and current Spec Kit memory constraints.
Portable skill source inspected at corp-skills commit
755e9860cc8dd46431accd260890cc653a292326: skills/cveta2/references/usage.md
still requires Python 3.10 or newer. Parent must update it and applicable evaluation
cases, validate package Markdown/frontmatter/links/discovery, and record its commit.
Other skill commands/API and runtime/dataset documentation are unaffected.

## Verification and delivery

Run uv lock without upgrade; inspect removed branches and compare retained versions.
Run frozen offline pytest on Python 3.12/3.13, Ruff/mypy, import/effect checks,
documentation checks, build and isolated wheel CLI/import/metadata tests outside
checkout. Record actual dated results and limitations in verification-2026-10-15.md.
Parent runs native commit/push hooks and integrates by merge to main; semantic-release
owns version/changelog/tag, with no GitHub Releases or assets.
