"""Implementation of the ``cveta2 setup-clearml`` command."""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from cveta2.commands._helpers import config_path_from_args
from cveta2.commands.interactive import wizard
from cveta2.config import (
    ClearmlProjectMapping,
    load_clearml_config,
    require_interactive,
    save_clearml_config,
)
from cveta2.projects_cache import load_projects_cache

if TYPE_CHECKING:
    import argparse
    from pathlib import Path


def run_setup_clearml(args: argparse.Namespace) -> None:
    """Configure ClearML project mappings for dataset publishing."""
    config_path = config_path_from_args(args)
    if args.list_only:
        _list_mappings(config_path)
        return

    require_interactive(
        "The 'setup-clearml' command is fully interactive. "
        "Edit the config file directly to set clearml mappings."
    )

    projects = load_projects_cache()
    if not projects:
        logger.warning(
            "Кэш проектов пуст. Сначала выполните 'cveta2 setup-cache' "
            "для загрузки списка проектов."
        )
        return

    cfg = load_clearml_config(config_path)

    enabled = wizard.prompt_clearml_enabled(current=cfg.enabled)
    if enabled is not None:
        cfg = cfg.model_copy(update={"enabled": enabled})

    logger.info(
        f"Найдено проектов: {len(projects)}. "
        "Укажите ClearML project и dataset name для каждого."
    )
    logger.info("Нажмите Enter, чтобы пропустить проект или принять значение.\n")

    changed = False
    for project in projects:
        existing = cfg.get_mapping(project.name)
        result = _prompt_project_mapping(project.name, project.id, existing)
        if result is not None:
            cfg.projects[project.name] = result
            changed = True
        elif existing is not None:
            changed = True

    if changed:
        save_clearml_config(cfg, config_path)
        logger.info("Готово! ClearML маппинг обновлён.")
    else:
        logger.info("Ничего не изменено.")


def _list_mappings(config_path: Path) -> None:
    """Print current ClearML project mappings and exit."""
    cfg = load_clearml_config(config_path)
    logger.info(f"ClearML enabled: {cfg.enabled}")
    if not cfg.projects:
        logger.info("ClearML маппинг не задан.")
        return
    for name, mapping in sorted(cfg.projects.items()):
        logger.info(
            f"  {name}: project={mapping.clearml_project!r}, "
            f"dataset={mapping.clearml_dataset!r}"
        )


def _prompt_project_mapping(
    project_name: str,
    project_id: int,
    existing: ClearmlProjectMapping | None,
) -> ClearmlProjectMapping | None:
    """Prompt user for ClearML project/dataset for one CVAT project."""
    default_proj = existing.clearml_project if existing else ""
    default_ds = existing.clearml_dataset if existing else ""

    clearml_project = wizard.prompt_clearml_project(
        f"  {project_name} (id={project_id})", default_proj
    )

    if not clearml_project:
        return None

    clearml_dataset = wizard.prompt_clearml_dataset(default_ds, project_name)

    return ClearmlProjectMapping(
        clearml_project=clearml_project,
        clearml_dataset=clearml_dataset,
    )
