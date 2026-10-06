# Feature Specification: Dataset correctness

**Feature Branch**: `fix/review-bugs-20261004`
**Created**: 2026-10-04
**Status**: Specified
**Input**: Fix DATA-001 through DATA-007 and OPS-001/002.

## User Scenarios & Testing

### User Story 1 - Reliable dataset conversion and merge (Priority: P1)
Users merge deletion files and export datasets without losing literal image names or retaining stale output.
**Why this priority**: Corrupted dataset identity or stale bytes changes training data.
**Independent Test**: Convert and merge temporary datasets, inspect all output bytes and metadata.
**Acceptance Scenarios**:
1. Given NA-like names, deletion removes exactly those names.
2. Given missing or unsupported split values, export fails before modifying the destination.
3. Given repeated exports, changed bytes replace previous bytes; repeated COCO export removes only metadata-owned obsolete files and splits.

### User Story 2 - Contextual malformed input handling (Priority: P1)
Users receive contextual errors for malformed CSV/YAML and retain valid sibling YOLO rows.
**Why this priority**: Bad external data must be diagnosable without malformed boxes.
**Independent Test**: Import malformed fixtures and assert errors, warnings and surviving rows.
**Acceptance Scenarios**:
1. Given invalid CSV/YAML, a contextual domain error identifies the input; unexpected internal failures propagate.
2. Given invalid numeric YOLO lines, each is skipped with file:line warnings while valid rows remain.

### User Story 3 - Faithful helper operations (Priority: P2)
Users clone each task's images with frame correspondence and upload source class mappings without reassignment.
**Why this priority**: Helpers must preserve source semantics.
**Independent Test**: Fake CVAT boundary with distinct task images, sparse class IDs and empty projects.
**Acceptance Scenarios**:
1. Given different task frame counts/orders, each cloned task preserves its own sequence; an empty project succeeds.
2. Given sparse source class IDs, annotations retain names; malformed mappings and unknown IDs fail before remote writes.

### Edge Cases
Unsafe cleanup paths, symlink parents, corrupted ownership metadata, fractional/negative class IDs, nonfinite coordinates, confidence outside [0,1], unsupported split values mixed with valid splits.

## Requirements

### Functional Requirements
- **FR-001 / DATA-001**: Preserve literal NA-like deletion names in CSV and merge.
- **FR-002 / DATA-002**: Validate every exported row split as train/val/test before writes.
- **FR-003 / DATA-003**: Refresh existing destination image bytes on repeated exports.
- **FR-004 / DATA-004**: Replace COCO metadata-owned output, remove obsolete owned images/annotations/splits, preserve unrelated files; reject ambiguous/unsafe cleanup and validate inputs before destination modification.
- **FR-005 / DATA-005**: Translate expected CSV parse/decode/read failures to contextual domain errors while preserving unexpected exceptions.
- **FR-006 / DATA-006**: Translate malformed YAML syntax/types/class maps to contextual domain errors while preserving unexpected exceptions.
- **FR-007 / DATA-007**: Accept nonnegative integral class IDs; finite centers in [0,1], sizes in (0,1], and optional confidence in [0,1]. Skip malformed lines with file:line warnings and retain valid siblings. Existing extra-field detection compatibility remains, validating every numeric field.
- **FR-008 / OPS-001**: Clone task-specific image sets with explicit source frame correspondence, including empty projects.
- **FR-009 / OPS-002**: Preserve source ID-name mappings; reject malformed mappings/unknown IDs without reassignment or dropping.

### Key Entities
Dataset row, split, image bytes, COCO ownership manifest, YOLO class mapping, source task frame sequence.

## Success Criteria
### Measurable Outcomes
- **SC-001**: All nine finding IDs have regression coverage and dated evidence.
- **SC-002**: Repeated COCO export leaves zero obsolete owned files and zero deleted unrelated files.
- **SC-003**: Malformed lines produce zero malformed output boxes; valid siblings remain.

## Assumptions
Distinct images satisfy the existing unique-basename/stem contract. Missing images retain the existing warning contract. Atomic rollback after unexpected I/O failure is outside scope; input validation precedes writes. Helper SDK imports are existing dev-tool boundaries, unchanged.

## Clarifications
2026-10-04: Supplied requirements resolve behavior ambiguities; numeric domains above make YOLO validation explicit. COCO JSON metadata establishes legacy ownership; missing or corrupt metadata cannot authorize cleanup.

## Related Features
[CVAT write safety](../002-cvat-write-safety/spec.md), [storage interfaces](../004-storage-interfaces/spec.md).
