# Data model

SharedProjectConfig schema_version=1 has cvat identity, projects registry and datasets. ProjectDefinition holds stable id, optional display name, sync_root, ignored_prefix, task_cache_s3 and ignored task records. DatasetDefinition holds sources, clearml destination, api_url, s3_roots, empty_classes, splits and overlap decisions. SourceDefinition has name/type and either project registry key or s3 URI.

Personal schema_version=1 stores project_config reference plus existing auth/runtime/local-path sections; shared-owned legacy fields are rejected after migration.

SourceSnapshot holds source name/type, optional project_id, task metadata, label fingerprint, four CSV texts, optional S3 URI/hash/ETag/version. TaskSnapshot holds id, updated_date and completed state. ManagedSnapshot format_version=1 holds definition fingerprint, registry fingerprint, source snapshots, image split assignments, overlap memberships and parent id. YAML tables preserve lexical strings and source partitions; no image bytes or secrets.

ManagedPreparation format_version=2 binds definition, parent, source snapshot, transformed bytes, payload hashes, image hashes, validation report and feedback findings. Feedback findings identify source/task/frame and reason codes with a deterministic marker. Local delivery ledger is separate from immutable payload and stores acknowledged issue identities.
