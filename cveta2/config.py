"""Configuration loading with priority: env > config file > preset > defaults."""

from __future__ import annotations

import getpass
import importlib.resources
import os
from pathlib import Path

import yaml
from loguru import logger
from pydantic import BaseModel

from cveta2.exceptions import InteractiveModeRequiredError

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


# Override config file path with CVETA2_CONFIG (e.g. /path/to/config.yaml).
def _config_path() -> Path:
    path = os.environ.get("CVETA2_CONFIG")
    return Path(path) if path else CONFIG_PATH


def get_projects_cache_path() -> Path:
    """Path to projects cache YAML (same directory as config file)."""
    return _config_path().parent / "projects.yaml"


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
        path = config_path if config_path is not None else _config_path()
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


def load_image_cache_config(config_path: Path | None = None) -> ImageCacheConfig:
    """Load the ``image_cache`` section from the config YAML."""
    path = config_path if config_path is not None else _config_path()
    data = _load_raw_yaml(path)
    raw_ic = data.get("image_cache")
    if not isinstance(raw_ic, dict):
        return ImageCacheConfig()
    return ImageCacheConfig(projects={k: Path(str(v)) for k, v in raw_ic.items()})


def save_image_cache_config(
    image_cache: ImageCacheConfig,
    config_path: Path | None = None,
) -> Path:
    """Update only the ``image_cache`` section of the config YAML.

    Preserves the existing ``cvat`` and any other sections.
    """
    path = config_path if config_path is not None else _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    existing = _load_raw_yaml(path)
    existing["image_cache"] = {k: str(v) for k, v in image_cache.projects.items()}

    content = yaml.safe_dump(
        existing,
        default_flow_style=False,
        sort_keys=False,
    )
    if not content.endswith("\n"):
        content += "\n"
    path.write_text(content, encoding="utf-8")
    logger.info(f"Image cache config saved to {path}")
    return path
