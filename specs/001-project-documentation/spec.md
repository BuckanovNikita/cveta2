# Feature Specification: Project documentation in Spec Kit

**Feature Branch**: `chore/adopt-spec-kit`
**Created**: 2026-09-30
**Status**: Completed
**Input**: Migrate all current non-human documentation to the Spec Kit workflow,
including the dataset-format reference explicitly requested by the user.

## Clarifications

### Session 2026-09-30

- Q: Does migration include the dataset-format reference as well as agent
  guidance, architecture context, and the historical bug review? → A: Also
  migrate DATASET_FORMAT.md. Keep user/contributor guides and changelog in place;
  retain executable skills as workflow tools.

## User Scenarios & Testing

### User Story 1 - Discover project rules through Spec Kit (Priority: P1)

An agent entering the repository finds one authoritative set of project rules
and architecture context before planning a change.

**Independent Test**: Follow the agent entry point to the constitution,
engineering guidance, and architecture context; all destinations exist.

**Acceptance Scenarios**:

1. **Given** either supported agent, **When** it reads its entry point, **Then**
   it reaches the same Spec Kit rules and applicable workflow tools.
2. **Given** existing operational constraints, **When** their source moves,
   **Then** ownership, verification, and release boundaries remain available.

### User Story 2 - Find technical contracts and evidence (Priority: P2)

A maintainer finds the current dataset contract and dated review evidence in
the Spec Kit artifacts, without treating historical findings as new work.

**Independent Test**: Compare the relocated contract and review to their source
content and follow their updated references from the user guides.

**Acceptance Scenarios**:

1. **Given** a dataset reader or source-package consumer, **When** documentation
   moves, **Then** the same complete format contract remains accessible.
2. **Given** the dated bug review, **When** it moves, **Then** dates, dispositions,
   suggested fixes, caveats, and historical check counts remain intact.

### Edge Cases

- Existing uncommitted adoption work and unrelated skills must survive.
- A fresh checkout has no active-feature pointer; explicit selection must work.
- Generated upstream templates and skill entry points must retain integrity.
- Historical review findings must not become unfinished implementation tasks.

## Requirements

### Functional Requirements

- **FR-001**: Agents MUST discover canonical Spec Kit rules through a minimal
  shared entry point, preserving Claude's symlink.
- **FR-002**: Existing portable engineering and architecture guidance MUST move
  without losing its constraints or documented behavior.
- **FR-003**: The dataset-format document MUST move as a complete living contract.
- **FR-004**: The bug review MUST move unchanged as dated historical evidence.
- **FR-005**: All live documentation references and source-package inclusion
  MUST target the new canonical locations; old standalone copies MUST retire.
- **FR-006**: Documentation checks MUST cover the new rules, contracts, and
  evidence, including language, links, and agent discovery.
- **FR-007**: User/contributor guides, release history, executable skills,
  application behavior, existing hooks, and unrelated changes MUST be preserved.
- **FR-008**: The migration MUST retain its specification, plan, tasks, quality
  checks, and dated verification evidence for continued Spec Kit development.

## Success Criteria

### Measurable Outcomes

- **SC-001**: All migrated documents have one canonical destination and no live
  reference targets a retired standalone file.
- **SC-002**: Every format-contract and historical-review source byte is retained.
- **SC-003**: Documentation checks pass and a built source package contains the
  relocated contract; both agent integrations remain healthy.
- **SC-004**: No application behavior, credentials, unrelated skills, hooks,
  application version, commit, or remote changes result from the migration.

## Assumptions

- This is a documentation migration, not a new application capability or a
  retrospective audit of all application behavior.
- Host-specific infrastructure procedures remain in the existing global skill;
  portable project requirements and links to workflow tools remain in the repo.
- The existing adoption branch and its uncommitted changes remain the workspace.
