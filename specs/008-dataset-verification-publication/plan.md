# Implementation Plan: Dataset verification and reviewed publication

**Branch**: `feat/dataset-verification-publication` | **Date**: 2026-10-20
**Spec**: [spec.md](spec.md)

## Summary

Port the released ed-killer v0.6.0 validation policies into cveta2's existing
inward layers. Add explicit verification, preparation and later publication.
Retire automatic fetch publishing and its obsolete configuration. Preserve CVAT
upload and fetch partition semantics. No split generation or pipeline automation.

## Technical Context

Python >=3.12,<3.14; uv, hatchling, pandas/Pydantic/Pillow/PyYAML/loguru,
Pandera >=0.34.1,<0.35 for validation and optional ClearML S3 extra >=2.1.12,<3.
Local CSV/YAML/JSON snapshots; external class HTTP API and ClearML/S3 storage.
Existing Ruff ALL, strict mypy, pytest, import-linter and effect checker remain
mandatory. This is a single library/CLI package. Validation is in-memory and
media decoding is cached by canonical local file within a call. No new throughput
SLA or distributed service is introduced.

## Constitution Check

Pre-design: PASS. Explicit scope and breaking removals are specified; no unresolved
material decisions. Native Spec Kit artifacts govern implementation. Existing
inward layers and effect checks cover additions. Prompt-free application and API,
Russian human interfaces, typed errors and isolated tests are retained.

Post-design: PASS. Domain receives immutable inspection facts; files/media/network
stay behind ports. New adapter group is added to the exhaustive contract without
loosening any direction. Full verification, fresh independent review, portable
skill maintenance and Git-only release remain required acceptance work.

## Architecture and ownership

[architecture.json](architecture.json) records the boundary and acceptance index.

| Area | Responsibility and interface | Effect ownership |
| --- | --- | --- |
| domain/verification | Pure schema/geometry/quarantine; ValidationOptions, ValidationResult, Issue and inspection facts | None; no filesystem, clock, network or warning emission |
| application/use_cases/verify.py, ports/verification.py | Verify DataFrame/CSV using injected media/files; no prompts | Adapters via typed ports |
| adapters/files/verification.py, media.py | Strict lexical CSV, diagnostics, canonical path resolution and image decoding | Local reads/writes, warning/log rendering at boundary |
| domain/bundle | Class identity, task supersession, trainability and prepared-record types | None; consumes inspected facts |
| application/use_cases/dataset_bundle.py, ports/dataset_bundle.py | Prepare and revalidate then publish; structured missing decisions | Injected snapshot, root, API and store operations |
| adapters/files/bundle.py, bundle_paths.py | YAML validation, four source snapshots, content hashes, atomic new-directory write and stable payload staging | Files and local containment |
| adapters/class_api, adapters/clearml | Class API, exact latest parent, S3 root checks and exact-three-file finalization | HTTP and optional SDK, controlled exception translation |
| composition/verification.py, dataset_bundle.py | Construct services without executing operations at import time | Explicit adapter creation |
| interfaces + public facades | CLI flags/prompts/exit mapping and prompt-free APIs | User interaction only |
| legacy publication paths | Remove automatic fetch publisher, setup command and config surface | Fetch no longer has ClearML effects |

Use `MediaInspection` facts keyed by positional row, including canonical path,
decoded size/format and issues; core validation never calls filesystem resolution.
The verification adapter supplies facts even when image decoding is disabled so
identity handling stays deterministic. Bundle policy canonicalizes classes before
core geometry validation and uses the same facts for native format/minimum size.

Prepared storage persists versioned JSON, payload/source SHA-256 hashes, destination,
parent identity, options and metadata decisions. Upload reads a stable snapshot,
checks every hash, repeats policy/root/media/API/parent validation, compares derived
payload and task manifest, checks latest parent immediately before publication,
and sends only staged payload bytes. This protects ordinary accidental edits;
it is not an approval signature against an owner modifying both files and record.

## Workstreams and dependencies

1. Parent owns Spec Kit artifacts, dependency/contract configuration and integration.
2. Validator worker owns domain/verification, verification port/use case/adapters and
   its focused tests. Establish inspection-fact API before bundle policy integration.
3. Bundle policy/remote worker owns domain/bundle, ClearML/class API and root adapters
   plus focused tests; coordinates with validator worker on inspection facts.
4. Legacy worker owns only automatic-publisher removal and existing affected tests.
   Parent waits for its CLI/API/config edits before wiring new commands.
5. Parent owns prepared snapshot persistence, bundle application workflow, composition,
   new CLI/API, integration tests and docs. Workers do not commit or delegate.
6. After integration and parent checks, a fresh read-only independent review covers
   behavior, architecture, compatibility, cleanup and evidence. Resolve findings,
   converge, then follow authorized commit/merge/semantic-release/tag pushes.

## Documentation and portable usage skill

Update README, docs/cli.md, docs/configuration.md, docs/images-and-cache.md,
docs/python-api.md, architecture memory and dataset contract. Canonical portable
skill `corp-skills/skills/cveta2/{SKILL.md,references/usage.md,references/evaluation.md}`
requires new workflow, removed-interface guidance and failure recovery examples.
Validate through its MAINTENANCE.md, record source commit and companion change;
installation is excluded. Preserve inactive completed feature history.

## Acceptance

Port upstream behavioral fixtures, add immutable snapshot/tampering tests, no-side-
effect failure cases, current-key coverage and CLI/API exit/decision tests. Run
focused tests then full pytest with coverage, Ruff, mypy, vulture, import-linter,
effect checker with negative cases, docs, build/install and existing hook gates.
Live tests use the integration skill and one owned run tag; verify the exact three
published files, parent immutability and complete exact-tag cleanup. Record actual
results, review and diff reconciliation in dated evidence before architecture
acceptance and convergence. Missing checks remain gaps.
