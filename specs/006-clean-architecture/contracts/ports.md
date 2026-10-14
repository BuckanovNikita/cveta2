# Application boundary contracts

| Port | Operations and ownership | Failure/ordering contract |
|---|---|---|
| CVAT API/session | Existing neutral API and context-managed task sessions; SDK adapter translates values/errors | Injected sessions are not closed by public API; owned sessions close deterministically |
| Task cache | get, put, invalidate, prune with explicit settings | Preserve recency; degradation warns; strict invalidation aborts before remote writes; disabled reads still permit local invalidation |
| Image storage | discover local images; resolve server mapping; upload/download/sync with typed outcomes | Preserve confinement, pinned mappings, existing-key logic and per-object failures |
| Dataset/conversion files | CSV read/write, dataset enumeration, image dimensions/materialization, temporary output lifecycle | Preserve Unicode, symlink containment, cleanup and schemas |
| Manifest store | load, save, list, delete | Atomic persistence and recovery ordering; no duplicate ambiguous creation |
| Publisher | Publish completed dataset with resolved settings | Optional absence/failure remains nonfatal and reported |
| Execution | Run typed work with explicit worker limit/catch behavior | Return input order, propagate designated failures, cancel queued work and join active work |

Ports live in `application.ports`; shared neutral values may live in domain, application settings or results. Use narrow workflow-specific interfaces. Composition constructs adapters and resolved settings and injects them explicitly. Inner modules cannot construct production adapters, import public facades, discover configuration, read environment, prompt, or start threads/processes.

Public signatures, identities, CLI messages and exit codes remain compatible. Facades adapt defaults but contain no business policy. Unsupported `_client`, `_client_ops`, `services`, `_clearml` and `commands` imports are removed after migration.

Executable checks cover positive fixtures and rejected direct/transitive/type-only/local imports, adapter peer dependencies, cycles, unclassified modules, facade imports and aliased effect calls. Inner imports succeed with SDKs blocked.
