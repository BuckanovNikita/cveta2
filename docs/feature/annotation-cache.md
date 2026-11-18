# Annotation cache

`cveta2 fetch`, `cveta2 fetch-task`, `cveta2.fetch` and `cveta2.fetch_task` read CVAT
annotations through a persistent cache of raw shapes, stored per job, plus a per-task
entry with frame metadata and issues. The cache lives on local disk and, when the
project has cloud storage, is mirrored to S3 so users of one project share it. Commands
that change a task drop its entries. `fetch --skip-validation` (`skip_validation=True`)
is the explicit promotion of finished annotation jobs, with strict invalidation before
each change. Rows are always rebuilt from the live job list; see
[fetch and partition](fetch-and-partition.md) for how rows are built.

## What is cached

| Entry | File | Contents | Written when |
| -- | -- | -- | -- |
| Job entry | `job_<job id>.json` | Raw shapes of one job | The job is finished and has an update time |
| Task entry | `task.json` | Raw shapes of the whole task | The task's jobs cannot be separated and every job is finished with an update time |
| Metadata entry | `meta.json` | Frame metadata (frames and deleted frame IDs) and complete issues | Every job of the task is finished with an update time, and the issue read succeeded |

- A job is finished at stage `acceptance` with state `completed`. A job without an
  update time is never cached, nor is a task or metadata entry that covers it.
- Jobs are separable when every job has type `annotation` and no two frame ranges
  overlap. Tasks with Ground Truth, consensus or other job types, or overlapping
  ranges, use one task entry.
- Entries hold raw shapes only, never records or local paths. CSV rows, `task_completed`,
  `job_stage` and `job_state` are rebuilt from the live job list on every fetch.
- The CVAT task status never gates reuse.
- Every entry records `schema_version` (6), `task_id`, `task_updated_date`, every
  covered job (`id`, `type`, `start_frame`, `stop_frame`, `stage`, `state`,
  `updated_date`) and `cached_at` (UTC, diagnostic only).

## Freshness

An entry is used only while its schema version is 6, its task ID matches, its
`task_updated_date` equals the live task's update time and its recorded jobs equal the
live jobs it covers, field for field. A job entry covers one job; task and metadata
entries cover all jobs of the task.

| Change | Effect |
| -- | -- |
| One job's stage, state or update time changes, task time unchanged | That job's shapes, plus metadata and issues, are read again |
| Task update time changes (for example a project label edit, or CVAT moving it when annotations are saved) | Every job of the task is read again |
| A job appears, vanishes or changes range or type | Its entry misses; metadata and issues are read again |
| A frame is deleted or an issue is added without moving the task or a job update time | Not seen until such a change: accepted limit |

- Every fetch reads each task's job list. A task whose shapes and metadata all come
  from the cache costs exactly that one CVAT request and counts as a cache hit in the
  fetch summary.
- For a separable task with no reusable job entry, the task's annotations are read
  with one request and split into job entries by frame range. If a shape lies outside
  every range, nothing is written for that read. When some job entries are reusable,
  only the other jobs are read through the job endpoint.
- An incomplete issue read is never cached; the next run reads metadata and issues
  again.
- Polygon and shape-type warnings are emitted when shapes are read from CVAT. When every
  shape of a task came from the cache they go to the debug log; a partly cached task
  warns again for all its shapes. The missing-frame-metadata warning appears on every
  fetch.

## Reading, writing and failures

- Lookup order: local entry, then the S3 mirror. A valid S3 entry is copied to the
  local cache.
- A local entry that fails validation or does not match the live task and jobs is logged
  (`<layer>: запись <name> задачи <id> не прошла валидацию (<n> ошибок) — данные будут загружены заново`
  or `<layer>: запись <name> задачи <id> устарела: <reason> — данные будут загружены заново`),
  deleted and treated as a miss; the S3 mirror is not consulted for it. A stale S3
  entry is neither copied nor deleted.
- A local entry that cannot be read (permissions, broken mount) warns
  `Не удалось прочитать локальный кэш задачи <id>: <error>`, stays on disk and is
  treated as a miss. A failed delete warns and continues.
- Local writes are atomic (temporary sibling, then rename); a failed write warns
  `Не удалось сохранить локальный кэш <name>: <error>` and the fetch continues.
- Any S3 failure other than a missing key (`NoSuchKey`, `404`, `NoSuchBucket`) warns
  once
  `S3-кэш аннотаций недоступен (<error>) — до конца запуска используется только локальный кэш.`
  and disables the mirror for the rest of the run. Failing to create the S3 client
  (for example a missing AWS profile) has the same effect for an ordinary fetch.
- `--force` (`cache="refresh"`) skips every read and still writes fresh entries.
  `--no-cache` (`cache="off"`) or `CVETA2_DISABLE_CACHE=true` (any case) disables reads,
  writes, S3 access, old-format removal and pruning for the run.
- A malformed `task_cache_s3` value (not `s3://bucket[/prefix]` or a nonempty bare
  prefix) fails when the configuration loads
  ([connection and configuration](connection-and-configuration.md)), before any fetch or
  invalidation uses it.

## Removal

- **Vanished jobs**: whenever a task is read with caching enabled, its local job and task
  entries that do not belong to a current cacheable job or task scope are deleted. The metadata entry
  is never removed this way.
- **Deleted tasks**: a full `fetch` (not `fetch-task`) deletes local entries of tasks
  absent from its unfiltered task list, read after any promotion, and logs
  `Кэш аннотаций: удалено устаревших записей: <n>`. Ignored and unfinished tasks are in
  that list and keep their entries. S3 entries are never pruned. A task deleted after
  the listing is pruned on the next run.
- **Old format**: entries of schema 5 and older were one `task_<id>.json` file per task.
  They are never read. Each cached `fetch` or `fetch-task` deletes the project's local
  ones and logs `Кэш аннотаций: удалено записей старого формата: <n>`; failed deletes
  warn `Кэш аннотаций: не удалось удалить записей старого формата: <n>`. A task's old S3
  object is deleted the first time new entries of that task are written in a run,
  touching only keys under the cache prefix. A failed S3 delete warns once
  `S3-кэш аннотаций: не удалось удалить запись старого формата (<error>) — старые записи до конца запуска не удаляются, зеркало используется дальше.`
  and the mirror stays in use. An older cveta2 sharing the mirror then reads such tasks
  from CVAT again.

## Invalidation after task changes

`upload`, `task mark-deleted`, `task drop-label`, `task delete`, `task status` and their
API functions drop every entry of the task they changed: the local task directory, the
old-format local file and, when a mirror is configured, every S3 key under the task's
prefix plus its old-format object.

- The entry is selected with the same configuration file as fetch
  (`Connection.config_path` in the API), using that project's `tasks_root` and
  `task_cache_s3`.
- Task commands invalidate when the command block exits, after success or failure, and
  look up the project's cloud storage before the change.
- Invalidation never raises. Unreadable cache settings warn
  `Кэш задачи <id> не очищен: не удалось прочитать настройки кэша (<error>).`; an
  unavailable mirror warns and the local entry is still removed. The CVAT result of the
  command is kept.
- With caching disabled through `CVETA2_DISABLE_CACHE`, only the local entry is removed
  and S3 is not contacted.
- `upload` passes no cloud storage to invalidation, so its S3 step runs only when
  `task_cache_s3` is a full `s3://bucket/prefix` value; a newly created task has no
  entries in any case.

## Explicit promotion (`fetch --skip-validation`)

`cveta2 fetch --skip-validation` and `cveta2.fetch(..., skip_validation=True)` accept
finished annotation work in CVAT before the export. The default is off, and
`fetch-task` / `fetch_task` have no such option.

- Every project task not on the ignore list (silent or not) is inspected through its
  full job list. A task qualifies only when it has at least one job and every job,
  whatever its type or frame coverage, has state `completed` with stage `annotation` or
  `acceptance`. Jobs at `annotation`/`completed` are changed to `acceptance`/`completed`,
  one at a time within a task. A task with nothing at `annotation` gets no write; empty
  and other tasks are untouched.
- Tasks are inspected concurrently up to `network.cvat_workers`. All workers finish
  before task selection, so `--completed-only` in the same run sees the accepted tasks.
- Before the first job write of a task, its cache entries are deleted strictly: the
  local entry under the selected configuration's `tasks_root`, and, when caching is
  enabled, the S3 mirror including `task_cache_s3`. With `--no-cache`,
  `CVETA2_DISABLE_CACHE=true` or `cache="off"` only the local entry is deleted and S3 is
  not contacted. A task that needs no write is not invalidated.
- Any failure aborts before annotation reads, image downloads and CSV writes, with
  `Cveta2Error`:

  | Failure | Message |
  | -- | -- |
  | Project task list | `Не удалось получить задачи проекта <project id>: <error>` |
  | Task job list | `Не удалось получить jobs задачи <task id>: <error>` |
  | Cache deletion, including an S3 mirror whose client could not be created | `Не удалось очистить кэш задачи <task id>: <error>` |
  | Job update | `Не удалось принять job <job id> задачи <task id>: <error>` |

- Successful CVAT changes are not rolled back. A rerun inspects the current jobs and
  writes only the remaining `annotation`/`completed` jobs. Concurrent external edits have
  no transactional guarantee.
- The run logs `Принятие завершённой разметки: прошло <s> с`.

## Storage locations

| Layer | Location |
| -- | -- |
| Local, default | `$XDG_CACHE_HOME/cveta2/task_annotations/project_<project id>/task_<task id>/` (`~/.cache/cveta2/…` without `XDG_CACHE_HOME`) |
| Local, configured | `<tasks_root>/project_<project id>/task_<task id>/`, where `tasks_root` is the project's `cache.projects.<name>.tasks_root` or else `cache.tasks_root` |
| S3, default | `<project storage prefix>/.cveta2_cache/task_annotations/task_<task id>/` in the project's CVAT cloud storage bucket |
| S3, `task_cache_s3: s3://bucket/prefix` | `<prefix>/task_annotations/task_<task id>/` in that bucket |
| S3, `task_cache_s3: prefix` | `<prefix>/task_annotations/task_<task id>/` in the project's bucket |

- The S3 mirror always starts from the project's own CVAT cloud storage and its
  endpoint; `sync_root` overrides never move it. A project without cloud storage has no
  mirror unless `task_cache_s3` is a full `s3://` value.
- Local directories and files are created group-writable (0775 / 0664). The default
  location is inside the user's home directory, so the local layer is shared only when
  `tasks_root` points at a shared directory. Where these settings live:
  [connection and configuration](connection-and-configuration.md).
