# Research and decisions (2026-10-28)

- Inspected base `13ffec2` (v0.11.1). Existing small batches HEAD each key then GET;
  ordinary fetch writes `.tasks` then removes it; pruning lists project tasks a
  second time; path memoization happens after repeated confinement resolution.
  Decision: eliminate those effects while preserving existing fallback/order.
- CVAT SDK REST request dispatch uses `pool_manager.request`; configuration uses
  urllib3 Retry with status_forcelist 502/503/504. Default raise_on_status loses
  the final response after exhaustion. Decision: copy effective retry policy for
  each call, changing only raise_on_status. Reject mutating shared pool settings.
- Preserve constructor/bootstrap advisory version checks and injected-client
  operation. Capture at transport, not only outer port methods, so nested pages
  and issue comments retain actual endpoint and resource/query IDs.
- Planning handoff reports 202 focused baseline tests and local 503 reproduction;
  these are prior-agent evidence, not checks executed in this implementation turn.
- Neutral frozen diagnostic values avoid SDK leakage. Bounded, allowlisted context
  avoids credentials/cookies/raw HTML; exception causes remain available to callers.
- Existing ordered runner, per-request contexts, injected application clock/locks
  and architecture negative fixtures are reused instead of new concurrency stages.
