"""Configuration loading with priority: env > config file > preset > defaults."""

from __future__ import annotations

import importlib.resources
import os
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar

import yaml
from loguru import logger
from pydantic import BaseModel, Field, field_validator

from cveta2.exceptions import InteractiveModeRequiredError, MissingCredentialsError

if TYPE_CHECKING:
    from collections.abc import Callable

_T = TypeVar("_T")

CONFIG_DIR = Path.home() / ".config" / "cveta2"
CONFIG_PATH = CONFIG_DIR / "config.yaml"


def is_interactive_disabled() -> bool:
    """Return True when CVETA2_NO_INTERACTIVE is set to 'true' (case-insensitive)."""
    return os.environ.get("CVETA2_NO_INTERACTIVE", "").lower() == "true"


def is_cache_disabled() -> bool:
    """Return True when CVETA2_DISABLE_CACHE is set to 'true' (case-insensitive)."""
    return os.environ.get("CVETA2_DISABLE_CACHE", "").lower() == "true"


def should_raise_on_fetch_failure() -> bool:
    """Return True when CVETA2_RAISE_ON_FAILURE requests aborting on first error."""
    return os.environ.get("CVETA2_RAISE_ON_FAILURE", "").lower() == "true"


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


def _parse_timeout_env(raw: str | None) -> float | None:
    """Parse CVETA2_DATA_TIMEOUT env value; warn and return None on garbage."""
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        logger.warning(
            f"Некорректное значение CVETA2_DATA_TIMEOUT={raw!r} — "
            f"ожидается число секунд; таймаут не применяется."
        )
        return None


class CvatConfig(BaseModel):
    """CVAT connection settings."""

    host: str = ""
    organization: str | None = None
    username: str | None = None
    password: str | None = None
    request_timeout: float | None = None

    @field_validator("host")
    @classmethod
    def _strip_host_trailing_slash(cls, value: str) -> str:
        """Normalize host URL by stripping trailing slashes."""
        return value.rstrip("/")

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
            username=os.environ.get("CVAT_USERNAME"),
            password=os.environ.get("CVAT_PASSWORD"),
            request_timeout=_parse_timeout_env(os.environ.get("CVETA2_DATA_TIMEOUT")),
        )

    def merge(self, override: CvatConfig) -> CvatConfig:
        """Return a new config where *override* values take priority over self.

        Only non-empty / non-None values from *override* win.
        """
        return CvatConfig(
            host=override.host or self.host,
            organization=override.organization or self.organization,
            username=override.username or self.username,
            password=override.password or self.password,
            request_timeout=(
                override.request_timeout
                if override.request_timeout is not None
                else self.request_timeout
            ),
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
        """Write config to a YAML file, preserving all non-``cvat`` sections."""
        path.parent.mkdir(parents=True, exist_ok=True)
        existing_data = _load_raw_yaml(path)

        cvat_data: dict[str, str | float] = {"host": self.host}
        if self.organization:
            cvat_data["organization"] = self.organization
        if self.username:
            cvat_data["username"] = self.username
        if self.password:
            cvat_data["password"] = self.password
        if self.request_timeout is not None:
            cvat_data["request_timeout"] = self.request_timeout

        output: dict[str, object] = {"cvat": cvat_data}
        output.update(
            (key, value) for key, value in existing_data.items() if key != "cvat"
        )
        if image_cache is not None and image_cache.projects:
            output["image_cache"] = {k: str(v) for k, v in image_cache.projects.items()}

        content = yaml.safe_dump(output, default_flow_style=False, sort_keys=False)
        if not content.endswith("\n"):
            content += "\n"
        path.write_text(content, encoding="utf-8")
        logger.info(f"Config saved to {path}")
        return path

    def require_credentials(self) -> CvatConfig:
        """Return self when credentials are present; raise otherwise.

        Never prompts.  The CLI layer prompts for missing credentials
        before opening a client (``cveta2.commands._bootstrap``).
        """
        if self.username and self.password:
            return self
        raise MissingCredentialsError(
            "Учётные данные CVAT не настроены. Задайте CVAT_USERNAME и "
            f"CVAT_PASSWORD или заполните cvat.username/password в {CONFIG_PATH}."
        )


# ---------------------------------------------------------------------------
# Image cache config
# ---------------------------------------------------------------------------


class ImageCacheConfig(BaseModel):
    """Per-project mapping: project_name -> local directory for images."""

    projects: dict[str, Path] = Field(default_factory=dict)

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


# ---------------------------------------------------------------------------
# Cache settings (image/task cache roots, S3 layout)
# ---------------------------------------------------------------------------


class CacheProjectSettings(BaseModel):
    """Cache settings for one project (unset fields fall back to globals).

    ``images_root``/``tasks_root`` are local roots for downloaded images
    and the task-annotation cache.  ``ignored_prefix`` is the leading part
    of S3 keys stripped on local save (the remainder keeps its subfolders).
    ``task_cache_s3`` points the shared task cache at an explicit
    ``s3://bucket/prefix`` (or a bare prefix within the project bucket).
    """

    images_root: Path | None = None
    tasks_root: Path | None = None
    ignored_prefix: str | None = None
    task_cache_s3: str | None = None


class CacheConfig(BaseModel):
    """Global cache settings plus per-project overrides."""

    images_root: Path | None = None
    tasks_root: Path | None = None
    projects: dict[str, CacheProjectSettings] = Field(default_factory=dict)

    def for_project(self, project_name: str) -> CacheProjectSettings:
        """Resolve effective settings for *project_name* (overrides win)."""
        proj = self.projects.get(project_name) or CacheProjectSettings()
        return CacheProjectSettings(
            images_root=proj.images_root or self.images_root,
            tasks_root=proj.tasks_root or self.tasks_root,
            ignored_prefix=proj.ignored_prefix,
            task_cache_s3=proj.task_cache_s3,
        )


def cache_dir_for_project(root: Path, project_name: str) -> Path:
    """Return ``root / sanitized(project_name)``. Replaces path-unsafe chars."""
    safe = project_name.replace("/", "_").replace("\\", "_").replace("\x00", "_")
    return root / safe


def _parse_cache_project(raw: object) -> CacheProjectSettings:
    """Parse one per-project entry of the ``cache.projects`` mapping."""
    if not isinstance(raw, dict):
        return CacheProjectSettings()
    return CacheProjectSettings(
        images_root=Path(str(raw["images_root"])) if raw.get("images_root") else None,
        tasks_root=Path(str(raw["tasks_root"])) if raw.get("tasks_root") else None,
        ignored_prefix=str(raw["ignored_prefix"])
        if raw.get("ignored_prefix")
        else None,
        task_cache_s3=str(raw["task_cache_s3"]) if raw.get("task_cache_s3") else None,
    )


def _parse_cache_section(raw: object) -> CacheConfig:
    """Parse the ``cache`` section from raw YAML value."""
    if not isinstance(raw, dict):
        return CacheConfig()
    projects_raw = raw.get("projects")
    projects = (
        {str(k): _parse_cache_project(v) for k, v in projects_raw.items()}
        if isinstance(projects_raw, dict)
        else {}
    )
    return CacheConfig(
        images_root=Path(str(raw["images_root"])) if raw.get("images_root") else None,
        tasks_root=Path(str(raw["tasks_root"])) if raw.get("tasks_root") else None,
        projects=projects,
    )


def load_cache_config(config_path: Path | None = None) -> CacheConfig:
    """Load the ``cache`` section from the config YAML."""
    return _load_section("cache", _parse_cache_section, config_path)


def _serialize_cache_project(settings: CacheProjectSettings) -> dict[str, str]:
    """Serialize one per-project cache entry, omitting unset fields."""
    data: dict[str, str] = {}
    if settings.images_root is not None:
        data["images_root"] = str(settings.images_root)
    if settings.tasks_root is not None:
        data["tasks_root"] = str(settings.tasks_root)
    if settings.ignored_prefix:
        data["ignored_prefix"] = settings.ignored_prefix
    if settings.task_cache_s3:
        data["task_cache_s3"] = settings.task_cache_s3
    return data


def _serialize_cache_section(cfg: CacheConfig) -> dict[str, object] | None:
    """Serialize cache config to a YAML-friendly dict, or None if empty."""
    result: dict[str, object] = {}
    if cfg.images_root is not None:
        result["images_root"] = str(cfg.images_root)
    if cfg.tasks_root is not None:
        result["tasks_root"] = str(cfg.tasks_root)
    projects = {
        name: serialized
        for name, settings in cfg.projects.items()
        if (serialized := _serialize_cache_project(settings))
    }
    if projects:
        result["projects"] = projects
    return result or None


def save_cache_config(
    cfg: CacheConfig,
    config_path: Path | None = None,
) -> Path:
    """Update only the ``cache`` section of the config YAML."""
    return _save_section(
        "cache",
        cfg,
        _serialize_cache_section,
        config_path,
        log_message="Cache config saved to {path}",
    )


class SyncRootsConfig(BaseModel):
    """Per-project mapping: project_name -> S3 root for image downloads.

    A root is either a full ``s3://bucket/prefix`` URL or a bare prefix
    string applied to the project's own CVAT bucket.
    """

    projects: dict[str, str] = Field(default_factory=dict)

    def get_root(self, project_name: str) -> str | None:
        """Return the sync root for *project_name*, or None if not configured."""
        return self.projects.get(project_name)


def _parse_sync_roots_section(raw: object) -> SyncRootsConfig:
    """Parse ``sync_roots`` section from raw YAML value."""
    if not isinstance(raw, dict):
        return SyncRootsConfig()
    return SyncRootsConfig(projects={str(k): str(v) for k, v in raw.items()})


def load_sync_roots_config(config_path: Path | None = None) -> SyncRootsConfig:
    """Load the ``sync_roots`` section from the config YAML."""
    return _load_section("sync_roots", _parse_sync_roots_section, config_path)


def _serialize_sync_roots_section(cfg: SyncRootsConfig) -> dict[str, str] | None:
    """Serialize sync roots config to YAML-friendly dict, or None if empty."""
    return dict(cfg.projects) or None


def save_sync_roots_config(
    cfg: SyncRootsConfig,
    config_path: Path | None = None,
) -> Path:
    """Update only the ``sync_roots`` section of the config YAML."""
    return _save_section(
        "sync_roots",
        cfg,
        _serialize_sync_roots_section,
        config_path,
        log_message="Sync roots config saved to {path}",
    )


class IgnoredTask(BaseModel):
    """A single ignored task entry (id + cached name + optional description)."""

    id: int
    name: str
    description: str = ""
    silent: bool = False


class IgnoreConfig(BaseModel):
    """Per-project mapping of ignored tasks.

    Ignored tasks are treated as permanently in-progress and skipped entirely.
    Each entry stores both the task ID and its human-readable name.
    """

    projects: dict[str, list[IgnoredTask]] = Field(default_factory=dict)

    def get_ignored_tasks(self, project_name: str) -> list[int]:
        """Return the list of ignored task IDs for *project_name*."""
        return [t.id for t in self.projects.get(project_name, [])]

    def get_ignored_entries(self, project_name: str) -> list[IgnoredTask]:
        """Return the full ignored-task entries for *project_name*."""
        return list(self.projects.get(project_name, []))

    def get_silent_task_ids(self, project_name: str) -> set[int]:
        """Return task IDs where ``silent=True`` for *project_name*."""
        return {t.id for t in self.projects.get(project_name, []) if t.silent}

    def add_task(
        self,
        project_name: str,
        task_id: int,
        task_name: str,
        description: str = "",
        *,
        silent: bool = False,
    ) -> None:
        """Add a task to the ignore list for *project_name*."""
        entries = self.projects.setdefault(project_name, [])
        if not any(e.id == task_id for e in entries):
            entries.append(
                IgnoredTask(
                    id=task_id, name=task_name, description=description, silent=silent
                )
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
                silent=bool(raw.get("silent", False)),
            )
        except (TypeError, ValueError) as e:
            logger.warning(
                f"Пропущена некорректная запись ignore (id={raw.get('id')!r}): {e}"
            )
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
    if entry.silent:
        data["silent"] = True
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
    image_quality: int = 100


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


def is_clearml_disabled() -> bool:
    """Return True when ``CVETA2_CLEARML`` is ``'false'``."""
    return os.environ.get("CVETA2_CLEARML", "").lower() == "false"


# ---------------------------------------------------------------------------
# ClearML config
# ---------------------------------------------------------------------------


class ClearmlProjectMapping(BaseModel):
    """Mapping of a single CVAT project to a ClearML project/dataset pair."""

    clearml_project: str
    clearml_dataset: str


class ClearmlConfig(BaseModel):
    """ClearML integration settings."""

    enabled: bool = False
    projects: dict[str, ClearmlProjectMapping] = Field(default_factory=dict)

    def get_mapping(self, project_name: str) -> ClearmlProjectMapping | None:
        """Return the ClearML mapping for *project_name*, or None if not configured."""
        return self.projects.get(project_name)


def _parse_clearml_section(raw: object) -> ClearmlConfig:
    """Parse ``clearml`` section from raw YAML value."""
    if not isinstance(raw, dict):
        return ClearmlConfig()
    enabled = raw.get("enabled", True)
    if not isinstance(enabled, bool):
        enabled = True
    projects_raw = raw.get("projects")
    if not isinstance(projects_raw, dict):
        return ClearmlConfig(enabled=enabled)
    projects: dict[str, ClearmlProjectMapping] = {}
    for proj_name, mapping in projects_raw.items():
        if not isinstance(mapping, dict):
            continue
        cp = mapping.get("clearml_project")
        cd = mapping.get("clearml_dataset")
        if isinstance(cp, str) and isinstance(cd, str):
            projects[str(proj_name)] = ClearmlProjectMapping(
                clearml_project=cp, clearml_dataset=cd
            )
    return ClearmlConfig(enabled=enabled, projects=projects)


def _serialize_clearml_section(cfg: ClearmlConfig) -> dict[str, object] | None:
    """Serialize ClearML config to YAML-friendly dict, or None if empty."""
    if not cfg.projects and not cfg.enabled:
        return None
    result: dict[str, object] = {"enabled": cfg.enabled}
    if cfg.projects:
        result["projects"] = {
            name: {
                "clearml_project": m.clearml_project,
                "clearml_dataset": m.clearml_dataset,
            }
            for name, m in cfg.projects.items()
        }
    return result


def load_clearml_config(config_path: Path | None = None) -> ClearmlConfig:
    """Load the ``clearml`` section from the config YAML."""
    return _load_section("clearml", _parse_clearml_section, config_path)


def save_clearml_config(
    cfg: ClearmlConfig,
    config_path: Path | None = None,
) -> Path:
    """Update only the ``clearml`` section of the config YAML."""
    return _save_section(
        "clearml",
        cfg,
        _serialize_clearml_section,
        config_path,
        log_message="ClearML config saved to {path}",
    )


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
