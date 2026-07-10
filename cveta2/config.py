"""Configuration loading with priority: env > config file > preset > defaults."""

from __future__ import annotations

import importlib.resources
import os
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

import yaml
from loguru import logger
from pydantic import BaseModel, Field, field_validator

from cveta2.exceptions import InteractiveModeRequiredError, MissingCredentialsError

if TYPE_CHECKING:
    from typing_extensions import Self

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


class SectionConfig(BaseModel):
    """Base for config-YAML sections: generic ``load``/``save`` via pydantic.

    Subclasses set ``section_key`` (their top-level YAML key) and may
    override ``_wrap_raw`` (map the raw section value onto model fields)
    and ``_to_raw`` (model → YAML value; ``None`` removes the section).
    """

    section_key: ClassVar[str]
    save_log: ClassVar[str] = "Config saved to {path}"

    @classmethod
    def _wrap_raw(cls, raw: dict[str, object]) -> dict[str, object]:
        """Map the raw YAML section mapping onto model fields."""
        return raw

    def _to_raw(self) -> object | None:
        """Serialize to the YAML section value; ``None`` removes the section."""
        data = self.model_dump(mode="json", exclude_defaults=True, exclude_none=True)
        return data or None

    @classmethod
    def load(cls, config_path: Path | None = None) -> Self:
        """Load this section from the config YAML (defaults when absent)."""
        raw = _load_raw_yaml(get_config_path(config_path)).get(cls.section_key)
        if not isinstance(raw, dict):
            return cls()
        return cls.model_validate(cls._wrap_raw(raw))

    def save(self, config_path: Path | None = None) -> Path:
        """Update only this section of the config YAML, keeping the rest."""
        path = get_config_path(config_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = _load_raw_yaml(path)
        serialized = self._to_raw()
        if serialized is None:
            existing.pop(self.section_key, None)
        else:
            existing[self.section_key] = serialized
        content = yaml.safe_dump(existing, default_flow_style=False, sort_keys=False)
        if not content.endswith("\n"):
            content += "\n"
        path.write_text(content, encoding="utf-8")
        logger.info(self.save_log.format(path=path))
        return path


class _ProjectsSection(SectionConfig):
    """Section whose YAML value is directly the ``projects`` mapping."""

    @classmethod
    def _wrap_raw(cls, raw: dict[str, object]) -> dict[str, object]:
        return {"projects": raw}

    def _to_raw(self) -> object | None:
        data = self.model_dump(mode="json", exclude_defaults=True, exclude_none=True)
        return data.get("projects") or None


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


class ImageCacheConfig(_ProjectsSection):
    """Per-project mapping: project_name -> local directory for images."""

    section_key: ClassVar[str] = "image_cache"
    save_log: ClassVar[str] = "Image cache config saved to {path}"

    projects: dict[str, Path] = Field(default_factory=dict)

    @field_validator("projects", mode="before")
    @classmethod
    def _coerce_scalars(cls, value: object) -> object:
        if isinstance(value, dict):
            return {str(k): str(v) for k, v in value.items()}
        return value

    def get_cache_dir(self, project_name: str) -> Path | None:
        """Return the cache directory for *project_name*, or None if not configured."""
        return self.projects.get(project_name)

    def set_cache_dir(self, project_name: str, path: Path) -> None:
        """Add or update the cache directory for *project_name*."""
        self.projects[project_name] = path


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

    @field_validator(
        "images_root", "tasks_root", "ignored_prefix", "task_cache_s3", mode="before"
    )
    @classmethod
    def _none_if_falsy(cls, value: object) -> object:
        return str(value) if value else None


class CacheConfig(SectionConfig):
    """Global cache settings plus per-project overrides."""

    section_key: ClassVar[str] = "cache"
    save_log: ClassVar[str] = "Cache config saved to {path}"

    images_root: Path | None = None
    tasks_root: Path | None = None
    projects: dict[str, CacheProjectSettings] = Field(default_factory=dict)

    @field_validator("images_root", "tasks_root", mode="before")
    @classmethod
    def _none_if_falsy(cls, value: object) -> object:
        return str(value) if value else None

    @field_validator("projects", mode="before")
    @classmethod
    def _drop_non_mapping_projects(cls, value: object) -> object:
        if not isinstance(value, dict):
            return {}
        return {
            str(k): v if isinstance(v, (dict, CacheProjectSettings)) else {}
            for k, v in value.items()
        }

    def _to_raw(self) -> object | None:
        data = self.model_dump(mode="json", exclude_defaults=True, exclude_none=True)
        projects = data.get("projects")
        if isinstance(projects, dict):
            pruned = {name: entry for name, entry in projects.items() if entry}
            if pruned:
                data["projects"] = pruned
            else:
                data.pop("projects")
        return data or None

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


class SyncRootsConfig(_ProjectsSection):
    """Per-project mapping: project_name -> S3 root for image downloads.

    A root is either a full ``s3://bucket/prefix`` URL or a bare prefix
    string applied to the project's own CVAT bucket.
    """

    section_key: ClassVar[str] = "sync_roots"
    save_log: ClassVar[str] = "Sync roots config saved to {path}"

    projects: dict[str, str] = Field(default_factory=dict)

    @field_validator("projects", mode="before")
    @classmethod
    def _coerce_scalars(cls, value: object) -> object:
        if isinstance(value, dict):
            return {str(k): str(v) for k, v in value.items()}
        return value

    def get_root(self, project_name: str) -> str | None:
        """Return the sync root for *project_name*, or None if not configured."""
        return self.projects.get(project_name)


class IgnoredTask(BaseModel):
    """A single ignored task entry (id + cached name + optional description)."""

    id: int
    name: str
    description: str = ""
    silent: bool = False


class IgnoreConfig(_ProjectsSection):
    """Per-project mapping of ignored tasks.

    Ignored tasks are treated as permanently in-progress and skipped entirely.
    Each entry stores both the task ID and its human-readable name.
    Loading supports both the new format (list of ``{id, name}`` dicts)
    and the legacy format (list of bare ints); saving always writes the
    new format.
    """

    section_key: ClassVar[str] = "ignore"
    save_log: ClassVar[str] = "Ignore config saved to {path}"

    projects: dict[str, list[IgnoredTask]] = Field(default_factory=dict)

    @field_validator("projects", mode="before")
    @classmethod
    def _parse_entries(cls, value: object) -> object:
        if not isinstance(value, dict):
            return {}
        projects: dict[str, list[IgnoredTask]] = {}
        for project_name, entries in value.items():
            if not isinstance(entries, list):
                continue
            parsed = [
                item if isinstance(item, IgnoredTask) else _parse_ignore_entry(item)
                for item in entries
            ]
            cleaned = [entry for entry in parsed if entry is not None]
            if cleaned:
                projects[str(project_name)] = cleaned
        return projects

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


class UploadConfig(SectionConfig):
    """Settings for the ``upload`` command."""

    section_key: ClassVar[str] = "upload"

    images_per_job: int = 100
    image_quality: int = 100


def is_clearml_disabled() -> bool:
    """Return True when ``CVETA2_CLEARML`` is ``'false'``."""
    return os.environ.get("CVETA2_CLEARML", "").lower() == "false"


class ClearmlProjectMapping(BaseModel):
    """Mapping of a single CVAT project to a ClearML project/dataset pair."""

    clearml_project: str
    clearml_dataset: str


class ClearmlConfig(SectionConfig):
    """ClearML integration settings.

    A present ``clearml:`` section without a boolean ``enabled`` key is
    treated as enabled; a missing section keeps the ``False`` default.
    """

    section_key: ClassVar[str] = "clearml"
    save_log: ClassVar[str] = "ClearML config saved to {path}"

    enabled: bool = False
    projects: dict[str, ClearmlProjectMapping] = Field(default_factory=dict)

    @classmethod
    def _wrap_raw(cls, raw: dict[str, object]) -> dict[str, object]:
        enabled = raw.get("enabled", True)
        return {**raw, "enabled": enabled if isinstance(enabled, bool) else True}

    @field_validator("projects", mode="before")
    @classmethod
    def _drop_invalid_mappings(cls, value: object) -> object:
        if not isinstance(value, dict):
            return {}
        return {
            str(name): mapping
            for name, mapping in value.items()
            if isinstance(mapping, ClearmlProjectMapping)
            or (
                isinstance(mapping, dict)
                and isinstance(mapping.get("clearml_project"), str)
                and isinstance(mapping.get("clearml_dataset"), str)
            )
        }

    def _to_raw(self) -> object | None:
        if not self.projects and not self.enabled:
            return None
        result: dict[str, object] = {"enabled": self.enabled}
        if self.projects:
            result["projects"] = self.model_dump(mode="json")["projects"]
        return result

    def get_mapping(self, project_name: str) -> ClearmlProjectMapping | None:
        """Return the ClearML mapping for *project_name*, or None if not configured."""
        return self.projects.get(project_name)
