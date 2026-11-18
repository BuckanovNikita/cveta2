# Verification and bundles

`cveta2 verify` checks one annotation CSV against a validation profile and, with
`--bundle`, turns a full-fetch directory into a prepared bundle for a later, separate
`cveta2 upload-dataset`. The Python API exposes the same operations as `cveta2.verify`,
`cveta2.verify_dataframe`, `cveta2.schema_for` and `cveta2.prepare_dataset`. Ordinary
verification needs neither CVAT nor ClearML and never changes its input. By default it
only reports; accepting repairs and removals is a separate, explicit choice. Bundle
preparation is standalone preparation: it consumes the four full-fetch CSVs with splits
assigned outside cveta2. Publishing a prepared bundle is described in
[ClearML publication](clearml-publication.md); managed preparation is described in
[managed datasets](managed-datasets.md).

## Python API

| Call | Behavior |
| -- | -- |
| `verify(path, *, profile="cveta2", options=None, output_dir=None, clean=False)` | Reads one CSV file, validates it, writes a report when `output_dir` is given and returns `ValidationResult` |
| `verify_dataframe(frame, *, profile="cveta2", options=None)` | Validates a caller-owned DataFrame; the frame and its index are not modified |
| `schema_for(profile)` | Returns the non-coercing Pandera `DataFrameSchema` of a profile |
| `prepare_dataset(source, *, output_dir, options)` | Prepares a bundle from a full-fetch directory and returns `PreparedDataset` |

- API calls never prompt and never exit. A missing preparation choice raises
  `MissingDecisions` with structured `decisions`.
- Profiles are exactly `cveta2` and `clearml-yolo`. Any other profile raises
  `DatasetInputError` (`Unknown validation profile: ...`).
- `DatasetInputError` subclasses both `Cveta2Error` and `ValueError`. Preparation
  failures raise `UploadError`, a `Cveta2Error` that is not exported at package level;
  `MissingDecisions` subclasses it.
- With `emit_warnings=True`, `verify` and `verify_dataframe` emit one `DatasetWarning`
  (a `UserWarning`) per distinct warning code, carrying that code's first message. When
  the input is not valid they also emit
  `Validation rejected N of M row(s); inspect result.issues and result.broken.` A
  warning never claims that a check passed.

### `ValidationOptions`

Unknown fields are rejected; the model is frozen.

| Field | Default | Meaning |
| -- | -- | -- |
| `iou_threshold` | `0.99` | Duplicate and class-conflict threshold, finite, in `(0, 1]`; a match is IoU `>=` threshold |
| `check_images` | `False` | Decode local image files |
| `image_root` | `None` | Directory joined with `image_name` for rows whose `image_path` is empty |
| `base_dir` | `None` | Base of relative `image_path` values; `verify` uses the CSV's directory and `verify_dataframe` the current directory when unset |
| `emit_warnings` | `True` | Emit `DatasetWarning`s as described above |

### `ValidationResult` and `Issue`

| Member | Meaning |
| -- | -- |
| `profile` | Profile used |
| `clean` | Proposed retained rows, with accepted repairs applied |
| `broken` | Rejected rows with their original values |
| `clean_row_positions`, `broken_row_positions` | Zero-based positions in the input, never index labels |
| `issues` | Every finding, sorted by row position (row-less findings first) |
| `input_row_count` | Number of input rows |
| `checked_checks`, `skipped_checks` | Check names, listed under "Checks" below |
| `structural_errors` | The table as a whole could not be validated |
| `input_image_count`, `clean_image_count` | Distinct nonempty `image_name` values in the input and in `clean` |
| `is_valid` | No structural error and no rejected row |
| `requires_cleanup` | A rejected row exists, or an issue `bbox_clipped` or `class_canonicalized` proposes a repair |
| `warnings` | Issues with severity `warning` |
| `reasons_for(row_position)` | Issues of that row; with structural errors, also every row-less error |

`is_valid` and `requires_cleanup` are independent: a valid input can still require
accepting a repair. Neither the result nor the presence of `clean` means cleanup was
accepted.

| `Issue` field | Type |
| -- | -- |
| `code` | `str` |
| `message` | `str` (English) |
| `severity` | `"error"` or `"warning"`, default `"error"` |
| `row_position` | `int` or `None` |
| `columns` | `tuple[str, ...]` |
| `related_rows` | `tuple[int, ...]` |
| `iou` | `float` or `None` |

## CSV reading

- The file is decoded as UTF-8 with an optional BOM and parsed with Python's `csv`
  module in strict mode. Every cell stays a string; nothing is inferred, so literal
  values such as `NA` or `001` survive. Column order is kept.
- An empty header cell or a repeated header fails with
  `CSV must have unique, nonempty column names.` A file with no header line fails the
  same way.
- A record whose cell count differs from the header fails with
  `CSV record N has K cells; expected M.` (N counts CSV records, the header being 1).
- Undecodable or malformed CSV fails with `Cannot read CSV <path>: <reason>`.
- These read failures raise `DatasetInputError` before validation. Through `verify` each
  of them is wrapped as `Cannot load verification input <path>: <message>`; bundle
  preparation reports them unwrapped. A header-only file with valid columns is a valid,
  empty table.
- A cell is missing only when it is empty (`""`), `None`, `pd.NA` or a float NaN.
  Whitespace and text such as `NA` are values.

## Profiles

### Required columns

| Profile | Required columns |
| -- | -- |
| `cveta2` | `image_name`, `image_width`, `image_height`, `instance_shape`, `instance_label`, `bbox_x_tl`, `bbox_y_tl`, `bbox_x_br`, `bbox_y_br` |
| `clearml-yolo` | `image_name`, `image_path`, `instance_label`, `bbox_x_tl`, `bbox_y_tl`, `bbox_x_br`, `bbox_y_br`, `split` |

- `cveta2` validates every known cveta2 CSV column that is present (see
  [fetch and partition](fetch-and-partition.md) for the columns), plus `width`, `height`
  and `source_row_id`. Other columns are kept unchanged and produce one
  `unknown_columns` warning.
- `clearml-yolo` validates only its required columns and `image_width`,
  `image_height`, `width`, `height`. Every other column, including `instance_shape`, is
  kept unchanged without validation or warning.

### Cell rules

| Column | Rule | Code |
| -- | -- | -- |
| `image_name` | Nonempty bare file name: no `/` or `\`, not `.` or `..` | `invalid_image_name` |
| `image_path` (`clearml-yolo`) | Nonempty text | `invalid_image_path` |
| `instance_label` | Nonempty text for a box; `clearml-yolo` also accepts a number | `invalid_label` |
| `instance_shape` (`cveta2`) | `box`, `none` or `deleted` | `invalid_shape` |
| bbox columns | Finite number when present; nonnegative | `invalid_coordinate`, `negative_coordinate` |
| `image_width`, `image_height`, `width`, `height` | Positive integral value; `cveta2` requires `image_width`/`image_height` and allows `0` on `deleted` rows | `invalid_dimension` |
| `task_id`, `frame_id`, `annotation_id` | Nonnegative integral value | `invalid_integer` |
| `z_order` | Integral value | `invalid_integer` |
| `occluded`, `task_completed` | Boolean, `true`/`false` in any case, or `0`/`1` | `invalid_boolean` |
| `rotation` | Finite number in `[0, 360]` | `invalid_rotation` |
| `confidence` | Finite number in `[0, 1]` | `invalid_confidence` |
| `attributes` | JSON object with string keys and string values | `invalid_attributes` |
| `split` | `train`, `val` or `test`; may be empty only in `cveta2` | `invalid_split` |
| `job_stage` | `annotation`, `validation` or `acceptance` | `invalid_job_stage` |
| `job_state` | `new`, `in progress`, `completed` or `rejected` | `invalid_job_state` |
| `issue_state` | `new` alone, or `open`/`resolved` values joined by ` \| ` (space, vertical bar, space) | `invalid_issue_state` |
| `task_name`, `task_updated_date`, `created_by_username`, `subset`, `source`, `issue_text`, `s3_image_path`, `image_path` | Text | `invalid_text` |

Except where a column is required above, an empty cell passes. Integral means
semantically integral: `12.0` passes, and large integers are compared without binary
floating-point rounding.

Row-level rules:

- A box needs all four coordinates (`missing_bbox`).
- An empty-image or deleted record has an empty label and all four coordinates empty
  (`invalid_negative`). In `cveta2` such a record has `instance_shape` `none` or
  `deleted`; in `clearml-yolo` it is any row whose label and coordinates are all empty,
  and a row with an empty label but some coordinate is invalid.
- Box geometry (`invalid_box_area`): in `cveta2`, width and height must be positive; in
  `clearml-yolo`, width and height must each exceed 2 pixels and the area must exceed 2
  square pixels. All values must be finite.

### Structural errors

A structural error rejects every row and stops further checks; only `schema` is
recorded as checked. Structural errors are:

- `invalid_header`: a DataFrame column name that is not a nonempty string, or repeated
  names (`verify_dataframe` only; CSV reading rejects these earlier);
- `missing_column` and `duplicate_column`, and any other error without a row position.

## Checks

Rows are grouped by image. In `cveta2` a group is one `image_name` within one `task_id`;
a row whose `task_id` is missing or not a nonnegative integer forms a separate unscoped
group, and an image that mixes scoped and unscoped rows gives one `unscoped_task`
warning. In `clearml-yolo` a group is one `image_name` across the whole file. A row
without a usable `image_name` is its own group.

Checks run in this order: schema, image identity, image files, image bounds, proposed
clipping (`clearml-yolo`), class conflicts (`clearml-yolo`), whole-image quarantine,
duplicates. A group that already has a row-level schema error is quarantined before the
identity and bounds checks, so those checks see only eligible groups. In
`clearml-yolo`, `negative_coordinate` waits until clipping has been tried.

| Code | Severity | Condition |
| -- | -- | -- |
| `mixed_image_kinds` | error | One group mixes boxes, empty-image rows and deleted rows |
| `path_conflict` | error | One image resolves to different local paths, or one canonical path belongs to several image names |
| `split_conflict` | error | One image has several splits |
| `invalid_local_path` | error | `image_path` is a URI (other than a Windows drive path) or cannot be resolved |
| `path_name_mismatch` | error | The resolved path's file name differs from `image_name` |
| `dimension_conflict` | error | Two dimension columns of a row, or two rows of one image, declare different sizes |
| `image_dimension_mismatch` | error | A declared size differs from the decoded size |
| `out_of_bounds` | error | A box leaves `0..width` x `0..height` of the known image size |
| `bounds_unchecked` | warning | Some boxes had no known image size |
| `rotation_ignored` | warning | Boxes with nonzero `rotation` are compared by their stored axis-aligned coordinates |
| `media_missing`, `media_unreadable` | error | Requested decoding found no file, an unreadable file, or no local path |
| `media_uninspected` | error | Decoding was requested but no inspection result exists for the row |
| `class_conflict` | error | `clearml-yolo`: two boxes of different labels in one image overlap at IoU `>=` threshold; both rows are reported |
| `image_quarantined` | error | Another rejected row of the same group rejected this row |
| `duplicate_row` | error | A later row equals an earlier retained row in every compared column |
| `high_iou` | error | A later box overlaps a retained box at IoU `>=` threshold |
| `exact_comparison_unavailable` | warning | A cell cannot be compared exactly; its value is kept and IoU is still checked |
| `bbox_clipped` | warning | A proposed clipping repair (see below) |
| `unknown_columns` | warning | `cveta2`: columns outside the known set |
| `empty_dataset` | warning | The table has no rows |

- Path resolution runs whenever the public functions verify, also without
  `check_images`: a nonempty `image_path` is used as given (with `~` expanded), an empty
  one is filled from `image_root` when set, and a relative path is joined to `base_dir`.
  URI paths are never downloaded.
- With `check_images`, each canonical file is decoded once with Pillow. EXIF orientations
  5 to 8 swap width and height. `cveta2` rows with `instance_shape` `deleted` are not
  decoded.
- The known image size is the decoded size when available, else the first complete pair
  of `image_width`/`image_height` or `width`/`height`.
- Any error on a row rejects every row of its group. Duplicate findings are the
  exception: `duplicate_row` and `high_iou` reject only the later row.
- Duplicates are compared in input order inside each retained group; the first row is
  the representative. `cveta2` compares full rows, including extra columns, and boxes
  regardless of label. `clearml-yolo` compares only its required columns, within one
  label. Empty-image and deleted rows take part only in exact comparison.

Check names recorded in `checked_checks`: `schema`, `image_identity`, `image_files`,
`upper_image_bounds`, `class_conflicts`, `full_row_duplicates`, `high_iou`. Bundle
preparation adds `class_policy`, `training_images`, `trainability`. `skipped_checks` can
contain `image_files` (decoding not requested), `upper_image_bounds` (some box without
a known size) and `full_row_duplicates` (exact comparison unavailable for some row).
`upper_image_bounds` can be both checked and skipped.

### Proposed clipping

Only `clearml-yolo` proposes repairs. An `out_of_bounds` box is clipped when all of
these hold:

- its group has no other error than `negative_coordinate` or `out_of_bounds`;
- the image size is known;
- every overflow beyond an image edge is strictly below 10 pixels;
- the clipped box still satisfies the `clearml-yolo` geometry rule.

Clipped coordinates are written as integers at the image edge, as text when the
original cell was text. The repair appears only in `clean`; `broken` and every report
keep the original values. After clipping, the schema is checked again on the final
coordinates. A row that cannot be clipped stays rejected with its group.

## Reports

`verify` with `output_dir` writes a new directory. An existing directory, or a
directory equal to the input CSV's directory, fails with `DatasetInputError`
(`Cannot write verification output: ...`). Files are serialized into a temporary
subdirectory first and then hard-linked into place.

| File | Written | Content |
| -- | -- | -- |
| `report.json` | Always | Report object below, UTF-8, two-space indentation |
| `broken.csv` | Always | Original rejected rows plus three metadata columns |
| `clean.csv` | Only with `clean=True` | Retained rows with accepted repairs |

`clean=True` without `output_dir` fails before reading the input
(`Explicit cleanup requires an output destination.`). With structural errors,
`clean=True` fails with
`Cannot write verification output: Structural errors cannot be cleaned away.` before
the directory is created.

| `report.json` key | Value |
| -- | -- |
| `profile` | `"cveta2"` or `"clearml-yolo"` |
| `is_valid`, `requires_cleanup`, `structural_errors` | Booleans |
| `counts` | Object with integers `input_rows`, `clean_rows`, `broken_rows`, `input_images`, `clean_images` |
| `clean_row_positions`, `broken_row_positions` | Arrays of original positions |
| `checked_checks`, `skipped_checks` | Arrays of check names |
| `issues` | Array of objects with the `Issue` fields |
| `metadata_columns` | Object mapping `row_position`, `reason_codes`, `reasons` to the appended `broken.csv` column names |

`broken.csv` appends `__validator_row_position`, `__validator_reason_codes` and
`__validator_reasons`; an underscore is appended to a name until it differs from every
input column. Reason codes and reasons are JSON arrays of the row's issue codes and
messages; with structural errors they also list every row-less error.

## Command line

```bash
cveta2 verify export/dataset.csv --profile cveta2 --output-dir inspection
cveta2 verify split.csv --profile clearml-yolo --check-images \
  --image-root /data/images --clean --output-dir cleaned
```

| Option | Meaning |
| -- | -- |
| `input` | CSV file, or the full-fetch directory with `--bundle` |
| `--profile {cveta2,clearml-yolo}` | Profile, default `cveta2`; ignored with `--bundle` |
| `--check-images`, `--image-root`, `--iou-threshold` (default `0.99`) | `ValidationOptions` fields; with `--bundle`, giving `--check-images`, `--image-root` or a threshold other than `0.99` fails |
| `--clean` | Accept repairs and removal of rejected rows |
| `--output-dir` | New report or bundle directory; required with `--clean` and `--bundle` |
| `--bundle` | Prepare a bundle |
| `--project`, `--dataset-name`, `--api-url`, `--local-root` (repeatable), `--s3-root` (repeatable), `--empty-class` (repeatable), `--accept-default-classes`, `--accept-class-changes` | Bundle preparation choices; any of them without `--bundle` fails with `Настройки публикации требуют --bundle.`; `--bundle` without `--project` fails with `Для --bundle укажите --project.`; both exit 2 (`Ошибка проверки: <message>`) |
| `--non-interactive` | Do not prompt for missing bundle decisions; ignored without `--bundle` |

- The command calls the API with `emit_warnings=False` and logs
  `Проверка: N строк; допустимых C, отклонённых B.` followed by one line
  `<code> строка <position>: <message>` per issue (the row part is omitted for row-less
  issues).
- `--clean` or `--bundle` without `--output-dir` fails with
  `Для --clean и --bundle требуется --output-dir.`

### Exit codes

| Code | `verify` | `verify --bundle` |
| -- | -- | -- |
| 0 | No structural error, and either no cleanup is required or `--clean` was given | The bundle is ready |
| 1 | Structural errors, or cleanup required without `--clean`; also cancellation (`Проверка отменена.`) | The bundle is not ready; cancellation |
| 2 | Input, option, configuration or write error, logged as `Ошибка проверки: <error>` | Same, including missing decisions that cannot be asked |

With `--clean` and structural errors the report cannot be written, so the exit code is
2.

## Bundle preparation

```bash
cveta2 verify export --bundle --output-dir prepared \
  --project CV/datasets --dataset-name reviewed \
  --api-url https://classes.example.org/api/classes \
  --local-root /data/images --s3-root s3://images/project \
  --empty-class 17 --accept-default-classes --accept-class-changes --non-interactive
```

### `PrepareOptions` and decisions

`PrepareOptions` rejects unknown fields and is frozen.

| Field | Default | CLI | Meaning |
| -- | -- | -- | -- |
| `project` | required | `--project` | Exact ClearML project name; must not be blank |
| `dataset_name` | `None` | `--dataset-name` | ClearML dataset name |
| `api_url` | `None` | `--api-url` | Class API; defaults to the parent's `api_url` |
| `local_roots` | `()` | `--local-root` | Approved local image directories, added to the parent's |
| `s3_roots` | `()` | `--s3-root` | Approved `s3://bucket/prefix` roots, added to the parent's |
| `class_empty` | `{}` | `--empty-class ID` (sets `True`) | Exclusion choice per class number |
| `accept_default_classes` | `False` | `--accept-default-classes` | New classes without a choice are kept (`empty: false`) |
| `accept_class_changes` | `False` | `--accept-class-changes` | Accept additions and renames relative to the parent |
| `clean` | `False` | `--clean` | Accept repairs and removal of rejected rows |

`Decision` has `kind`, `message`, `choices: tuple[str, ...]` and
`class_id: int | None`. Missing choices raise `MissingDecisions`; nothing is written:

| `kind` | Raised when | Message |
| -- | -- | -- |
| `dataset_name` | `dataset_name` is empty | `Укажите имя датасета ClearML.` |
| `api_url` | No `api_url` and no parent | `Укажите URL API классов.` |
| `class_changes` | A parent exists, the registry added or renamed classes and `accept_class_changes` is false | `Подтвердите изменения классов: <kind>: <name> (<number>), ...` |
| `class_empty` | A class added relative to the parent has no `class_empty` entry and `accept_default_classes` is false | `Исключать класс '<name>' (<number>)?` |
| `local_roots` | A `dataset.csv` image path lies outside every approved local root | `Укажите разрешённые каталоги изображений:` followed by the paths |

Without a parent every registry class counts as added, so each needs a `class_empty`
entry or `accept_default_classes`; `class_changes` arises only with a parent.

The CLI asks for missing decisions with prompts when stdin is a terminal,
`--non-interactive` is absent and `CVETA2_NO_INTERACTIVE` is not `true`; otherwise the
`MissingDecisions` message is the error (exit 2). Prompts: class decisions are yes/no
questions defaulting to no; a refused class change cancels (`Изменения классов не
подтверждены.`); uncovered paths offer their parent directories
(`Разрешить каталоги:`), and refusal cancels (`Корни изображений не подтверждены.`); an
empty name or URL cancels (`Подготовка отменена.`). After the answers the whole
preparation runs again.

### Preparation steps

1. Validate options; a blank `project` fails with `Укажите непустой проект ClearML.`
2. Read `dataset.csv`, `obsolete.csv`, `in_progress.csv` and `deleted.csv` from the
   source directory. Each must be a regular file, not a symlink; its bytes are captured
   once and parsed as described under "CSV reading". Each table needs `task_id` and
   `image_name` columns, even when header-only.
3. Find the parent dataset of the exact project and name and read its `dataset.yaml`
   (see [ClearML publication](clearml-publication.md)). A parent without `dataset.yaml`
   fails with `Родитель <id> не содержит dataset.yaml. Выберите новое имя датасета.`
4. Fetch the class registry from `api_url` and reconcile it with the parent's classes.
5. Check roots and image-path coverage of every `dataset.csv` row, before any row is
   filtered.
6. Validate `dataset.csv` with the bundle policy and derive the task manifest.
7. Write the preparation directory.

### Class registry

- `api_url` must be an HTTP(S) URL with a host and without embedded credentials;
  redirects are checked the same way. The request is an unauthenticated `GET` with
  `Accept: application/json` and a 30-second timeout.
- The response must be a JSON list of records with `id: int`, `number: int`,
  `name: str` (nonempty), `techClass: bool`, `isPeriodical: bool`, `isCritical: bool`
  and `threshold: float` (finite). Types are checked strictly; other fields are ignored.
  Failures: `Class API returned HTTP <code>; check the public endpoint`,
  `Class API request failed; check its URL, connectivity and timeout`,
  `Class API must return a JSON list of valid class definitions`.
- A class's identity is its `number`, stored as `prod_id`. A renamed class keeps its
  `empty` choice and gains the old name as an alias in `alt_names`; a name that returns
  to a former value is removed from the aliases.
- Duplicate numbers or names in the response, a parent `prod_id` absent from the
  response, and a name or alias that maps to two classes fail.
- `--empty-class` numbers unknown to the registry fail with
  `Неизвестные номера классов в настройках: [...]`.

### Roots

- Local roots are resolved (symlinks followed) and must be readable, listable
  directories. Every `image_path` in `dataset.csv` must be an absolute local path whose
  resolved form lies under an approved root; a relative or non-text path fails with
  `Upload image_path must be an absolute local path: ...`.
- Each approved S3 root is checked by a listing, as described under "S3 root check" in
  [ClearML publication](clearml-publication.md).
- Each nonempty `s3_image_path` must lie under at least one approved S3 root, and all
  matching roots must be in one bucket. An `s3://` path must match the root's bucket and
  prefix; a bucket-relative key is matched by prefix alone. Objects are not probed
  individually.
- Local and S3 roots are independent lists; neither is derived from the other.

### Bundle policy

The bundle policy runs `clearml-yolo` verification with image decoding always on and
the default IoU threshold, and adds:

| Code | Severity | Condition |
| -- | -- | -- |
| `unknown_class` | error | The label is no canonical name or alias |
| `empty_class` | error | The label's class has `empty: true` |
| `class_canonicalized` | warning | An alias was replaced by its canonical name |
| `training_image_format` | error | File extension, or decoded format, outside `avif`, `bmp`, `jp2`, `jpeg`, `jpg`, `mpo`, `png`, `tif`, `tiff`, `webp` (decoded `jpeg2000` is accepted) |
| `training_image_size` | error | The decoded image has a side shorter than 10 pixels |

- Labels are canonicalized before the class-conflict and duplicate checks.
- A class or training-image error rejects every row of the image in the whole file
  (`image_quarantined`, `Another rejected record quarantined this image.`). Rows
  rejected by the verification checks keep the rule above: their group is rejected,
  except that `duplicate_row` and `high_iou` reject only the later row.
- Blockers make a bundle unready regardless of `clean`:

| Blocker |
| -- |
| `Every input row must have a valid train, val or test split assignment.` |
| `Input CSV has structural validation errors.` |
| `No valid images remain for upload.` |
| `Required train split has no valid images.` / `Required val split has no valid images.` |
| `At least one valid training box is required.` |
| A task-manifest error, as its message |

- A val split of background images only is allowed.
- The bundle is ready when there is no blocker, no structural error, and either nothing
  requires cleanup or `clean` is true.

### Task manifest

`tasks.yaml` lists `included` and `obsolete` task IDs, both sorted and unique:

- `included`: the tasks of the retained rows. Every retained task/image pair must
  occur in `dataset.csv`.
- A task is completed when its rows say so: `task_completed` decides when present
  (boolean true or text `true` in any case); otherwise `job_stage` `acceptance` with
  `job_state` `completed`. Any unfinished row of a task, in any of the four tables, makes
  it not completed. A row of `in_progress.csv` also makes its task not completed unless
  its `task_completed` is explicitly true. Completed `deleted` rows in `in_progress.csv`
  (reopen markers) are ignored; pending deletions there count.
- `obsolete`: completed tasks that are not included and whose every image, as found in
  any of the four tables, also appears under a higher task ID that is completed or in
  `deleted.csv`. Validation
  rejection does not remove that evidence; a task that is only filtered out is not
  obsolete.
- Task IDs must be nonnegative integers and `image_name` nonempty in all four tables.

### Preparation directory

The directory must not exist and must lie outside the source directory; its parent is
created. Everything is staged in a temporary sibling and then hard-linked into place;
`preparation.sha256` is linked last, so a failed write never looks uploadable.

| Path | Written | Content |
| -- | -- | -- |
| `sources/dataset.csv`, `sources/obsolete.csv`, `sources/in_progress.csv`, `sources/deleted.csv` | Always | Exact captured source bytes |
| `report.json` | Always | Verification report without `metadata_columns`, plus the keys below |
| `broken-images.csv` | Always | Every original row of each image with a rejected row |
| `dataset.csv` | Ready only | Retained rows, canonical labels, accepted repairs; `\n` line endings |
| `dataset.yaml` | Ready only | Dataset metadata |
| `tasks.yaml` | Ready only | Task manifest |
| `preparation.json` | Ready only | Preparation record |
| `preparation.sha256` | Ready only | Hex SHA-256 of the `preparation.json` bytes and a newline |

Additional `report.json` keys: `blockers` (array of strings), `ready` (boolean),
`class_changes` (array of objects with `kind` `"added"` or `"renamed"`, `prod_id`,
`name`, `old_name` or `null`), `broken_image_rows` (integer).

| `dataset.yaml` key | Type and meaning |
| -- | -- |
| `api_url` | Public HTTP(S) class endpoint without credentials |
| `classes` | Map of canonical name to `ClassInfo` |
| `classes.<name>.prod_id` | Class API `number` |
| `classes.<name>.empty` | `bool`, default `false`: excluded from training |
| `classes.<name>.alt_names` | Nonempty former names, default empty |
| `images.local_root` | Approved local roots, canonical |
| `images.s3_root` | Approved S3 roots |

Metadata is read strictly: unknown keys, non-text or duplicate mapping keys and
recursive YAML aliases are rejected. Managed bundles add a `managed` section, described
in [managed datasets](managed-datasets.md).

| `preparation.json` key | Value |
| -- | -- |
| `format_version` | `1` |
| `options` | `PrepareOptions`, tuples as arrays, class-number keys as JSON object keys |
| `parent_id`, `parent_version` | Parent identity at preparation, or `null` |
| `source_hashes` | SHA-256 of each of the four source file names |
| `payload_hashes` | SHA-256 of `dataset.csv`, `dataset.yaml`, `tasks.yaml` |

The checksum detects accidental edits of the record; it is not a signature against a
deliberate rewrite by the machine's owner. Review the directory before publishing;
corrections go into the inputs or options and a new directory.

`PreparedDataset` has `directory`, `ready`, `validation` (`BundleValidation` with
`result`, `broken_images`, `blockers`), `metadata` and `tasks`.

The CLI logs the summary, the blockers and `Отчёт: <directory>`. When not ready it logs
`Набор не готов к публикации; исправьте исходные данные или явно разрешите очистку.`
and exits 1; when ready it logs
`Набор подготовлен. После проверки: cveta2 upload-dataset <directory>` and exits 0.

Preparation creates nothing remotely, but it reads ClearML (parent lookup, S3 root
listing) and the class API; the `clearml` extra requirement is described in
[ClearML publication](clearml-publication.md).
