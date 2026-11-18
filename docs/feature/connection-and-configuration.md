# Connection and configuration

cveta2 reads its settings from a personal file, an optional shared file, environment
variables and a bundled preset, opens one CVAT session per command or API call, and
applies one retry, timeout and concurrency policy to every CVAT and S3 request. The
commands are `cveta2 setup` (personal credentials, attaching a shared file, migrating
a legacy file) and `cveta2 doctor` (local configuration and cache diagnosis). Every
command that talks to CVAT selects a project with `--project` / `-p`; the Python API
takes the same project spec as `project=` and the connection as
`connection=cveta2.Connection(...)` (see [Python API](python-api.md)).

## Project and organization selection

A project spec is a numeric ID, a project name, or `ORG/NAME`.

| Spec | Meaning |
| -- | -- |
| `123`, `"123"` | Project ID 123 in the session organization |
| `"Name"` | Project named `Name` in the session organization |
| `"org/Name"` | Switch the session to organization `org`, then resolve `Name` |
| `"/Name"` | Switch the session to the personal workspace, then resolve `Name` |

- Only the first `/` separates the organization; leading and trailing spaces around
  both parts are stripped. An empty name part (`"org/"`, `"/"`) fails with
  `Некорректная спецификация проекта '<spec>': ожидается ORG/PROJECT или /PROJECT.`
- The organization prefix switches the session organization for every later CVAT
  request of that client. A spec without a prefix keeps the configured organization.
- A decimal spec is an ID and is never looked up by name. Its display name comes from
  the local projects cache when the cache holds the ID, otherwise from one project
  request; when that request fails the ID itself becomes the name. The name keys the
  ignore list, the image-cache directory and log lines.
- A name is matched case-insensitively against the projects of the session
  organization and resolves to CVAT's own spelling of the name. A connected client
  always lists the organization's current projects, so a stale cache cannot hide a
  duplicate name. Several matches fail before any change with
  `Имя проекта '<name>' неоднозначно: id=[<ids>]. Укажите числовой ID проекта.`;
  no match raises `ProjectNotFoundError` (`Project not found: '<name>'`).
- Without `--project`, interactive commands show a project picker with one page per
  organization. The first page is the configured organization (or the personal
  workspace); `→ Следующая организация: <name>` moves to the next page and
  `↻ Обновить список проектов с CVAT` rescans all organizations. The picker reads the
  projects cache and scans CVAT when the cache is empty; choosing a project switches
  the session organization. When a command echoes its re-run command, `-p` carries
  the `ORG/` prefix (`/` for the personal workspace) if the session organization
  differs from the configured one.
- `ignore` without `-p` instead offers a flat list of the project names known from the
  projects cache and the ignore lists, without organization pages or rescan, and exits
  with `Нет известных проектов. Укажите --project или запустите cveta2 fetch для заполнения кэша.`
  when there are none.
- `fetch-task` and `cveta2.fetch_task` without a project take the project of the first
  numeric task ID; see [fetch and partition](fetch-and-partition.md).

### Personal workspace

An organization of `null` or `""` means the personal workspace, in the shared file, in
the personal file and in `Connection(organization="")`. An empty `CVAT_ORGANIZATION`
is treated as unset: it does not override the organization from a file. A personal
value never overrides a nonempty shared organization (see Source precedence below).

### Projects cache

`projects.yaml` beside the selected personal file caches project lists per
organization:

```yaml
organizations:
- slug: ""            # personal workspace
  name: Личное пространство
  projects:
  - id: 1
    name: proj
```

A missing or unreadable cache is empty; invalid entries are skipped with a warning.
The cache only names projects and fills the picker; a connected client re-reads
projects for name resolution. The data commands use the cache beside the default or
`CVETA2_CONFIG` personal file.

## Configuration files

### Personal file

Default path `~/.config/cveta2/config.yaml`. It holds credentials, local paths and
runtime settings:

| Key | Content |
| -- | -- |
| `schema_version` | `1` for a file that references a shared file |
| `project_config` | Path of the shared file |
| `cvat.username`, `cvat.password` | CVAT credentials |
| `cvat.request_timeout` | HTTP read timeout in seconds (see Request timeouts) |
| `image_cache`, `cache.images_root`, `cache.tasks_root`, `cache.projects.<name>.images_root`, `cache.projects.<name>.tasks_root` | Local image and annotation-cache roots ([images](images.md), [annotation cache](annotation-cache.md)) |
| `network.s3_workers`, `network.cvat_workers`, `network.retry_attempts`, `network.retry_max_wait` | Concurrency and retry budget |
| `upload.images_per_job`, `upload.image_quality` | Upload defaults ([upload](upload-and-project-management.md)) |

- A `schema_version: 1` file accepts only the keys above. Any other top-level key,
  `cvat.host`, `cvat.organization`, a shared section or `ignored_prefix` /
  `task_cache_s3` under `cache.projects` fails with
  `Shared project policy/identity cannot be stored in personal configuration` or
  `Personal configuration contains unsupported/shared sections`, even when the value
  equals the shared one. An unknown `cvat` key fails with
  `Unknown personal CVAT setting`. A `schema_version: 1` file without
  `project_config` fails with
  `Versioned personal configuration requires a shared project_config reference`.
  Other `schema_version` values fail.
- A legacy file (no `schema_version`) that holds only connection settings, local paths
  and runtime settings stays usable by standalone commands while no shared file is
  selected. A legacy file with project policy (`projects`, `datasets`, `sync_roots`,
  `ignore`, `clearml`, or `ignored_prefix` / `task_cache_s3` under
  `cache.projects`), or with `cvat.host` / `cvat.organization` while a shared file is
  selected, raises `MigrationRequired`:
  `Legacy mixed configuration requires verification: cveta2 setup --migrate-config`.
- The personal file is written atomically with mode `0600`; a failed write leaves the
  previous file intact. When a file with a password is readable by group or others,
  loading restricts it to `0600` and warns
  `Права файла с паролем <path> ограничены до 0600.`; a file owned by another user is
  only reported.

### Shared file

The shared file is the team's authority for CVAT identity and project policy and holds
no credentials or local paths:

```yaml
schema_version: 1
cvat:
  host: https://cvat.example.org
  organization: team
projects:
  main:
    id: 12
    name: Main project
    sync_root: s3://images/main
    ignored_prefix: images/
    task_cache_s3: s3://cache/main
    ignore: []
datasets: {}
```

| Key | Rule |
| -- | -- |
| `cvat.host` | HTTP(S) URL without user or password; trailing `/` removed |
| `cvat.organization` | Organization slug; `null` or `""` is the personal workspace |
| `projects.<key>` | `<key>` matches `[A-Za-z0-9][A-Za-z0-9_-]*`; `id` is unique across projects |
| `projects.<key>.name` | CVAT project name used by name-keyed readers |
| `projects.<key>.sync_root`, `.task_cache_s3` | `s3://bucket[/prefix]` or a nonempty bare prefix ([images](images.md), [annotation cache](annotation-cache.md)) |
| `projects.<key>.ignored_prefix` | S3 prefix not mirrored locally ([images](images.md)) |
| `projects.<key>.ignore` | Records with `id` (nonnegative integer) and optional `name`, `description`, `silent` ([upload and project management](upload-and-project-management.md)) |
| `datasets` | Managed dataset definitions ([managed datasets](managed-datasets.md)) |

- Unknown keys anywhere fail validation, as do duplicate or non-string mapping keys and
  recursive aliases. A project key or project name that maps to two different IDs fails
  with `Ambiguous shared project name: <name>`.
- Invalid content fails with
  `Invalid shared project configuration <path>; fields: <field paths>`; the message
  names fields, never values.
- When a shared file is selected, the CVAT host and organization come only from it,
  and the per-project `sync_root`, `ignored_prefix`, `task_cache_s3` and `ignore`
  values come only from it. Personal `image_cache` entries and local cache roots stay
  personal and are matched to shared projects by key or name.

### Writing shared policy

Commands that change project policy (`ignore` and `cveta2.ignore` editing `ignore`,
`setup-cache` editing `ignored_prefix` and `task_cache_s3`) write the shared file; they
never create a personal override.

- Only the fields the command changed since it loaded the configuration are written;
  concurrent changes to other projects or fields survive.
- When another process set one of those fields to a different value in the meantime,
  the save fails with
  `Shared configuration <path> changed since it was loaded: project '<name>', field <field>; reload and repeat the change`.
  When the file changed during the save, it fails with
  `Shared configuration <path> changed during this save; reload and repeat the change`.
- The save takes a nonblocking OS lock on `.<file name>.lock` beside the shared file.
  A held lock fails with
  `Cannot lock shared configuration <path>; another writer may be active. Retry the change.`
  Closing the file or ending the process releases the lock; the lock file stays in
  place and must not be removed while commands run. A lock path that is a symlink or
  not a regular file fails.
- A shared file without write permission bits fails with
  `Shared project configuration is read-only: <path>`. The replacement keeps the
  file's mode and group.
- Without a shared file, saving `sync_roots` or `ignore` policy raises
  `MigrationRequired`
  (`Project policy requires shared configuration; attach it with setup --project-config`),
  and saving `ignored_prefix` / `task_cache_s3` raises
  `Shared cache policy requires a shared project configuration`.

### Preset

The bundled preset `cveta2/presets/default.yaml` supplies the lowest-priority
`cvat.host` (`http://localhost:8080`); only its `cvat` section is read. The upload
defaults (`images_per_job` 100, `image_quality` 100) are built-in model defaults. The
preset never replaces a selected shared file.

## Source precedence

| Setting | Order, first wins |
| -- | -- |
| Personal file | `--config` (only `setup`, `setup-cache` and `dataset` commands), `Connection.config_path` or `config_path=` → `CVETA2_CONFIG` → `~/.config/cveta2/config.yaml` |
| Shared file | `--project-config` or `project_config=` (managed commands and `setup`) → `CVETA2_PROJECT_CONFIG` → `project_config` in the personal file |
| Host, organization, username, password | API `Connection` field → environment → personal file → preset; with a shared file, host and organization come from the shared file |
| Request timeout | `CVETA2_DATA_TIMEOUT` → `cvat.request_timeout` |
| Workers and retry attempts | Environment variable → `network` section → default |

- Exactly one shared file is loaded. A saved relative `project_config` resolves from the
  personal file's directory; an explicit path and `CVETA2_PROJECT_CONFIG` resolve from
  the working directory; `~` is expanded.
- A missing, unreadable or invalid selected shared file fails; cveta2 never falls back
  to another shared source. A missing personal file is read as empty configuration; an
  unreadable or malformed one fails. An empty or non-string `project_config` fails with
  `project_config must be a nonempty file path`.
- Empty values never override: an empty environment variable or a `Connection` field
  of `None` or `""` leaves the lower source in place. The exception is
  `Connection(organization="")`, which selects the personal workspace. With a shared
  file selected, any `Connection.host` or `Connection.organization` that is not `None`,
  including `""`, must equal the shared identity or the call fails (below).
- With a shared file, `CVAT_HOST` or a nonempty `CVAT_ORGANIZATION` that differs from
  the shared identity fails with
  `CVAT identity environment overrides conflict with shared project configuration`;
  a differing `Connection.host`, `Connection.organization` or injected client fails
  with `Explicit host cannot override shared CVAT identity`,
  `Explicit organization cannot override shared CVAT identity` or
  `Injected client conflicts with shared CVAT identity`. Credentials, timeouts and
  network settings keep their own overrides.
- Malformed personal YAML fails with
  `Ошибка чтения YAML-конфигурации <path>: <error type>, строка <N>, столбец <M>.`;
  the shared-file reader fails with
  `Cannot read configuration <path>: <error type>, line <N>, column <M>`. Neither
  message quotes file content. The original parser exception is the `__cause__`.
- Credential errors name the personal file the configuration came from:
  `Учётные данные CVAT не настроены. Задайте CVAT_USERNAME и CVAT_PASSWORD или заполните cvat.username/password в <path>.`
- Interactively, every CLI command outside `cveta2 dataset` that talks to CVAT prompts
  for a missing username or password for that run and does not save the answer.
  `cveta2 dataset fetch`, `report-errors` and `publish` never prompt: missing
  credentials fail with the message above in either mode.

## Environment variables

| Variable | Effect |
| -- | -- |
| `CVETA2_CONFIG` | Personal file path |
| `CVETA2_PROJECT_CONFIG` | Shared file path |
| `CVAT_HOST`, `CVAT_ORGANIZATION` | Connection identity for standalone use; must match a selected shared file |
| `CVAT_USERNAME`, `CVAT_PASSWORD` | CVAT credentials |
| `CVETA2_DATA_TIMEOUT` | Read timeout in seconds; a non-number warns and is ignored |
| `CVETA2_S3_WORKERS`, `CVETA2_CVAT_WORKERS` | Worker counts; an integer below 1 or a non-integer warns and is ignored |
| `CVETA2_RETRY_ATTEMPTS` | Attempt budget; an integer below 2 or a non-integer warns and is ignored |
| `CVETA2_NO_INTERACTIVE` | `true` (any case) turns prompts into errors |
| `CVETA2_DISABLE_CACHE` | `true` (any case) disables the annotation cache ([annotation cache](annotation-cache.md)) |
| `CVETA2_RAISE_ON_FAILURE` | `true` (any case) aborts fetch on the first per-task 5xx |

`network.retry_max_wait` has no environment override.

## Non-interactive mode

With `CVETA2_NO_INTERACTIVE=true` every prompt raises `InteractiveModeRequiredError`:
`Interactive prompt required but CVETA2_NO_INTERACTIVE=true. <hint>`, where the hint
names the flag or variable to use instead. A prompt that meets closed standard input
raises the same error type with
`Interactive prompt required but standard input is closed. <hint>`. The variable unset
or any other value keeps interactive mode.

| Command | Non-interactive behavior |
| -- | -- |
| CVAT commands outside `cveta2 dataset` | A missing username fails with hint `Задайте CVAT_USERNAME/CVAT_PASSWORD.`, a missing password with `Задайте CVAT_PASSWORD.` |
| `setup` | Fails, except `setup --project-config PATH` |
| `setup-cache` | Fails, except `setup-cache --list` |
| `fetch`, `labels`, `ignore`, `upload`, `whats-new`, `task …` | A missing `-p` fails instead of opening a project picker (`s3-sync` without `-p` syncs every configured project and needs no picker) |
| `fetch` | An existing output directory is overwritten after the info message `Папка <dir> уже существует — перезапись (неинтерактивный режим).` |
| `fetch-task` | Writes into an existing output directory without a message, in either mode; fails without task values |
| `fetch`, `fetch-task` | An unconfigured image directory fails ([images](images.md)) |
| `upload` | Requires `-p`, `--name` and `--labels` ([upload](upload-and-project-management.md)) |
| `labels` | Only `--list` works |
| `ignore` | Only `--add`, `--remove` and `--list` work |
| `task drop-label`, `task delete` | Require `--yes` |
| `verify`, `dataset prepare` | Never overwrite an existing output directory ([verification](verification-and-bundles.md), [managed datasets](managed-datasets.md)) |

The Python API never prompts in either mode; see [Python API](python-api.md).

## Retries

Every CVAT call and S3 request runs under one retry mechanism: up to
`network.retry_attempts` attempts in total (default 5, minimum 2), with exponential
backoff starting at 1 second plus up to 1 second of random jitter, capped at
`network.retry_max_wait` seconds (default 30.0). A CVAT `Retry-After` header with a
finite nonnegative number of seconds replaces the backoff, capped at the same maximum;
a negative, nonfinite or non-numeric value or an HTTP date keeps the ordinary backoff.
Before each pause cveta2 logs
`<label>: попытка cveta2 <N>/<M> не удалась; повтор через <S> с: <diagnostics>`, with
label `CVAT API`, `CVAT write`, `CVAT idempotent write` or `S3`. The count covers only
cveta2's own attempts.

| Request kind | Operations | Retried on |
| -- | -- | -- |
| CVAT read | Listings, task, job, annotation, metadata and issue reads | HTTP 429, 500, 502, 503, 504 and transport errors |
| CVAT non-idempotent write | Task creation, data attachment, adding shapes, creating issues, deleting shapes or tasks, label changes | HTTP 429 only |
| CVAT idempotent write | Replacing deleted frames, updating a job's stage/state | HTTP 429, 500, 502, 503, 504 |
| S3 | Object reads and existence checks, image downloads, image uploads, annotation-cache and managed-source reads (listings rely on botocore retries only) | Error codes `SlowDown`, `RequestTimeout`, `RequestTimeTooSkewed`, `InternalError`, `503` and transport errors |

- A 429 means CVAT refused the request, so it is safe to repeat. A 5xx after a
  non-idempotent write is ambiguous; a 503 is never retried there, even with
  `Retry-After`, and logs
  `CVAT вернул 503: результат записи неизвестен, запрос не повторяется. Проверьте состояние в CVAT; продолжайте только после сверки.`
- S3 access denied (403) and missing objects (404) are not retried.
- A CVAT SDK error without an HTTP status (a payload the SDK could not build or
  read) becomes `CvatApiError` with status 0 and
  `CVAT SDK не смог обработать данные ответа или запроса: …` and is not retried. A
  transport error that outlives the budget becomes `CvatApiError` with
  `Сетевая ошибка при обращении к CVAT: …`.
- Inside the CVAT SDK, each request uses a copy of the SDK's retry policy with
  `raise_on_status` off, so the final HTTP response, including an exhausted 502, 503
  or 504, reaches cveta2 with its status. For methods other than GET, HEAD and
  OPTIONS the copy also disables read, other and status retries and `Retry-After`
  replays; connection retries remain. Shared pool settings are not changed.
- boto3 clients use botocore `standard` retries with 3 attempts beneath cveta2's
  own budget.

## Rate limits and server errors during fetch

These rules apply to the per-task reads of `fetch`, `fetch-task` and their API
functions:

- An exhausted 429 on a task's jobs, frame metadata or annotations aborts the fetch
  with `Cveta2Error`:
  `CVAT ограничивает частоту запросов (HTTP 429) на задаче <id>, повторы исчерпаны. Задача НЕ пропущена, чтобы датасет не потерял её молча — уменьшите network.cvat_workers и повторите запуск. Причина: <diagnostics>`.
- An exhausted 5xx on a task's jobs, frame metadata or annotations skips that task and
  continues. The log shows
  `Ошибка CVAT (HTTP <status>), задача #<id> '<name>' пропущена: <diagnostics>` and
  `Чтобы пропустить задачу при следующем запуске: cveta2 ignore --project '<project>' --add <id>`.
  With `CVETA2_RAISE_ON_FAILURE=true` the `CvatApiError` aborts the fetch instead.
- Any other CVAT error, authentication and configuration failures, and exhausted
  transport failures abort the fetch.
- A failed issue read is optional: any CVAT error on it, including an exhausted 429 or
  5xx, degrades the task instead of aborting. The task is still exported with empty
  `issue_text` / `issue_state`, a warning names the task, and its metadata is not
  cached ([annotation cache](annotation-cache.md)).
- The fetch summary reports tasks from cache, loaded from CVAT, skipped and with
  incomplete issues, separates stage wall time from summed worker time, and lists the
  skipped and degraded task IDs
  ([fetch and partition](fetch-and-partition.md)).

## CVAT diagnostics

A failed CVAT HTTP request attaches `CvatRequestDiagnostics` to its `CvatApiError`
(fields in [Python API](python-api.md)). The message reads
`CVAT: операция <operation>, <method> <endpoint>; HTTP <status or неизвестен>; UTC <ISO time>; <resource ids>; <request ids>; <summary>`,
followed by
`. Проверьте proxy/ingress и доступность backend; источник сбоя по одному статусу не установлен.`
for 502, 503 and 504, and by `. Проверьте логи backend CVAT по времени и ID запроса.`
otherwise.

- The context belongs to the request that actually failed, including a page of a
  listing or an issue-comment read. Operation and request context are local to the
  call and the thread; concurrent requests never mix context, and a success never
  carries an earlier failure.
- The endpoint keeps scheme, host and path, drops URL credentials and fragments, and
  keeps only the query parameters `project_id`, `task_id`, `job_id`, `issue_id`,
  `cloud_storage_id`, `org_id`, `page` and `page_size` with decimal values; it is
  limited to 1024 characters. After a redirect it is the final URL.
- Resource IDs come from the operation's arguments, the path and the allowed query
  parameters. Request IDs come only from the response headers `X-Request-Id`,
  `X-Correlation-Id` and `Traceparent`, each limited to 128 characters.
- The response summary is at most 512 characters, read from at most 4096 bytes of a
  preloaded body. HTML becomes `HTML-ответ скрыт`; JSON yields only its `detail`,
  `message` and `error` strings (`JSON-ответ без краткого сообщения об ошибке` when
  there are none, `JSON-ответ скрыт: неполный или некорректный` when it does not
  parse). Credentials in text, `Authorization`-style values, cookies and any password,
  token or secret sent with the request are replaced by `[redacted]`.
- A status that is not known is 0. cveta2 never probes the server on its own after a
  failure.
- A connection that cannot be opened at the transport level (unreachable server, bad
  host scheme, another SDK setup error) fails with
  `Не удалось подключиться к CVAT (<endpoint>): <diagnostics>`. An HTTP error while it
  opens, such as a rejected login, raises `CvatApiError` with that HTTP status and its
  diagnostics, without the connection prefix. The SDK's
  server-version compatibility check is advisory: an unsupported or unreadable server
  version only logs the SDK warning.

## Request timeouts

`cvat.request_timeout` or `CVETA2_DATA_TIMEOUT` sets the HTTP read timeout in seconds
for CVAT and S3.

- Unset or 0 means no read timeout. A positive value gives CVAT requests a
  `(10, value)` connect/read timeout and S3 clients the read timeout `value`; S3 always
  has a 10-second connect timeout.
- A negative or nonfinite value fails validation; the CLI prints
  `Некорректная конфигурация: request_timeout: … Проверьте YAML и переменные окружения.`
- The CVAT timeout also covers the server-version check and login made while the
  session opens. The value is local to the calling context, so parallel callers keep
  independent timeouts.

## Transfer concurrency

| Setting | Default | Used by |
| -- | -- | -- |
| `network.s3_workers` | 16 | S3 transfers in both directions, image downloads, and paging of S3 listings across first-level subfolders |
| `network.cvat_workers` | 4 | Concurrent tasks in `fetch` (including job promotion), job status updates and issue creation in `upload` |

- Values must be integers of at least 1; an invalid file value fails validation.
- The S3 connection pool size is `max(s3_workers, 10)`.
- A parallel S3 listing returns keys sorted exactly as a serial listing would.
- Results of concurrent work are merged in input order, so output does not depend on
  completion order.
- Keep `cvat_workers` small: CVAT rate-limits long before S3, and each 429 costs a
  backoff pause. When CVAT answers 429, lower `cvat_workers`.
- The worker counts and retry budget apply to the calling context. They are installed
  when a CLI command or an API function opens its client; a `CvatClient` constructed
  directly runs with one worker of each kind and the default retry budget.

## `cveta2 setup`

```bash
cveta2 setup [--config PATH]
cveta2 setup [--config PATH] --project-config PATH
cveta2 setup [--config PATH] --migrate-config [--project-config PATH]
```

- **Ordinary run** (interactive only). Without a shared file it asks for the host
  (default the saved host or `https://app.cvat.ai`), the organization slug (an empty
  answer must be confirmed as "no organization"), the username and the password
  (empty keeps the saved password), and saves them to the personal file. With a shared
  file it takes host and organization from the shared file, validates the effective
  configuration, and asks only for credentials. Without a shared file it then asks for
  a shared file path (empty skips):
  - an existing file is attached when the host and organization just saved equal the
    shared identity, removing them from the personal file in the same write;
    otherwise it fails with
    `CVAT host/organization in <personal> differ from shared configuration <shared>; correct them in setup or choose the shared file of that server`
    and the shared file stays unchanged;
  - a path that does not exist shows the migration preview below for that path; any
    unresolved item fails with
    `Общая конфигурация отличается; выполните setup --migrate-config после согласования.`,
    and only a confirmed preview creates the shared file there (declining changes
    nothing).
- **`--project-config PATH`** validates the shared file and saves its absolute path as
  `project_config` with `schema_version: 1`. It neither asks for credentials nor
  copies or edits the shared file, and works in non-interactive mode. A legacy personal
  file that holds project policy or `cvat.host` / `cvat.organization` fails with
  `MigrationRequired`
  (`Legacy mixed configuration requires verification: cveta2 setup --migrate-config`);
  every file written by an ordinary `setup` without a shared file holds the host, so
  such a file is attached through `--migrate-config` or the shared-path prompt of an
  ordinary run, which drops a matching host and organization. A legacy file with any
  other key that a `schema_version: 1` file rejects fails with `MigrationRequired`
  (`Legacy fields require reviewed separation before attachment: cveta2 setup --migrate-config`).
- **`--migrate-config`** (interactive only) splits a legacy mixed file:
  1. It first completes an interrupted approved migration, if its journal exists.
  2. It prints a JSON preview of both target files with the username and password as
     `<redacted>`, and the list of unresolved items. Any unresolved item stops the
     command with `Сначала устраните неоднозначные настройки из отчёта миграции.`
  3. After confirmation it writes a private backup
     `<personal name>.pre-v1-<first 12 hex of the original SHA-256>.bak`, a journal
     `<personal name>.migration.json` with paths and hashes only, then creates the
     shared file and replaces the personal file. Declining changes nothing.
  - The shared path is `--project-config` or `project-config.yaml` beside the personal
    file. An existing shared file that differs in meaning is never overwritten.
  - Every project named in the legacy `sync_roots`, `ignore` or `cache.projects`
    sections or in the projects cache of the legacy organization is migrated, even one
    without policy. Each needs exactly one cached ID for its name; otherwise it is
    reported as unresolved. Its key is the name when the name matches
    `[A-Za-z0-9][A-Za-z0-9_-]*`, otherwise `project-<id>`.
  - Unknown fields and sections (including a retired `clearml` section), a missing
    host, ambiguous or uncached projects, key collisions and invalid ignore records are
    reported as unresolved, so the migration cannot proceed until they are removed or
    resolved by hand.
  - A changed personal file after the preview fails with
    `Configuration changed after migration preview; review again`. A damaged or
    incomplete journal fails with a message naming the recovery steps.

## `cveta2 doctor`

`cveta2 doctor [--cache]` checks the configuration of the default or `CVETA2_CONFIG`
personal file and the local caches. It does not contact CVAT, so success does not
prove the server is reachable.

| Check | Kind | Failure effect |
| -- | -- | -- |
| Configuration loads; host and both credentials are present | Required | Exit 1 |
| `image_cache` directories exist | Optional | Warning |
| AWS credentials resolvable by boto3 (profile, region and a masked access key are shown) | Optional | Warning |
| Group permissions of cache trees | Optional | Warning |

- Exit code 0 when the required check passes, 1 when it fails or cannot run; the last
  line is `doctor: обязательные проверки пройдены` or
  `doctor: обязательные проверки не пройдены`.
- The permission check covers every existing `image_cache` directory, `cache`
  roots (global and per project) and cveta2's own cache base (`$XDG_CACHE_HOME/cveta2`
  or `~/.cache/cveta2`), walking a nested root only once and skipping the per-user
  prompt history. Files need group read and write; directories need group read,
  write and execute. With `CVETA2_DISABLE_CACHE=true` and without `--cache` the check
  is reported as disabled.
- `--cache` adds the missing group bits to every path the current user owns and never
  changes other bits. Paths owned by others are listed with their owners, followed by
  `These users own the remaining paths and must run 'cveta2 doctor --cache' themselves: <user> (<n> items), …`.
  A directory that cannot be read is reported without its contents. cveta2 never
  changes groups or the setgid bit.
- Group bits share a cache only among members of the files' group, and a new file
  takes its creator's primary group. A cache shared by several users therefore needs a
  common group on its root, usually inherited through a setgid bit that an
  administrator sets.
