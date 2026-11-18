# Architecture

These rules govern code structure. Commands and verification procedures are in
[development procedures](development.md); product behavior is in the feature files under
`docs/feature/`, for example [fetch and partition](feature/fetch-and-partition.md).

## Layers

Source dependencies point inward:

```text
public facades → interfaces → composition → adapters → application → domain
                                         application: use_cases → client → ports → settings/results
```

- **Domain** (`cveta2/domain/`) owns pure policies and neutral values and depends only on
  domain. `cveta2/presets/` (the bundled `default.yaml`) sits on the same layer.
- **Application** owns typed ports and orchestration. Inside it, `use_cases/` depends on
  `client/` and `ports/`, and the neutral `settings.py` and `results.py` cannot depend on
  orchestration. Application receives resolved settings and effects explicitly; it never
  discovers configuration or creates adapters.
- **Adapters** (`cveta2/adapters/`) implement application-owned contracts and never import
  application orchestration (`application.client`, `application.use_cases`).
- **Composition** (`cveta2/composition/`) constructs and injects production dependencies;
  it may also depend directly on inner layers.
- **Interfaces** (`cveta2/interfaces/`) are the incoming adapters: the CLI, its commands
  and the public API.
- **Public facades** are the supported top-level modules (`api.py`, `cli.py`, `client.py`,
  `config.py`, `exceptions.py`, `models.py`, `dataset_partition.py`, `task_cache.py`,
  `image_downloader.py`, `image_uploader.py`, `s3_types.py`, `s3_utils.py`, `fs_utils.py`,
  `projects_cache.py`, `upload_manifest.py`, plus `__main__.py`). They keep supported
  imports, signatures and model and exception identities. `__init__.py` exposes public
  names lazily and `__main__.py` delegates to the CLI. Canonical packages never import a
  facade or the public root. Removed internal package paths are not compatibility promises.

Internal package siblings stay acyclic.

## Packages

- **`domain/`**: Pydantic annotation, project and task models; `Cveta2Error` and its
  public subclasses; partition, merge, conversion, baseline, output, path, cache,
  storage and upload policies; `verification/`, `bundle/` and `managed/` own the pure
  policies of explicit verification, reviewed publication and managed datasets;
  `class_registry.py` owns class-registry records and their fingerprint.
- **`application/ports/`**: application-owned typed contracts and neutral DTOs, including
  `CvatApiPort` and frozen raw CVAT dataclasses, cache, image, storage, dataset,
  conversion, workflow-file, manifest (`ManifestStore`), execution
  (`ConcurrentRunner`), verification, bundle and managed-dataset ports.
- **`application/settings.py`, `application/results.py`**: validated settings and neutral
  results, without configuration loading or environment discovery.
- **`application/client/`**: the SDK-free `ApplicationClient`, built from explicit ports:
  session lifecycle, project and task reads, per-task fetch pipelines and row assembly,
  shape extraction and mapping, job-cache decisions, task writes and upload mapping.
  `TaskWriteSession` memoizes one metadata read per task; `FetchContext` carries shared
  fetch state.
- **`application/use_cases/`**: prompt-free orchestration that raises `Cveta2Error`:
  fetch, upload (`upload/` with planning, staging, recovery and orchestration), convert,
  merge, whats-new, `ORG/PROJECT` resolution, task operations, verification, bundle
  preparation and the managed-dataset workflows.
- **`adapters/`**: outgoing effects, in independent groups:
  - `cvat/`: CVAT SDK client construction, requests, conversion of opaque SDK objects to
    DTOs and translation to `CvatApiError`; `transport.py` owns context-local timeouts
    and the read, non-idempotent-write and idempotent-write request policies.
  - `s3/`: boto3 construction, downloads, uploads, image sync, the shared annotation-cache
    mirror, transfer outcomes and credential diagnostics; `errors.py` supplies the
    CLI-only translation to `Cveta2Error` that `composition/runtime.py` hands to the CLI.
  - `config/`: YAML, environment and preset loading, project configuration selection and
    the projects cache.
  - `clearml/`: ClearML parent lookup, publication and storage access.
  - `class_api/`: public HTTP class-registry reads.
  - `files/` and `execution/`: shared local file effects (CSV and text IO, path
    confinement, materialization, image search, recovery records, bundle files) and
    thread fan-out with context-local `Workers` propagation and retry. Retry predicates
    stay beside the protected calls in the CVAT and S3 adapters.
- **`composition/`**: production dependency construction. `client.py` holds the
  supported `CvatClient` facade around `ApplicationClient`; the other modules resolve
  workflow settings and inject cache, storage, files, manifests, clocks, locks, runners,
  configuration, diagnostics and the verification, bundle and managed-dataset effects.
- **`interfaces/`**: `cli.py` (late-bound command registry, dispatch and the error and
  exit boundary); `commands/` (thin per-command adapters that own argument mapping,
  prompts and `sys.exit`; `_parsers.py` holds shared argument declarations,
  `_bootstrap.py` the `open_client()` single configuration load and credential prompt,
  `interactive/` the questionary pickers and wizards); `api/` and the dataset modules
  (prompt-free public API mapping; public symbols keep their original module identities
  for serialization and introspection).

Update this document when module responsibilities change.

## Effect ownership

- Domain and application may use lexical paths, in-memory pandas, Pydantic and Loguru.
- File and pandas IO, configuration and environment discovery, SDK and network IO,
  clocks, prompts and thread or process execution are external effects. They belong to
  adapters, composition or incoming interfaces as appropriate.
- Dependencies and resolved settings are passed explicitly; no global service locator
  supplies effects. Runners, clocks and locks are explicit application dependencies.
- Port protocols never import concrete implementations. Package initializers do not
  eagerly load infrastructure when inner contracts are imported.
- Incoming `interfaces/commands/` own prompts, argument mapping and `sys.exit`.
  Application workflows and the public API never prompt.
- `ConcurrentRunner` receives the ordered items, the work function, the worker limit and
  the caught exception types. Outcomes keep input order; caught per-item failures stay
  explicit outcomes; an uncaught failure cancels queued work and joins active work before
  propagating. Composition supplies the concrete runner and worker values; application
  never starts threads directly.
- `CvatClient(cfg=None, client_factory=None, *, api=None)` keeps lazy credential checks
  until it enters its owned session. Supplied APIs and sessions stay owned by the
  caller; owned sessions close deterministically. `ApplicationClient` receives resolved
  settings, image and execution ports and an optional session factory or API, without
  reading configuration or constructing production clients.
- `DatasetFiles` and `ConversionFiles` expose workflow operations; the file adapters
  behind them keep UTF-8 and newline handling, symlink containment, collision checks and
  cleanup. Domain owns coordinate, label and schema validation and output formatting;
  configured image search directories arrive as values. Upload checkpoints go through
  `ManifestStore`.

## Adapter independence

The CVAT, S3, config, ClearML and class-API adapter groups do not import each other; they
may use the shared `files` and `execution` adapters. Composition injects typed ports
between them. Each SDK has one owner:

| SDK | Only importer |
| --- | --- |
| `cvat_sdk` | `cveta2/adapters/cvat/` |
| `boto3`, `botocore` | `cveta2/adapters/s3/` |
| `clearml` | `cveta2/adapters/clearml/` |
| `questionary` | `cveta2/interfaces/commands/interactive/` |

## Code conventions

- Preserve the declared Python compatibility and the uv, Ruff, mypy, pytest and
  import-linter toolchain.
- Use explicit types; never add `from __future__ import annotations`.
- Use `loguru`, Pydantic configuration and models, and f-strings.
- Catch specific exceptions; Ruff `BLE001` rejects broad handlers and stays unsuppressed.
  Never swallow a failure silently: log a `warning` when the caller receives degraded or
  incomplete results.
- When a loop skips failed items, track and summarize the skipped items.
- Use dynamic attribute access only at opaque third-party SDK boundaries, and say why.

## Enforcement

The import contracts in `[tool.importlinter]` of [pyproject.toml](../pyproject.toml)
classify every runtime module exhaustively and enforce the inward layers, adapter
independence, the adapters' exclusion from orchestration, facade and public-root
exclusion, SDK and prompt ownership and sibling acyclicity, including local and
type-only imports. `tests/architecture_effects.py`, run by `tests/test_architecture.py`,
rejects effect imports and calls (aliases included) in inner layers. Negative fixtures
exercise forbidden dependencies and effects.

After changing boundaries, run:

```bash
uv run --locked lint-imports
uv run --locked pytest tests/test_architecture.py
```

Reuse the existing contracts. Where a boundary a change affects lacks enforcement, add
scoped coverage and a meaningful forbidden-dependency negative case. Architecture
acceptance reconciles the affected modules, the task-owned diff, the executed checks and
the independent review.
