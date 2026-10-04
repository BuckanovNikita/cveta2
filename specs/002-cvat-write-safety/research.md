# Research

Baseline 875dca9 selects first duplicate name, silently filters missing box coordinates, fingerprints only frame/selected-label sets, accepts any positive shape count, leaks unlink OSError, and retries write 503 with Retry-After. Existing RawAnnotations, NewShape and TaskWriteSession metadata support exact reconciliation without shared type changes. Unknown task identity after create must stop for manual review instead of blindly creating again.
