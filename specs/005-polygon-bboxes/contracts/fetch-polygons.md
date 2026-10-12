# Fetch polygon contract

`fetch` and `fetch-task`, including their API equivalents, use the existing
arguments and CSV schema. Standalone polygon annotations are exported as ordinary
boxes under [FR-001 through FR-007](../spec.md#functional-requirements).

Coordinates are raw axis-aligned vertex bounds with zero rotation. Warning output
identifies the task and annotation and explains approximation. Invalid polygons
are skipped with the reason and a per-task count. Cache hits do not replay parsing
warnings. Tracks and other unsupported shapes retain their previous behavior.

The shared output reference is the
[living dataset contract](../../001-project-documentation/contracts/dataset-format.md).
