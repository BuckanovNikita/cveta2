# Implementation Plan: Enforced clean architecture

**Branch**: `refactor/clean-architecture` | **Date**: 2026-10-14 | **Spec**: [spec.md](spec.md)

## Summary

Reorganize the complete package into domain, application, outgoing adapters, composition and incoming interfaces. Keep supported public modules as compatibility facades and preserve existing observable behavior. Replace service construction of infrastructure with explicit application-owned ports and resolved settings. Enforce dependency and effect boundaries with negative regression fixtures.

## Technical Context

Python 3.10+, uv, Pydantic, pandas, Loguru, CVAT SDK, boto3, optional ClearML, argparse. Existing pytest, Ruff, mypy, vulture, import-linter and mutmut toolchains remain authoritative. No dependency upgrade or storage migration. Existing integration lifecycle remains unchanged.

## Constitution Check

Before research: specification and accepted compatibility decisions exist; tests and release gates are retained. Principle II is amended to describe the approved inward architecture, replacing obsolete package names while preserving dependency discipline. After design: explicit dependency/effect ownership, data compatibility, failure ordering, review and verification are covered by this plan, contracts and architecture record. No remaining principle exceptions.

## Module Design

| Layer | Responsibilities | Allowed project dependencies |
|---|---|---|
| `domain` | Models, errors, partitions, pure merge/validation/key/conversion rules | Domain only |
| `application.ports`, `settings`, `results` | Neutral typed values and contracts | Domain and neutral contracts |
| `application.client` | CVAT operations over neutral API/session and image ports | Ports, settings, results, domain |
| `application.use_cases` | Fetch/upload/task/resolve/merge/conversion orchestration | Client, ports, settings, results, domain |
| `adapters` | CVAT/S3/ClearML/configuration/files/execution effects | Application contracts, domain; shared file/execution adapters where needed |
| `composition` | Resolve configuration, construct dependencies and public client | Adapters and inner layers |
| `interfaces` | CLI, prompts and Python API mapping | Composition and inner layers |
| Public top-level facades | Preserve supported imports and identities | Canonical implementations |

Canonical modules must never import public facades. Incoming interfaces are separate from outgoing adapters to prevent an interface/bootstrap cycle. Domain/application initializers and the root package must be inert or lazy. Keep `presets/default.yaml` at its current resource path. Classify every runtime module, enforce adapter peer independence and acyclic internal packages, and include external, local and type-only SDK imports.

## Interfaces and Effect Ownership

Application owns CVAT API/session, task cache/invalidation, image storage, dataset/conversion files, manifest persistence, publication and execution ports. Dependencies are passed explicitly at construction or invocation; there is no global service locator. Resolved settings contain validated values, never loading methods. Concrete filesystem, SDK, environment/configuration, clock, prompt, thread and process effects belong outside domain/application. Lexical paths, in-memory pandas, Pydantic and Loguru remain permitted.

`CvatClient(cfg=None, client_factory=None, *, api=None)` remains an outer compatible facade around the application client; session ownership, deferred credentials, organization and injected API behavior remain intact. Cache invalidation exists even when cache reads are disabled. Concurrency preserves input order, joins active jobs and cancels queued jobs on propagated failures. Preserve all schemas, keys, paths and write ordering described in [contracts/ports.md](contracts/ports.md).

## Implementation and Parallel Work

The parent first establishes canonical package paths, neutral shared values and agreed ports. Then three bounded streams may proceed concurrently: (A) CVAT adapter/application client; (B) fetch/upload/cache/image storage and recovery; (C) conversion/merge/dataset filesystem. File ownership is disjoint. The parent owns config/runtime composition, interfaces/facades, mechanical caller migration, import/effect gates, mutation migration and integration. Shared contract changes are serialized through the parent. No delegate delegates further.

After integration, run required checks and obtain a fresh independent review of the final diff. Fix findings, rerun affected checks and request a fresh review after material corrections. Complete convergence and architecture acceptance before release.

## Verification and Acceptance

Retain existing behavioral tests and add recording-port and isolated-import tests. Negative architecture fixtures must reject outward dependencies, adapter coupling, SDK escape, canonical-to-facade imports, sibling cycles, unclassified modules and inner effects. Preserve mutation scope function-by-function, revalidating equivalent identities without reducing the ratchet. Run `uv run lint-imports`, Ruff check/format, mypy, vulture, pytest with coverage, fast/full mutation profiles, build, documentation tests, and serial full live integration using the integration skill with exact-tag cleanup. Capture dated evidence and limitations. Release follows authorized Conventional Commits and semantic-release Git tags only; no GitHub Release objects or package assets.

## Complexity and Risks

Whole-package migration was explicitly selected. Existing signatures and model aliases must survive while internal test monkeypatch targets move to canonical owners. Conversion and upload recovery have ordering-sensitive effects; split policy from IO without rewriting algorithms. Import-linter cannot recognize filesystem effects: supplement it with AST effect checks and isolated imports. Reconcile the architecture record with the actual diff at acceptance.
