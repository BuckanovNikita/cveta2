# Implementation Plan: Managed datasets

## Summary and technical context
Implement FR-001–FR-020 as a baseline delta using Python >=3.12,<3.14, existing uv/Pydantic/pandas/Loguru/pytest tooling and no new application framework. One native Spec Kit ledger owns all work. Existing standalone publication remains supported with explicit version-aware managed metadata.

## Constitution Check (before research and after design)
PASS: approved behavior specified before code; typed inward dependencies and explicit effects; no future annotations in new code; Russian human guidance/CLI, English feature artifacts; tests and docs required; exact ownership and reviewed Git-tag-only release. Deliberate compatibility change: shared policy/identity overrides are rejected after user-reviewed migration. No unrelated workflow/tooling changes.

## Architecture
See [architecture.json](architecture.json). Domain/managed owns schema and pure policies. Application ports own managed-source, storage, feedback and persistence effects; use cases orchestrate without discovering configuration. Config/S3/CVAT/ClearML/files adapters remain independent; composition injects dependencies. Interfaces own prompts and exits. Existing import/effect contracts cover new modules; update exhaustive coverage only where required, retaining negative fixtures.

## Contracts and ownership
See [contracts/managed.md](contracts/managed.md) and [data-model.md](data-model.md). Parent owns domain/managed/models.py, shared ports/model changes, composition and CLI/API wiring, architecture tooling, native artifacts and common fixtures. Each child has exclusive named paths; children never delegate or edit another owner's files. Tasks are dependency ordered and marked [P] only when disjoint.

## Parallel implementation
Foundation: parent freezes typed contracts and validates architecture planning. Wave 1: A config/migration/setup and tests; B source retrieval/reuse and tests; C pure split/overlap/diff and tests. Parent progresses wiring and review fixtures. Barrier: inspect every result and run focused integration checks. Wave 2: A preparation/snapshot persistence; B feedback/idempotency; C Russian guides and external usage skill after interface freeze. Parent publication and API/CLI integration. Fresh read-only final review starts after parent verification; reviewer has no implementation ownership. Maximum parent plus three active children; preserve parent model/effort and bounded contexts.

## Migration and compatibility
Personal schema v1: credentials, local cache paths, runtime settings, project_config reference. Shared schema v1: server/org, project registry and all data policies/mappings. No personal shared-field overlay. Resolve shared path explicit argument > CVETA2_PROJECT_CONFIG > personal reference; relative references are anchored to personal-file directory. Existing personal env credential/runtime overrides remain; shared identity conflicts fail. Review redacted migration proposal before activation; preserve original bytes in protected backup, stage shared first then activate personal pointer, retain recoverable transaction journal. Existing shared files are never overwritten. Unknown legacy fields are preserved in backup and reported as unresolved. Setup attaches only; explicit policy writers require writable shared config.

## Validation
Run targeted feature tests then Ruff/mypy/full pytest, lint-imports, scripts/check_architecture.py and tests/test_architecture.py, docs tests and package build. Respect required hook fast/full mutation gates. Live integration uses running-integration-tests/k8s-infra, one owned tag, serial tests and exact-tag cleanup. Review final scope/check evidence then validate architecture acceptance. Repeat implement/converge until no required work remains.

## Documentation and release
Update baseline, architecture context, README/docs in Russian and portable usage package skills/cveta2/{SKILL.md,references/usage.md,references/evaluation.md}. Inspected companion source commit 3609778906d3e63d0d160cb7d81510f4bf4849db; run its MAINTENANCE checks/evaluations and record companion commit. Use commit skill and hooks; merge-only main; semantic-release owns version/tag/changelog; no GitHub Releases/assets/package publication.

## Accepted cold-start amendment

FR-021/SC-007 explicitly cover configured mappings with no ClearML project/dataset. Successful absence proof yields a null parent; only publish creates the first version. Unit and owned live scenarios verify first publication and subsequent reuse. See T020 and dated verification.

## Release acceptance amendment — empty organization

A direct reproduction showed shared organization empty string loaded as personal-workspace null but failed credential-save equality. Normalize both neutral CvatIdentity and CvatConfig organization values at their validation boundaries, retaining strict nonempty shared-identity refusal. Add focused schema/file/environment tests and independent review. No new effects/import edges; reuse the existing architecture record and gates. Preserve the already created local v0.13.0 tag and issue a patch after merge rather than rewriting a tag.
