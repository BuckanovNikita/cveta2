"""Persistent cache of fetched task annotations (local disk + optional S3).

Completed CVAT tasks are immutable in practice, so their fetched
annotations are cached in ``~/.cache/cveta2/task_annotations`` (and,
when the project has an attached cloud storage, mirrored to S3 so all
users share one cache).  A cache problem must never fail the fetch:
every S3 error self-disables the backend for the rest of the run.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from botocore.exceptions import BotoCoreError, ClientError
from loguru import logger
from pydantic import BaseModel, ValidationError

from cveta2.config import CacheConfig, is_cache_disabled
from cveta2.fs_utils import default_cache_base, replace_shared_bytes
from cveta2.models import TaskAnnotations
from cveta2.s3_utils import (
    build_s3_key,
    make_s3_client,
    parse_sync_root,
    s3_get_bytes,
    s3_retry,
)

if TYPE_CHECKING:
    from pathlib import Path

    from cveta2.image_downloader import CloudStorageInfo
    from cveta2.models import TaskInfo
    from cveta2.s3_types import S3Client

# v4: payload records carry task-wide completion; older per-frame job
# mappings lost unfinished jobs in overlapping or sparse job layouts.
# v3: payload records carry ``job_stage``/``job_state`` in place of
# ``task_status``; a v2 entry has no per-job review position, and the
# partition would read every one of its rows as still unreviewed.
# v2: payload records carry ``frame_path`` (nested CVAT frame names); v1
# entries were saved after basename collapse and would rebuild a wrong
# ``s3_image_path`` for multilevel S3 hierarchies.
CACHE_SCHEMA_VERSION = 4

_COMPLETED_STATUS = "completed"
_MISSING_KEY_CODES = frozenset({"NoSuchKey", "404", "NoSuchBucket"})

# Layer names for the rejection log, kept at module level so they carry no
# behaviour: the value only ever reaches an f-string in _validate_envelope.
_SOURCE_LOCAL = "локальный кэш"
_SOURCE_S3 = "S3-кэш"


class CachedTaskEnvelope(BaseModel):
    """Versioned wrapper around a cached :class:`TaskAnnotations` payload.

    ``task_updated_date`` invalidates stale payloads; ``cached_at`` records
    when the payload was fetched for diagnostics.
    """

    schema_version: int
    task_id: int
    task_updated_date: str
    cached_at: str
    payload: TaskAnnotations


def get_task_cache_dir(project_id: int, root: Path | None = None) -> Path:
    """Return the local cache directory for a project's task annotations.

    *root* (the ``cache.tasks_root`` setting) replaces the default
    ``~/.cache/cveta2/task_annotations`` base when provided.
    """
    if root is not None:
        return root / f"project_{project_id}"
    return default_cache_base() / "task_annotations" / f"project_{project_id}"


def invalidate_local_entry(
    project_id: int,
    task_id: int,
    project_name: str,
    cs_info: CloudStorageInfo | None = None,
) -> None:
    """Drop the cache entry for *task_id* after a task mutation.

    The local entry always goes.  With *cs_info* (the project's CVAT cloud
    storage) the S3 mirror entry goes too — otherwise the next fetch would
    backfill the pre-mutation payload from S3.  ``CVETA2_DISABLE_CACHE``
    keeps S3 untouched, as it does for every other cache operation.
    """
    settings = CacheConfig.load().for_project(project_name)
    cache_dir = get_task_cache_dir(project_id, root=settings.tasks_root)
    s3 = (
        None
        if is_cache_disabled()
        else S3CacheBackend.from_cloud_storage(
            cs_info, task_cache_s3=settings.task_cache_s3
        )
    )
    TaskAnnotationCache(cache_dir, s3=s3).invalidate(task_id)


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
    rest of the run.
    """

    def __init__(
        self,
        s3_client: S3Client,
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
        self._disabled = False

    @classmethod
    def from_cloud_storage(
        cls,
        cs_info: CloudStorageInfo | None,
        task_cache_s3: str | None = None,
    ) -> S3CacheBackend | None:
        """Build a backend from CVAT cloud storage info (None when absent).

        *task_cache_s3* (the ``cache.projects.<name>.task_cache_s3``
        setting) overrides the location: a full ``s3://bucket/prefix``
        may target another bucket; a bare prefix stays in the project
        bucket.  The project storage endpoint is used in both cases.
        """
        if task_cache_s3:
            bucket, prefix = parse_sync_root(task_cache_s3)
            if bucket is None:
                if cs_info is None:
                    return None
                bucket = cs_info.bucket
            endpoint_url = cs_info.endpoint_url if cs_info else ""
            return cls(
                make_s3_client(endpoint_url or None),
                bucket,
                prefix,
                explicit_location=True,
            )
        if cs_info is None:
            return None
        return cls(
            make_s3_client(cs_info.endpoint_url or None),
            cs_info.bucket,
            cs_info.prefix,
        )

    def get(self, task_id: int) -> bytes | None:
        """Fetch the raw cache entry for *task_id*, or None on miss/failure."""
        if self._disabled:
            return None
        try:
            data = s3_get_bytes(self._s3, self._bucket, self._entry_key(task_id))
        except ClientError as e:
            if _client_error_code(e) in _MISSING_KEY_CODES:
                return None
            self._disable(e)
            return None
        except (BotoCoreError, OSError) as e:
            self._disable(e)
            return None
        return data

    def put(self, task_id: int, data: bytes) -> None:
        """Store the raw cache entry for *task_id* (best effort)."""
        if self._disabled:
            return
        try:
            _s3_put_bytes(self._s3, self._bucket, self._entry_key(task_id), data)
        except (ClientError, BotoCoreError, OSError) as e:
            self._disable(e)

    def delete(self, task_id: int) -> None:
        """Drop the raw cache entry for *task_id* (best effort, idempotent)."""
        if self._disabled:
            return
        try:
            _s3_delete_object(self._s3, self._bucket, self._entry_key(task_id))
        except (ClientError, BotoCoreError, OSError) as e:
            self._disable(e)

    def _entry_key(self, task_id: int) -> str:
        """Build the S3 key of the cache entry for *task_id*."""
        entry = f"task_annotations/task_{task_id}.json"
        if not self._explicit_location:
            entry = f".cveta2_cache/{entry}"
        return build_s3_key(self._key_prefix, entry)

    def _disable(self, error: Exception) -> None:
        """Log one Russian warning and stop using S3 for the rest of the run."""
        self._disabled = True
        logger.warning(
            f"S3-кэш аннотаций недоступен ({error}) — до конца запуска "
            f"используется только локальный кэш."
        )


class TaskAnnotationCache:
    """Local (plus optional S3) cache of per-task annotation payloads.

    Only tasks CVAT currently reports as ``completed`` are cached or
    served. A cached entry must also match the task's live ``updated_date``;
    annotation and project-label edits therefore cannot leave rendered
    annotations stale.
    """

    def __init__(self, local_dir: Path, s3: S3CacheBackend | None = None) -> None:
        """Store the local cache directory and optional S3 backend."""
        self._local_dir = local_dir
        self._s3 = s3

    def get(self, task: TaskInfo) -> TaskAnnotations | None:
        """Return the cached payload for *task*, or None on miss."""
        if task.status != _COMPLETED_STATUS:
            return None
        local = self._get_local(task)
        if local is not None:
            return local
        return self._get_s3(task)

    def put(self, task: TaskInfo, result: TaskAnnotations) -> None:
        """Cache complete results for completed tasks; omit degraded issues."""
        if task.status != _COMPLETED_STATUS or not result.issues_complete:
            return
        envelope = CachedTaskEnvelope(
            schema_version=CACHE_SCHEMA_VERSION,
            task_id=task.id,
            task_updated_date=task.updated_date,
            cached_at=datetime.now(timezone.utc).isoformat(),
            payload=result,
        )
        data = envelope.model_dump_json().encode()
        self._write_local(task.id, data)
        if self._s3 is not None:
            self._s3.put(task.id, data)

    def invalidate_local(self, task_id: int) -> None:
        """Remove the local cache entry for *task_id* if present."""
        self._local_path(task_id).unlink(missing_ok=True)

    def invalidate(self, task_id: int) -> None:
        """Remove the entry for *task_id* from every layer, S3 included.

        Only a task mutation calls this: :meth:`prune` and a schema
        mismatch drop the local copy alone, since a valid S3 entry
        written by a newer cveta2 must survive an older one's run.
        """
        self.invalidate_local(task_id)
        if self._s3 is not None:
            self._s3.delete(task_id)

    def prune(self, live_task_ids: set[int]) -> int:
        """Remove local entries whose task no longer exists; return count.

        Deletion goes through :meth:`invalidate_local`, which rebuilds the
        canonical ``task_{id}.json`` name — the only name this cache ever
        writes, so it always names the file the glob just found.
        """
        removed = 0
        for path in self._local_dir.glob("task_*.json"):
            task_id = _task_id_from_filename(path.name)
            if task_id is None or task_id in live_task_ids:
                continue
            self.invalidate_local(task_id)
            removed += 1
        return removed

    def _get_local(self, task: TaskInfo) -> TaskAnnotations | None:
        """Read and validate the local entry; delete it when invalid.

        An entry that cannot be read at all (permissions, a truncated
        mount) is a plain miss and is left on disk — only entries proven
        invalid are dropped.
        """
        try:
            raw = self._local_path(task.id).read_bytes()
        except FileNotFoundError:
            return None
        except OSError as e:
            logger.info(f"Не удалось прочитать локальный кэш задачи {task.id}: {e}")
            return None
        envelope = _validate_envelope(raw, task, source=_SOURCE_LOCAL)
        if envelope is None:
            self.invalidate_local(task.id)
            return None
        return envelope.payload

    def _get_s3(self, task: TaskInfo) -> TaskAnnotations | None:
        """Read a valid entry from S3, backfilling the local cache on hit."""
        if self._s3 is None:
            return None
        raw = self._s3.get(task.id)
        if raw is None:
            return None
        envelope = _validate_envelope(raw, task, source=_SOURCE_S3)
        if envelope is None:
            return None
        self._write_local(task.id, raw)
        return envelope.payload

    def _write_local(self, task_id: int, data: bytes) -> None:
        """Atomically write the local entry (best effort)."""
        try:
            replace_shared_bytes(self._local_path(task_id), data)
        except OSError as e:
            logger.warning(f"Не удалось сохранить локальный кэш задачи {task_id}: {e}")

    def _local_path(self, task_id: int) -> Path:
        """Build the local file path of the entry for *task_id*."""
        return self._local_dir / f"task_{task_id}.json"


def _validate_envelope(
    raw: bytes, task: TaskInfo, source: str
) -> CachedTaskEnvelope | None:
    """Parse *raw* and return the envelope when it matches the live *task*.

    Every rejection is logged with its reason so cache misses stay
    diagnosable (*source* names the cache layer in the message).
    """
    try:
        envelope = CachedTaskEnvelope.model_validate_json(raw)
    except ValidationError as e:
        logger.info(
            f"{source}: запись задачи {task.id} не прошла валидацию "
            f"({e.error_count()} ошибок) — задача будет загружена заново"
        )
        return None
    if envelope.schema_version != CACHE_SCHEMA_VERSION:
        logger.info(
            f"{source}: запись задачи {task.id} имеет версию схемы "
            f"{envelope.schema_version} (ожидается {CACHE_SCHEMA_VERSION}) — "
            f"задача будет загружена заново"
        )
        return None
    if envelope.task_id != task.id:
        logger.info(
            f"{source}: запись задачи {task.id} принадлежит задаче "
            f"{envelope.task_id} — задача будет загружена заново"
        )
        return None
    if envelope.task_updated_date != task.updated_date:
        logger.info(
            f"{source}: запись задачи {task.id} устарела "
            f"({envelope.task_updated_date!r} вместо {task.updated_date!r}) — "
            f"задача будет загружена заново"
        )
        return None
    return envelope


def _task_id_from_filename(filename: str) -> int | None:
    """Extract the task id from a ``task_{id}.json`` cache file name."""
    stem = filename.removeprefix("task_").removesuffix(".json")
    if not stem.isdigit():
        return None
    return int(stem)
