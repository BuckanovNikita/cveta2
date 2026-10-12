# Feature Specification: Polygon bounding boxes

**Feature Branch**: `feat/polygon-bboxes`

**Created**: 2026-10-12

**Status**: Implemented and verified

**Input**: Convert standalone CVAT polygons to tight axis-aligned bounding
boxes in `fetch` and `fetch-task`, retaining contextual approximation warnings.

## User Scenarios & Testing

### User Story 1 - Export polygon annotations as boxes (Priority: P1)

A dataset user fetches tasks containing polygons and receives usable detection
annotations with the original annotation context.

**Why this priority**: Valid annotations are currently discarded.

**Independent Test**: Fetch a polygon-only frame through either fetch command
and inspect the resulting box row and warning.

**Acceptance Scenarios**:

1. **Given** triangle vertices `(12, 30.5), (90.75, 10.25), (40.5, 80)`,
   **When** fetched, **Then** its box is `(12, 10.25, 90.75, 80)` with zero
   rotation and a warning naming the task and annotation.
2. **Given** a concave polygon with unordered extrema, fractional coordinates,
   a repeated closing vertex, or vertices outside the image, **When** fetched,
   **Then** all vertices determine the bounds without rounding or clipping.
3. **Given** a polygon with labels, attributes, author, task/frame metadata and
   frame issues, **When** converted, **Then** that context is preserved.
4. **Given** a polygon on a deleted frame, **When** fetched, **Then** the
   existing deletion and partition precedence is preserved.

### User Story 2 - Diagnose rejected polygons (Priority: P2)

A dataset user can distinguish approximation from malformed input without
losing other valid shapes in the task.

**Why this priority**: Invalid geometry must not abort an otherwise useful fetch.

**Independent Test**: Fetch a task mixing valid and invalid polygons,
rectangles, and unsupported shapes; inspect output and warnings.

**Acceptance Scenarios**:

1. **Given** fewer than three coordinate pairs, an odd coordinate count,
   nonfinite coordinates, or zero-width/height bounds, **When** fetched,
   **Then** the polygon is skipped with a task/annotation/reason warning and
   a per-task skipped-polygon count summary.
2. **Given** rectangles, unsupported shapes and tracks beside polygons,
   **When** fetched, **Then** rectangle behavior and existing unsupported-shape
   and track handling remain unchanged; the track warning accurately names
   supported standalone shapes.

### User Story 3 - Refresh previously incomplete caches (Priority: P2)

A user with completed-task caches receives polygon boxes without manually
clearing local or shared caches.

**Why this priority**: Existing cached exports discarded these annotations.

**Independent Test**: Seed old local and S3 entries, fetch the task, and fetch
again from the refreshed cache.

**Acceptance Scenarios**:

1. **Given** an old local or S3 task cache, **When** fetched, **Then** the old
   entry is rejected and fresh output includes polygon boxes.
2. **Given** a refreshed cache, **When** fetched again, **Then** the same boxes
   survive; conversion warnings follow existing parsing-only logging behavior.

### Edge Cases

- Three coordinate pairs are sufficient when bounds have positive width and
  height; no additional topology or polygon-area validation is required.
- Missing-frame handling follows the existing extractor contract.
- A frame with only rejected shapes retains the existing unannotated-row behavior.
- Source rotation does not rotate polygon vertices or the resulting box.

## Requirements

### Functional Requirements

- **FR-001**: Both fetch paths MUST export each valid standalone polygon as an
  ordinary `instance_shape="box"` record using the minimum/maximum x/y of all
  vertices, preserving floating-point values without rounding or clipping.
- **FR-002**: Converted boxes MUST have zero rotation and preserve labels,
  attributes, annotation IDs, author, source, occlusion, z-order, task/frame
  metadata, and issues through the existing annotation mapping.
- **FR-003**: Each converted polygon MUST produce a warning identifying its
  task and annotation and explaining the bounding-box approximation.
- **FR-004**: Malformed polygons as enumerated in Story 2 MUST be skipped with
  contextual warnings and a per-task skipped-count summary.
- **FR-005**: Rectangles, tracks, other unsupported shapes, deletion precedence,
  and unannotated-frame handling MUST retain their current behavior.
- **FR-006**: Previously cached local and S3 task exports MUST be rejected;
  refreshed caches MUST retain polygon boxes, with existing cache-hit logging.
- **FR-007**: Public API signatures, CLI flags, CSV columns, and dependencies
  MUST remain unchanged. Russian user documentation, the architecture reference,
  and the dataset contract MUST describe the new behavior.

### Key Entities

- **Standalone polygon**: CVAT annotation with a coordinate sequence and the
  existing annotation identity and metadata.
- **Bounding box**: Detection record describing the polygon's axis-aligned
  envelope, retaining its context.
- **Task cache**: Local/shared stored task output whose generation determines
  whether it includes polygon annotations.

## Success Criteria

### Measurable Outcomes

- **SC-001**: Every valid polygon in the acceptance cases yields one box with
  exactly the expected bounds through both fetch paths.
- **SC-002**: Every malformed case yields a diagnostic and contributes exactly
  once to the skipped-polygon count, without losing valid neighboring shapes.
- **SC-003**: Old local and S3 exports refresh automatically, and subsequent
  cached exports retain identical polygon boxes.
- **SC-004**: Existing rectangle, deletion, conversion, API, and CSV contracts
  remain valid under the affected regression suites and repository gates.

## Assumptions

- Only standalone polygons are in scope; tracks and segmentation export are not.
- Warnings occur while parsing shapes; cache hits do not replay them.
- No new geometry dependency or validity rules beyond the listed checks are needed.

## Clarifications

### Session 2026-10-12

The supplied implementation plan settles geometry, metadata, malformed inputs,
warnings, cache invalidation, compatibility, and delivery. The clarification
scan found no material ambiguity requiring a question. All scope, data,
interaction, reliability, integration, edge-case, constraint, terminology and
completion categories are clear; no new performance or security contract is
introduced.
