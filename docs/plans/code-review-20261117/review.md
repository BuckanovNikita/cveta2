# Full project code review — 2026-11-17

## Review context

- Reviewed commit: `63cd25522f29c566a25840a944f6486e7d3451ed` on `main`, equal to
  local `origin/main`. Remote references were not fetched.
- Scope: the whole `cveta2` package (about 24,500 lines), the verification
  tooling (`Taskfile.yml`, `scripts/`, hooks) and the live-test infrastructure
  under `tests/integration/`.
- Contracts: [baseline](../../../specs/baseline.md),
  [dataset contract](../../dataset-contract.md),
  [architecture](../../../.specify/memory/architecture.md) and
  [engineering guidance](../../../.specify/memory/engineering.md).
- Review only. No product code, tests, configuration or documentation was changed,
  and nothing was staged or committed. This file is untracked.
- Relationship to the [2026-11-15 review](../code-review-20261115/review.md): that
  review was made at this same commit, so its nine findings (R01–R09) are carried
  over here rather than restated. This review rechecked them and looked for
  further defects, starting from the siblings of each earlier finding.

## How to read this report

- **Carried** findings keep their `R` numbers. **New** findings are numbered `N01`
  onward, most severe first. `Q` items are behaviours that existing tests pin, so
  they need a product decision rather than a fix.
- **Evidence** is one of:
  - *Reproduced* — a standalone script exercised product code and showed the wrong
    outcome. External services were in-memory fakes or a loopback HTTP server.
  - *Static* — code reading only.
- **Fix path** is one of:
  - *Direct* — the behaviour already contradicts a documented contract. Handle it
    as a bug fix with a failing test first.
  - *Spec Kit* — the fix changes documented behaviour or an output format, so it
    needs a feature delta from the baseline.
  - *Decision* — the owner must choose a policy first.
- Priorities: **P1** data loss, writes outside the intended directory, or a
  credential exposure; **P2** a wrong result or a failure in a supported scenario;
  **P3** minor.

Nothing here was observed on a live CVAT, S3, ClearML or Kubernetes service.

## Summary

| Priority | Carried | New | Total |
| --- | --- | --- | --- |
| P1 | 4 | 2 | 6 |
| P2 | 5 | 20 | 25 |
| P3 | 0 | 24 | 24 |
| Decision (`Q`) | — | 4 | 4 |

The new findings cluster around five root causes:

1. **The CLI error boundary is narrower than the baseline promises.**
   `interfaces/cli.py:235-244` catches only `Cveta2Error` and `ValidationError`.
   Adapters let `OSError`, `UnicodeError`, `ValueError`, botocore errors, CVAT SDK
   errors, `EOFError` and `RecursionError` through, so many ordinary failures end
   in a traceback (N18, N06, N12, and carried R08).
2. **YOLO export has no ownership or confinement pass.** COCO export validates
   ownership and symlinks before writing; YOLO does not (R01, R02, N01, N09).
3. **Configuration is resolved by more than one path.** Some callers bypass the
   normal resolver or the selected config file (R07, N07, N13).
4. **Personal and shared configuration writes are not safe.** Permissions,
   atomicity and concurrent edits (N02, N04, N11, N12).
5. **The managed path lacks safeguards the standalone path has** (R04, R05, N14,
   N37, Q3), and its feedback ledger cannot recover from its own writes
   (N15, N16).

## Findings table

| ID | Pri | Finding | Evidence | Fix path |
| --- | --- | --- | --- | --- |
| R01 | P1 | YOLO cleanup deletes unrelated files | Reproduced again | Spec Kit |
| R02 | P1 | YOLO export writes through symlinked split directories | Reproduced again | Direct |
| R03 | P1 | Upload accepts image names escaping the search directory | Reproduced again | Direct |
| R04 | P1 | Legacy-parent adoption changes published splits | Code confirmed, not rerun | Direct |
| N01 | P1 | YOLO export writes through symlinked label files and `dataset.yaml` | Reproduced | Direct |
| N02 | P1 | `setup` saves the password world-readable and non-atomically | Reproduced | Direct |
| R05 | P2 | Managed publication accepts CSV-only parents | Code confirmed, not rerun | Direct |
| R06 | P2 | Upload reconstructs some existing S3 keys incorrectly | Code confirmed, not rerun | Direct |
| R07 | P2 | `doctor` rejects valid shared configuration | Reproduced again | Direct |
| R08 | P2 | Invalid encoding in an optional baseline aborts `whats-new` | Reproduced again | Direct |
| R09 | P2 | Infrastructure preflight ignores node scheduling eligibility | Code confirmed, static | Direct |
| N03 | P2 | Label deletion uses the weak prompt after an incomplete usage count | Reproduced | Direct |
| N04 | P2 | A shared-policy save reverts another writer's change | Reproduced | Direct |
| N05 | P2 | A rejected task create leaves an upload that can neither rerun nor resume | Reproduced | Direct |
| N06 | P2 | A malformed `task_cache_s3` breaks fetch and fails mutations after they succeed | Reproduced | Direct |
| N07 | P2 | Cache invalidation ignores `Connection.config_path` | Reproduced | Direct |
| N08 | P2 | `verify` rejects the multi-issue `issue_state` that fetch writes | Reproduced | Direct |
| N09 | P2 | A re-export can use its own previous output as the image source | Reproduced | Direct |
| N10 | P2 | YOLO export writes out-of-range values that the importer then drops | Reproduced | Decision |
| N11 | P2 | The `setup` wizard cannot attach an existing shared file | Reproduced | Direct |
| N12 | P2 | A damaged migration journal blocks `setup --migrate-config` for good | Reproduced | Direct |
| N13 | P2 | Attached-mode `setup` writes one-run environment overrides to disk | Reproduced | Direct |
| N14 | P2 | Managed CLI errors exit 1 instead of 2 | Reproduced | Direct |
| N15 | P2 | A failed feedback delivery can never be retried after a sibling succeeds | Reproduced with fakes | Direct, after live check |
| N16 | P2 | Feedback from one preparation makes a sibling preparation look stale | Reproduced with fakes | Direct, after live check |
| N17 | P2 | Editing pytest plugin or hook code makes `verify` run zero tests | Reproduced in a scratch copy | Direct |
| N18 | P2 | Ordinary failures escape the CLI as tracebacks (ten sources) | Reproduced, one part static | Direct |
| N19 | P2 | Issue comments are kept newest-first | Static, version-dependent | Direct, after live check |
| N20 | P2 | `--from-yolo` ignores EXIF orientation | Reproduced | Decision |
| N21 | P2 | Interrupting the pytest controller during seeding leaks the session | Static | Direct |
| N22 | P2 | Live-session seeding has no timeout | Static | Direct |
| N23–N46 | P3 | Twenty-four minor findings | Mixed | See [P3 findings](#p3-findings) |
| Q1–Q4 | — | Four pinned behaviours | Mixed | Decision |

## P1 findings

### R01–R04 — carried over

See the [2026-11-15 review](../code-review-20261115/review.md) for the full text.
Status on 2026-11-17:

- **R01, R02, R03** were reproduced again with fresh scripts and still fail as
  described.
- **R04** was not rerun; the cited code is unchanged.

Note for the R01 fix: establishing ownership needs a record of what the previous
export wrote. That adds a file to the YOLO output, so it changes the dataset
contract and belongs in a Spec Kit delta. R02 and N01 need no format change.

### N01 — YOLO export writes through symlinked label files and `dataset.yaml`

**Location:** `cveta2/application/use_cases/convert/yolo.py:47,74,84`, writing
through `cveta2/adapters/files/dataset.py:37`. `_prepare_yolo_output`
(`cveta2/adapters/files/conversion.py:241-246`) checks nothing.

This is the per-file sibling of R02. If `labels/train/a.txt` or `dataset.yaml` in
the output directory is a symlink, the export overwrites the link's target and
exits 0. COCO export already rejects a symlinked metadata file
(`conversion.py:183-184`).

**Reproduced:** both external target files were overwritten with generated content.

**Proposed fix:** one validate-before-write pass for YOLO, shared with R02. Reject
a symlinked output ancestor, split directory, label path or `dataset.yaml` with a
`Cveta2Error` before the first write. Alternatively write each file to a temporary
name and `os.replace` it, which replaces a link instead of following it.

**Regression test:** plant symlinks at a label path and at `dataset.yaml`, export,
and assert the external files are unchanged.

### N02 — `setup` saves the password world-readable and non-atomically

**Location:** `cveta2/adapters/config/settings.py:139-142` (`_write_raw_yaml` uses
`path.write_bytes`), reached from `CvatConfig.save_to_file` and
`SectionConfig.save`.

A fresh `cveta2 setup` under the default umask creates `config.yaml` as mode
`0644` with `password:` in clear text. The migration and attach paths already
write personal files as `0600` through `project._private_write`, and
`tests/test_managed_config.py:353` asserts that mode. The plain write is also not
atomic: a crash or a full disk during it truncates the file and loses the
credentials and every other section.

**Reproduced:** `personal config mode: 0o644 | contains password: True`.

**Proposed fix:** route every personal-file write through the existing atomic
`0600` writer (`_private_write(path, content, replace=True)`), and tighten the
mode of an existing file that holds a password.

**Regression test:** run setup on a fresh path and assert mode `0o600`; inject a
write failure and assert the previous file is intact.

**Priority note:** this is P1 on a shared host, where other local users can read
the file. On a single-user workstation the exposure is smaller.

## P2 findings

### R05–R09 — carried over

See the [2026-11-15 review](../code-review-20261115/review.md). Status:

- **R07, R08** were reproduced again.
- **R05, R06** were not rerun; the cited code is unchanged. For R06, two more
  callers receive the same prefix-relative value and belong in the same fix:
  `cveta2/adapters/s3/upload.py:145` and `cveta2/adapters/files/dataset.py:116`.
- **R09** remains static.

### N03 — Label deletion uses the weak prompt after an incomplete usage count

**Location:** `cveta2/interfaces/commands/labels.py:296-306` and
`cveta2/application/client/read.py:74-107`.

`count_label_usage` skips any task whose annotations cannot be read and returns
partial counts with no "incomplete" signal. The label then shows 0 annotations,
so the command asks the y/n question "Удалить 1 меток (аннотаций нет)?" instead
of requiring the label names to be retyped. Confirming deletes the label's
annotations in the unread task, irreversibly. Two warnings about the skipped task
are logged before the prompt; the defect is the "no annotations" wording and the
weaker confirmation.

A second, static gap: only `annotations.shapes` are counted. `RawAnnotations`
carries no tags or tracks, so a label used only there also shows 0.

**Reproduced** for the skipped-task case.

**Proposed fix:** return a result that says whether the count is complete (for
example the skipped task IDs). When it is incomplete, use the destructive
confirmation and say the count is unknown. Count tags and tracks per label.

**Regression test:** one task raises `CvatApiError`; expect the retype-names prompt.

### N04 — A shared-policy save reverts another writer's change

**Location:** `cveta2/adapters/config/settings.py:205-224`, the comparison loop at
lines 215–219.

`save()` reloads the shared file and compares the stale in-memory section for
*every* shared project against it. A project that another writer changed since
this instance loaded therefore counts as a change and is written back to its old
value. The baseline says policy writes update shared storage or fail.

**Reproduced:** two `IgnoreConfig` instances; the second writer's entry for
project B was removed when the first saved an entry for project A.

**Proposed fix:** remember the shared values at load time and write only the
projects that differ from that snapshot. Add an advisory lock, or compare the
file's hash before replacing it and refuse on drift.

**Regression test:** the two-instance interleave keeps both entries, for `ignore`
and for `sync_roots`.

### N05 — A rejected task create leaves an upload that can neither rerun nor resume

**Location:** `cveta2/application/use_cases/upload/recovery.py:110-121`; refusals
at `recovery.py:205-210` and `orchestration.py:88-91`.

`creation_pending=True` is saved before the create call and nothing clears it
when CVAT answers with a definitive rejection such as 400 or 403. Afterwards a
plain rerun says to use `--resume`, and `--resume` says the create outcome is
unknown. The only way out is to delete a file under
`~/.cache/cveta2/uploads/`, and neither message names it. The baseline requires
manual inspection for an *uncertain* creation; a 4xx reply is not uncertain.

**Reproduced** with a 400 reply.

**Proposed fix:** when create fails with a definitive 4xx status before the task
ID is known, clear `creation_pending` with a required save and re-raise. Keep 5xx,
status 0 and timeouts pending. Put the manifest path in both refusal messages.

**Regression test:** a 400 create followed by a rerun creates exactly one task; a
503 create still refuses.

### N06 — A malformed `task_cache_s3` breaks fetch and fails mutations after they succeed

**Location:** `cveta2/adapters/s3/task_cache.py:109-128`. Reached from
`use_cases/fetch.py:129,278`, the `finally` in `use_cases/task_ops.py:40-41` and
`use_cases/upload/orchestration.py:112`.

Values such as `s3://`, `s3:///x`, `/` or blanks are accepted when configuration
loads. `parse_sync_root` then raises a raw `ValueError`:

- every `fetch` ends in a traceback;
- task commands apply the CVAT change and then raise from the `finally` block,
  which also masks an error from the mutation itself;
- upload creates the task and raises before recording completion.

Separately, `make_s3_client` sits outside the disable-on-failure handling, so a
missing `AWS_PROFILE` makes `fetch --no-images` die with a raw `ProfileNotFound`
instead of warning and using the local cache.

**Reproduced** for both triggers.

**Proposed fix:** validate `task_cache_s3` when configuration loads. Convert the
`ValueError` to `Cveta2Error` as `use_cases/resolve.py:169-172` already does.
On a client construction failure, ordinary fetch should warn and continue with
the local cache. After a successful mutation, an invalidation failure should warn
rather than raise.

### N07 — Cache invalidation ignores `Connection.config_path`

**Location:** `cveta2/composition/workflows.py:64-73`; line 71 calls
`CacheConfig.load()` with no path, while fetch at line 36 uses the selected file.

API task mutations and upload invalidate the cache described by the *default*
configuration. With `Connection(config_path=...)`, the entry under the custom
`tasks_root` or `task_cache_s3` survives, and if the default configuration is
malformed the call raises after the remote write has already succeeded. The
baseline says custom file selection also selects adjacent project-cache state.

**Reproduced:** after `task_set_status` the custom-root entry still existed and
the next fetch made no annotation request.

**Limit:** stale data is only served when the CVAT mutation leaves the task's
`updated_date` unchanged. The fake keeps the date; live CVAT was not checked. The
CLI is unaffected, because it has no per-call config path.

**Proposed fix:** resolve the cache settings once in composition, from the same
selected file that `fetch_dependencies` uses, and bind them into the invalidator
that the API task operations and upload receive. This keeps configuration
selection out of the application port. When invalidation fails after a
successful remote write, warn instead of raising.

### N08 — `verify` rejects the multi-issue `issue_state` that fetch writes

**Location:** `cveta2/domain/verification/schema.py:294-297`; producer at
`cveta2/application/client/context.py:29-34`.

The schema accepts only `open`, `resolved`, `open | resolved`, `resolved | open`
and `new`. Fetch writes one state per issue joined with ` | `, so a frame with two
open issues yields `open | open`. Every row of that image is then reported as
`invalid_issue_state` and quarantined, `verify` exits 1, and `--clean` drops
valid rows. The dataset contract says multiple issues join with ` | `.

**Reproduced:** `open | open` and `open | resolved | open` broke 2 of 2 rows; the
`open | resolved` control broke none.

**Proposed fix:** replace the enumeration with a predicate: exactly `new`, or a
non-empty ` | `-separated run of `open` and `resolved`.

### N09 — A re-export can use its own previous output as the image source

**Location:** `cveta2/adapters/files/materialization.py:56-69`. Contributing:
the recursive basename search where the lexicographically last path wins
(`cveta2/domain/paths.py:21`), and the output directory not being excluded from
the search directories (`cveta2/application/use_cases/convert/common.py:72`).

Trigger: `--image-dir data -o data/yolo`, then export again after replacing a
source image. The previous output sorts after the source and wins.

| Link mode | Outcome |
| --- | --- |
| `symlink` | The output image becomes a link to itself; the run exits 0 |
| `copy`, `hardlink` | The old bytes are kept |
| `copy`, with `--image-dir` set to the old split directory | The image is deleted and a raw `FileNotFoundError` escapes |

The dataset contract says repeat exports refresh image bytes.

**Reproduced** for all three rows.

**Proposed fix:** exclude paths under the resolved output directory from the image
search. In `_link_or_copy`, resolve the source before unlinking the destination
and refuse when they are the same file.

### N10 — YOLO export writes out-of-range values that the importer then drops

**Location:** `cveta2/domain/conversion.py:350-369`; validation at lines 135–145
checks only finiteness and ordering.

A box that crosses the image edge is exported with a width of 1.2 or a centre of
1.125. Fetch itself produces such boxes from out-of-image polygon vertices.
Importing that output with `--from-yolo` skips those lines, so the image silently
becomes a negative. The dataset contract gives the ranges as centres in [0, 1]
and sizes in (0, 1].

**Reproduced** as a round trip.

**Decision needed:** reject such boxes before any output exists, or clip them to
the image with a warning and reject boxes that become degenerate. Either choice
changes documented export behaviour.

### N11 — The `setup` wizard cannot attach an existing shared file

**Location:** `cveta2/interfaces/commands/setup.py:125-139` and
`cveta2/adapters/config/project.py:453,541-545`.

Entering an existing team file at the wizard's shared-path prompt always fails
with "Общая конфигурация отличается". The personal file now holds host and
organization, so `setup --project-config` then raises `MigrationRequired`, and
`setup --migrate-config` fails for the same "differs" reason. The user has to
edit YAML by hand. The baseline says ordinary setup offers shared-file attachment.

Two causes:

- The wizard builds a migration proposal from the personal file and the discovery
  cache, so any real team file differs from it.
- The comparison is raw YAML against `model_dump()`, so a hand-written file that
  omits null defaults such as `sync_root` differs even when it means the same.

**Reproduced** for all three commands.

**Proposed fix:** when a shared file already exists, attach instead of migrating:
if the personal host and organization equal the shared ones, drop them and call
`attach_project_config`; otherwise raise a specific identity-mismatch error.
Compare validated models, not raw YAML.

### N12 — A damaged migration journal blocks `setup --migrate-config` for good

**Location:** `cveta2/adapters/config/project.py:469-495`.

An empty or truncated `config.yaml.migration.json`, or one that references a
deleted stage file, raises `JSONDecodeError`, `KeyError` or `FileNotFoundError`.
Recovery runs before anything else and the journal is never cleared, so every
later run fails the same way. The baseline says interrupted migration is
recoverable through its journal.

**Reproduced** for a truncated journal and a missing stage.

**Proposed fix:** parse the journal into a validated model and convert these
errors into a `ManagedError` that names the journal and says how to recover.
Write the journal atomically.

### N13 — Attached-mode `setup` writes one-run environment overrides to disk

**Location:** `cveta2/interfaces/commands/setup.py:96`.

With a shared file attached, setup seeds its defaults from `CvatConfig.load()`,
which includes environment overrides. Pressing Enter at the password prompt then
saves `CVAT_PASSWORD` and `CVETA2_DATA_TIMEOUT` from the environment into the
personal file. `docs/configuration.md` describes environment values as one-run
overrides, and the standalone branch already reads only the file.

**Reproduced:** the saved file contained the environment password and timeout.

**Proposed fix:** always seed defaults from `CvatConfig.from_file`, take host and
organization from the shared file, and use `load()` only to validate.

### N14 — Managed CLI errors exit 1 instead of 2

**Location:** `cveta2/interfaces/commands/managed.py:55-93`.

`run_managed` has no error mapping, so a `ManagedError` falls through to the
generic boundary and exits 1 — the same code as "preparation not ready". The
baseline and `docs/cli.md:719-720` say configuration, source and publication
errors exit 2. `commands/verification.py:190-205` already maps errors this way.

**Reproduced:** `dataset show` with a missing shared config exited 1.

**Proposed fix:** wrap the dispatch in the same `Cveta2Error`, `ValidationError`
and `OSError` handler that verification uses, exiting 2.

### N15 — A failed feedback delivery can never be retried after a sibling succeeds

**Location:** `cveta2/application/use_cases/managed_feedback.py:70-71` and
`cveta2/adapters/files/managed_feedback.py:101-102`.

Findings A and B are on one task. A's issue creation fails transiently after its
receipt is recorded with the task date T0. B succeeds and moves the task to T1.
On every later run A's live date differs from its receipt and A's issue does not
exist, so `_known_delivery` raises "Unacknowledged task change during feedback".
A is never delivered and publication stays blocked — by the tool's own write.

**Reproduced with fakes** that advance the task date when an issue is created.

**Limit:** this matters only if CVAT changes `task.updated_date` on issue
creation. A code comment assumes it and a live test says it "may". Confirm on the
live stand before fixing.

**Proposed fix:** when the live fingerprint equals the receipt's and the date
change is explained by acknowledged receipts for the same task, rebase the
pending receipt to the live date and deliver.

### N16 — Feedback from one preparation makes a sibling preparation look stale

**Location:** `cveta2/adapters/files/managed_feedback.py:46-48` (the ledger is
scoped to one preparation directory) and
`cveta2/application/use_cases/managed_publication.py:84-87`.

`docs/cli.md` describes preparing an inspection directory and then preparing with
`--clean` into a new directory from the same fetch. If errors are reported from
the first directory, the second one's fresh ledger records the existing issue as
T1→T1. Nothing connects the snapshot's T0 to T1, so publication fails with "CVAT
task changed; fetch again". The baseline says feedback metadata alone must not
make annotations appear stale.

**Reproduced with fakes**; same live premise as N15.

**Proposed fix:** either record the feedback fingerprint per task in the snapshot
and accept a newer date when it is unchanged, or key the ledger by the source
snapshot so every preparation from one fetch shares it.

### N17 — Editing pytest plugin or hook code makes `verify` run zero tests

**Location:** the `TESTMON_ENV` digest in `Taskfile.yml:79-83`.

The digest hashes `.py` content only for `scripts/`. For `tests/` and `cveta2/` it
hashes file membership and leaves content to testmon. Testmon records
dependencies per test, so code that runs at pytest startup — `tests/env_isolation.py`
and collection hooks in `conftest.py` — is nobody's dependency.

**Reproduced in a scratch copy of the repository** with its own testmon data:
after replacing the line that redirects `HOME` in `tests/env_isolation.py`, the
digest was unchanged and `pytest --testmon` selected zero tests ("no tests ran").
The exit status was not captured, but an unchanged tree produces the same
zero-selection result, which `verify` treats as a pass. A change that breaks HOME
isolation therefore goes through the commit gate without one test running.

**Proposed fix:** include the content of `tests/env_isolation.py` and every
`conftest.py` in the digest, so such an edit forces a full baseline.

### N18 — Ordinary failures escape the CLI as tracebacks

The baseline says expected operational failures have typed errors and CLI
failures have no incidental traceback. `cveta2/interfaces/cli.py:235-244` catches
only `Cveta2Error` and `ValidationError`. Ten sources reach it with something else:

| # | Source | Location | Raw exception | Evidence |
| --- | --- | --- | --- | --- |
| a | S3 access denied, missing credentials, unreachable endpoint in `upload`, `s3-sync`, `fetch` | `adapters/s3/utils.py:266-311`, `adapters/s3/download.py:317-320` | botocore `ClientError`, `NoCredentialsError` | Reproduced |
| b | Mistyped host scheme such as `htps://` | `adapters/cvat/connection.py:75-79` | `InvalidHostException` | Reproduced |
| c | CVAT payload the SDK cannot deserialize, such as a null datetime | `adapters/cvat/transport.py:56-72` | `ApiTypeError` | Reproduced |
| d | Unreadable or unwritable personal config | `adapters/config/settings.py:101-104,141-142` | `PermissionError` | Reproduced |
| e | A prompt with stdin closed | `interfaces/commands/interactive/primitives.py:156-158` | `EOFError` | Reproduced |
| f | `--from-yolo`: non-UTF-8 label file or split list, corrupt image | `adapters/files/conversion.py:54-59,118,254-256` | `UnicodeDecodeError`, `UnidentifiedImageError` | Reproduced |
| g | `upload --in-progress` file that is empty, non-UTF-8 or malformed | `adapters/files/task_output.py:45-53` | `EmptyDataError`, `UnicodeDecodeError`, `ParserError` | Reproduced |
| h | `whats-new` with a non-numeric `task_id` cell | `domain/partition.py:78-79` | `ValueError` | Reproduced |
| i | Upload fingerprint with a non-finite value in an unlabelled row or extra column | `domain/upload.py:113-126` | `ValueError` | Reproduced |
| j | Managed fetch with an output directory whose parent is a file | `adapters/files/managed_sources.py:192` | `FileExistsError` | Reproduced |

Related notes:

- Row c breaks the port's own promise that no `cvat_sdk` exception crosses it
  (`application/ports/cvat.py:6-8`).
- Row f also aborts the whole conversion for one bad label file, where a malformed
  line is skipped with a warning.
- Row g has a second defect: a file without an `image_name` column returns an
  empty set with no warning, so nothing is excluded.
- Two further raw-exception sources are in the P3 list: N41 (deeply nested YAML)
  and N42 (a Unicode digit as a task selector).

**Proposed fix:**

1. Translate inside the owning adapter into a contextual `Cveta2Error` that names
   the file or resource, keeping the original exception as the cause. The CLI
   cannot do this for rows a–c: import-linter allows `botocore` only in
   `adapters/s3` and `cvat_sdk` only in `adapters/cvat`.
   - Rows b and c belong in `adapters/cvat/connection.py` and `transport.py`,
     which also restores the port's promise.
   - Row a belongs in `adapters/s3`. **Decision needed:**
     `tests/test_image_download_failures.py:80` deliberately pins that the
     downloader re-raises the original botocore error. Either that pin changes to
     "a typed error whose cause is the original", or composition supplies a
     translator that only the CLI path uses.
   - Row e belongs in the interactive primitives: treat `EOFError` as the existing
     "interactive mode required" error.
2. Do not add a blanket `except Exception` to the CLI. The baseline says to
   preserve unexpected defects.

**Regression tests:** one case per row, asserting `SystemExit` with the resource
named and no traceback.

### N19 — Issue comments are kept newest-first

**Location:** `cveta2/adapters/cvat/sdk_adapter.py:162-171`; consumers at
`application/client/upload_mapping.py:155-156` and `application/client/context.py:30`.

The dataset contract says one issue's comments join in creation order. The
adapter requests comments without a `sort` parameter. In a local CVAT 2.82 source
tree, `CommentViewSet` defaults to `ordering = "-id"`. If the server returns
newest first, fetch writes `issue_text` in reverse, and `upload --resume` matches
an existing issue by `comments[0]` — the latest reply, not the initial message —
so an issue that received a reply is created a second time.

**Static and version-dependent.** The project's live stand pins CVAT 2.59.1,
which was not checked. A live test with a two-comment issue would settle it.

**Proposed fix:** pass `sort="id"` to the comments list call.

### N20 — `--from-yolo` ignores EXIF orientation

**Location:** `cveta2/adapters/files/conversion.py:54-59`.

For a JPEG with EXIF orientation 6 the importer records the unrotated size, so
width and height are swapped and pixel coordinates are computed on the wrong
axis. Verification's decoder (`adapters/files/media.py:46-47`) applies the
orientation, so the two disagree about the same image.

**Reproduced.** The contract names EXIF only for verification and bundles, so
whether import should match is a **decision**.

### N21 — Interrupting the pytest controller during seeding leaks the session

**Location:** `tests/integration/lifecycle.py:239-251,1027,1030` and
`tests/integration/conftest.py:72-75`.

The live session runs in an xdist worker, and only the worker installs the
SIGTERM handler. When a signal reaches only the controller, execnet interrupts
the worker after 5 seconds and force-exits it 10 seconds later. Inside `call()`
that interrupt is a `KeyboardInterrupt`, which is not forwarded to the child, so
the worker waits for a child that got no signal and is killed before teardown.
The namespace, its port-forwards and the seed process remain. The engineering
guidance says the namespace is deleted on interruption.

**Static**, from reading `lifecycle.py` and the installed execnet and xdist.

**Proposed fix:** in `call()`, forward the interrupt to the child, wait a few
seconds, then kill it. Send `kubectl delete namespace --wait=false` as the first
teardown step.

### N22 — Live-session seeding has no timeout

**Location:** `tests/integration/lifecycle.py:239-241,1009-1010,1044` and
`tests/integration/seed_cvat.py:293`.

`call()` has no deadline, `urlretrieve` has no timeout, and the SDK's
`wait_for_completion` loops without bound. If a CVAT worker is killed after
readiness, or the coco8 download stalls, `task integration` never ends: neither a
deferral nor a failure, with the namespace held. The engineering guidance says
seeding keeps its own operation timeout.

**Static.**

**Proposed fix:** give the seed step a deadline that raises `SetupBlockedError`,
so the namespace is deleted, and use a timeout for the download.

## P3 findings

| ID | Finding | Location | Evidence | Proposed fix |
| --- | --- | --- | --- | --- |
| N23 | Images are written to S3 before the "neither local nor on S3" check refuses the upload | `use_cases/upload/staging.py:101-129` | Reproduced | Compute the unreachable list before uploading |
| N24 | After a lost `put_task_shapes` reply, an immediate `--resume` sees no shapes and appends again | `use_cases/upload/recovery.py:48-79` | Static | Add an annotations-pending checkpoint; refuse when pending and remote is empty |
| N25 | Two concurrent uploads of one dataset both pass the manifest check and create two tasks | `use_cases/upload/recovery.py:204-223` | Static | Hold an exclusive lock per fingerprint for the run |
| N26 | urllib3's default retry replays `DELETE`, so `task delete` can report 404 for a task it deleted | `adapters/cvat/diagnostics.py:341-343` | Reproduced | Disable status and read retries for non-safe methods |
| N27 | `task mark-deleted --image` drops unmatched names with no warning | `application/client/task_ops.py:56-58` | Static | Warn with the unmatched names, as `--frame` does |
| N28 | Shapes on frames missing from the task metadata are dropped with no warning or count | `application/client/extractors.py:43-45` | Reproduced | Count and warn per task |
| N29 | Cache reuse checks task status, not the job state its completion was computed from | `adapters/s3/task_cache.py:195,204` | Static, depends on CVAT | Store a job fingerprint in the cache entry |
| N30 | The local annotation cache is not scoped by CVAT host, so two servers prune each other's entries | `adapters/s3/task_cache.py:37-45,239-253` | Static | Add a host segment to the cache path |
| N31 | Migration creates the shared team file as `0600`, unreadable to colleagues | `adapters/config/project.py:168-178,484` | Reproduced | Give the shared stage the umask-default mode |
| N32 | `doctor` flags the per-user prompt history, and `doctor --cache` makes it group-writable | `interfaces/commands/doctor.py:152` | Reproduced | Exclude `prompt_history` from the cache walk |
| N33 | Shared-config diagnostics omit the file name (duplicate keys) or the line and column (syntax errors) | `adapters/config/project.py:44-50,78-79` | Reproduced | Pass the path in; reuse the personal reader's formatting |
| N34 | `--from-yolo` prediction mode misses images with an uppercase extension or `.tif`, and exits 0 with an empty CSV | `adapters/files/conversion.py:39-49` | Reproduced | Match the suffix case-insensitively; add `.tif` |
| N35 | Bundle YAML checking re-walks a reused anchor on every reference; a 555-byte file took 11 seconds | `adapters/files/bundle.py:35-52` | Reproduced | Remember fully checked nodes |
| N36 | `heic` and `heif` are listed as supported, but no decoder is registered, so such images are always quarantined | `domain/bundle/validation.py:21-37` | Static; the locked Pillow registers neither extension, but no HEIC file was decoded | Register a decoder or drop the extensions |
| N37 | Managed path gaps against standalone: no S3 root check at prepare; output inside the source is not refused; the contract says `tasks.yaml` holds label definitions and the registry snapshot, but only their hashes are stored | `adapters/files/managed_preparation.py:166-169`, `domain/managed/models.py:214-240` | Static | Add the checks; reconcile the contract text |
| N38 | A mutation run whose budget expires before any mutant is judged prints "No judged mutant … survived" and exits 0 | `scripts/mutation.py:313-314,370-371,441-444` | Message reproduced, trigger static | Report "no verdict" and exit non-zero |
| N39 | `INTEGRATION_KEEP_DATA=1` through pytest overwrites an existing kept-session record, orphaning the earlier session | `tests/integration/lifecycle.py:1151-1158` | Static | Check for an existing record, as `command_up` does |
| N40 | The shared-cache writer uses a predictable temporary name in group-writable directories | `adapters/files/shared.py:60-74` | Static | Use an exclusively created temporary file |
| N41 | A parent `dataset.yaml` or class-API response nested about 900 deep escapes as `RecursionError` | `adapters/files/bundle.py:56-63`, `adapters/class_api/http.py:67-71` | Reproduced | Catch `RecursionError` in both readers |
| N42 | A Unicode digit such as `²` passes `isdigit()` and then fails `int()` in task selectors | `interfaces/commands/ignore.py:131`, `application/client/fetch.py:207-208` | Static | Use `isdecimal()` |
| N43 | A namespace create that is interrupted or times out after the server accepted it is never deleted, because `created` is set only after `kubectl` returns | `tests/integration/lifecycle.py:927-928,1060-1061` | Static | Label the namespace with a per-session token; after a failed create, delete it if it carries the token |
| N44 | `SKIP` is passed straight to prek, so `SKIP=verify,conventional-pre-commit` also disables commit-message validation, which the guidance says stays active | `scripts/git-hook.sh:9-19` | Static, assumes prek honours `SKIP` for every hook | Clear `SKIP` for the `commit-msg` hook type, or reject values other than `verify` |
| N45 | The architecture effect checker misses `time.strftime`, `time.time_ns`, `datetime.today`, `asyncio.sleep` and `Path.walk` in inner layers; no current module uses them | `tests/architecture_effects.py:15-48` | Reproduced | Add them to the effect lists with negative fixtures |
| N46 | Once `/readyz` has answered, a refused connection during the namespace-rights probe is reported as ERROR (exit 1) with an RBAC message, not UNAVAILABLE (exit 3) | `tests/integration/lifecycle.py:444-453` | Static | Classify connectivity failures in the later probes as unavailable |

## Decisions needed

These behaviours are pinned by existing tests or follow the letter of the
contract. They are listed because their outcomes look unintended.

### Q1 — Unfinished tasks decide deletion precedence

`cveta2/domain/partition.py:118-140,214-231`. Deletion precedence is computed over
all tasks, while dataset selection uses completed tasks only.

- Completed task 3 annotates an image and completed task 5 deletes it. When
  unfinished task 9 starts re-annotating it, the image returns to `dataset.csv`
  with task 3's old boxes and leaves `deleted.csv`.
- An unfinished deletion in task 9 immediately removes an image that a completed
  task annotated.

**Reproduced.** `tests/test_partition.py:154-191` computes the same outcome, so a
change needs the baseline, the contract and the test oracle updated together.

### Q2 — Findings on frames covered by overlapping jobs cannot be delivered

`cveta2/adapters/cvat/managed_feedback.py:77-83` raises "Feedback frame has no
unique annotation job" for a frame that two regular jobs cover. Fetch supports
overlapping jobs with a "prefer unfinished, then lowest job ID" rule. Since
undelivered mapped findings block publication, such a dataset cannot be published
until someone edits CVAT. `tests/test_managed_feedback.py:285-291` asserts the
rejection. **Reproduced.**

### Q3 — Managed preparation accepts class changes without a decision

`cveta2/composition/managed.py:89-96` discards `reconcile_classes(...).changes`.
When the registry adds or renames a class after a parent exists, managed
preparation proceeds, where standalone raises `MissingDecisions`. Shared policy
may be meant to count as the decision. **Static.**

### Q4 — The definition fingerprint binds fields that do not affect the dataset

`cveta2/domain/managed/models.py:254-270`. Editing an ignored task's description,
reordering sources, or adding an overlap decision changes the hash. The existing
fetch is then rejected at prepare, and the next fetch re-downloads every task.
The baseline says unrelated shared entries do not invalidate preparation.
**Static.**

## Suggested batching

Seven independent batches, each suitable for its own worktree. Within a batch the
fixes share files and tests.

| Batch | Findings | Notes |
| --- | --- | --- |
| Export confinement | R01, R02, N01, N09, N10, N20, N34 | R01 and N10 need Spec Kit or a decision first; the rest are direct |
| CLI error boundary | N18 a–j, R08, N41, N42, N33 | One pattern applied per adapter; the cheapest large win |
| Upload | R03, R06, N05, N23, N24, N25 | R03 and R06 first |
| Configuration and caches | N02, N04, N11, N12, N13, R07, N07, N06, N31, N32, N40 | N02 first |
| CVAT client | N03, N19, N26, N27, N28, N29, N30 | N19 needs a live check first |
| Datasets and bundles | R04, R05, N08, N14, N15, N16, N35, N36, N37, Q2–Q4 | N15 and N16 need a live check first |
| Tooling and live tests | N17, N21, N22, R09, N38, N39, N43–N46 | No product code |

## Areas inspected without findings

This list is relayed from the area reviewers. Their conclusions here were not
rechecked independently.

- Retry policy assignment per CVAT endpoint, and the per-pool `raise_on_status`
  wrapper not mutating shared policy.
- `ConcurrentRunner` ordering, cancellation and context propagation.
- Diagnostics redaction of credentials, cookies, headers and URL user info.
- The fetch promotion barrier, numeric task selection and cache pruning.
- Corrupt local cache entries: warned, treated as a miss and removed.
- COCO export ownership checks; conversion validating before any write.
- CSV text columns preserving values such as `001`, `NA` and `True`; BOM handling.
- Lazy `__init__` exports and facade object identity.
- Timeout validation; migration recovery between its two file writes.
- Standalone bundle publication: hash binding, staging copy, three-file
  publication, finalization checks and parent rules.
- Truncated and bit-flipped media: about 770 damaged images were rejected and no
  exception escaped the decoder.
- Managed split determinism, immutable preparation directories and S3 capture.

## Verification evidence

Executed on `63cd255` on 2026-11-17:

```bash
env -u UV_PROJECT_ENVIRONMENT CVETA2_TEST_WORKERS=4 \
  uv run --locked task --exit-code check test-full
```

- Lock check, Ruff lint and format checks, import-linter, mypy, Vulture and Deptry
  passed.
- All **2,384 non-live tests passed** in 12.81 seconds. Testmon selection was
  disabled for this run, which refreshed this worktree's testmon history.

What this establishes: the existing assertions hold at this commit. It does not
establish the absence of the defects above.

Not run:

- Live integration tests and the full `acceptance` task.
- Mutation testing, since no code changed.
- The packaging build.
- Any check against a live CVAT, S3, ClearML or Kubernetes service.

Method:

- The package was split into eight bounded, read-only reviews: fetch and cache;
  CVAT adapters and writes; upload and S3; conversion and files; configuration,
  CLI and API; verification and standalone bundles; managed datasets; tooling and
  live-test infrastructure.
- Before inclusion, the cited source of every finding was opened and compared with
  the claim, and every reproduction script was rerun, with one exception: the
  carried findings R04, R05, R06 and R09 were confirmed against the code only.
- Third-party premises were read in the installed packages for N21 and N22
  (execnet, xdist and the CVAT SDK wait loop). The CVAT server premise behind N19
  was read in a separate local CVAT 2.82 source tree by the area reviewer only.
- Reproduction scripts imported `tests.env_isolation` before product modules, kept
  their data in the session's scratch directory and were not added as regression
  tests. They are ephemeral.
- N17 was reproduced in a `git archive` copy of the repository with its own
  testmon data, not in this worktree.

Coverage limits:

- The unit tests were sampled for structural problems only, not reviewed file by
  file.
- Not read in full: parts of `tests/integration/seed_cvat.py` and `cvat_stand.py`,
  `tests/integration/clone_project_to_s3.py`, `scripts/benchmark_fetch.py`, the
  Kubernetes manifests (searched for kinds, service types, resources and
  secrets), `cveta2/interfaces/api/fetch.py` and `upload.py` beyond their
  configuration plumbing, the port protocol files, `docs/cli.md` and
  `docs/python-api.md`.
- Findings that depend on live service behaviour need a live check before a fix:
  N15, N16, N19, N29, and the stale-data consequence of N07.

This file records findings as of the date above. It does not mark any fix,
acceptance, integration or release as complete.
