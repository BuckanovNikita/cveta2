# ClearML publication

`cveta2 upload-dataset PREPARED_DIR` and `cveta2.upload_dataset(prepared_dir)` publish a
prepared bundle, made by `cveta2 verify --bundle` or `cveta2.prepare_dataset`, as a new
finalized ClearML dataset version. The only input is the prepared directory: sources,
options and cleanup choices cannot be changed at upload. Before creating anything
remotely, the command rereads the bound files and repeats every preparation check. It
then publishes exactly `dataset.csv`, `dataset.yaml` and `tasks.yaml`. Preparation is
described in [verification and bundles](verification-and-bundles.md). Managed
publication (`cveta2 dataset publish`) has its own preparation and checks, described in
[managed datasets](managed-datasets.md), but uses the same ClearML parent lookup, S3 root
check and child publication described here.

## The `clearml` extra

- ClearML is optional. The extra `cveta2[clearml]` installs `clearml[s3]>=2.1.12,<3`.
  CSV verification, fetch and CVAT upload work without it.
- Only the `cveta2.adapters.clearml` package imports `clearml`, at the moment a call
  needs it. A missing package fails with
  `Install cveta2[clearml] and configure the ClearML SDK before uploading`. Bundle
  preparation reaches this point too, because it looks up the parent and lists S3 roots.
  `cveta2 dataset diff` with a ClearML dataset ID reads that dataset's files through a
  separate reader, which fails instead with
  `Install cveta2[clearml] to read published dataset evidence`.
- ClearML and S3 credentials come from the ClearML SDK's own configuration and
  environment. cveta2 stores none of them, in its configuration, in the preparation
  record or in the payload.
- `cveta2.adapters.clearml.availability.is_clearml_available()` returns whether
  `clearml` can be imported. No command calls it; the import failure above is the check
  that applies.
- Ordinary project and task fetch never initializes ClearML or publishes. CVAT
  `cveta2 upload` is a separate operation that does not involve ClearML.

## Dataset identity and versions

- A destination is an exact ClearML project name and dataset name, taken from the
  preparation record (`options.project`, `options.dataset_name`). Datasets in
  subprojects do not match.
- The ClearML project does not need to exist beforehand; the first publication creates
  it.
- Every successful publication creates a new child dataset with that project and name.
  cveta2 sets no version string; `Publication.version` is the version ClearML reports
  for the child and can be `None`.
- The parent is the latest finalized, nonarchived dataset with exactly that project and
  name. The first publication of a name has no parent and creates a dataset without
  parents.

### Parent lookup

1. List finalized, nonarchived datasets of the project, without recursive search, and
   keep rows whose project equals the requested one. A successful listing without the
   name proves that no parent exists. A listing failure is an error, never absence.
2. Retrieve the latest finalized, nonarchived dataset of that project and name. A
   result with another project or name, or one that is not finalized, fails with
   `ClearML returned a different project/name or an unfinalized parent`.
3. When the parent lists `dataset.yaml`, download only that file, without soft links.
   A missing download fails with
   `ClearML parent advertised dataset.yaml but its download is missing`.

How preparation treats a parent without `dataset.yaml` is described in
[verification and bundles](verification-and-bundles.md). Parents are never modified.

### S3 root check

Each approved `s3://bucket/prefix` root is listed through ClearML's storage manager
without probing individual objects:

| Condition | Message |
| -- | -- |
| Not an `s3://` URL with a bucket, or contains credentials, a query, a fragment, a backslash, a NUL or empty, `.` or `..` path segments | `S3 roots must be s3://bucket/prefix URLs without credentials, query or fragment` |
| The listing returns nothing usable | `S3 listing unavailable for <root>; check ClearML storage configuration` |
| A nonempty prefix has no object below `<prefix>/` | `S3 root prefix does not exist or is empty: <root>` |
| Any SDK or storage error | `Cannot access S3 root <root>; configure ClearML S3 storage and list permissions; ...` |

A bucket root with no objects passes.

## Checks before upload

`upload-dataset` performs these steps in order and stops at the first failure. Nothing
is created in ClearML before step 9.

1. Read `preparation.json` and `preparation.sha256` as regular, nonsymlink files. The
   SHA-256 of the record bytes must equal the stored checksum:
   `Preparation record changed (hash mismatch); prepare again.`
2. Parse the record strictly (`format_version` `1`, no unknown keys). An empty project
   or dataset name fails with `Prepared destination is incomplete; prepare again.`
3. `sources` must not be a symlink. Read the four source copies and the three payload
   files as regular, nonsymlink files. The bound file names must equal the expected
   inventory (`Invalid prepared file inventory; prepare again.`), and every SHA-256 must
   match (`Prepared files changed (hash mismatch); prepare again.`).
4. Parse `dataset.yaml` and `tasks.yaml` strictly and `dataset.csv` lexically, then copy
   the three payload byte strings into a private temporary directory. Publication uses
   only this copy; later edits of the prepared directory have no effect. The copy is
   removed when the command ends, also on failure.
5. The latest parent's ID and version must equal those recorded at preparation:
   `Latest parent changed; подготовьте датасет заново.`
6. The class registry at `api_url` must reconcile with `dataset.yaml` without any
   change: `Class identities changed; подготовьте датасет заново.`
7. Repeat the root checks on the source `dataset.csv`; the canonical roots must equal
   `dataset.yaml.images`: `Корни изображений изменились; подготовьте датасет заново.`
   Root failures and uncovered paths fail the same way as in preparation.
8. Validate twice with the bundle policy, decoding every image again:
   - the payload `dataset.csv` must have no blocker, no structural error and nothing
     requiring cleanup:
     `Подготовленные данные больше не проходят проверку: <blockers and issue messages>`;
   - the source `dataset.csv` must have no blocker or structural error
     (`Исходные данные больше не проходят проверку; подготовьте датасет заново.`), and
     may require cleanup only when the record's `clean` is true
     (`Очистка исходных данных не была разрешена.`);
   - the task manifest and payload bytes derived again from the sources must equal the
     reviewed ones:
     `Результат повторной проверки изменился; подготовьте датасет заново.`
9. Check the parent again (step 5), because ClearML offers no compare-and-swap, then
   publish.

Any failure in steps 1 to 8 requires a new preparation in a new directory. Malformed
YAML fails with `Cannot parse <name>: <reason>`. Filesystem errors and invalid record or
metadata fields from any step are reported as
`Cannot read prepared bundle <dir>: <details>`; details name fields and reasons but
never echo input values.

## Child publication

1. Check that the three payload files exist (`Required upload file is missing: <name>`).
2. Create a child dataset with the project, the name and the parent ID as its only
   parent, or no parent.
3. Refuse a child whose ID equals the parent's:
   `ClearML returned parent <id> as the child; refusing mutation`.
4. Remove every inherited file and link from the child (the parent stays intact); any
   survivor fails with `Created ClearML dataset <id> retained inherited entries`.
5. Add `dataset.csv`, `dataset.yaml` and `tasks.yaml`; the child must list exactly
   these three: `Created ClearML dataset <id> does not contain exactly the three bundle files`.
6. Upload synchronously with SDK retries disabled. A failed upload or remaining pending
   files fail with `Upload did not complete for created ClearML dataset <id>`; a lost
   file fails with `Upload lost bundle files for created ClearML dataset <id>`.
7. Finalize without an implicit upload and confirm the final state:
   `Finalization did not complete for created ClearML dataset <id>`; the finalized
   manifest must still be exactly the three files:
   `Finalized ClearML dataset <id> has an unexpected file manifest`.

Images, source copies, reports, `preparation.json` and `preparation.sha256` are never
published. The result is `Publication(dataset_id: str, version: str | None)`, returned
only after step 7 succeeds.

### Failures after creation

- Nothing is retried or rolled back. Every failure after step 2 names the child ID.
- An SDK error while creating the child fails with
  `Cannot create ClearML child dataset; check ClearML configuration, credentials and connectivity (<error>)`.
- An SDK error after creation fails with
  `Publication failed for created ClearML dataset <id>; inspect it before retrying; check ClearML configuration, credentials and connectivity (<error>)`.
- An interrupt after creation raises `UploadCancelled`:
  `Publication interrupted for ClearML dataset <id>; its remote state is uncertain. Inspect it before retrying.`
  An interrupt before creation stays a `KeyboardInterrupt`.
- A failure never means the child was finalized; inspect it in ClearML before retrying.

## Command line and API

```bash
cveta2 upload-dataset prepared
```

The single argument is the prepared directory. On success the command logs
`Опубликован датасет <id>, версия <version>.`, with `назначена сервером` when ClearML
reports no version.

| Exit code | Meaning | Log |
| -- | -- | -- |
| 0 | The child is finalized and confirmed | `Опубликован датасет ...` |
| 1 | Interrupted or cancelled | `Публикация отменена: <reason>` |
| 2 | Blocked or failed: unprepared or changed directory, failed check, ClearML or filesystem error | `Ошибка публикации: <error>` |

`upload_dataset` raises `Cveta2Error` subclasses for blocked and failed publication
(`UploadError`) and for interrupted publication after creation (`UploadCancelled`). It
never prompts and performs no cleanup.
