"""Setup-wizard prompts for ``setup``, ``setup-cache`` and ``setup-clearml``.

These keep the bespoke formatting the wizards rely on (bracketed defaults,
the organization retry loop, per-project loops, RU/EN yes-no parsing) while
routing every read through :mod:`cveta2.commands.interactive.primitives`, so
no raw ``input``/``getpass`` survives in the command modules.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cveta2.commands.interactive import primitives
from cveta2.config import require_interactive

if TYPE_CHECKING:
    from pathlib import Path

_YES_TOKENS = {"да", "yes", "y", "true", "1"}
_NO_TOKENS = {"нет", "no", "n", "false", "0"}

_SETUP_HINT = (
    "The 'setup' command is fully interactive. "
    "Configure via env vars (CVAT_HOST, CVAT_USERNAME, CVAT_PASSWORD) "
    "or edit the config file directly."
)
_CACHE_HINT = (
    "The 'setup-cache' command is fully interactive. "
    "Edit the config file directly to set image_cache paths."
)
_CLEARML_HINT = (
    "The 'setup-clearml' command is fully interactive. "
    "Edit the config file directly to set the ClearML mapping."
)


def _prompt_with_default(
    label: str,
    default: str,
    *,
    hint: str,
    history_key: str | None = None,
) -> str:
    """Prompt showing *default* in brackets; empty input keeps the default."""
    suffix = f" [{default}]" if default else ""
    return (
        primitives.text(
            f"{label}{suffix}: ",
            hint=hint,
            default=default,
            allow_empty=True,
            history_key=history_key,
        )
        or default
    )


def prompt_host(default: str) -> str:
    """Ask for the CVAT host, defaulting to *default*."""
    return _prompt_with_default(
        "Хост CVAT", default, hint=_SETUP_HINT, history_key="cvat-host"
    )


def prompt_username(default: str) -> str:
    """Ask for the CVAT username, defaulting to *default*."""
    return _prompt_with_default(
        "Имя пользователя", default, hint=_SETUP_HINT, history_key="cvat-username"
    )


def prompt_password() -> str:
    """Ask for the CVAT password without echo (empty means unchanged)."""
    require_interactive(_SETUP_HINT)
    return primitives.prompt_password("Пароль: ")


def prompt_organization(existing_org: str | None) -> str | None:
    """Ask for an org slug until one is given or its absence is confirmed."""
    org_default = existing_org or ""
    while True:
        organization = _prompt_with_default(
            "Slug организации",
            org_default,
            hint=_SETUP_HINT,
            history_key="cvat-organization",
        )
        if organization:
            return organization
        if primitives.confirm(
            "Организация не указана. Подтвердите, что у вас нет организации",
            hint=_SETUP_HINT,
        ):
            return None


def prompt_cache_root() -> Path | None:
    """Ask for the cache root directory; ``None`` when left empty."""
    return primitives.path(
        "Корневая директория кэша (по умолчанию для проектов: корень/имя_проекта) []: ",
        hint=_CACHE_HINT,
        history_key="cache-root",
    )


def prompt_tasks_root(default: Path | None) -> Path | None:
    """Ask for the local task-annotation cache root; ``None`` keeps current."""
    shown = str(default) if default else "~/.cache/cveta2/task_annotations"
    return primitives.path(
        f"Локальный кэш аннотаций задач [{shown}]: ",
        hint=_CACHE_HINT,
        history_key="tasks-root",
    )


def confirm_project_cache_settings() -> bool:
    """Ask whether to configure per-project S3 cache settings."""
    return primitives.confirm(
        "Настроить ignored_prefix / task_cache_s3 по проектам?",
        default=False,
        hint=_CACHE_HINT,
    )


def prompt_ignored_prefix(project_name: str, default: str | None) -> str | None:
    """Ask for a project's ignored S3 prefix; empty input keeps *default*."""
    shown = default or "не задан"
    return (
        primitives.text(
            f"  {project_name}: игнорируемый префикс S3 [{shown}]: ",
            hint=_CACHE_HINT,
            allow_empty=True,
            history_key="ignored-prefix",
        )
        or default
    )


def prompt_task_cache_s3(project_name: str, default: str | None) -> str | None:
    """Ask for a project's task-cache S3 location; empty input keeps *default*."""
    shown = default or "по умолчанию (<префикс изображений>/.cveta2_cache)"
    return (
        primitives.text(
            f"  {project_name}: S3-путь кэша задач [{shown}]: ",
            hint=_CACHE_HINT,
            allow_empty=True,
            history_key="task-cache-s3",
        )
        or default
    )


def confirm_apply_to_all() -> bool:
    """Ask whether to apply the derived cache paths to all projects."""
    return primitives.confirm(
        "Применить ко всем проектам?", default=True, hint=_CACHE_HINT
    )


def prompt_project_cache_dir(label: str, default_path: Path | None) -> Path | None:
    """Ask for one project's cache dir.  ``None`` keeps the current value."""
    shown = str(default_path) if default_path is not None else "не задан"
    return primitives.path(
        f"{label} [{shown}]: ", hint=_CACHE_HINT, history_key="project-cache-dir"
    )


def prompt_clearml_enabled(*, current: bool) -> bool | None:
    """Ask whether to enable ClearML.  ``None`` leaves the value unchanged."""
    default = "да" if current else "нет"
    answer = primitives.text(
        f"Включить ClearML интеграцию? [{default}]: ",
        hint=_CLEARML_HINT,
        allow_empty=True,
    )
    token = (answer or "").lower()
    if token in _YES_TOKENS:
        return True
    if token in _NO_TOKENS:
        return False
    return None


def prompt_clearml_project(label: str, default_proj: str) -> str:
    """Ask for a ClearML project name for one CVAT project."""
    suffix = f" [{default_proj}]" if default_proj else " [пропустить]"
    return (
        primitives.text(
            f"{label} clearml_project{suffix}: ",
            hint=_CLEARML_HINT,
            default=default_proj,
            allow_empty=True,
            history_key="clearml-project",
        )
        or default_proj
    )


def prompt_clearml_dataset(default_ds: str, fallback: str) -> str:
    """Ask for a ClearML dataset name, defaulting to *default_ds* or *fallback*."""
    shown = default_ds or fallback
    return (
        primitives.text(
            f"    clearml_dataset [{shown}]: ",
            hint=_CLEARML_HINT,
            allow_empty=True,
            history_key="clearml-dataset",
        )
        or default_ds
        or fallback
    )
