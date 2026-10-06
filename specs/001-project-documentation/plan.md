# Implementation Plan: Project documentation in Spec Kit

**Date**: 2026-09-30 | **Spec**: [spec.md](spec.md)

## Summary

Move canonical engineering context into Spec Kit memory, retain the dataset
contract and historical review in this feature, and leave only agent discovery
instructions at the root. Preserve content, references, packaging, and existing
workflows without changing application behavior.

## Technical Context

Use existing Markdown documentation, repository-local Spec Kit 1.0.13,
pytest documentation checks, and Hatch source-package configuration. No new
application dependencies, migrations, services, or live infrastructure runs.

## Constitution Check

- I: Current spec, plan, and tasks track this migration; scope clarified by user.
- II: Architecture and dataset behavior are preserved, not redesigned.
- III: Only a docstring reference changes in application source; no new logging,
  configuration, error handling, or annotation conventions.
- IV: Run documentation tests, relevant static checks, integration manifest and
  prerequisite checks, and source-package content verification.
- V: Preserve unrelated work, canonical agent symlink, executable skills, hooks,
  application version, and authorization boundaries. Use global infrastructure
  procedures rather than copying machine paths into new tracked guidance.

Gate passed before implementation and after the completed migration;
see [dated verification](evidence/verification-2026-09-30.md).

## Project Structure and Ownership

| Content | Canonical destination |
|---|---|
| Agent discovery | Root AGENTS.md, with CLAUDE.md as its symlink |
| Project governance | .specify/memory/constitution.md |
| Operational engineering guidance | .specify/memory/engineering.md |
| Module map and data flows | .specify/memory/architecture.md |
| Dataset contract | contracts/dataset-format.md in this feature |
| Historical review | evidence/bug-review-2026-09-04.md in this feature |
| User and contributor guides | Existing README.md, CONTRIBUTING.md, docs/ and scripts/README.md |
| Executable workflows | Existing agent skill directories |

The current memory and dataset contract remain living sources across future
features. New behavioral work creates or updates the appropriate feature spec
and reconciles affected shared context/contracts. Dated review evidence stays
historical; it neither mandates fixes nor certifies the present codebase.

## Implementation Changes

- Relocate full source documents and portable engineering sections; remove the
  three retired standalone references after updating all consumers.
- Keep the global infrastructure skill authoritative for machine-specific
  registry paths, capacity, credential lookup, and lifecycle procedures.
- Update constitution references and increment its governance version to 1.1.0
  for expanded documentation ownership. Preserve its ratification date.
- Update human guide navigation, source-package allowlist, and the API docstring
  reference. Keep all dataset tables and historical dispositions unchanged.
- Extend documentation discovery to Spec Kit memory and feature artifacts;
  verify entry-point delegation and retired-source absence.

## Validation and Recovery

Run the checks in quickstart.md and record actual results in evidence/.
Validate source fidelity, existing skill hashes, symlink integrity, and no
unrelated changes. Fix broken references before completion. No commit or push.
File moves remain reversible through the working diff; do not reset user work.
