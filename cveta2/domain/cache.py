"""Versioned annotation-cache entry headers and pure freshness checks."""

from pydantic import BaseModel, ConfigDict

from cveta2.domain.models import TaskInfo

# v6: entries hold the raw shapes of one job (or of a whole task whose jobs
# cannot be separated) and record every covered job's identity, review
# position and update time. Records are rebuilt from fresh jobs on every
# run, so a job moved without touching the task is noticed. v5 entries
# held finished records per task and are removed, never read.
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
CACHE_SCHEMA_VERSION = 6

# Layer names for the rejection log, kept at module level so they carry no
# behaviour: the value only ever reaches an f-string in the adapter.
_SOURCE_LOCAL = "локальный кэш"
_SOURCE_S3 = "S3-кэш"


class CachedJob(BaseModel):
    """The state of one CVAT job an entry was cached against."""

    model_config = ConfigDict(frozen=True)

    id: int
    type: str
    start_frame: int
    stop_frame: int
    stage: str
    state: str
    updated_date: str


class CachedEntryHeader(BaseModel):
    """What an annotation entry was cached against, besides its shapes.

    ``task_updated_date`` stays part of validity because a project label
    edit moves it on every task; ``cached_at`` is for diagnostics only.
    """

    schema_version: int
    task_id: int
    task_updated_date: str
    jobs: list[CachedJob]
    cached_at: str


def entry_mismatch(header: CachedEntryHeader, task: TaskInfo, jobs: list[CachedJob]) -> str | None:
    """Return why *header* no longer describes the live task and jobs, or None."""
    if header.schema_version != CACHE_SCHEMA_VERSION:
        return f"версия схемы {header.schema_version} (ожидается {CACHE_SCHEMA_VERSION})"
    if header.task_id != task.id:
        return f"запись принадлежит задаче {header.task_id}"
    if header.task_updated_date != task.updated_date:
        return f"задача изменена ({header.task_updated_date!r} вместо {task.updated_date!r})"
    if header.jobs != jobs:
        return "изменились jobs (состав, этап, состояние или время обновления)"
    return None


def task_id_from_name(name: str) -> int | None:
    """Extract the task id from a ``task_{id}`` entry name, with or without ``.json``."""
    stem = name.removeprefix("task_").removesuffix(".json")
    if not name.startswith("task_") or not stem.isdigit():
        return None
    return int(stem)
