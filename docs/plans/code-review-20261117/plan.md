# Remediation plan for the 2026-11-17 code review

This is the plain plan that constitution principle I allows for bug fixes that
change no capability contract. The failing observations and reproductions are in
[review.md](review.md). Fixes that change a documented contract are held for a
decision and then go through Spec Kit; they are listed under
[Held for a decision](#held-for-a-decision).

## Scope and branches

- Base: `main` at `63cd255`.
- Integration branch: `fix/code-review-20261117`. Batch branches merge into it in
  waves, with development verification after each wave.
- `main` is not moved, nothing is pushed and no release is made under this plan
  without separate authorization.

Each fix records a failing regression test first, then the change, then
verification of the original failure path. Tooling fixes carry no unit tests,
because project rules forbid tests of project tooling.

## Carried findings (R01–R09)

These come from the 2026-11-15 review at the same commit. One line each, so this
plan stands alone:

| ID | Finding | Location |
| --- | --- | --- |
| R01 | YOLO re-export prune deletes image and label files it never owned | `adapters/files/conversion.py:149-170` |
| R02 | YOLO export accepts symlinked output directories and writes through them | `adapters/files/conversion.py:241-246` |
| R03 | Upload accepts `image_name` values with `..` or absolute paths | `adapters/files/image_search.py:68-72` |
| R04 | Managed preparation ignores a legacy parent's published splits | `use_cases/managed_preparation.py:145-153` |
| R05 | Managed publication accepts a parent without `dataset.yaml` | `composition/managed.py:76-78` |
| R06 | Upload staging passes prefix-relative paths to `build_s3_key` | `use_cases/upload/staging.py:123,131` |
| R07 | `doctor` uses `CvatConfig.from_env()` when the personal file is absent | `interfaces/commands/doctor.py:89-94` |
| R08 | `read_baseline_siblings` does not catch `UnicodeError` | `adapters/files/dataset.py:204-205` |
| R09 | Live-test preflight ignores cordoned, not-ready or tainted nodes | `tests/integration/lifecycle.py:381-390` |

## Batches

Batches are cut by file ownership so they can run in parallel worktrees. A file
has one owning batch; shared test helpers and shared documents take append-only
edits and are reconciled at integration.

| Batch | Branch | Findings | Owned code |
| --- | --- | --- | --- |
| Export | `fix/cr-export` | R02, N01, N09, N34, N18f | `adapters/files/{conversion,materialization,image_search}.py`, `use_cases/convert/`, `domain/conversion.py` |
| Upload and S3 | `fix/cr-upload` | R03, R06, R08, N05, N23, N25, N18g, N18i, N40 | `use_cases/upload/`, `domain/{upload,paths}.py`, `adapters/s3/{upload,download,utils,images}.py`, `adapters/files/{dataset,manifests,task_output,shared}.py` |
| CVAT client | `fix/cr-cvat` | N03, N19, N26, N27, N28, N18b, N18c, N42 | `adapters/cvat/` except `managed_*`, `adapters/execution/`, `application/client/`, `ports/{cvat,dtos}.py`, `commands/{labels,ignore,task_ops}.py` |
| Cache and fetch | `fix/cr-cache` | N06, N07, N18h | `adapters/s3/task_cache.py`, `composition/workflows.py`, `use_cases/{fetch,task_ops,whats_new}.py`, `domain/{partition,baseline,cache}.py`, `ports/cache.py` |
| Configuration | `fix/cr-config` | N02, N04, N11, N12, N13, R07, N31, N32, N33, N18d, N18e, load-time validation for N06 | `adapters/config/`, `commands/{setup,doctor,_helpers,_bootstrap}.py`, `commands/interactive/`, `ProjectDefinition` validators |
| Verification and bundle | `fix/cr-bundle` | N08, N14, N35, N41, N18j | `domain/verification/`, `adapters/files/{bundle,managed_sources}.py`, `adapters/class_api/`, `commands/managed.py` |
| Managed datasets | `fix/cr-managed` | R04, R05, N15, N16, N37 | `domain/managed/` except `ProjectDefinition`, `use_cases/managed_*.py`, `adapters/files/managed_{preparation,feedback}.py`, `adapters/cvat/managed_*.py`, `composition/managed.py` |
| Tooling | `fix/cr-tooling` | N17, N21, N22, R09, N38, N39, N43, N44, N45, N46 | `Taskfile.yml`, `scripts/`, `tests/integration/`, `tests/architecture_effects.py` |

## Held for a decision

| ID | Why it is held |
| --- | --- |
| R01 | Ownership needs a record in the YOLO output, which changes the output format |
| N10 | Reject or clip boxes that cross the image edge |
| N20 | Whether `--from-yolo` applies EXIF orientation |
| N18a | A test pins that the S3 downloader re-raises raw botocore errors |
| N24 | The fix adds a checkpoint and bumps the upload manifest schema |
| N29 | The fix costs one request per cache hit; confirm the premise on a live stand first |
| N30 | Scoping the cache by host changes the documented cache path |
| N36 | Add a HEIF decoder dependency, or drop the extensions |
| Q1–Q4 | Behaviours pinned by existing tests |

## Verification

1. Each batch: targeted unit tests while working, then development verification
   (`verify`) through the commit hook on its final commit.
2. After each merge wave: `verify` on the integration branch.
3. After integration: the changed-function mutation report, then fresh independent
   review of the combined diff.
4. Acceptance on the clean integration tip, including live tests. The lifecycle
   fixes (R09, N21, N22, N39, N43, N46) are only exercised by that run. If the
   cluster is unavailable, acceptance is deferred and reported as incomplete.

## Evidence

Dated results are appended here as work completes.

- 2026-11-17: review completed; `check` and `test-full` passed on `63cd255`
  (2,384 unit tests). No fix applied yet.
