"""Persistent cache of fetched task annotations (local disk + optional S3).

Completed CVAT tasks are immutable in practice, so their fetched
annotations are cached in ``~/.cache/cveta2/task_annotations`` (and,
when the project has an attached cloud storage, mirrored to S3 so all
users share one cache).  A cache problem must never fail the fetch:
every S3 error self-disables the backend for the rest of the run.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from botocore.exceptions import BotoCoreError, ClientError
from loguru import logger
from pydantic import BaseModel, ValidationError

from cveta2.models import TaskAnnotations
from cveta2.s3_utils import build_s3_key, make_s3_client, s3_retry

if TYPE_CHECKING:
    from cveta2.image_downloader import CloudStorageInfo
    from cveta2.models import TaskInfo
    from cveta2.s3_types import S3Client

CACHE_SCHEMA_VERSION = 1

_COMPLETED_STATUS = "completed"
_MISSING_KEY_CODES = frozenset({"NoSuchKey", "404", "NoSuchBucket"})


class CachedTaskEnvelope(BaseModel):
    """Versioned wrapper around a cached :class:`TaskAnnotations` payload."""

    schema_version: int
    task_id: int
    task_updated_date: str
    cached_at: str
    payload: TaskAnnotations


def get_task_cache_dir(project_id: int) -> Path:
    """Return the local cache directory for a project's task annotations."""
    xdg_cache = os.environ.get("XDG_CACHE_HOME", "")
    base = Path(xdg_cache) if xdg_cache else Path.home() / ".cache"
    return base / "cveta2" / "task_annotations" / f"project_{project_id}"


def invalidate_local_entry(project_id: int, task_id: int) -> None:
    """Drop the local cache entry for *task_id* after a task mutation."""
    TaskAnnotationCache(get_task_cache_dir(project_id)).invalidate_local(task_id)


@s3_retry
def _s3_get_bytes(s3_client: S3Client, bucket: str, key: str) -> bytes:
    """Download an S3 object body as bytes."""
    resp = s3_client.get_object(Bucket=bucket, Key=key)
    data: bytes = resp["Body"].read()
    return data


@s3_retry
def _s3_put_bytes(s3_client: S3Client, bucket: str, key: str, data: bytes) -> None:
    """Upload bytes to an S3 object."""
    s3_client.put_object(Bucket=bucket, Key=key, Body=data)


def _client_error_code(error: ClientError) -> str:
    """Extract the error code string from a botocore ClientError."""
    return str(error.response.get("Error", {}).get("Code", ""))


class S3CacheBackend:
    """Shared S3 mirror of the task-annotation cache.

    Entries live under ``{key_prefix}/.cveta2_cache/task_annotations/``
    next to the project images.  Any S3 failure (except a plain missing
    key) disables the backend for the rest of the run.
    """

    def __init__(self, s3_client: S3Client, bucket: str, key_prefix: str) -> None:
        """Store the S3 client and target bucket/prefix."""
        self._s3 = s3_client
        self._bucket = bucket
        self._key_prefix = key_prefix
        self._disabled = False

    @classmethod
    def from_cloud_storage(
        cls,
        cs_info: CloudStorageInfo | None,
    ) -> S3CacheBackend | None:
        """Build a backend from CVAT cloud storage info (None when absent)."""
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
            data = _s3_get_bytes(self._s3, self._bucket, self._entry_key(task_id))
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

    def _entry_key(self, task_id: int) -> str:
        """Build the S3 key of the cache entry for *task_id*."""
        return build_s3_key(
            self._key_prefix,
            f".cveta2_cache/task_annotations/task_{task_id}.json",
        )

    def _disable(self, error: Exception) -> None:
        """Log one Russian warning and stop using S3 for the rest of the run."""
        self._disabled = True
        logger.warning(
            f"S3-кэш аннотаций недоступен ({error}) — до конца запуска "
            f"используется только локальный кэш."
        )


class TaskAnnotationCache:
    """Local (plus optional S3) cache of per-task annotation payloads.

    Only tasks with status ``completed`` are cached; an entry is valid
    only while its ``task_updated_date`` matches the live task.
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
        """Cache *result* for a completed *task* (no-op otherwise)."""
        if task.status != _COMPLETED_STATUS:
            return
        envelope = CachedTaskEnvelope(
            schema_version=CACHE_SCHEMA_VERSION,
            task_id=task.id,
            task_updated_date=task.updated_date,
            cached_at=datetime.now(timezone.utc).isoformat(),
            payload=result,
        )
        data = envelope.model_dump_json().encode("utf-8")
        self._write_local(task.id, data)
        if self._s3 is not None:
            self._s3.put(task.id, data)

    def invalidate_local(self, task_id: int) -> None:
        """Remove the local cache entry for *task_id* if present."""
        self._local_path(task_id).unlink(missing_ok=True)

    def prune(self, live_task_ids: set[int]) -> int:
        """Remove local entries whose task no longer exists; return count."""
        removed = 0
        for path in self._local_dir.glob("task_*.json"):
            task_id = _task_id_from_filename(path.name)
            if task_id is None or task_id in live_task_ids:
                continue
            path.unlink(missing_ok=True)
            removed += 1
        return removed

    def _get_local(self, task: TaskInfo) -> TaskAnnotations | None:
        """Read and validate the local entry; delete it when invalid."""
        path = self._local_path(task.id)
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            return None
        except OSError as e:
            logger.info(f"Не удалось прочитать локальный кэш задачи {task.id}: {e}")
            return None
        envelope = _validate_envelope(raw, task, source="локальный кэш")
        if envelope is None:
            path.unlink(missing_ok=True)
            return None
        return envelope.payload

    def _get_s3(self, task: TaskInfo) -> TaskAnnotations | None:
        """Read a valid entry from S3, backfilling the local cache on hit."""
        if self._s3 is None:
            return None
        raw = self._s3.get(task.id)
        if raw is None:
            return None
        envelope = _validate_envelope(raw, task, source="S3-кэш")
        if envelope is None:
            return None
        self._write_local(task.id, raw)
        return envelope.payload

    def _write_local(self, task_id: int, data: bytes) -> None:
        """Atomically write the local entry (best effort)."""
        try:
            self._local_dir.mkdir(parents=True, exist_ok=True)
            tmp_path = self._local_dir / f"task_{task_id}.json.tmp{os.getpid()}"
            tmp_path.write_bytes(data)
            tmp_path.replace(self._local_path(task_id))
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
            f"(в кэше updated_date={envelope.task_updated_date!r}, "
            f"в CVAT {task.updated_date!r}) — задача будет загружена заново"
        )
        return None
    return envelope


def _task_id_from_filename(filename: str) -> int | None:
    """Extract the task id from a ``task_{id}.json`` cache file name."""
    stem = filename.removeprefix("task_").removesuffix(".json")
    if not stem.isdigit():
        return None
    return int(stem)
