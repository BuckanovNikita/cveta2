# Data and lifecycle contracts

Existing Pydantic annotation models, DataFrame columns and serialization remain unchanged. Canonical ownership moves to domain; public imports retain object identity.

Neutral CVAT records and API protocols belong to application contracts. SDK models never cross these contracts. Storage identity (`CloudStorageInfo`), transfer outcomes and upload intent are neutral values. Resolved settings carry explicit values without loading methods.

Cached task envelopes retain schema, task recency and storage keys. Upload manifests retain schema version 3, identity/fingerprint, pinned mapping, task ID, creation-pending and completion counters. Persist intent before creation; record recoverable progress; do not repeat ambiguous creation; remove completed manifests only after completion. Promotion invalidates strictly before the first remote annotation update.

Dataset partitions retain task-ID recency and deletion-first same-task ties. File adapters preserve CSV encoding, columns and paths; conversion preserves confidence, polygons, image materialization and cleanup. See the unchanged [dataset contract](../001-project-documentation/contracts/dataset-format.md).
