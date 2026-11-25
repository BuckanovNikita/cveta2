# Commands validate the current files; no hash lock

Up to 0.15, `verify --bundle` and `dataset prepare` recorded SHA-256 checksums of their output, and the publishing commands refused any directory whose files, configuration or class registry had changed since then. A user could not fix a single row by hand. Since 0.16, no command compares a local file, the configuration or the registry with a recorded checksum. Every command validates what is in the directory now against every content rule, and publishes only when no row is rejected.

A command stops only for two reasons:

- **wrong content**, for example a rejected row, a class without a bbox, or one image in two splits;
- **stale remote state**: a ClearML version newer than the one recorded at preparation, a CVAT task completed after the fetch, or a CVAT server other than the one fetched.

Every other difference in the sources only warns. Findings from a task that carries such a warning are skipped and counted.

## Considered options

- **Limited edits:** only the split, dropping images, `empty` flags and roots may change. Rejected: it needs more code, and a row still cannot be fixed by hand.
- **Re-seal:** edit freely, then run `verify` again to lock the bundle anew. Rejected: it adds one more command and keeps a lock that guards nothing the content rules don't already check.

## Consequences

The published dataset is whatever passes the rules at publication time, including edits made after preparation. To keep that safe, the rules themselves have to be complete: class coverage, one split per image and no rejected rows. A checksum would not catch a mistake the rules miss.
