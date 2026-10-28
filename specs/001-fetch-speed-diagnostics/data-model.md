# Data model

`CvatRequestDiagnostics` is a frozen neutral value in domain/errors.py: operation
and method strings; sanitized endpoint string; resource_ids and request_ids as
immutable tuples of name/value pairs; timezone-aware UTC timestamp; integer
status_code (0 if unavailable); bounded response_summary. No request/SDK object
or credential is retained. `CvatApiError.diagnostics` defaults to None and is
keyword-only; existing message/status_code/retry_after positional arguments remain.

`FetchContext` retains selected `tasks` and adds a complete unfiltered task-ID
snapshot or None when only a shortlist was retrieved. An empty complete snapshot
is distinct from absence. Cache pruning requires completeness. Snapshot lifetime
is one fetch after the promotion barrier; later deletion reconciles next run.

Fetch statistics distinguish cache hits, successful live results, skipped tasks
and results with incomplete issues. Degraded is a subset of successful results.
Wall duration uses injected clock; worker-duration sums are labelled separately.
No dataset schema or cache payload version changes.
