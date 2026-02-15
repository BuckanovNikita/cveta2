"""Implementation of the ``cveta2 setup`` and ``cveta2 setup-cache`` commands."""

from __future__ import annotations

import getpass
import sys
from pathlib import Path

from loguru import logger

from cveta2.client import CvatClient
from cveta2.commands._helpers import load_config, require_host
from cveta2.config import (
    CvatConfig,
    load_image_cache_config,
    require_interactive,
    save_image_cache_config,
)
from cveta2.projects_cache import ProjectInfo, load_projects_cache, save_projects_cache


def run_setup(config_path: Path) -> None:
    """Interactively ask user for CVAT credentials and core settings."""
    require_interactive(
        "The 'setup' command is fully interactive. "
        "Configure via env vars (CVAT_HOST, CVAT_TOKEN, etc.) "
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

    logger.info("Аутентификация: токен (t) или логин/пароль (p)?")
    auth_choice = ""
    while auth_choice not in ("t", "p"):
        auth_choice = input("Выберите [t/p]: ").strip().lower()

    token: str | None = None
    username: str | None = None
    password: str | None = None

    if auth_choice == "t":
        token_default = existing.token or ""
        prompt = "Персональный токен доступа"
        if token_default:
            prompt += f" [{token_default[:6]}...]"
        prompt += ": "
        token = input(prompt).strip() or token_default
        if not token:
            logger.warning("Токен не указан — его можно добавить позже.")
    else:
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
        token=token,
        username=username,
        password=password,
    )

    saved_path = cfg.save_to_file(config_path)
    logger.info(f"Готово! Конфигурация сохранена в {saved_path}")


def run_setup_cache(config_path: Path) -> None:
    """Interactively configure image cache directories for all known projects."""
    require_interactive(
        "The 'setup-cache' command is fully interactive. "
        "Edit the config file directly to set image_cache paths."
    )

    projects = _ensure_projects_list(config_path)
    if not projects:
        sys.exit("Нет доступных проектов.")

    image_cache = load_image_cache_config(config_path)

    logger.info(f"Найдено проектов: {len(projects)}. Укажите путь кэша для каждого.")
    logger.info("Нажмите Enter, чтобы пропустить проект или оставить текущий путь.\n")

    changed = False
    for project in projects:
        current = image_cache.get_cache_dir(project.name)
        if current is not None:
            prompt = f"  {project.name} (id={project.id}) [{current}]: "
        else:
            prompt = f"  {project.name} (id={project.id}) [не задан]: "

        raw = input(prompt).strip()
        if not raw:
            continue

        resolved = Path(raw).resolve()
        image_cache.set_cache_dir(project.name, resolved)
        changed = True
        logger.info(f"    → {resolved}")

    if changed:
        save_image_cache_config(image_cache, config_path)
        logger.info("Готово! Пути кэширования обновлены.")
    else:
        logger.info("Ничего не изменено.")


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
