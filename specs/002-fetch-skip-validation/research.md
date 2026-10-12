# Research decisions

- Decision: Service preflight before normal fetch. Existing prepare_fetch lists
  tasks afresh, so no client or partition rewrite is needed. Filtering rows only
  would violate the required CVAT mutation and completed-only semantics.
- Decision: Full get_task_jobs response defines eligibility. Exported rows omit
  some job types/frame ranges and cannot prove whole-task completion.
- Decision: Invalidate configured local/S3 cache before writes with strict errors.
  Existing invalidate_local_entry loads default configuration; S3 delete normally
  swallows failure. Reusing either unchanged risks stale payloads on retry.
  Pre-invalidation avoids masking PATCH errors or leaving a fully accepted task
  with an old S3 entry after failed cleanup. Ordinary cache policy remains intact.
- Decision: Reuse run_concurrent with Workers.cvat and fail-fast error propagation.
  Its executor waits for active work; no fetch starts after any promotion failure.
  Per-job parallelism would complicate partial failure ordering unnecessarily.
- Decision: No transactional guarantee against other CVAT editors/cache writers.
  The existing port has no compare-and-swap job operation; requirements use the
  retrieved snapshot, with retained successful transitions and explicit retries.
