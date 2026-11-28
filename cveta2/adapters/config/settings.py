"""Configuration loading with priority: env > config file > preset > defaults."""

import importlib.resources
import os
import stat
from pathlib import Path
from typing import ClassVar, NamedTuple, Self, override

import yaml
from loguru import logger
from pydantic import BaseModel, Field, PrivateAttr, field_validator

from cveta2.adapters.config.project import (
    config_yaml_bytes,
    optional_global_config,
    optional_project_config,
    write_personal_file,
    write_shared_project_fields,
)
from cveta2.application.settings import (
    CacheProjectSettings,
    IgnoredTask,
    _none_if_falsy,
)
from cveta2.domain.errors import (
    Cveta2Error,
    InteractiveModeRequiredError,
    MissingCredentialsError,
)
from cveta2.domain.managed.models import ManagedError, MigrationRequired, ProjectConfig, ProjectDefinition

CONFIG_DIR = Path.home() / ".config" / "cveta2"
CONFIG_PATH = CONFIG_DIR / "config.yaml"


def _env_flag(name: str, expected: str) -> bool:
    """Return True when environment variable *name* equals *expected*.

    Comparison is case-insensitive; an unset variable never matches.
    """
    return os.environ.get(name, "").lower() == expected


def is_interactive_disabled() -> bool:
    """Return True when CVETA2_NO_INTERACTIVE is set to 'true' (case-insensitive)."""
    return _env_flag("CVETA2_NO_INTERACTIVE", "true")


def is_cache_disabled() -> bool:
    """Return True when CVETA2_DISABLE_CACHE is set to 'true' (case-insensitive)."""
    return _env_flag("CVETA2_DISABLE_CACHE", "true")


def should_raise_on_fetch_failure() -> bool:
    """Return True when CVETA2_RAISE_ON_FAILURE requests aborting on first error."""
    return _env_flag("CVETA2_RAISE_ON_FAILURE", "true")


def require_interactive(hint: str) -> None:
    """Raise if interactive prompts are disabled.

    Parameters
    ----------
    hint:
        Human-readable explanation of which CLI flag / env var the caller
        should use instead of an interactive prompt.

    """
    if is_interactive_disabled():
        raise InteractiveModeRequiredError(f"Interactive prompt required but CVETA2_NO_INTERACTIVE=true. {hint}")


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
    data = yaml.safe_load(ref.read_bytes())
    if isinstance(data, dict):
        return data
    return {}


def _load_raw_yaml(path: Path) -> dict[str, object]:
    """Load a YAML file and return its top-level mapping (or empty dict)."""
    try:
        if not path.is_file():
            return {}
        content = path.read_bytes()
    except OSError as error:
        raise Cveta2Error(f"Не удалось прочитать конфигурацию {path}: {type(error).__name__}.") from error
    try:
        data = yaml.safe_load(content) or {}
    except yaml.YAMLError as e:
        details = type(e).__name__
        if isinstance(e, yaml.MarkedYAMLError):
            mark = e.problem_mark or e.context_mark
            if mark is not None:
                details += f", строка {mark.line + 1}, столбец {mark.column + 1}"
        raise Cveta2Error(f"Ошибка чтения YAML-конфигурации {path}: {details}.") from e
    if not isinstance(data, dict):
        logger.warning(f"Invalid config format in {path}; expected mapping.")
        return {}
    return data


def _write_raw_yaml(path: Path, data: dict[str, object]) -> None:
    """Atomically write *data* as owner-only UTF-8 YAML, creating the config directory.

    The personal file holds the CVAT password, so it is never group- or
    world-readable, and a failed write keeps the previous file intact.
    """
    try:
        write_personal_file(path, config_yaml_bytes(data))
    except OSError as error:
        raise Cveta2Error(f"Не удалось записать конфигурацию {path}: {type(error).__name__}.") from error


def _restrict_to_owner(path: Path) -> None:
    """Remove group/other access from a password-bearing file the user owns.

    Files written by older versions followed the umask (often ``0644``).  A
    file owned by someone else, or a refused ``chmod``, is reported, not fatal.
    """
    if os.name != "posix":
        return
    try:
        status = path.stat()
        if not stat.S_IMODE(status.st_mode) & 0o077:
            return
        if status.st_uid != os.getuid():
            logger.warning(f"Файл с паролем {path} доступен другим пользователям; ограничьте права до 0600.")
            return
        path.chmod(0o600)
    except OSError as error:
        logger.warning(f"Не удалось ограничить права файла с паролем {path}: {type(error).__name__}.")
        return
    logger.warning(f"Права файла с паролем {path} ограничены до 0600.")


def _shared_section(section: str, personal: object, shared: ProjectConfig) -> object:
    """Supply policy exclusively from shared data while keeping local paths."""
    if section == "sync_roots":
        return {key: value.sync_root for key, value in shared.projects.items() if value.sync_root is not None}
    if section == "ignore":
        return {key: value.ignore for key, value in shared.projects.items() if value.ignore}
    if section == "cache":
        result = dict(personal) if isinstance(personal, dict) else {}
        projects = dict(result.get("projects", {}))
        for key, value in shared.projects.items():
            local_value = projects.get(key, {})
            local = dict(local_value) if isinstance(local_value, dict) else {}
            if value.ignored_prefix is not None:
                local["ignored_prefix"] = value.ignored_prefix
            if value.task_cache_s3 is not None:
                local["task_cache_s3"] = value.task_cache_s3
            if local:
                projects[key] = local
        result["projects"] = projects
        return result
    return personal


def _split_cache_policy(
    values: dict[str, object], shared: ProjectConfig, loaded: object = None
) -> dict[str, dict[str, object]]:
    """Remove shared fields from serialized local cache values.

    With *loaded* (the section as serialized when it was loaded), only policy
    the caller edited since then counts as a change; otherwise every value
    that differs from *shared* does.
    """
    changes: dict[str, dict[str, object]] = {}
    projects = values.get("projects", {})
    loaded_projects = _dict_value(_dict_value(loaded).get("projects"))
    if isinstance(projects, dict):
        for name, fields in projects.items():
            if not isinstance(fields, dict):
                continue
            policy = {key: fields.pop(key) for key in ("ignored_prefix", "task_cache_s3") if key in fields}
            if policy:
                selected_project = shared.projects.get(name)
                if selected_project is None:
                    raise ManagedError(f"Unknown shared project: {name}")
                if loaded is None:
                    changed = {key: value for key, value in policy.items() if value != getattr(selected_project, key)}
                else:
                    before = _dict_value(loaded_projects.get(name))
                    changed = {key: value for key, value in policy.items() if value != before.get(key)}
                if changed:
                    changes[name] = changed
    values["projects"] = (
        {name: fields for name, fields in projects.items() if fields} if isinstance(projects, dict) else {}
    )
    return changes


def _dict_value(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _snapshot_values(changes: dict[str, dict[str, object]], snapshot: ProjectConfig) -> dict[str, dict[str, object]]:
    """Shared values of the changed fields as they were when the section loaded."""
    expected: dict[str, dict[str, object]] = {}
    for name, fields in changes.items():
        project = snapshot.projects.get(name)
        expected[name] = {
            field: getattr(project, field)
            if project is not None
            else ProjectDefinition.model_fields[field].get_default(call_default_factory=True)
            for field in fields
        }
    return expected


class _SharedBaseline(NamedTuple):
    """What a section saw when it last loaded or saved shared policy."""

    snapshot: ProjectConfig  # the raw global file: never carries a local override
    section: object  # the section's own serialized form


def _save_shared_section(
    path: Path,
    section: str,
    serialized: object,
    shared: ProjectConfig,
    baseline: _SharedBaseline | None = None,
) -> object:
    """Route explicit policy edits to shared storage; local saves do not shadow it.

    With a *baseline*, only projects the caller edited since it was taken are
    written, so another writer's later change to a different project survives;
    a concurrent change to the same field is refused instead of overwritten.
    Without one (a section built in memory) every value that differs from the
    current shared file is written.
    """
    snapshot, loaded = baseline if baseline is not None else (None, None)
    changes: dict[str, dict[str, object]] = {}
    values = dict(serialized) if isinstance(serialized, dict) else {}
    if section in {"sync_roots", "ignore"}:
        field = "sync_root" if section == "sync_roots" else "ignore"
        default: object = None if field == "sync_root" else []
        unknown = set(values) - set(shared.projects)
        if unknown:
            raise ManagedError(f"Unknown shared projects: {sorted(unknown)}")
        if snapshot is None:
            for key, project in shared.projects.items():
                value = values.get(key, default)
                if value != getattr(project, field):
                    changes[key] = {field: value}
        else:
            before = _dict_value(loaded)
            for name in sorted(set(values) | set(before)):
                value = values.get(name, default)
                if value != before.get(name, default):
                    changes[name] = {field: value}
    elif section == "cache":
        changes = _split_cache_policy(values, shared, loaded if snapshot is not None else None)
    if changes:
        expected = _snapshot_values(changes, snapshot) if snapshot is not None else None
        write_shared_project_fields(path, changes, expected=expected)
    return values or None


class SectionConfig(BaseModel):
    """Base for config-YAML sections: generic ``load``/``save`` via pydantic.

    Subclasses set ``section_key`` (their top-level YAML key) and may
    override ``_wrap_raw`` (map the raw section value onto model fields)
    and ``_to_raw`` (model → YAML value; ``None`` removes the section).
    """

    section_key: ClassVar[str]
    save_log: ClassVar[str] = "Config saved to {path}"
    # Shared policy as of the last load/save, so a save writes only this
    # instance's edits (see ``_save_shared_section``).
    _shared_baseline: _SharedBaseline | None = PrivateAttr(default=None)

    @classmethod
    def _wrap_raw(cls, raw: dict[str, object]) -> dict[str, object]:
        """Map the raw YAML section mapping onto model fields."""
        return raw

    def _dump(self) -> dict[str, object]:
        """Model → YAML-safe mapping with defaulted fields dropped.

        ``mode="json"`` is load-bearing: ``Path`` values (``image_cache``,
        ``cache.images_root``) have no ``yaml.safe_dump`` representer, so the
        python-mode dump cannot be written at all.  Every optional field in
        this hierarchy defaults to ``None``, so ``exclude_defaults`` already
        subsumes ``exclude_none``.
        """
        return self.model_dump(mode="json", exclude_defaults=True)

    def _to_raw(self) -> object | None:
        """Serialize to the YAML section value; ``None`` removes the section."""
        return self._dump() or None

    @classmethod
    def load(cls, config_path: Path | None = None, *, project_path: Path | None = None) -> Self:
        """Load this section from the config YAML (defaults when absent)."""
        path = get_config_path(config_path)
        personal = _load_raw_yaml(path)
        effective = optional_project_config(path, project_path)
        raw_global = optional_global_config(path, project_path)
        raw = personal.get(cls.section_key)
        if effective is not None:
            raw = _shared_section(cls.section_key, raw, effective)
        section = cls.model_validate(cls._wrap_raw(raw)) if isinstance(raw, dict) else cls()
        if raw_global is not None:
            section._remember_shared(raw_global)  # noqa: SLF001 - this factory owns the snapshot
        return section

    def project_keys(self, name: str, project_id: int | None) -> tuple[str, ...]:
        """Prefer the stable configuration key. A legacy personal name must not belong to another ID."""
        if self._shared_baseline is None or project_id is None:
            return (name,)
        shared = self._shared_baseline.snapshot
        key = shared.key_for_id(project_id)
        keys = (key,) if key is not None else ()
        return keys if name in shared.projects else (*keys, name)

    def project_key(self, name: str, project_id: int | None) -> str:
        """Return the key for an explicit write, refusing another project's binding."""
        keys = self.project_keys(name, project_id)
        if not keys:
            raise ManagedError(f"Configure a separate project key for CVAT ID {project_id} before saving its settings.")
        return keys[0]

    def _remember_shared(self, raw: ProjectConfig) -> None:
        """Keep the raw global file as the baseline of later team writes."""
        self._shared_baseline = _SharedBaseline(raw, self._to_raw())

    def save(self, config_path: Path | None = None) -> Path:
        """Update only this section of the config YAML, keeping the rest."""
        path = get_config_path(config_path)
        existing = _load_raw_yaml(path)
        serialized = self._to_raw()
        shared = optional_project_config(path)
        if shared is not None:
            serialized = _save_shared_section(path, self.section_key, serialized, shared, self._shared_baseline)
            refreshed = optional_global_config(path)
            if refreshed is not None:
                self._remember_shared(refreshed)
            if self.section_key in {"sync_roots", "ignore"}:
                return path
        elif self.section_key in {"sync_roots", "ignore"} and serialized:
            raise MigrationRequired(
                "Project policy requires shared configuration; attach it with setup --global-config"
            )
        elif self.section_key == "cache" and isinstance(serialized, dict):
            projects = serialized.get("projects", {})
            if isinstance(projects, dict) and any(
                isinstance(fields, dict) and set(fields) & {"ignored_prefix", "task_cache_s3"}
                for fields in projects.values()
            ):
                raise MigrationRequired("Shared cache policy requires a shared project configuration")
        if serialized is None:
            existing.pop(self.section_key, None)
        else:
            existing[self.section_key] = serialized
        _write_raw_yaml(path, existing)
        logger.info(self.save_log.format(path=path))
        return path


class _ProjectsSection(SectionConfig):
    """Section whose YAML value is directly the ``projects`` mapping."""

    @classmethod
    @override
    def _wrap_raw(cls, raw: dict[str, object]) -> dict[str, object]:
        return {"projects": raw}

    @override
    def _to_raw(self) -> object | None:
        return self._dump().get("projects") or None


def _parse_timeout_env(raw: str | None) -> float | None:
    """Parse CVETA2_DATA_TIMEOUT env value; warn and return None on garbage."""
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        logger.warning("Некорректное значение CVETA2_DATA_TIMEOUT — ожидается число секунд; таймаут не применяется.")
        return None


class CvatConfig(BaseModel):
    """CVAT connection settings."""

    host: str = ""
    organization: str | None = None
    username: str | None = None
    password: str | None = None
    request_timeout: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    _source_path: Path | None = PrivateAttr(default=None)

    @field_validator("organization")
    @classmethod
    def personal_workspace(cls, value: str | None) -> str | None:
        """Normalize the existing empty-organization personal-workspace alias."""
        return value or None

    @field_validator("host")
    @classmethod
    def _strip_host_trailing_slash(cls, value: str) -> str:
        """Normalize host URL by stripping trailing slashes."""
        return value.rstrip("/")

    @classmethod
    def _from_cvat_section(cls, data: dict[str, object]) -> Self:
        """Build from a raw YAML top-level dict (reads the ``cvat`` key)."""
        cvat_section = data.get("cvat")
        if not isinstance(cvat_section, dict):
            return cls()
        return cls(**{k: v for k, v in cvat_section.items() if k in cls.model_fields})

    @classmethod
    def from_file(cls, path: Path = CONFIG_PATH) -> Self:
        """Load config from a YAML file.  Returns empty config if file is missing."""
        cfg = cls._from_cvat_section(_load_raw_yaml(path))
        cfg._source_path = path  # noqa: SLF001 - this factory owns the model source
        if cfg.password:
            _restrict_to_owner(path)
        return cfg

    @property
    def source_path(self) -> Path | None:
        """Personal file this configuration was loaded from, if any."""
        return self._source_path

    @classmethod
    def from_env(cls) -> Self:
        """Build config from environment variables."""
        return cls(
            host=os.environ.get("CVAT_HOST", ""),
            organization=os.environ.get("CVAT_ORGANIZATION"),
            username=os.environ.get("CVAT_USERNAME"),
            password=os.environ.get("CVAT_PASSWORD"),
            request_timeout=_parse_timeout_env(os.environ.get("CVETA2_DATA_TIMEOUT")),
        )

    def merge(self, override: "CvatConfig") -> "CvatConfig":
        """Return a new config where *override* values take priority over self.

        Only non-empty / non-None values from *override* win.
        """
        merged = CvatConfig(
            host=override.host or self.host,
            organization=override.organization or self.organization,
            username=override.username or self.username,
            password=override.password or self.password,
            request_timeout=(
                override.request_timeout if override.request_timeout is not None else self.request_timeout
            ),
        )
        # This model method owns source provenance for both model instances.
        merged._source_path = override._source_path or self._source_path  # noqa: SLF001
        return merged

    @classmethod
    def load(cls, config_path: Path | None = None, *, project_path: Path | None = None) -> "CvatConfig":
        """Merge preset, file, and env: preset < file < env."""
        preset_data = _load_preset_data()
        preset_cfg = cls._from_cvat_section(preset_data)
        path = get_config_path(config_path)
        file_cfg = cls.from_file(path)
        env_cfg = cls.from_env()
        shared = optional_project_config(path, project_path)
        if shared is not None:
            identity = shared.cvat
            if (env_cfg.host and env_cfg.host != identity.host) or (
                env_cfg.organization is not None and env_cfg.organization != identity.organization
            ):
                raise ManagedError("CVAT identity environment overrides conflict with shared project configuration")
            file_cfg = file_cfg.model_copy(update={"host": identity.host, "organization": identity.organization})
            env_cfg = env_cfg.model_copy(update={"host": "", "organization": None})
        return preset_cfg.merge(file_cfg).merge(env_cfg)

    def save_to_file(self, path: Path = CONFIG_PATH) -> Path:
        """Write config to a YAML file, preserving all non-``cvat`` sections."""
        existing_data = _load_raw_yaml(path)

        shared = optional_project_config(path)
        if shared is not None and (self.host != shared.cvat.host or self.organization != shared.cvat.organization):
            raise ManagedError("CVAT identity must be changed in shared project configuration")
        # An empty host is never written: the key alone would mark the file as legacy-attached.
        cvat_data: dict[str, str | float] = {"host": self.host} if shared is None and self.host else {}
        if self.organization and shared is None:
            cvat_data["organization"] = self.organization
        if self.username:
            cvat_data["username"] = self.username
        if self.password:
            cvat_data["password"] = self.password
        if self.request_timeout is not None:
            cvat_data["request_timeout"] = self.request_timeout

        output: dict[str, object] = {"cvat": cvat_data}
        output.update((key, value) for key, value in existing_data.items() if key != "cvat")
        _write_raw_yaml(path, output)
        logger.info(f"Config saved to {path}")
        return path

    def require_credentials(self) -> Self:
        """Return self when credentials are present; raise otherwise.

        Never prompts.  The CLI layer prompts for missing credentials
        before opening a client (``cveta2.interfaces.commands._bootstrap``).

        Both halves of the message carry an ``f`` prefix on purpose, matching
        every other raise in the mutation-gated modules: mutmut's string
        operator fires on plain literals only, and prose is not behaviour
        (see the ``do_not_mutate_patterns`` note in pyproject.toml).
        """
        if self.username and self.password:
            return self
        raise MissingCredentialsError(
            f"Учётные данные CVAT не настроены. Задайте CVAT_USERNAME и "
            f"CVAT_PASSWORD или заполните cvat.username/password в "
            f"{self._source_path or get_config_path()}."
        )


def _coerce_mapping_scalars(value: object) -> object:
    """Coerce a raw YAML mapping's keys and values to str (pre-validation).

    A ``null`` or empty value means "not configured", as in
    :class:`CacheConfig`; ``str(None)`` would otherwise become a real path.
    """
    if isinstance(value, dict):
        return {str(k): str(v) for k, v in value.items() if v is not None and v != ""}
    return value


class ImageCacheConfig(_ProjectsSection):
    """Per-project mapping: project_name -> local directory for images.

    The explicit entry here wins; projects without one fall back to the
    ``cache.images_root`` setting (see :class:`CacheConfig` and
    :func:`resolve_images_cache_dir`).
    """

    section_key: ClassVar[str] = "image_cache"
    save_log: ClassVar[str] = "Image cache config saved to {path}"

    projects: dict[str, Path] = Field(default_factory=dict)

    coerce_scalars = field_validator("projects", mode="before")(_coerce_mapping_scalars)

    def get_cache_dir(self, project_name: str, project_id: int | None = None) -> Path | None:
        """Return the cache directory for *project_name*, or None if not configured."""
        return next(
            (self.projects[key] for key in self.project_keys(project_name, project_id) if key in self.projects), None
        )

    def set_cache_dir(self, project_name: str, path: Path) -> None:
        """Add or update the cache directory for *project_name*."""
        self.projects[project_name] = path


class CacheConfig(SectionConfig):
    """Global cache settings plus per-project overrides.

    ``images_root`` is only the fallback image-cache root: an explicit
    per-project path in the ``image_cache`` section
    (:class:`ImageCacheConfig`) always wins.
    """

    section_key: ClassVar[str] = "cache"
    save_log: ClassVar[str] = "Cache config saved to {path}"

    images_root: Path | None = None
    tasks_root: Path | None = None
    projects: dict[str, CacheProjectSettings] = Field(default_factory=dict)

    none_if_falsy = field_validator("images_root", "tasks_root", mode="before")(_none_if_falsy)

    @field_validator("projects", mode="before")
    @classmethod
    def _drop_non_mapping_projects(cls, value: object) -> object:
        if not isinstance(value, dict):
            return {}
        return {str(k): v if isinstance(v, (dict, CacheProjectSettings)) else {} for k, v in value.items()}

    @override
    def _to_raw(self) -> object | None:
        data = self._dump()
        projects = data.get("projects")
        if isinstance(projects, dict):
            pruned = {name: entry for name, entry in projects.items() if entry}
            if pruned:
                data["projects"] = pruned
            else:
                data.pop("projects")
        return data or None

    def for_project(self, project_name: str, project_id: int | None = None) -> CacheProjectSettings:
        """Resolve effective settings for *project_name* (overrides win)."""
        entries = [self.projects[key] for key in self.project_keys(project_name, project_id) if key in self.projects]
        project = entries[0] if entries else CacheProjectSettings()
        return CacheProjectSettings(
            images_root=next((entry.images_root for entry in entries if entry.images_root), self.images_root),
            tasks_root=next((entry.tasks_root for entry in entries if entry.tasks_root), self.tasks_root),
            ignored_prefix=project.ignored_prefix,
            task_cache_s3=project.task_cache_s3,
        )


def cache_dir_for_project(root: Path, project_name: str) -> Path:
    """Return a contained cache component, percent-encoding unsafe characters."""
    safe = project_name.replace("%", "%25").replace("/", "%2F").replace("\\", "%5C").replace("\x00", "%00")
    if safe in {"", ".", ".."}:
        safe = "%empty" if not safe else safe.replace(".", "%2E")
    destination = root / safe
    if not destination.resolve().is_relative_to(root.resolve()):
        raise Cveta2Error(f"Путь кэша проекта {project_name!r} выходит за корень {root}")
    return destination


def images_cache_dir_from(
    image_cache: "ImageCacheConfig",
    project_settings: CacheProjectSettings,
    project_name: str,
    project_id: int | None = None,
) -> Path | None:
    """Return the image-cache dir for a project from already-loaded config.

    The explicit ``image_cache`` entry wins; otherwise the project's
    effective ``images_root`` yields ``images_root/<sanitized_name>``;
    with neither configured the result is None.
    """
    cached_dir = image_cache.get_cache_dir(project_name, project_id)
    if cached_dir is not None:
        return cached_dir
    if project_settings.images_root is not None:
        return cache_dir_for_project(project_settings.images_root, project_name)
    return None


def resolve_images_cache_dir(
    project_name: str,
    config_path: Path | None = None,
    project_id: int | None = None,
) -> Path | None:
    """Load the ``image_cache`` and ``cache`` sections and resolve the dir."""
    return images_cache_dir_from(
        ImageCacheConfig.load(config_path),
        CacheConfig.load(config_path).for_project(project_name, project_id),
        project_name,
        project_id,
    )


class SyncRootsConfig(_ProjectsSection):
    """Per-project mapping: project_name -> S3 root for image downloads.

    A root is either a full ``s3://bucket/prefix`` URL or a bare prefix
    string applied to the project's own CVAT bucket.
    """

    section_key: ClassVar[str] = "sync_roots"
    save_log: ClassVar[str] = "Sync roots config saved to {path}"

    projects: dict[str, str] = Field(default_factory=dict)

    coerce_scalars = field_validator("projects", mode="before")(_coerce_mapping_scalars)

    def get_root(self, project_name: str, project_id: int | None = None) -> str | None:
        """Return the sync root for *project_name*, or None if not configured."""
        return next(
            (self.projects[key] for key in self.project_keys(project_name, project_id) if key in self.projects), None
        )


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
            parsed = [item if isinstance(item, IgnoredTask) else _parse_ignore_entry(item) for item in entries]
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
    ) -> bool:
        """Add a task to the ignore list for *project_name*.

        Returns True if the task was newly added; an existing id is left
        untouched.
        """
        entries = self.projects.setdefault(project_name, [])
        if any(e.id == task_id for e in entries):
            return False
        entries.append(IgnoredTask(id=task_id, name=task_name, description=description, silent=silent))
        return True

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
                silent=bool(raw.get("silent")),
            )
        except (TypeError, ValueError) as e:
            logger.warning(f"Пропущена некорректная запись ignore (id={raw.get('id')!r}): {e}")
            return None
    if isinstance(raw, int):
        return IgnoredTask(id=raw, name="")
    if isinstance(raw, str) and raw.strip().isdigit():
        return IgnoredTask(id=int(raw), name="")
    return None


class UploadConfig(SectionConfig):
    """Settings for the ``upload`` command."""

    section_key: ClassVar[str] = "upload"

    # images_per_job reaches CVAT as segment_size and divides the job-count
    # estimate, so a hand-written 0 either fails inside CVAT or raises
    # ZeroDivisionError after the task was already created. Rejecting it at
    # load time names the setting instead.
    images_per_job: int = Field(default=100, gt=0)
    # CVAT rejects a chunk quality of 0 since 2.65, so the range is 1-100.
    image_quality: int = Field(default=100, ge=1, le=100)


class NetworkConfig(SectionConfig):
    """Transfer concurrency and retry budget.

    ``cvat_workers`` stays deliberately smaller than ``s3_workers``: CVAT
    rate-limits well before object storage does, and every 429 it returns
    costs a backoff sleep that eats the parallelism it was meant to buy.
    """

    section_key: ClassVar[str] = "network"

    s3_workers: int = Field(default=16, gt=0)
    cvat_workers: int = Field(default=4, gt=0)
    # Below 2 there is no retry at all, which is the behaviour this setting
    # exists to replace.
    retry_attempts: int = Field(default=5, ge=2)
    retry_max_wait: float = Field(default=30.0, gt=0)

    @classmethod
    def resolve(cls, config_path: Path | None = None, *, project_path: Path | None = None) -> Self:
        """Load the section, then let environment variables override it.

        ``SectionConfig.load`` reads the config file only; these knobs are
        the ones an operator wants to change for a single run on a slow or
        rate-limited link, so they get an env override too.
        """
        base = cls.load(config_path, project_path=project_path)
        return cls(
            s3_workers=_parse_int_env("CVETA2_S3_WORKERS") or base.s3_workers,
            cvat_workers=_parse_int_env("CVETA2_CVAT_WORKERS") or base.cvat_workers,
            retry_attempts=_parse_int_env("CVETA2_RETRY_ATTEMPTS", minimum=2) or base.retry_attempts,
            retry_max_wait=base.retry_max_wait,
        )


def _parse_int_env(name: str, minimum: int = 1) -> int | None:
    """Read an int of at least *minimum* from the environment.

    Garbage and out-of-range values are warned about and ignored, never
    raised: the file or default value must survive a typo in the shell.
    """
    raw = os.environ.get(name)
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        logger.warning(f"Некорректное значение {name}={raw!r} — ожидается целое число; значение игнорируется.")
        return None
    if value < minimum:
        logger.warning(f"Значение {name}={value} должно быть не меньше {minimum}; игнорируется.")
        return None
    return value


__all__ = ["CacheProjectSettings", "IgnoredTask"]
