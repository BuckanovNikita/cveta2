"""Cache of CVAT projects (id, name) in a YAML file next to config."""

from __future__ import annotations

from typing import TYPE_CHECKING

import yaml
from loguru import logger

from cveta2.config import get_projects_cache_path
from cveta2.models import ProjectInfo

if TYPE_CHECKING:
    from pathlib import Path


def load_projects_cache(path: Path | None = None) -> list[ProjectInfo]:
    """Load list of projects from cache file. Returns [] if file missing or invalid."""
    cache_path = path if path is not None else get_projects_cache_path()
    if not cache_path.is_file():
        return []
    try:
        with cache_path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except (OSError, yaml.YAMLError) as e:
        logger.warning(f"Failed to load projects cache from {cache_path}: {e}")
        return []
    if not isinstance(data, dict):
        return []
    raw = data.get("projects")
    if not isinstance(raw, list):
        return []
    result: list[ProjectInfo] = []
    for item in raw:
        if isinstance(item, dict) and "id" in item and "name" in item:
            try:
                result.append(ProjectInfo(id=int(item["id"]), name=str(item["name"])))
            except (TypeError, ValueError) as e:
                logger.warning(
                    "Skipping invalid projects cache entry (id=%r, name=%r): %s",
                    item.get("id"),
                    item.get("name"),
                    e,
                )
                continue
    return result


def save_projects_cache(projects: list[ProjectInfo], path: Path | None = None) -> Path:
    """Write projects list to cache YAML. Creates parent dir if needed."""
    cache_path = path if path is not None else get_projects_cache_path()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "projects": [{"id": p.id, "name": p.name} for p in projects],
    }
    content = yaml.safe_dump(data, default_flow_style=False, sort_keys=False)
    if not content.endswith("\n"):
        content += "\n"
    cache_path.write_text(content, encoding="utf-8")
    logger.trace(f"Projects cache saved to {cache_path} ({len(projects)} projects)")
    return cache_path
