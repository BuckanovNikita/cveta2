"""Implementation of the ``cveta2 setup`` command."""

from __future__ import annotations

import getpass
from pathlib import Path

from loguru import logger

from cveta2.config import (
    CvatConfig,
    ImageCacheConfig,
    load_image_cache_config,
    require_interactive,
)


def run_setup(config_path: Path) -> None:
    """Interactively ask user for CVAT settings and save them to config file."""
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

    image_cache = _setup_image_cache(config_path)
    saved_path = cfg.save_to_file(config_path, image_cache=image_cache)
    logger.info(f"Готово! Конфигурация сохранена в {saved_path}")


def _setup_image_cache(config_path: Path) -> ImageCacheConfig:
    """Interactively configure per-project image cache directories."""
    image_cache = load_image_cache_config(config_path)
    setup_images = (
        input("Настроить пути для кэширования изображений? [y/n]: ").strip().lower()
    )
    if setup_images != "y":
        return image_cache
    while True:
        proj_name = input("Имя проекта (пустая строка — завершить): ").strip()
        if not proj_name:
            break
        proj_path = input(f"Путь для изображений проекта {proj_name!r}: ").strip()
        if proj_path:
            resolved = Path(proj_path).resolve()
            image_cache.set_cache_dir(proj_name, resolved)
            logger.info(f"  {proj_name} -> {resolved}")
    return image_cache
