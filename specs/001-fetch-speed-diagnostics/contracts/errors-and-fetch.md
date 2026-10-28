# Public compatibility contract

Existing `CvatApiError(message, status_code=0, retry_after=None)` calls and public
exception identities remain valid. Add keyword-only `diagnostics=None` with the
neutral `CvatRequestDiagnostics` exported by cveta2.exceptions. Retry hints and
causes survive. Fetch signatures, return values, CSV schema/order and worker
settings are unchanged. No report file or automatic server investigation is added.

Exhausted SDK 502/503/504 responses now reach the existing task-level 5xx policy:
warn/skip by default, raise in strict mode. Required-read exhausted 429 aborts.
Optional issue failures remain degraded results and are not cached as complete.
Russian messages identify actual operation/endpoint and available request IDs;
backend investigation for API failures, proxy/ingress/backend availability for
gateway failures, with component attribution stated as a hypothesis unless known.

Ordinary fetch never touches `.tasks`; `save_tasks=True` writes it. Full fetch
prunes from its complete post-promotion snapshot, never its filtered selection.
