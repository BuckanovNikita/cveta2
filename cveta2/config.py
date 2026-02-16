"""Configuration loading with priority: env > config file > preset > defaults."""

from __future__ import annotations

import getpass
import importlib.resources
import os
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar

import yaml
from loguru import logger
from pydantic import BaseModel

from cveta2.exceptions import InteractiveModeRequiredError

if TYPE_CHECKING:
    from collections.abc import Callable

_T = TypeVar("_T")

CONFIG_DIR = Path.home() / ".config" / "cveta2"
CONFIG_PATH = CONFIG_DIR / "config.yaml"


def is_interactive_disabled() -> bool:
    """Return True when CVETA2_NO_INTERACTIVE is set to 'true' (case-insensitive)."""
    return os.environ.get("CVETA2_NO_INTERACTIVE", "").lower() == "true"


def require_interactive(hint: str) -> None:
    """Raise if interactive prompts are disabled.

    Parameters
    ----------
    hint:
        Human-readable explanation of which CLI flag / env var the caller
        should use instead of an interactive prompt.

    """
    if is_interactive_disabled():
        raise InteractiveModeRequiredError(
            f"Interactive prompt required but CVETA2_NO_INTERACTIVE=true. {hint}"
        )


def get_config_path(config_path: Path | None = None) -> Path:
    """Return path to config file.

    Uses *config_path* if provided, otherwise CVETA2_CONFIG env var,
    otherwise default CONFIG_PATH.
    """
    if config_path is not None:
        return config_path
    path = os.environ.get("CVETA2_CONFIG")
    return Path(path) if path else CONFIG_PATH


def get_projects_cache_path(config_path: Path | None = None) -> Path:
    """Path to projects cache YAML (same directory as config file)."""
    return get_config_path(config_path).parent / "projects.yaml"


def _load_preset_data() -> dict[str, object]:
    """Load the bundled preset YAML and return raw dict."""
    ref = importlib.resources.files("cveta2.presets").joinpath("default.yaml")
    text = ref.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    if isinstance(data, dict):
        return data
    return {}


def _load_raw_yaml(path: Path) -> dict[str, object]:
    """Load a YAML file and return its top-level mapping (or empty dict)."""
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        logger.warning(f"Invalid config format in {path}; expected mapping.")
        return {}
    return data


def _load_section(
    section_key: str,
    parse_fn: Callable[[object], _T],
    config_path: Path | None = None,
) -> _T:
    """Load a config section: path, raw YAML, then parse with *parse_fn*."""
    path = get_config_path(config_path)
    data = _load_raw_yaml(path)
    return parse_fn(data.get(section_key))


def _save_section(
    section_key: str,
    value: _T,
    serialize_fn: Callable[[_T], object | None],
    config_path: Path | None = None,
    *,
    log_message: str | None = None,
) -> Path:
    """Update one section of the config YAML.

    If *serialize_fn* returns None, the section key is removed.
    """
    path = get_config_path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = _load_raw_yaml(path)
    serialized = serialize_fn(value)
    if serialized is None:
        existing.pop(section_key, None)
    else:
        existing[section_key] = serialized
    content = yaml.safe_dump(
        existing,
        default_flow_style=False,
        sort_keys=False,
    )
    if not content.endswith("\n"):
        content += "\n"
    path.write_text(content, encoding="utf-8")
    if log_message and "{path}" in log_message:
        logger.info(log_message.format(path=path))
    else:
        logger.info(log_message or f"Config saved to {path}")
    return path


class CvatConfig(BaseModel):
    """CVAT connection settings."""

    host: str = ""
    organization: str | None = None
    token: str | None = None
    username: str | None = None
    password: str | None = None

    @classmethod
    def _from_cvat_section(cls, data: dict[str, object]) -> CvatConfig:
        """Build from a raw YAML top-level dict (reads the ``cvat`` key)."""
        cvat_section = data.get("cvat", {})
        if not isinstance(cvat_section, dict):
            return cls()
        return cls(**{k: v for k, v in cvat_section.items() if k in cls.model_fields})

    @classmethod
    def from_file(cls, path: Path = CONFIG_PATH) -> CvatConfig:
        """Load config from a YAML file.  Returns empty config if file is missing."""
        if not path.is_file():
            return cls()
        logger.trace(f"Loading config from {path}")
        data = _load_raw_yaml(path)
        return cls._from_cvat_section(data)

    @classmethod
    def from_env(cls) -> CvatConfig:
        """Build config from environment variables."""
        return cls(
            host=os.environ.get("CVAT_HOST", ""),
            organization=os.environ.get("CVAT_ORGANIZATION"),
            token=os.environ.get("CVAT_TOKEN"),
            username=os.environ.get("CVAT_USERNAME"),
            password=os.environ.get("CVAT_PASSWORD"),
        )

    def merge(self, override: CvatConfig) -> CvatConfig:
        """Return a new config where *override* values take priority over self.

        Only non-empty / non-None values from *override* win.
        """
        return CvatConfig(
            host=override.host or self.host,
            organization=override.organization or self.organization,
            token=override.token or self.token,
            username=override.username or self.username,
            password=override.password or self.password,
        )

    @classmethod
    def load(cls, config_path: Path | None = None) -> CvatConfig:
        """Merge preset, file, and env: preset < file < env."""
        preset_data = _load_preset_data()
        preset_cfg = cls._from_cvat_section(preset_data)
        path = get_config_path(config_path)
        file_cfg = cls.from_file(path)
        env_cfg = cls.from_env()
        return preset_cfg.merge(file_cfg).merge(env_cfg)

    def save_to_file(
        self,
        path: Path = CONFIG_PATH,
        *,
        image_cache: ImageCacheConfig | None = None,
    ) -> Path:
        """Write config to a YAML file, preserving ``image_cache`` section."""
        path.parent.mkdir(parents=True, exist_ok=True)

        # Preserve existing image_cache if not explicitly provided
        existing_image_cache = image_cache
        if existing_image_cache is None:
            existing_data = _load_raw_yaml(path)
            raw_ic = existing_data.get("image_cache")
            if isinstance(raw_ic, dict):
                existing_image_cache = ImageCacheConfig(
                    projects={k: Path(str(v)) for k, v in raw_ic.items()},
                )

        cvat_data: dict[str, str] = {"host": self.host}
        if self.organization:
            cvat_data["organization"] = self.organization
        if self.token:
            cvat_data["token"] = self.token
        if self.username:
            cvat_data["username"] = self.username
        if self.password:
            cvat_data["password"] = self.password

        output: dict[str, object] = {"cvat": cvat_data}
        if existing_image_cache and existing_image_cache.projects:
            output["image_cache"] = {
                k: str(v) for k, v in existing_image_cache.projects.items()
            }

        content = yaml.safe_dump(output, default_flow_style=False, sort_keys=False)
        if not content.endswith("\n"):
            content += "\n"
        path.write_text(content, encoding="utf-8")
        logger.info(f"Config saved to {path}")
        return path

    def ensure_credentials(self) -> CvatConfig:
        """Prompt interactively for missing credentials.  Returns updated copy."""
        username = self.username
        password = self.password
        token = self.token

        if token:
            return self

        if not username:
            require_interactive("Задайте CVAT_TOKEN или CVAT_USERNAME/CVAT_PASSWORD.")
            logger.info("Учётные данные не указаны. Введите логин CVAT:")
            username = input("Имя пользователя: ")
        if not password:
            require_interactive("Задайте CVAT_TOKEN или CVAT_PASSWORD.")
            password = getpass.getpass(f"Пароль для {username}: ")

        return self.model_copy(update={"username": username, "password": password})


# ---------------------------------------------------------------------------
# Image cache config
# ---------------------------------------------------------------------------


class ImageCacheConfig(BaseModel):
    """Per-project mapping: project_name -> local directory for images."""

    projects: dict[str, Path] = {}

    def get_cache_dir(self, project_name: str) -> Path | None:
        """Return the cache directory for *project_name*, or None if not configured."""
        return self.projects.get(project_name)

    def set_cache_dir(self, project_name: str, path: Path) -> None:
        """Add or update the cache directory for *project_name*."""
        self.projects[project_name] = path


def _parse_image_cache_section(raw: object) -> ImageCacheConfig:
    """Parse ``image_cache`` section from raw YAML value."""
    if not isinstance(raw, dict):
        return ImageCacheConfig()
    return ImageCacheConfig(projects={k: Path(str(v)) for k, v in raw.items()})


def load_image_cache_config(config_path: Path | None = None) -> ImageCacheConfig:
    """Load the ``image_cache`` section from the config YAML."""
    return _load_section("image_cache", _parse_image_cache_section, config_path)


class IgnoredTask(BaseModel):
    """A single ignored task entry (id + cached name + optional description)."""

    id: int
    name: str
    description: str = ""


class IgnoreConfig(BaseModel):
    """Per-project mapping of ignored tasks.

    Ignored tasks are treated as permanently in-progress and skipped entirely.
    Each entry stores both the task ID and its human-readable name.
    """

    projects: dict[str, list[IgnoredTask]] = {}

    def get_ignored_tasks(self, project_name: str) -> list[int]:
        """Return the list of ignored task IDs for *project_name*."""
        return [t.id for t in self.projects.get(project_name, [])]

    def get_ignored_entries(self, project_name: str) -> list[IgnoredTask]:
        """Return the full ignored-task entries for *project_name*."""
        return list(self.projects.get(project_name, []))

    def add_task(
        self,
        project_name: str,
        task_id: int,
        task_name: str,
        description: str = "",
    ) -> None:
        """Add a task to the ignore list for *project_name*."""
        entries = self.projects.setdefault(project_name, [])
        if not any(e.id == task_id for e in entries):
            entries.append(
                IgnoredTask(id=task_id, name=task_name, description=description)
            )

    def remove_task(self, project_name: str, task_id: int) -> bool:
        """Remove a task from the ignore list for *project_name*.

        Returns True if the task was found and removed.
        """
        entries = self.projects.get(project_name, [])
        for i, e in enumerate(entries):
            if e.id == task_id:
                entries.pop(i)
                if not entries:
                    del self.projects[project_name]
                return True
        return False


def _parse_ignore_entry(raw: object) -> IgnoredTask | None:
    """Parse a single ignore entry (new dict format or legacy bare int)."""
    if isinstance(raw, dict) and "id" in raw:
        try:
            return IgnoredTask(
                id=int(raw["id"]),
                name=str(raw.get("name", "")),
                description=str(raw.get("description", "")),
            )
        except (TypeError, ValueError):
            return None
    if isinstance(raw, int):
        return IgnoredTask(id=raw, name="")
    if isinstance(raw, str) and raw.strip().isdigit():
        return IgnoredTask(id=int(raw), name="")
    return None


def _parse_ignore_section(raw: object) -> IgnoreConfig:
    """Parse ``ignore`` section from raw YAML value (supports dict of lists format)."""
    if not isinstance(raw, dict):
        return IgnoreConfig()
    projects: dict[str, list[IgnoredTask]] = {}
    for project_name, entries in raw.items():
        if not isinstance(entries, list):
            continue
        parsed: list[IgnoredTask] = []
        for item in entries:
            entry = _parse_ignore_entry(item)
            if entry is not None:
                parsed.append(entry)
        if parsed:
            projects[str(project_name)] = parsed
    return IgnoreConfig(projects=projects)


def load_ignore_config(config_path: Path | None = None) -> IgnoreConfig:
    """Load the ``ignore`` section from the config YAML.

    Supports both the new format (list of ``{id, name}`` dicts) and the
    legacy format (list of bare ints).
    """
    return _load_section("ignore", _parse_ignore_section, config_path)


def _serialize_ignore_entry(entry: IgnoredTask) -> dict[str, object]:
    """Serialize an ``IgnoredTask`` to a dict for YAML output."""
    data: dict[str, object] = {"id": entry.id, "name": entry.name}
    if entry.description:
        data["description"] = entry.description
    return data


def _serialize_ignore_section(ignore: IgnoreConfig) -> dict[str, object] | None:
    """Serialize ignore config to YAML-friendly dict, or None if empty."""
    if not ignore.projects:
        return None
    return {
        proj: [_serialize_ignore_entry(e) for e in entries]
        for proj, entries in ignore.projects.items()
    }


def save_ignore_config(
    ignore: IgnoreConfig,
    config_path: Path | None = None,
) -> Path:
    """Update only the ``ignore`` section of the config YAML.

    Always writes the new ``{id, name}`` dict format.
    Preserves the existing ``cvat``, ``image_cache`` and other sections.
    """
    return _save_section(
        "ignore",
        ignore,
        _serialize_ignore_section,
        config_path,
        log_message="Ignore config saved to {path}",
    )


class UploadConfig(BaseModel):
    """Settings for the ``upload`` command."""

    images_per_job: int = 100


def _parse_upload_section(raw: object) -> UploadConfig:
    """Parse ``upload`` section from raw YAML value."""
    if not isinstance(raw, dict):
        return UploadConfig()
    filtered = {k: v for k, v in raw.items() if k in UploadConfig.model_fields}
    return UploadConfig(**filtered)


def load_upload_config(config_path: Path | None = None) -> UploadConfig:
    """Load the ``upload`` section from the config YAML."""
    return _load_section("upload", _parse_upload_section, config_path)


def _serialize_image_cache_section(image_cache: ImageCacheConfig) -> dict[str, str]:
    """Serialize image cache config to YAML-friendly dict."""
    return {k: str(v) for k, v in image_cache.projects.items()}


def save_image_cache_config(
    image_cache: ImageCacheConfig,
    config_path: Path | None = None,
) -> Path:
    """Update only the ``image_cache`` section of the config YAML.

    Preserves the existing ``cvat`` and any other sections.
    """
    return _save_section(
        "image_cache",
        image_cache,
        _serialize_image_cache_section,
        config_path,
        log_message="Image cache config saved to {path}",
    )
