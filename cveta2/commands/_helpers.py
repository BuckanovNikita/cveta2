"""Shared helpers for CLI commands."""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

from loguru import logger

from cveta2.config import CONFIG_PATH, CvatConfig

if TYPE_CHECKING:
    from pathlib import Path

    import pandas as pd


def load_config(config_path: Path | None = None) -> CvatConfig:
    """Load config from file and env. Path from CVETA2_CONFIG or argument."""
    return CvatConfig.load(config_path=config_path)


def require_host(cfg: CvatConfig) -> None:
    """Abort with a friendly message when host is not configured."""
    if cfg.host:
        return
    config_path = os.environ.get("CVETA2_CONFIG", str(CONFIG_PATH))
    sys.exit(
        "Ошибка: хост CVAT не настроен.\n"
        "Запустите setup для сохранения настроек:\n  cveta2 setup\n"
        "Или задайте переменные окружения: CVAT_HOST и "
        "(CVAT_TOKEN или CVAT_USERNAME/CVAT_PASSWORD).\n"
        f"Файл конфигурации: {config_path}"
    )


def write_df_csv(df: pd.DataFrame, path: Path, label: str) -> None:
    """Write a DataFrame to CSV and log the result."""
    df.to_csv(path, index=False, encoding="utf-8")
    logger.info(f"{label} saved to {path} ({len(df)} rows)")


def write_deleted_txt(deleted_names: list[str], path: Path) -> None:
    """Write deleted image names to a text file, one per line."""
    content = "\n".join(deleted_names)
    if deleted_names:
        content += "\n"
    path.write_text(content, encoding="utf-8")
    logger.info(f"Deleted images list saved to {path} ({len(deleted_names)} names)")
