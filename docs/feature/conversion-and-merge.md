# Conversion and merge

Conversion and merge work on local files only and need no CVAT, S3 or ClearML access.
`cveta2 convert` translates between the cveta2 CSV and detection formats in three
directions: `--to-yolo` (API `cveta2.convert_to_yolo`) writes an ultralytics YOLO
dataset, `--to-coco` (API `cveta2.convert_to_coco`) writes a COCO detection dataset,
and `--from-yolo` (API `cveta2.convert_from_yolo`) reads a YOLO dataset or bare YOLO
predictions back into a cveta2 CSV. `cveta2 merge` (API `cveta2.merge`) combines an
old and a new dataset CSV, removing deleted and reopened images. The CSV columns are
defined in [fetch and partition](fetch-and-partition.md); the files `deleted.csv` and
`in_progress.csv` that merge consumes are produced there.

## Convert

### Inputs

| CLI | API | Meaning |
| --- | --- | --- |
| `--to-yolo` / `--from-yolo` / `--to-coco` | function name | Direction; exactly one is required |
| `--dataset/-d CSV` | `dataset` | Source CSV for `--to-yolo` and `--to-coco` |
| `--input/-i DIR` | `input_dir` | YOLO directory for `--from-yolo` |
| `--output/-o PATH` (required) | `output_dir` / `output_csv` | Output directory, or output CSV for `--from-yolo` |
| `--link-mode MODE` | `link_mode="auto"` | Image placement for exports |
| `--image-dir DIR ...` | `image_dirs=None` | Extra image search directories |
| `--names-file YAML` | `names_file=None` | Class names for prediction import |
| `--read-all-sizes` | `read_all_sizes=False` | Measure every image on import |

Without `-d` an export fails with
`Ошибка: для --to-yolo / --to-coco укажите --dataset / -d.`; without `-i` an import
fails with `Ошибка: для --from-yolo укажите --input / -i.` The API functions return the
output directory (exports) or the output CSV path (import).

### Export input checks

Every check below runs before the output directory is created or changed.

- The CSV needs `image_name`, `instance_shape` and `split`. Only rows with
  `instance_shape` `box` or `none` are exported; deletion rows are ignored.
- Every exported row needs `split` equal to `train`, `val` or `test`. Empty values fail
  with `Ошибка: у <N> изображений не задан split. Примеры: ...`; other values fail with
  `Ошибка: недопустимый split [...]: <images>. Допустимы train, val, test.`
- `image_width` and `image_height` are required columns, and `instance_label` plus the
  four box columns are required when box rows exist:
  `Ошибка: в <csv> отсутствуют столбцы: [...]`.
- `image_name` must be a nonempty bare file name: no directory, not `.` or `..`, no
  backslash or NUL byte. Otherwise
  `Ошибка: некорректное имя изображения в <csv>: '<name>'`.
- Width and height must be finite positive integers:
  `Ошибка: некорректный размер '<name>' ... в <csv>`.
- A box row needs a nonempty label (`Ошибка: не задан класс '<name>' в <csv>`) and finite
  coordinates with `bbox_x_br > bbox_x_tl` and `bbox_y_br > bbox_y_tl`
  (`Ошибка: некорректный bbox '<name>' в <csv>`). A box already zero-sized or inverted
  in the CSV therefore stops the export.
- CSV read failures (missing file, empty file, NUL byte, parse or decode error) are
  `Cveta2Error` messages that name the file.

### Class mapping

The class map is built from the sorted distinct labels of the box rows. YOLO class IDs
start at 0 and COCO category IDs at 1. Labels are kept literally; the map is logged.

### Image discovery and placement

- Search roots for exports and for prediction import are the explicit image directories
  followed by every directory listed in the personal `image_cache` section (all
  projects, without duplicates). `cache.images_root` is not used. Dataset-mode import
  uses neither; it reads images from the paths in `dataset.yaml`.
- Images are looked up by name with the rules described in
  [upload](upload-and-project-management.md). For exports, files and directories whose
  real location lies inside the output directory are never used as a source, and a
  search root inside the output directory is skipped with a warning.
- Images that are not found are listed in one warning
  (`Не найдено <N> изображений: ...`); their labels and metadata are still written.
- Link modes: `auto` (default) and `reflink` try a reflink and fall back to a copy,
  warning once per run; `hardlink` hard-links, `symlink` links to the resolved source,
  `copy` copies with metadata. Any other mode fails with
  `Неизвестный link-mode: '<mode>'`.
- A destination that already is the same file as the source (and is not a symlink) is
  kept as it is. Any other existing destination is replaced, so a repeat export refreshes
  image bytes.

### YOLO export

Layout:

```
<output>/
  images/<split>/<image_name>
  labels/<split>/<image stem>.txt
  dataset.yaml
```

- `dataset.yaml` has `path` (the resolved absolute output directory), one key per
  exported split among `train`, `val`, `test` with value `images/<split>`, and `names`
  mapping class ID to label. It is written with ASCII escapes, so non-ASCII label names
  appear escaped.
- Each label line is `<class_id> <xc> <yc> <w> <h>` with six decimals, normalized by the
  row's image size; a file with lines ends with a newline. Files are written as UTF-8
  with `\n` line endings.
- Clipping: each corner of a box is clamped to `[0, width] x [0, height]`. A box whose
  formatted width or height is `0.000000` after clipping and rounding is left out, also
  when it lies inside the image. The image is still exported, with an empty label file
  when no box remains. The run ends with warnings
  `Боксы, выходящие за границы изображения, обрезаны по ним: <N> (...)` and
  `Пропущены боксы с нулевой шириной или высотой после обрезки или округления: <N> (...)`.
  Every written line satisfies the import ranges below.
- An image with only `none` rows gets an empty label file; a `none` row never empties a
  label file that box rows of the same image and split wrote.
- An image that appears in several splits is placed once, in the first split written,
  while each of its splits gets a label file.

Output safety, checked before the first write:

- `labels/`, `labels/<split>/`, each target label file and `dataset.yaml` must not be
  symlinks, and existing ones must be a directory or a regular file respectively:
  `Ошибка: небезопасный каталог разметки YOLO: <path>` or
  `Ошибка: небезопасный путь вывода YOLO: <path>`.
- A symlinked `images/` or `images/<split>/` is accepted only when every image to place
  there already exists as a regular file that is the same file as its source, so no
  write goes through the link. Otherwise
  `Ошибка: небезопасный каталог изображений YOLO: <path>`.
- A symlinked directory above the output directory is allowed.

Re-export cleanup: after writing, cveta2 treats every first-level subdirectory of
`images/` and `labels/` as its own. It removes each file or file symlink there whose
extension (case-insensitive) is `.jpg`, `.jpeg`, `.png`, `.bmp`, `.tiff` or `.webp`
under `images/`, or `.txt` under `labels/`, and that is not part of the current export.
No record of an earlier export is needed. Files with other extensions, files directly in
`images/` or `labels/` or deeper in the tree, and the contents of a symlinked `images/`,
`labels/` or split directory are left untouched. Source images are never removed.
`dataset.yaml` is written last.

### COCO export

Layout (`val` is written to `valid`):

```
<output>/
  train/_annotations.coco.json, train/<image_name>
  valid/_annotations.coco.json, valid/<image_name>
  test/_annotations.coco.json,  test/<image_name>
```

Each `_annotations.coco.json` (UTF-8, Unicode kept, indent 2):

| Key | Records |
| --- | --- |
| `images` | `id` (1, 2, ... in sorted name order), `file_name`, `width`, `height` |
| `annotations` | `id` (1, 2, ... in row order), `image_id`, `category_id`, `bbox` `[x, y, w, h]`, `area`, `iscrowd: 0` |
| `categories` | `id`, `name`, `supercategory: "none"`, ordered by `id` |

`bbox` values and `area` are rounded to two decimals. COCO export does not clip boxes.

Replacement and ownership, checked before any write:

- The output directory and its ancestors must not be symlinks
  (`Ошибка: каталог COCO является ссылкой: <path>`); `train`, `valid`, `test` must be
  real directories when present, and their `_annotations.coco.json` must not be a
  symlink.
- An existing `_annotations.coco.json` is the ownership record of its split: it must
  parse as an object with an `images` list whose `file_name` values are unique bare
  names other than `_annotations.coco.json`. Unreadable, ambiguous or unsafe metadata
  stops the export with an error naming the file.
- An image named `_annotations.coco.json` is rejected. A destination that already exists
  and is not owned by the previous export stops the export:
  `Ошибка: путь не принадлежит предыдущему экспорту COCO: <path>`.
- After writing, owned files that are not part of the current export are removed, and an
  owned split directory left empty is removed. Unrelated files are kept.

No rollback is promised: an unexpected I/O failure during writing can leave partial
output, and the error is reported.

### YOLO import (`--from-yolo`)

The mode is chosen by `<input>/dataset.yaml`: dataset mode when the file exists,
prediction mode otherwise.

Label line rules (both modes): blank lines are ignored. A line needs at least five
numeric fields, all finite; the class ID must be a nonnegative integer, `xc` and `yc`
in `[0, 1]`, `w` and `h` in `(0, 1]`, and an optional sixth field (confidence) in
`[0, 1]`. Fields beyond the sixth must be finite and are ignored, with one warning per
file. An invalid line is skipped with
`Пропущена некорректная строка <path>:<line>: '<text>'` and a per-file count; valid
lines of the same file are kept. A label file that cannot be read as UTF-8 is skipped
with a warning, and the number of such files is reported at the end.

Dataset mode:

- `dataset.yaml` must be a mapping (`Ошибка: <path> не содержит YAML-словарь`) with
  `names` as a list (position is the ID) or a mapping from nonnegative integer or ASCII
  decimal string keys to unique nonempty names. Missing names fail with
  `Ошибка: в <path> не найдены имена классов (names)`; malformed ones name the entry.
  YAML read and syntax failures name the file.
- `path` is the dataset root: absent or empty means the YAML's directory, a relative path
  is resolved from the YAML's directory, `~` is expanded.
- Splits are read in the order `train`, `val`, `test`; an absent split is skipped. A
  split value is a path or a list of paths, relative to the root. A directory is
  searched recursively for the image extensions above (case-insensitive, sorted); a
  `.txt` file lists images, one per line, absolute, `./`-relative to the list file or
  otherwise relative to the root; an image file is used directly. A missing source
  warns. Images are deduplicated by resolved path.
- A listed image that does not exist is skipped with a warning. The label file is the
  image path with its last `images` component replaced by `labels` and the suffix
  `.txt`, or the same path with `.txt` when there is no `images` component. Symlinked
  images keep the dataset's own label path. An image without a label file, or whose
  label file has no valid line, becomes one `none` row. An image whose label file
  cannot be read as UTF-8 produces no row and is counted in the unreadable-file warning.
- An unreadable split list stops the import with the file named.

Prediction mode:

- Every `*.txt` under the input directory, recursively and sorted, is a label file; none
  fails with `Ошибка: не найдено .txt файлов в <dir>`.
- Class names come from `--names-file`: a YAML mapping with a `names` key, or a mapping
  itself, in the same `names` forms as above. A missing file fails with
  `Ошибка: файл имён классов не найден: <path>`. Without a names file, every ID becomes
  the label `class_<id>`.
- A label file without a valid line produces no row. Its image is found by the label
  stem in the input directory, then each search root, each with its `images/`
  subdirectory, matching the image extensions above plus `.tif` case-insensitively.
  Labels without an image are skipped and listed in one warning. Predicted rows have no
  `split`; the sixth field fills `confidence`.

Both modes:

- A class ID with no entry in the class names becomes the label `class_<id>`.
- An image that cannot be opened when its size is read (the first image that produces
  rows, or every such image with `--read-all-sizes`) stops the import with
  `Ошибка: не удалось прочитать изображение <path>: ...`.
- Image size is read from the first image and reused for all images unless
  `--read-all-sizes` is given. A nonpositive size fails with
  `Ошибка: некорректный размер изображения '<name>' (<w>x<h>). Ширина и высота должны быть положительными.`
- Output rows follow the cveta2 column order. `image_name` is the image file name,
  `frame_id` counts images from 0 and `annotation_id` counts boxes from 1. Box rows have
  pixel coordinates rounded to two decimals, `occluded=False`, `z_order=0`,
  `rotation=0.0`. Every row has `task_id=0`, `task_name="yolo"`, `source="yolo"`,
  `attributes` `{}` and empty `job_stage`, `job_state`, `task_updated_date`,
  `created_by_username` and `subset`.

## Merge

### Inputs

| CLI | API `merge(...)` | Meaning |
| --- | --- | --- |
| `--old PATH` (required) | `old` | Base dataset CSV |
| `--new PATH` (required) | `new` | Newer dataset CSV |
| `--output/-o PATH` (required) | `output` | Merged CSV; parent directories are created |
| `--deleted PATH` | `deleted=None` | Images to remove from the result |
| `--in-progress PATH` | `in_progress=None` | `in_progress.csv` of the new fetch |
| `--by-task` | `by_task=False` | Resolve conflicts by task ID |

- `old` and `new` need `image_name`, `instance_shape`, `instance_label` and the four box
  columns. With `--by-task` both also need `task_id`:
  `Ошибка: --by-task требует столбец 'task_id' в <path>, но он отсутствует.`
- `--deleted` is a CSV whose first nonblank line contains `image_name`, or a plain list
  with one image name per line. Names are read literally (`NA` stays a name).
- `--in-progress` needs an `image_name` column.
- The API returns the merged `DataFrame` and writes the same file as the CLI.

### Rules

- Images are identified by `image_name`, and every decision applies to all rows of an
  image. The result holds the kept rows of `old` followed by the kept rows of `new`,
  each in file order, with the union of both files' columns.
- An image only in `old` or only in `new` keeps its rows.
- An image in both files keeps the rows of one side. By default `new` wins. With
  `--by-task`, the side whose largest numeric `task_id` for that image is larger wins;
  a tie, or a side without a usable `task_id`, gives the image to `new`.
- Every name in `--deleted` is removed from both sides.
- Reopened images: with `--in-progress`, an image that has at least one row there with
  an explicitly true `task_completed` (a boolean true or the text `true` in any letter
  case) loses its `old` rows. Its `new` rows are kept unless `--by-task` gave the image
  to `old`; then the image has no rows in the result. Other rows of the file
  remove nothing, and a file without `task_completed` removes nothing. Without
  `--in-progress` nothing is removed for this reason.
- Split carry-over: when `old` has a nonempty `split` for an image, every merged row of
  that image with an empty `split` receives the first nonempty `old` value. When `old`
  has no `split` values the merge warns
  `В old-датасете нет данных split — пропагация split невозможна` and fills nothing.
  When `new` also has a split for a shared image that `old` assigns, the merge warns and
  the winning side's value stays.
- The log reports counts of images only in old, only in new, conflicts won by each side,
  deleted, reopened and the total row count.
