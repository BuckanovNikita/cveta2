# Promotion requirements checklist

**Purpose**: Review mutation, recovery and compatibility requirements.
**Created**: 2026-10-12
**Feature**: [Specification](../spec.md)
**Review Ownership**: Reviewer-owned; checked items approve requirements quality,
not implementation completion. Implement reads these markers without changing them.

## Completeness and clarity

- [x] CHK001 Are opt-in defaults, API/CLI surfaces and echo requirements explicit? [Clarity, Spec FR-001]
- [x] CHK002 Is whole-task eligibility defined for all job types and empty lists? [Completeness, Spec FR-002]
- [x] CHK003 Are allowed transitions and already-accepted no-ops unambiguous? [Clarity, Spec FR-003]
- [x] CHK004 Are promotion ordering and completed-only interaction specified? [Consistency, Spec FR-004]
- [x] CHK005 Are cache configuration, disabled S3 and partial failures covered? [Coverage, Spec FR-006]
- [x] CHK006 Are abort, retained writes and retry requirements consistent? [Coverage, Spec FR-007]
- [x] CHK007 Are unchanged CSV/deletion/order contracts and fetch-task scope explicit? [Consistency, Spec FR-001, FR-005]
- [x] CHK008 Are external editing assumptions and observable outcomes bounded? [Measurability, Spec Assumptions, SC-001–SC-004]

## Notes

The supplied plan authorizes implementation and workflow review. Review before
implementation; report unresolved criteria instead of treating them as passed.

2026-10-12 independent requirements review: all eight criteria pass. Spec,
plan and tasks agree on strict invalidation before mutation, fresh completed-only
selection, sequential per-task updates and the output barrier. No blocking
cross-artifact gaps found. Markers approve requirements quality only; behavior
still needs the planned unit, live and independent implementation verification.
