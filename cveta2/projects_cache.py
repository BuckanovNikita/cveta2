"""Cache of CVAT projects grouped by organization, in a YAML file next to config.

Format::

    organizations:
    - slug: ""            # "" = personal workspace
      name: Личное пространство
      projects:
      - id: 1
        name: proj

The legacy flat ``projects:`` format is ignored (the cache refills on the
next rescan).

The file is read and written as bytes so its encoding never depends on the
process locale: PyYAML decodes UTF-8 on load and encodes it on save. Organization
names are Russian, so a locale-default codec would mangle them on Windows.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

import yaml
from loguru import logger
from pydantic import BaseModel, ValidationError

from cveta2.config import get_projects_cache_path
from cveta2.models import ProjectInfo

if TYPE_CHECKING:
    from pathlib import Path


class _YamlDumpOptions(TypedDict):
    r"""Serializer knobs for the cache file.

    ``load_orgs_cache`` reads through ``yaml.safe_load``, which is blind to
    all three, but this is a file in the config directory that people open
    and hand-edit: the keys stay in the order the model declares them and
    Cyrillic organization names stay literal rather than ``\uXXXX``-escaped.
    """

    encoding: str
    sort_keys: bool
    allow_unicode: bool


_YAML_DUMP: _YamlDumpOptions = {
    "encoding": "utf-8",
    "sort_keys": False,
    "allow_unicode": True,
}

PERSONAL_WORKSPACE_SLUG = ""
"""Org key of the personal workspace in the cache and in ``/PROJECT`` specs."""

PERSONAL_WORKSPACE_TITLE = "Личное пространство"


class OrgProjects(BaseModel):
    """Cached projects of one organization (``""`` slug = personal workspace)."""

    slug: str
    name: str
    projects: list[ProjectInfo]


def load_orgs_cache(path: Path | None = None) -> list[OrgProjects]:
    """Load per-organization project lists. Returns [] if missing or invalid."""
    cache_path = path if path is not None else get_projects_cache_path()
    if not cache_path.is_file():
        return []
    try:
        data = yaml.safe_load(cache_path.read_bytes())
    except (OSError, yaml.YAMLError) as e:
        logger.warning(f"Failed to load projects cache from {cache_path}: {e}")
        return []
    if not isinstance(data, dict) or not isinstance(data.get("organizations"), list):
        return []
    result: list[OrgProjects] = []
    for item in data["organizations"]:
        try:
            result.append(OrgProjects.model_validate(item))
        except ValidationError as e:
            logger.warning(f"Skipping invalid projects cache entry {item!r}: {e}")
    return result


def save_orgs_cache(orgs: list[OrgProjects], path: Path | None = None) -> Path:
    """Write per-organization project lists. Creates parent dir if needed."""
    cache_path = path if path is not None else get_projects_cache_path()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    data = {"organizations": [org.model_dump() for org in orgs]}
    cache_path.write_bytes(yaml.safe_dump(data, **_YAML_DUMP))
    logger.trace(f"Projects cache saved to {cache_path} ({len(orgs)} organizations)")
    return cache_path


def update_org_projects(
    slug: str,
    name: str,
    projects: list[ProjectInfo],
    path: Path | None = None,
) -> Path:
    """Replace one organization's project list in the cache, keeping the rest."""
    orgs = [org for org in load_orgs_cache(path) if org.slug != slug]
    orgs.append(OrgProjects(slug=slug, name=name, projects=projects))
    return save_orgs_cache(orgs, path)


def load_projects_cache(
    path: Path | None = None,
    org: str | None = None,
) -> list[ProjectInfo]:
    """Flat project list from the cache.

    *org* of ``None`` merges all organizations; a slug (``""`` = personal
    workspace) selects that organization only.
    """
    orgs = load_orgs_cache(path)
    if org is not None:
        orgs = [entry for entry in orgs if entry.slug == org]
    return [project for entry in orgs for project in entry.projects]
