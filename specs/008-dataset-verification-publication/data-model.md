# Data model

ValidationOptions fixes profile-independent policy (IoU, media and path context).
Issue references zero-based input positions. ValidationResult carries clean rows,
original broken rows, issues, checked/skipped checks, original validity and cleanup
requirement. MediaInspection contains externally collected canonical paths, decoded
sizes/formats and positional failures; no domain record performs effects.

DatasetMetadata stores public api_url, canonical class names mapped to stable
prod_id (= API number), empty flags, aliases and independent local/S3 roots.
Class reconciliation preserves old aliases and empty decisions and rejects missing
previous identities or ambiguity. FetchTables holds all four immutable input tables.
TaskManifest contains sorted unique nonnegative included/obsolete task IDs.

PreparedRecord version 1 binds project/name, pinned parent ID/version, source/payload
SHA-256 hashes, preparation options and class decisions. A PreparedDataset result
points to the new local directory with validation, metadata and manifest. It is
uploadable only when every required validation and explicit decision succeeded.

Transitions: source -> validation report -> explicitly accepted preparation ->
local review -> full revalidation -> remote child -> uploaded -> finalized.
Any source/payload/prerequisite mismatch returns to source correction/preparation.
A child created before failure is reported by ID and is never described as finalized.
