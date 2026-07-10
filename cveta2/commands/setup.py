"""Implementation of the ``cveta2 setup`` and ``cveta2 setup-cache`` commands."""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from cveta2.commands._bootstrap import open_client
from cveta2.commands._helpers import config_path_from_args
from cveta2.commands.interactive import wizard
from cveta2.config import (
    CacheConfig,
    CacheProjectSettings,
    CvatConfig,
    ImageCacheConfig,
    cache_dir_for_project,
    require_interactive,
)
from cveta2.exceptions import Cveta2Error
from cveta2.projects_cache import load_projects_cache, save_projects_cache

if TYPE_CHECKING:
    import argparse
    from pathlib import Path

    from cveta2.models import ProjectInfo


def run_setup(args: argparse.Namespace) -> None:
    """Interactively ask user for CVAT credentials and core settings."""
    config_path = config_path_from_args(args)
    require_interactive(
        "The 'setup' command is fully interactive. "
        "Configure via env vars (CVAT_HOST, CVAT_USERNAME, CVAT_PASSWORD) "
        "or edit the config file directly."
    )
    existing = CvatConfig.from_file(config_path)

    host_default = existing.host or "https://app.cvat.ai"
    host = wizard.prompt_host(host_default)
    organization = wizard.prompt_organization(existing.organization)

    username = wizard.prompt_username(existing.username or "")
    password = wizard.prompt_password()
    if not password and existing.password:
        password = existing.password
        logger.info("Пароль не изменён (использован существующий).")

    cfg = CvatConfig(
        host=host,
        organization=organization,
        username=username,
        password=password,
    )

    saved_path = cfg.save_to_file(config_path)
    logger.info(f"Готово! Конфигурация сохранена в {saved_path}")


def run_setup_cache(args: argparse.Namespace) -> None:
    """Interactively configure image cache directories for all known projects."""
    config_path = config_path_from_args(args)
    if args.list_only:
        _list_cache_paths(config_path)
        return

    require_interactive(
        "The 'setup-cache' command is fully interactive. "
        "Edit the config file directly to set image_cache paths."
    )

    projects = _ensure_projects_list(config_path)
    if not projects:
        raise Cveta2Error("Нет доступных проектов.")

    image_cache = ImageCacheConfig.load(config_path)
    cache_root = wizard.prompt_cache_root()

    if _setup_image_cache_dirs(
        projects, image_cache, cache_root, config_path, reset=args.reset
    ):
        logger.info("Пути кэширования изображений обновлены.")

    if _setup_cache_settings(projects, cache_root, config_path):
        logger.info("Настройки кэша обновлены.")
    logger.info("Готово!")


def _setup_image_cache_dirs(
    projects: list[ProjectInfo],
    image_cache: ImageCacheConfig,
    cache_root: Path | None,
    config_path: Path,
    *,
    reset: bool,
) -> bool:
    """Interactive ``image_cache`` stage; returns True when saved."""
    if cache_root is not None and _apply_root_to_all_projects(
        projects, image_cache, cache_root, reset=reset
    ):
        image_cache.save(config_path)
        return True

    logger.info(f"Найдено проектов: {len(projects)}. Укажите путь кэша для каждого.")
    logger.info("Нажмите Enter, чтобы принять значение по умолчанию или пропустить.\n")

    changed = False
    for project in projects:
        default_path = _default_cache_path(
            project, image_cache, cache_root, reset=reset
        )
        changed |= _prompt_project_cache_dir(project, image_cache, default_path)

    if changed:
        image_cache.save(config_path)
    return changed


def _setup_cache_settings(
    projects: list[ProjectInfo],
    cache_root: Path | None,
    config_path: Path,
) -> bool:
    """Interactive ``cache`` section stage; returns True when saved."""
    cache_cfg = CacheConfig.load(config_path)
    changed = False

    if cache_root is not None and cache_cfg.images_root != cache_root:
        cache_cfg.images_root = cache_root
        changed = True

    tasks_root = wizard.prompt_tasks_root(cache_cfg.tasks_root)
    if tasks_root is not None and tasks_root != cache_cfg.tasks_root:
        cache_cfg.tasks_root = tasks_root
        changed = True

    if wizard.confirm_project_cache_settings():
        for project in projects:
            changed |= _prompt_project_cache_settings(cache_cfg, project.name)

    if changed:
        cache_cfg.save(config_path)
    return changed


def _prompt_project_cache_settings(cache_cfg: CacheConfig, name: str) -> bool:
    """Prompt one project's ignored_prefix / task_cache_s3. True if changed."""
    current = cache_cfg.projects.get(name) or CacheProjectSettings()
    ignored = wizard.prompt_ignored_prefix(name, current.ignored_prefix)
    task_cache_s3 = wizard.prompt_task_cache_s3(name, current.task_cache_s3)
    if ignored == current.ignored_prefix and task_cache_s3 == current.task_cache_s3:
        return False
    cache_cfg.projects[name] = current.model_copy(
        update={"ignored_prefix": ignored, "task_cache_s3": task_cache_s3}
    )
    return True


def _list_cache_paths(config_path: Path) -> None:
    """Print current image_cache paths and cache settings, then exit."""
    image_cache = ImageCacheConfig.load(config_path)
    cache_cfg = CacheConfig.load(config_path)
    if not image_cache.projects and not cache_cfg.model_dump(exclude_defaults=True):
        logger.info("Пути кэша не заданы.")
        return
    for name, path in sorted(image_cache.projects.items()):
        logger.info(f"  {name}: {path}")
    if cache_cfg.images_root is not None:
        logger.info(f"  images_root: {cache_cfg.images_root}")
    if cache_cfg.tasks_root is not None:
        logger.info(f"  tasks_root: {cache_cfg.tasks_root}")
    for name, settings in sorted(cache_cfg.projects.items()):
        if settings.ignored_prefix:
            logger.info(f"  {name}: ignored_prefix: {settings.ignored_prefix}")
        if settings.task_cache_s3:
            logger.info(f"  {name}: task_cache_s3: {settings.task_cache_s3}")
        if settings.images_root is not None:
            logger.info(f"  {name}: images_root: {settings.images_root}")
        if settings.tasks_root is not None:
            logger.info(f"  {name}: tasks_root: {settings.tasks_root}")


def _apply_root_to_all_projects(
    projects: list[ProjectInfo],
    image_cache: ImageCacheConfig,
    cache_root: Path,
    *,
    reset: bool,
) -> bool:
    """Show derived paths for all projects; assign them all on confirmation."""
    defaults = {
        project.name: _default_cache_path(project, image_cache, cache_root, reset=reset)
        for project in projects
    }
    for name, path in defaults.items():
        logger.info(f"  {name} -> {path}")
    if not wizard.confirm_apply_to_all():
        return False
    for name, path in defaults.items():
        if path is not None:
            image_cache.set_cache_dir(name, path)
    return True


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
        return cache_dir_for_project(cache_root, project.name)
    return None


def _prompt_project_cache_dir(
    project: ProjectInfo,
    image_cache: ImageCacheConfig,
    default_path: Path | None,
) -> bool:
    """Prompt for one project's cache dir; update config. Return True if changed."""
    resolved = wizard.prompt_project_cache_dir(
        f"  {project.name} (id={project.id})", default_path
    )
    if resolved is not None:
        image_cache.set_cache_dir(project.name, resolved)
        logger.info(f"    → {resolved}")
        return True
    if default_path is not None:
        image_cache.set_cache_dir(project.name, default_path)
        logger.info(f"    → {default_path}")
        return True
    return False


def _ensure_projects_list(config_path: Path) -> list[ProjectInfo]:
    """Return cached projects; fetch from CVAT if cache is empty."""
    projects = load_projects_cache()
    if projects:
        return projects

    logger.info("Кэш проектов пуст. Загружаю список с CVAT...")
    with open_client(config_path) as client:
        projects = client.list_projects()

    if projects:
        save_projects_cache(projects)
        logger.info(f"Загружено проектов: {len(projects)}")
    return projects
