"""Versioned task-cache values and pure payload validation."""

from loguru import logger
from pydantic import BaseModel, ValidationError

from cveta2.domain.models import TaskAnnotations, TaskInfo

# v5: standalone polygons contribute bounding boxes; older entries discarded
# them and can incorrectly report polygon-only frames as unannotated.
# v4: payload records carry task-wide completion; older per-frame job
# mappings lost unfinished jobs in overlapping or sparse job layouts.
# v3: payload records carry ``job_stage``/``job_state`` in place of
# ``task_status``; a v2 entry has no per-job review position, and the
# partition would read every one of its rows as still unreviewed.
# v2: payload records carry ``frame_path`` (nested CVAT frame names); v1
# entries were saved after basename collapse and would rebuild a wrong
# ``s3_image_path`` for multilevel S3 hierarchies.
CACHE_SCHEMA_VERSION = 5

_COMPLETED_STATUS = "completed"

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
        logger.warning(
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
