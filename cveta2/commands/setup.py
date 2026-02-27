"""Implementation of the ``cveta2 setup`` and ``cveta2 setup-cache`` commands."""

from __future__ import annotations

import getpass
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from cveta2.client import CvatClient
from cveta2.commands._helpers import load_config, require_host
from cveta2.config import (
    CvatConfig,
    ImageCacheConfig,
    load_image_cache_config,
    require_interactive,
    save_image_cache_config,
)
from cveta2.projects_cache import load_projects_cache, save_projects_cache

if TYPE_CHECKING:
    from cveta2.models import ProjectInfo


def run_setup(config_path: Path) -> None:
    """Interactively ask user for CVAT credentials and core settings."""
    require_interactive(
        "The 'setup' command is fully interactive. "
        "Configure via env vars (CVAT_HOST, CVAT_USERNAME, CVAT_PASSWORD) "
        "or edit the config file directly."
    )
    existing = CvatConfig.from_file(config_path)

    host_default = existing.host or "https://app.cvat.ai"
    host = input(f"Хост CVAT [{host_default}]: ").strip() or host_default
    org_default = existing.organization or ""
    org_prompt = "Slug организации (необязательно)"
    if org_default:
        org_prompt += f" [{org_default}]"
    org_prompt += ": "
    organization = input(org_prompt).strip() or org_default

    username_default = existing.username or ""
    prompt = "Имя пользователя"
    if username_default:
        prompt += f" [{username_default}]"
    prompt += ": "
    username = input(prompt).strip() or username_default
    password = getpass.getpass("Пароль: ")
    if not password and existing.password:
        password = existing.password
        logger.info("Пароль не изменён (использован существующий).")

    cfg = CvatConfig(
        host=host,
        organization=organization or None,
        username=username,
        password=password,
    )

    saved_path = cfg.save_to_file(config_path)
    logger.info(f"Готово! Конфигурация сохранена в {saved_path}")


def run_setup_cache(
    config_path: Path,
    *,
    reset: bool = False,
    list_paths: bool = False,
) -> None:
    """Interactively configure image cache directories for all known projects."""
    if list_paths:
        _list_cache_paths(config_path)
        return

    require_interactive(
        "The 'setup-cache' command is fully interactive. "
        "Edit the config file directly to set image_cache paths."
    )

    projects = _ensure_projects_list(config_path)
    if not projects:
        sys.exit("Нет доступных проектов.")

    image_cache = load_image_cache_config(config_path)
    cache_root = _prompt_cache_root()
    logger.info(f"Найдено проектов: {len(projects)}. Укажите путь кэша для каждого.")
    logger.info("Нажмите Enter, чтобы принять значение по умолчанию или пропустить.\n")

    changed = False
    for project in projects:
        default_path = _default_cache_path(
            project, image_cache, cache_root, reset=reset
        )
        changed |= _prompt_project_cache_dir(project, image_cache, default_path)

    if changed:
        save_image_cache_config(image_cache, config_path)
        logger.info("Готово! Пути кэширования обновлены.")
    else:
        logger.info("Ничего не изменено.")


def _list_cache_paths(config_path: Path) -> None:
    """Print current image_cache paths and exit."""
    image_cache = load_image_cache_config(config_path)
    if not image_cache.projects:
        logger.info("Пути кэша не заданы.")
        return
    for name, path in sorted(image_cache.projects.items()):
        logger.info(f"  {name}: {path}")


def _prompt_cache_root() -> Path | None:
    """Ask user for cache root; return resolved path or None if empty."""
    raw = input(
        "Корневая директория кэша (по умолчанию для проектов: корень/имя_проекта) []: "
    ).strip()
    return Path(raw).expanduser().resolve() if raw else None


def _default_cache_path(
    project: ProjectInfo,
    image_cache: ImageCacheConfig,
    cache_root: Path | None,
    *,
    reset: bool,
) -> Path | None:
    """Default path: existing config, or cache_root/project_name, or None."""
    if not reset and image_cache.get_cache_dir(project.name) is not None:
        return image_cache.get_cache_dir(project.name)
    if cache_root is not None:
        return _cache_dir_for_project(cache_root, project.name)
    return None


def _prompt_project_cache_dir(
    project: ProjectInfo,
    image_cache: ImageCacheConfig,
    default_path: Path | None,
) -> bool:
    """Prompt for one project's cache dir; update config. Return True if changed."""
    prompt = (
        f"  {project.name} (id={project.id}) [{default_path}]: "
        if default_path is not None
        else f"  {project.name} (id={project.id}) [не задан]: "
    )
    raw = input(prompt).strip()
    if raw:
        resolved = Path(raw).expanduser().resolve()
        image_cache.set_cache_dir(project.name, resolved)
        logger.info(f"    → {resolved}")
        return True
    if default_path is not None:
        image_cache.set_cache_dir(project.name, default_path)
        logger.info(f"    → {default_path}")
        return True
    return False


def _cache_dir_for_project(cache_root: Path, project_name: str) -> Path:
    """Return cache_root / sanitized(project_name). Replaces path-unsafe chars."""
    safe = project_name.replace("/", "_").replace("\\", "_").replace("\x00", "_")
    return cache_root / safe


def _ensure_projects_list(config_path: Path) -> list[ProjectInfo]:
    """Return cached projects; fetch from CVAT if cache is empty."""
    projects = load_projects_cache()
    if projects:
        return projects

    logger.info("Кэш проектов пуст. Загружаю список с CVAT...")
    cfg = load_config(config_path=config_path)
    require_host(cfg)

    with CvatClient(cfg) as client:
        projects = client.list_projects()

    if projects:
        save_projects_cache(projects)
        logger.info(f"Загружено проектов: {len(projects)}")
    return projects
