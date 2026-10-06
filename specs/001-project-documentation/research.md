# Migration decisions

**Date**: 2026-09-30

- The user's scope includes AGENTS.md content, ARCHITECTURE.md,
  DATASET_FORMAT.md, and BUG_REVIEW.md. README.md, CONTRIBUTING.md, docs/,
  scripts/README.md, changelog, fixture readmes, and executable skills stay.
- Spec Kit memory holds shared project context. The dataset reference is a
  living contract in this feature's contracts directory. The bug review is
  historical evidence with its original date and dispositions, preserved
  unchanged rather than reinterpreted as current defects.
- Keep AGENTS.md as the discovery entry point because both agents need it;
  CLAUDE.md remains its symlink. Other workflow tools read the same memory.
- The dataset reference ships in the source distribution today, so relocation
  requires updating the Hatch include list and checking the built archive.
- Existing documentation tests only discover root/docs Markdown. Extend their
  maintained-document scope to Spec Kit memory and feature artifacts; exclude
  upstream templates with unresolved example links.
- Machine-specific procedures already have an authoritative global k8s-infra
  skill and project integration wrappers. Do not copy absolute machine paths
  into new memory documents; keep the project's owned-tag and cleanup contract.
- No behavior implementation, bug remediation, dependency change, live test,
  commit, push, release, or optional extension is part of this migration.
