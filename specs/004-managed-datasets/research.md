# Research decisions

- Reuse existing four-table partition and training validation contracts; preserve per-source evidence so filtered rows never destroy incremental provenance.
- Keep exactly three payload files; extend tasks.yaml with source snapshots rather than introducing an archive.
- Opaque external scripts run outside cveta2; lineage is explicit and optional, never guessed.
- Hash decoded source bytes/image bytes in effect adapters; pure policies receive hashes and immutable snapshots.
- Separate shared-file selection from shared-value overrides. Two-file migration uses a journal/recoverable activation, not a false multi-file atomicity claim.
- Preserve existing API/SDK boundaries and provide typed ports, no new dependency framework.
