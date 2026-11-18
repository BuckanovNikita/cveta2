"""Persistent cache of fetched job annotations (local disk + optional S3).

Each finished CVAT job's raw shapes are cached in
``~/.cache/cveta2/task_annotations/project_<id>/task_<id>/job_<id>.json``
(``task.json`` when a task's jobs cannot be separated) and, when the project
has an attached cloud storage, mirrored to S3 so all users share one cache.
An entry is served only while the task's update time and every covered
job's identity, stage, state and update time are unchanged. Ordinary S3
cache errors disable the backend for the rest of the run. Mutation
preflight can require strict invalidation instead.
"""

import dataclasses
import shutil
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import TypeVar

from botocore.exceptions import BotoCoreError, ClientError
from loguru import logger
from pydantic import ValidationError

from cveta2.adapters.files.shared import default_cache_base, replace_shared_bytes
from cveta2.adapters.s3.types import S3Client
from cveta2.adapters.s3.utils import list_s3_objects, make_s3_client, s3_get_bytes, s3_retry
from cveta2.application.ports.cache import AnnotationScope, TaskMeta
from cveta2.application.ports.dtos import RawAnnotations, RawDataMeta, RawIssue, RawJob, RawShape
from cveta2.application.settings import CacheProjectSettings
from cveta2.domain.cache import (
    _SOURCE_LOCAL,
    _SOURCE_S3,
    CACHE_SCHEMA_VERSION,
    CachedEntryHeader,
    CachedJob,
    entry_mismatch,
    task_id_from_name,
)
from cveta2.domain.errors import Cveta2Error
from cveta2.domain.models import TaskInfo
from cveta2.domain.paths import build_s3_key, parse_sync_root
from cveta2.domain.storage import CloudStorageInfo

_MISSING_KEY_CODES = frozenset({"NoSuchKey", "404", "NoSuchBucket"})


class CachedAnnotationsEntry(CachedEntryHeader):
    """One cache entry: the raw shapes of a job (or of a whole task)."""

    shapes: list[RawShape]


class CachedTaskMetaEntry(CachedEntryHeader):
    """The task's frame metadata and complete issues, keyed on every job of the task."""

    data_meta: RawDataMeta
    issues: list[RawIssue]


_Entry = TypeVar("_Entry", bound=CachedEntryHeader)
_META = "meta"


def _cached_jobs(jobs: Sequence[RawJob]) -> list[CachedJob]:
    return [CachedJob.model_validate(dataclasses.asdict(job)) for job in jobs]


def _legacy_name(task_id: int) -> str:
    """Return the relative path of the old per-task entry (schema 5 and older)."""
    return f"task_{task_id}.json"


def _parse_entry(  # noqa: PLR0913 - one validation for every entry kind
    raw: bytes, model: type[_Entry], task: TaskInfo, jobs: list[CachedJob], *, label: str, source: str
) -> _Entry | None:
    """Return the entry when it still describes the live task and jobs; log why not."""
    try:
        entry = model.model_validate_json(raw)
    except ValidationError as e:
        logger.warning(
            f"{source}: запись {label} задачи {task.id} не прошла валидацию "
            f"({e.error_count()} ошибок) — данные будут загружены заново"
        )
        return None
    reason = entry_mismatch(entry, task, jobs)
    if reason is not None:
        logger.info(f"{source}: запись {label} задачи {task.id} устарела: {reason} — данные будут загружены заново")
        return None
    return entry


def get_task_cache_dir(project_id: int, root: Path | None = None) -> Path:
    """Return the local cache directory for a project's task annotations.

    *root* (the ``cache.tasks_root`` setting) replaces the default
    ``~/.cache/cveta2/task_annotations`` base when provided.
    """
    if root is not None:
        return root / f"project_{project_id}"
    return default_cache_base() / "task_annotations" / f"project_{project_id}"


@s3_retry
def _s3_put_bytes(s3_client: S3Client, bucket: str, key: str, data: bytes) -> None:
    """Upload bytes to an S3 object."""
    s3_client.put_object(Bucket=bucket, Key=key, Body=data)


@s3_retry
def _s3_delete_object(s3_client: S3Client, bucket: str, key: str) -> None:
    """Delete an S3 object (S3 answers a missing key with a plain 204)."""
    s3_client.delete_object(Bucket=bucket, Key=key)


def _client_error_code(error: ClientError) -> str:
    """Extract the error code from a botocore ClientError as a string.

    A response carrying no code stringifies to ``"None"``, which is not a
    missing-key code: an error we cannot classify disables the cache
    instead of reading as a miss.
    """
    return str(error.response.get("Error", {}).get("Code"))


class S3CacheBackend:
    """Shared S3 mirror of the task-annotation cache.

    By default entries live under
    ``{key_prefix}/.cveta2_cache/task_annotations/`` next to the project
    images; an explicit ``cache.projects.<name>.task_cache_s3`` location
    stores them under ``{key_prefix}/task_annotations/`` instead.  Any S3
    failure (except a plain missing key) disables the backend for the
    rest of the run.  A client that cannot be constructed leaves the
    backend unavailable from the start: reads and writes are skipped, and
    only a strict deletion reports the original failure.
    """

    def __init__(
        self,
        s3_client: S3Client | None,
        bucket: str,
        key_prefix: str,
        *,
        explicit_location: bool = False,
    ) -> None:
        """Store the S3 client, target bucket/prefix and layout mode."""
        self._s3 = s3_client
        self._bucket = bucket
        self._key_prefix = key_prefix
        self._explicit_location = explicit_location
        self._disabled = s3_client is None
        self._legacy_delete_failed = False
        self._unavailable: BotoCoreError | None = None

    @classmethod
    def from_cloud_storage(
        cls,
        cs_info: CloudStorageInfo | None,
        task_cache_s3: str | None = None,
    ) -> "S3CacheBackend | None":
        """Build a backend from CVAT cloud storage info (None when absent).

        *task_cache_s3* (the ``cache.projects.<name>.task_cache_s3``
        setting) overrides the location: a full ``s3://bucket/prefix``
        may target another bucket; a bare prefix stays in the project
        bucket.  The project storage endpoint is used in both cases.
        """
        if task_cache_s3:
            try:
                bucket, prefix = parse_sync_root(task_cache_s3)
            except ValueError as e:
                raise Cveta2Error(f"Некорректный task_cache_s3 {task_cache_s3!r}: {e}") from e
            if bucket is None:
                if cs_info is None:
                    return None
                bucket = cs_info.bucket
            endpoint_url = cs_info.endpoint_url if cs_info else ""
            return cls._connect(endpoint_url or None, bucket, prefix, explicit_location=True)
        if cs_info is None:
            return None
        return cls._connect(cs_info.endpoint_url or None, cs_info.bucket, cs_info.prefix)

    @classmethod
    def _connect(
        cls,
        endpoint_url: str | None,
        bucket: str,
        key_prefix: str,
        *,
        explicit_location: bool = False,
    ) -> "S3CacheBackend":
        """Build a backend, or an unavailable one when no client can be made."""
        try:
            client = make_s3_client(endpoint_url)
        except BotoCoreError as e:
            backend = cls(None, bucket, key_prefix, explicit_location=explicit_location)
            backend._unavailable = e
            backend._disable(e)
            return backend
        return cls(client, bucket, key_prefix, explicit_location=explicit_location)

    def get(self, name: str) -> bytes | None:
        """Fetch the raw entry at relative *name*, or None on miss/failure."""
        if self._disabled or self._s3 is None:
            return None
        try:
            data = s3_get_bytes(self._s3, self._bucket, self._key(name))
        except ClientError as e:
            if _client_error_code(e) in _MISSING_KEY_CODES:
                return None
            self._disable(e)
            return None
        except (BotoCoreError, OSError) as e:
            self._disable(e)
            return None
        return data

    def put(self, name: str, data: bytes) -> None:
        """Store the raw entry at relative *name* (best effort)."""
        if self._disabled or self._s3 is None:
            return
        try:
            _s3_put_bytes(self._s3, self._bucket, self._key(name), data)
        except (ClientError, BotoCoreError, OSError) as e:
            self._disable(e)

    def delete_legacy(self, task_id: int) -> None:
        """Drop the task's old per-task object (best effort).

        A bucket may allow reads and writes but not deletes. A failure warns
        once and stops further old-object deletes for the run; the mirror
        itself stays in use.
        """
        if self._disabled or self._s3 is None or self._legacy_delete_failed:
            return
        try:
            _s3_delete_object(self._s3, self._bucket, self._key(_legacy_name(task_id)))
        except (ClientError, BotoCoreError, OSError) as e:
            self._legacy_delete_failed = True
            logger.warning(
                f"S3-кэш аннотаций: не удалось удалить запись старого формата ({e}) — "
                "старые записи до конца запуска не удаляются, зеркало используется дальше."
            )

    def delete_task(self, task_id: int, *, strict: bool = False) -> None:
        """Drop every entry of a task and its old object; strict preflight must succeed or raise.

        The listing asks for ``task_<id>/`` with the slash, so ``task_12``
        never matches the entries of ``task_123``.
        """
        if self._s3 is None:
            if strict:
                raise Cveta2Error(
                    f"Не удалось удалить S3-кэш задачи {task_id}: {self._unavailable}"
                ) from self._unavailable
            return
        if self._disabled and not strict:
            return
        try:
            keys = [key for key, _name in list_s3_objects(self._s3, self._bucket, self._key(f"task_{task_id}"))]
            for key in [*keys, self._key(_legacy_name(task_id))]:
                _s3_delete_object(self._s3, self._bucket, key)
        except (ClientError, BotoCoreError, OSError) as e:
            if strict:
                raise Cveta2Error(f"Не удалось удалить S3-кэш задачи {task_id}: {e}") from e
            self._disable(e)

    def _key(self, name: str) -> str:
        """Build the S3 key of relative entry *name* under the cache root."""
        entry = f"task_annotations/{name}"
        if not self._explicit_location:
            entry = f".cveta2_cache/{entry}"
        return build_s3_key(self._key_prefix, entry)

    def _disable(self, error: Exception) -> None:
        """Log one Russian warning and stop using S3 for the rest of the run."""
        self._disabled = True
        logger.warning(f"S3-кэш аннотаций недоступен ({error}) — до конца запуска используется только локальный кэш.")


class TaskAnnotationCache:
    """Local (plus optional S3) cache of raw annotations per job.

    The fetch decides which jobs are cacheable; this class only stores and
    validates entries. An entry is served only while it matches the live
    task's ``updated_date`` and every covered job exactly, so an annotation,
    label, stage or state change makes it a miss.
    """

    def __init__(self, local_dir: Path, s3: S3CacheBackend | None = None) -> None:
        """Store the local cache directory and optional S3 backend."""
        self._local_dir = local_dir
        self._s3 = s3
        self._legacy_dropped: set[int] = set()

    def get(self, task: TaskInfo, scope: AnnotationScope) -> RawAnnotations | None:
        """Return the cached shapes of *scope*, or None on miss."""
        entry = self._read(task, scope.name, CachedAnnotationsEntry, _cached_jobs(scope.jobs))
        return None if entry is None else RawAnnotations(shapes=entry.shapes)

    def put(self, task: TaskInfo, scope: AnnotationScope, annotations: RawAnnotations) -> None:
        """Cache *scope*'s shapes; the first write of a task also drops its old S3 object."""
        entry = CachedAnnotationsEntry(
            schema_version=CACHE_SCHEMA_VERSION,
            task_id=task.id,
            task_updated_date=task.updated_date,
            jobs=_cached_jobs(scope.jobs),
            cached_at=datetime.now(timezone.utc).isoformat(),
            shapes=list(annotations.shapes),
        )
        self._write(task.id, scope.name, entry)

    def get_meta(self, task: TaskInfo, jobs: Sequence[RawJob]) -> TaskMeta | None:
        """Return the task's cached frame metadata and issues while task and all jobs are unchanged."""
        entry = self._read(task, _META, CachedTaskMetaEntry, _cached_jobs(jobs))
        return None if entry is None else TaskMeta(data_meta=entry.data_meta, issues=entry.issues)

    def put_meta(self, task: TaskInfo, jobs: Sequence[RawJob], meta: TaskMeta) -> None:
        """Cache the task's frame metadata and complete issues against all of its jobs."""
        entry = CachedTaskMetaEntry(
            schema_version=CACHE_SCHEMA_VERSION,
            task_id=task.id,
            task_updated_date=task.updated_date,
            jobs=_cached_jobs(jobs),
            cached_at=datetime.now(timezone.utc).isoformat(),
            data_meta=meta.data_meta,
            issues=list(meta.issues),
        )
        self._write(task.id, _META, entry)

    def _write(self, task_id: int, label: str, entry: CachedEntryHeader) -> None:
        data = entry.model_dump_json().encode()
        name = f"task_{task_id}/{label}.json"
        self._write_local(name, data)
        if self._s3 is not None:
            self._s3.put(name, data)
            if task_id not in self._legacy_dropped:
                self._legacy_dropped.add(task_id)
                self._s3.delete_legacy(task_id)

    def keep_only(self, task_id: int, scopes: Sequence[AnnotationScope]) -> None:
        """Delete the task's local entries other than *scopes* (vanished jobs, changed layout)."""
        # The task's metadata entry is checked against all jobs when read, never pruned here.
        wanted = {f"{scope.name}.json" for scope in scopes} | {f"{_META}.json"}
        task_dir = self._local_dir / f"task_{task_id}"
        try:
            stale = [path for path in task_dir.glob("*.json") if path.name not in wanted]
        except OSError as error:
            logger.warning(f"Не удалось просмотреть локальный кэш задачи {task_id}: {error}")
            return
        for path in stale:
            self._unlink_quiet(path, task_id)

    def invalidate_local(self, task_id: int, *, strict: bool = False) -> None:
        """Remove the task's local entries and old file, optionally requiring success."""
        try:
            shutil.rmtree(self._local_dir / f"task_{task_id}")
        except FileNotFoundError:
            pass
        except OSError as error:
            if strict:
                raise
            logger.warning(f"Не удалось удалить локальный кэш задачи {task_id}: {error} — записи не используются")
        try:
            (self._local_dir / _legacy_name(task_id)).unlink(missing_ok=True)
        except OSError as error:
            if strict:
                raise
            logger.warning(f"Не удалось удалить старую запись кэша задачи {task_id}: {error}")

    def invalidate(self, task_id: int, *, strict: bool = False) -> None:
        """Remove every entry of *task_id* from every layer, S3 included.

        Only a task mutation calls this: :meth:`prune` drops the local copy
        alone, since a valid S3 entry written by a newer cveta2 must survive
        an older one's run. With ``strict=True``, local and S3 failures abort
        mutation preflight.
        """
        self.invalidate_local(task_id, strict=strict)
        if self._s3 is not None:
            self._s3.delete_task(task_id, strict=strict)
            self._legacy_dropped.add(task_id)

    def prune(self, live_task_ids: set[int]) -> int:
        """Remove local entries of tasks that no longer exist; return the task count."""
        removed = 0
        for path in self._local_dir.glob("task_*"):
            task_id = task_id_from_name(path.name)
            if not path.is_dir() or task_id is None or task_id in live_task_ids:
                continue
            self.invalidate_local(task_id)
            removed += 1
        return removed

    def remove_legacy_entries(self) -> int:
        """Delete the project's old per-task ``task_<id>.json`` files; return how many."""
        removed = 0
        failed = 0
        for path in self._local_dir.glob("task_*.json"):
            if task_id_from_name(path.name) is None:
                continue
            try:
                path.unlink()
            except FileNotFoundError:
                continue
            except OSError as error:
                failed += 1
                logger.debug(f"Старая запись кэша {path} не удалена: {error}")
                continue
            removed += 1
        if failed:
            logger.warning(f"Кэш аннотаций: не удалось удалить записей старого формата: {failed}")
        return removed

    def _read(self, task: TaskInfo, label: str, model: type[_Entry], jobs: list[CachedJob]) -> _Entry | None:
        """Read a valid entry locally, else from S3 with a local backfill.

        A local entry proven invalid is deleted; one that cannot be read at
        all (permissions, a truncated mount) is a plain miss left on disk.
        """
        name = f"task_{task.id}/{label}.json"
        path = self._local_dir / name
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            pass
        except OSError as e:
            logger.warning(f"Не удалось прочитать локальный кэш задачи {task.id}: {e}")
        else:
            entry = _parse_entry(raw, model, task, jobs, label=label, source=_SOURCE_LOCAL)
            if entry is not None:
                return entry
            self._unlink_quiet(path, task.id)
            return None
        if self._s3 is None:
            return None
        shared = self._s3.get(name)
        if shared is None:
            return None
        entry = _parse_entry(shared, model, task, jobs, label=label, source=_SOURCE_S3)
        if entry is not None:
            self._write_local(name, shared)
        return entry

    def _write_local(self, name: str, data: bytes) -> None:
        """Atomically write the local entry (best effort)."""
        try:
            replace_shared_bytes(self._local_dir / name, data)
        except OSError as e:
            logger.warning(f"Не удалось сохранить локальный кэш {name}: {e}")

    @staticmethod
    def _unlink_quiet(path: Path, task_id: int) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError as error:
            logger.warning(f"Не удалось удалить локальный кэш задачи {task_id}: {error} — запись не используется")


class AnnotationCacheFactory:
    """Construct task caches with already resolved settings."""

    def create(
        self,
        project_id: int,
        cs_info: CloudStorageInfo | None,
        settings: CacheProjectSettings,
        *,
        local_only: bool = False,
    ) -> TaskAnnotationCache:
        """Build a project cache, optionally restricting it to local files."""
        return TaskAnnotationCache(
            get_task_cache_dir(project_id, root=settings.tasks_root),
            s3=S3CacheBackend.from_cloud_storage(cs_info, task_cache_s3=settings.task_cache_s3)
            if not local_only
            else None,
        )
