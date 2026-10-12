# Research: Polygon bounding boxes

## Observed failure — 2026-10-12

On base `3533315`, `_collect_shapes` with vertices `(12, 30.5),
(90.75, 10.25), (40.5, 80)` emits the unsupported-polygon warning and returns
zero annotations. Expected bounds are `(12, 10.25, 90.75, 80)`.
Baseline extractor, SDK adapter and task-cache suites: 120 passed.

## Decisions

- **Geometry**: Use min/max of alternating x/y coordinates. This covers triangles,
  concavity, arbitrary extrema ordering, repeated closing vertices and outside
  coordinates without a geometry dependency. Reject rotated boxes, clipping and
  rounding because the supplied contract explicitly requires axis-aligned bounds.
- **Validation**: Reject fewer than six values, odd length, any nonfinite value,
  and non-positive width/height before constructing a box. Topology and signed
  area checks would introduce unrequested validity rules.
- **Mapping**: Share the existing BBoxAnnotation construction, overriding only
  geometry and polygon rotation. This preserves metadata and downstream consumers.
- **Warnings**: Approximation warning per converted polygon; malformed warning
  with task/annotation/reason and a per-task skip total. Preserve existing
  unsupported-shape behavior and correct the track support description.
- **Cache**: Increment the envelope generation from 4 to 5. Existing validation
  rejects either storage layer; a new fetch replaces stale output. Reusing version
  4 could silently retain discarded polygons even with correct extraction.
- **Scope**: Keep existing fetch/partition/conversion modules intact and prove the
  shared behavior through service-level tests. No external research is required;
  repository code and the approved contract determine the design.
