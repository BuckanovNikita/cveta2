"""Prompts of the ``setup`` wizards: personal (credentials, caches) and global (team settings).

These keep the bespoke formatting the wizards rely on (bracketed defaults,
the organization retry loop, per-project loops, RU/EN yes-no parsing) while
routing every read through :mod:`cveta2.interfaces.commands.interactive.primitives`, so
no raw ``input``/``getpass`` survives in the command modules.
"""

from typing import TYPE_CHECKING

from cveta2.composition.configuration import require_interactive
from cveta2.domain.errors import Cveta2Error
from cveta2.interfaces.commands.interactive import primitives

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

SETUP_HINT = (
    "The 'setup' wizard is interactive. Use option flags (cveta2 setup --help), "
    "CVAT_USERNAME/CVAT_PASSWORD, or edit the config file directly."
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
    return _prompt_with_default("Хост CVAT", default, hint=SETUP_HINT, history_key="cvat-host")


def prompt_username(default: str) -> str:
    """Ask for the CVAT username, defaulting to *default*."""
    return _prompt_with_default("Имя пользователя", default, hint=SETUP_HINT, history_key="cvat-username")


def prompt_password() -> str:
    """Ask for the CVAT password without echo (empty means unchanged)."""
    require_interactive(SETUP_HINT)
    return primitives.prompt_password("Пароль: ")


def prompt_organization(existing_org: str | None) -> str | None:
    """Ask for an org slug until one is given or its absence is confirmed."""
    org_default = existing_org or ""
    while True:
        organization = _prompt_with_default(
            "Slug организации",
            org_default,
            hint=SETUP_HINT,
            history_key="cvat-organization",
        )
        if organization:
            return organization
        if primitives.confirm(
            "Организация не указана. Подтвердите, что у вас нет организации",
            hint=SETUP_HINT,
        ):
            return None


def prompt_cache_root() -> "Path | None":
    """Ask for the cache root directory; ``None`` when left empty."""
    return primitives.path(
        "Корневая директория кэша (по умолчанию для проектов: корень/имя_проекта) []: ",
        hint=SETUP_HINT,
        history_key="cache-root",
    )


def prompt_tasks_root(default: "Path | None") -> "Path | None":
    """Ask for the local task-annotation cache root; ``None`` keeps current."""
    shown = str(default) if default else "~/.cache/cveta2/task_annotations"
    return primitives.path(
        f"Локальный кэш аннотаций задач [{shown}]: ",
        hint=SETUP_HINT,
        history_key="tasks-root",
    )


def _prompt_team_value(  # noqa: PLR0913 - one prompt of the global wizard, fully described
    project_name: str,
    label: str,
    shown: str,
    *,
    unset: str,
    history_key: str,
    validate: "Callable[[str], bool | str] | None" = None,
) -> str | None:
    """Ask for one team value of a project; ``None`` on Enter, which keeps the current value."""
    return (
        primitives.text(
            f"  {project_name}: {label} [{shown}] (Enter — оставить; удалить — --unset {unset}): ",
            hint=SETUP_HINT,
            allow_empty=True,
            validate=validate,
            history_key=history_key,
        )
        or None
    )


def prompt_ignored_prefix(project_name: str, default: str | None) -> str | None:
    """Ask for a project's ignored S3 prefix; empty input keeps *default*."""
    answer = _prompt_team_value(
        project_name,
        "игнорируемый префикс S3",
        default or "не задан",
        unset="ignored-prefix",
        history_key="ignored-prefix",
    )
    return answer or default


def prompt_task_cache_s3(project_name: str, default: str | None) -> str | None:
    """Ask for a project's task-cache S3 location; empty input keeps *default*."""
    answer = _prompt_team_value(
        project_name,
        "S3-путь кэша задач",
        default or "по умолчанию (<префикс изображений>/.cveta2_cache)",
        unset="task-cache-s3",
        history_key="task-cache-s3",
    )
    return answer or default


def prompt_clearml_project(project_name: str, default: str | None) -> str | None:
    """Ask for the ClearML project the bundles are published to; empty input keeps *default*."""
    answer = _prompt_team_value(
        project_name,
        "проект ClearML для публикации",
        default or "не задан",
        unset="clearml-project",
        history_key="clearml-project",
    )
    return answer or default


def prompt_dataset_name(project_name: str, default: str | None) -> str | None:
    """Ask for the ClearML dataset name; empty input keeps *default*."""
    answer = _prompt_team_value(
        project_name,
        "имя датасета ClearML",
        default or "не задано",
        unset="dataset-name",
        history_key="dataset-name",
    )
    return answer or default


def prompt_api_url(project_name: str, default: str | None) -> str | None:
    """Ask for the URL of the class API; empty input keeps *default*."""
    answer = _prompt_team_value(
        project_name,
        "URL API классов",
        default or "не задан",
        unset="api-url",
        history_key="api-url",
    )
    return answer or default


def _class_ids(raw: str) -> list[int] | None:
    """Parse comma-separated class IDs; ``None`` when one of them is not an integer."""
    try:
        return [int(part) for part in raw.split(",") if part.strip()]
    except ValueError:
        return None


def prompt_empty_classes(project_name: str, default: list[int]) -> list[int]:
    """Ask for the excluded class IDs, comma-separated; empty input keeps *default*."""
    answer = _prompt_team_value(
        project_name,
        "ID исключённых классов через запятую",
        ", ".join(str(class_id) for class_id in default) or "нет",
        unset="empty-class",
        history_key="empty-classes",
        validate=lambda raw: _class_ids(raw) is not None or "Введите целые числа через запятую.",
    )
    if answer is None:
        return default
    parsed = _class_ids(answer)
    if parsed is None:
        # The prompt's validator re-asks; this only guards callers that bypass it.
        raise Cveta2Error(f"Некорректные ID классов: {answer}")
    return parsed


def confirm_apply_to_all() -> bool:
    """Ask whether to apply the derived cache paths to all projects."""
    return primitives.confirm("Применить ко всем проектам?", default=True, hint=SETUP_HINT)


def prompt_project_cache_dir(label: str, default_path: "Path | None") -> "Path | None":
    """Ask for one project's cache dir.  ``None`` keeps the current value."""
    shown = str(default_path) if default_path is not None else "не задан"
    return primitives.path(f"{label} [{shown}]: ", hint=SETUP_HINT, history_key="project-cache-dir")
