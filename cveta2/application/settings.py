"""Validated settings without configuration discovery or loading effects."""

from pathlib import Path

from pydantic import BaseModel, field_validator


def _none_if_falsy(value: object) -> object:
    """Coerce falsy YAML values (``""`` / ``0`` / ``null``) to None, else str."""
    return str(value) if value else None


class CacheProjectSettings(BaseModel):
    """Cache settings for one project (unset fields fall back to globals).

    ``images_root``/``tasks_root`` are local roots for downloaded images
    and the task-annotation cache.  ``ignored_prefix`` is the leading part
    of S3 keys stripped on local save (the remainder keeps its subfolders).
    ``task_cache_s3`` points the shared task cache at an explicit
    ``s3://bucket/prefix`` (or a bare prefix within the project bucket).
    """

    images_root: Path | None = None
    tasks_root: Path | None = None
    ignored_prefix: str | None = None
    task_cache_s3: str | None = None

    none_if_falsy = field_validator(
        "images_root", "tasks_root", "ignored_prefix", "task_cache_s3", mode="before"
    )(_none_if_falsy)


class IgnoredTask(BaseModel):
    """A single ignored task entry (id + cached name + optional description)."""

    id: int
    name: str
    description: str = ""
    silent: bool = False


class ClearmlProjectMapping(BaseModel):
    """Mapping of a single CVAT project to a ClearML project/dataset pair."""

    clearml_project: str
    clearml_dataset: str
