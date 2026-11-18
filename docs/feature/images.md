# Images

`cveta2 fetch` and `cveta2 fetch-task` download the images their rows reference from
the S3 cloud storage attached to the CVAT project into a local image directory that
mirrors the S3 key layout. `cveta2 s3-sync` copies every object under a project's
storage prefix into the same directory, and `cveta2 setup-cache` configures where
those directories are. The Python counterparts are the `images_dir` /
`download_images` parameters of `cveta2.fetch` and `cveta2.fetch_task`, `cveta2.s3_sync`,
`CvatClient.download_images` and `CvatClient.sync_project_images`. Neither download nor
sync ever writes or deletes S3 objects. Image upload to S3 belongs to
[upload and project management](upload-and-project-management.md).

## Source storage

- The source is the project's own cloud storage (the project's `source_storage` in
  CVAT): its bucket, prefix and endpoint. Task storages are never used.
  `CvatClient.detect_project_cloud_storage` reads it once per project for the client's
  lifetime.
- The project's `sync_root` setting (`s3://bucket/prefix`, or a bare prefix in the
  project's bucket) replaces the bucket and prefix for fetch downloads and `s3-sync`;
  the endpoint stays the project's. `s3-sync --root` (`root=` in `cveta2.s3_sync`)
  overrides it for one run and requires `--project`
  (`Ошибка: --root требует явного указания проекта через --project.`). An override is
  logged as `Проект '<name>': корень синхронизации переопределён на s3://<bucket>/<prefix>`.
  A malformed root fails (`Некорректный sync root '<root>': отсутствует имя бакета.` or
  `… пустое значение.`). An override on a project without cloud storage warns and is not
  applied.
- Overrides never affect CVAT upload or the [annotation cache](annotation-cache.md)
  mirror.
- S3 credentials come from boto3's standard chain (`~/.aws/credentials`,
  `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`, profiles, IAM roles). cveta2 stores no
  S3 credentials. The S3 read timeout follows `CVETA2_DATA_TIMEOUT` /
  `cvat.request_timeout` and the connect timeout is 10 seconds
  ([connection and configuration](connection-and-configuration.md)).

## Where images are stored

The image directory of a project is resolved in this order:

1. `--images-dir DIR` (`images_dir=`), made absolute;
2. the project's `image_cache.<project name>` entry;
3. `<images_root>/<encoded project name>`, where `images_root` is the project's
   `cache.projects.<name>.images_root` or else `cache.images_root`.

- `--no-images` (`download_images=False`) skips the download and the resolution.
- With nothing configured, an interactive fetch asks
  `Укажите путь для кэширования изображений проекта '<name>': ` and saves the answer as
  `image_cache.<name>` in the personal configuration; an empty answer warns
  `Путь не указан — загрузка изображений пропущена.` and skips the download. A
  non-interactive fetch fails with
  `Ошибка: путь кэширования изображений для проекта '<name>' не настроен.` followed by
  `Укажите --images-dir, --no-images или добавьте image_cache.<name> в конфигурацию.`;
  the API raises `Cveta2Error` without prompting.
- `upload` and `s3-sync` use the same resolution; `convert` does not use `images_root`
  ([conversion and merge](conversion-and-merge.md)).
- Under `images_root` the project name becomes one directory component: `%`, `/`, `\`
  and NUL are percent-encoded (`%25`, `%2F`, `%5C`, `%00`), an empty name becomes
  `%empty`, and `.` / `..` have their dots encoded as `%2E`. Ordinary names keep their
  spelling. A path that would still leave the root fails with
  `Путь кэша проекта '<name>' выходит за корень <root>`. The logical project name is
  unchanged everywhere else.
- New directories and files are group-writable (0775 / 0664); `cveta2 doctor --cache`
  repairs existing ones ([connection and configuration](connection-and-configuration.md)).

### Local layout

- An image is saved at its S3 key relative to the storage prefix: frame `sub/img.jpg`
  under prefix `data/proj` is fetched from `data/proj/sub/img.jpg` and saved as
  `<dir>/sub/img.jpg`. A relative frame name that already starts with `<prefix>/` is
  taken as the full key, so frame `data/proj/sub/img.jpg` maps to the same key.
- With the project's `ignored_prefix` setting, only that leading part is stripped from
  the key instead of the storage prefix, keeping more of the hierarchy: with
  `ignored_prefix: data`, key `data/projA/2026-01/img.jpg` is saved as
  `<dir>/projA/2026-01/img.jpg`. A key that does not start with `ignored_prefix` is kept
  whole.
- A file lying flat in the directory root does not satisfy a nested key; that image is
  downloaded into its subdirectory.

## Download during fetch

- Download runs after all tasks are processed and before any CSV is written. The set is
  the unique `image_name` values of annotation and unannotated-frame rows; deleted
  frames are not downloaded. For each image the first row's nested frame name is used.
- An image whose expected local file already exists as a regular file counts as cached
  and needs no S3 request.
- Up to 2,000 uncached images are downloaded by a direct GET of their canonical key,
  without HEAD. Only a missing-key response (`NoSuchKey`, `NotFound`, `404`) moves the
  image to the listing fallback. Larger batches go to the listing directly.
- The listing fallback lists every object under the prefix and matches each image by
  its key relative to the prefix, then its full canonical key, then its basename. With
  several objects of one basename, the first key in sorted order wins. The found key
  becomes the row's `s3_image_path` and decides the local path: frame `img.jpg` found as
  `prefix/month/img.jpg` is saved as `month/img.jpg`. A later run repeats the GET and
  listing to rediscover that key, then finds the local file and does not download again.
- Images the listing cannot find are counted as failed and warned
  `Не найдены на S3 (<n> шт.): <names>` (first 10 names). An object that disappears
  between listing and download is counted as failed and warned
  `Объекты исчезли с S3 после listing: <names>`.
- A request-level failure on any image (access denied, missing credentials or profile,
  unreachable endpoint, other non-missing errors after retries) aborts the download and
  the fetch. A failure while reading the response body or writing the local file counts
  that image as failed, logs
  `Не удалось загрузить <name> (key=<key>): <error>` and lets the others continue.
- Transfers run up to `network.s3_workers` at a time; each worker holds one object in
  memory. Retryable S3 errors are retried ([connection and configuration](connection-and-configuration.md)).
  Files are written to a temporary sibling and renamed into place, so an interrupted
  write never leaves a partial file that a later run would treat as cached.
- Without project cloud storage every pending image counts as failed and the run warns
  `Project cloud storage не задан — все изображения помечены как failed. Укажите project_id при вызове download_images.`.
- The result is logged as
  `Изображения: <downloaded> загружено, <cached> из кэша, <failed> ошибок (всего <total>); прошло <s> с`.
  Failed images do not change the exit status of `fetch`.

### Paths in rows

After the download step every row, including deleted rows, gets:

- `s3_image_path`: the key found by the download, otherwise the canonical key under the
  storage prefix; set whenever the project has cloud storage, also with `--no-images`.
- `image_path`: the absolute resolved local path when the file exists in the image
  directory; empty with `--no-images` or when the file is absent.

Local paths are checked once per unique destination per run.

## `cveta2 s3-sync`

`cveta2 s3-sync [-p PROJECT] [--root ROOT]` downloads every object under a project's
storage prefix that is missing locally. `cveta2.s3_sync(project, target_dir, *,
root=None, connection=None)` syncs one project into an explicit `target_dir`, using the
configured `sync_root` (unless `root` is given) and `ignored_prefix`, and returns
`DownloadStats`.

- Without `--project` the command syncs every project named in `image_cache` or
  `cache.projects` that resolves to an image directory, in name order. With `--project`
  (ID, name or `ORG/NAME`) the project is resolved in CVAT first and its CVAT name
  selects the image directory, `ignored_prefix` and `sync_root`.
- No project to sync fails with
  `Ошибка: нет проектов для синхронизации — не настроены ни image_cache, ни cache.projects.`
  plus a hint to run `cveta2 setup-cache`. A requested project without an image directory
  fails with `Ошибка: для проекта '<name>' не настроен путь кэширования изображений.`.
- When syncing all projects, a project CVAT cannot resolve is logged and skipped; a
  project without cloud storage warns
  `Проект '<name>': cloud storage не найден — пропускаем.` and is skipped. Skipped
  projects are listed in `Синхронизация неполная: пропущены проекты [<names>]` and do not
  change the exit status.
- Every listed object is a candidate; objects are not filtered by extension. Keys ending
  in `/` (folder markers) are skipped. Supported image extensions matter only to
  [conversion and merge](conversion-and-merge.md) and
  [verification and bundles](verification-and-bundles.md).
- Before any write the complete key-to-destination mapping is validated. The whole sync
  fails without downloading when a key is not canonical (an empty, `.` or `..` segment,
  as in `root//a.jpg`), a destination leaves the image directory (including through an
  existing symlink), two keys resolve to one destination
  (`Объекты S3 '<key>' и '<key>' имеют одно назначение <path>`) or a destination lies
  inside another destination file (`Конфликт назначений S3: <path> вложен в другой файл`).
- Only an existing regular file counts as cached. A directory where a file should be is
  not removed; its download fails and is counted.
- A failure of one object is logged as one line and counted; the other transfers
  finish. After all projects, the command exits with an error that has one line per
  affected project:
  `Ошибка: проект '<name>': не удалось скачать <failed> из <total> объектов из s3://<bucket>/<prefix>. Повторите s3-sync: скачанные файлы будут пропущены.`.
  The API returns the counters instead of raising.
- `DownloadStats` has integer `downloaded`, `cached`, `failed` and `total`.

## S3 failures on the command line

- In `fetch`, `fetch-task`, `s3-sync` and `upload`, a request-level S3 failure (access
  denied, missing credentials or profile, unreachable endpoint and other botocore
  client, credential, region or transport errors) ends the command with exit status 1
  and `Ошибка S3 (<operation> s3://<bucket>/<prefix>): <error>`, without a traceback.
  The operation is `загрузка изображений из S3` for fetch downloads and `синхронизация`
  for sync.
- SDK errors that indicate a caller defect, such as parameter validation, are not
  translated and keep their traceback.
- The Python API raises the original botocore or boto3 exception; a note in
  `__notes__` names the operation and `s3://bucket/prefix`.

## Safe paths

- Frame names are relative POSIX paths inside the storage prefix. An absolute frame
  name is accepted only under the prefix; its leading `/` is dropped. Otherwise it fails
  with `Абсолютный путь изображения '<name>' находится вне настроенного корня '<prefix>'`.
- A key with an empty, `.` or `..` segment fails with
  `Небезопасный путь изображения '<name>': путь должен оставаться внутри настроенного корня хранилища`.
- A destination that resolves outside the image directory, including through an
  existing symlink, fails with
  `Небезопасный путь изображения '<name>': назначение находится вне локального кэша <dir>`.
- A key with a doubled separator is a distinct S3 object and is not collapsed.

## `cveta2 setup-cache`

`cveta2 setup-cache [--config PATH] [--reset] [--list]` configures image directories and
cache settings for every known project. It has no Python counterpart.

- `--list` logs every `image_cache` entry and the `cache` settings (`images_root`,
  `tasks_root`, and per project `ignored_prefix`, `task_cache_s3`, `images_root`,
  `tasks_root`), or `Пути кэша не заданы.`, without prompts or CVAT access. It works in
  non-interactive mode; every other use requires interactive mode.
- The project list comes from the local projects cache; when that is empty it is loaded
  from CVAT (`Кэш проектов пуст. Загружаю список с CVAT...`). No projects fails with
  `Нет доступных проектов.`.
- The command first asks for a cache root. With a root it shows each project's default
  path and asks once to apply all of them. The default is the project's existing
  `image_cache` path, or `<root>/<encoded project name>` with `--reset` or when none
  exists. Otherwise it asks per project, and Enter keeps the default or skips a project
  without one.
- It then saves a given root as `cache.images_root`, asks for `cache.tasks_root` and,
  optionally, each project's `ignored_prefix` and `task_cache_s3`, which are written to
  the shared project configuration
  ([connection and configuration](connection-and-configuration.md)).
