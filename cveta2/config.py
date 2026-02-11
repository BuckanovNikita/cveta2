"""Configuration loading with priority: env > config file > defaults."""

from __future__ import annotations

import getpass
import os
from pathlib import Path

import yaml
from loguru import logger
from pydantic import BaseModel

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
        raise RuntimeError(
            f"Interactive prompt required but CVETA2_NO_INTERACTIVE=true. {hint}"
        )


# Override config file path with CVETA2_CONFIG (e.g. /path/to/config.yaml).
def _config_path() -> Path:
    path = os.environ.get("CVETA2_CONFIG")
    return Path(path) if path else CONFIG_PATH


def get_projects_cache_path() -> Path:
    """Path to projects cache YAML (same directory as config file)."""
    path = os.environ.get("CVETA2_CONFIG")
    if path:
        return Path(path).parent / "projects.yaml"
    return CONFIG_DIR / "projects.yaml"


class CvatConfig(BaseModel):
    """CVAT connection settings."""

    host: str = ""
    organization: str | None = None
    token: str | None = None
    username: str | None = None
    password: str | None = None

    @classmethod
    def from_file(cls, path: Path = CONFIG_PATH) -> CvatConfig:
        """Load config from a YAML file.  Returns empty config if file is missing."""
        if not path.is_file():
            return cls()
        logger.trace(f"Loading config from {path}")
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        if not isinstance(data, dict):
            logger.warning(f"Invalid config format in {path}; expected mapping.")
            return cls()
        cvat_section = data.get("cvat", {})
        if not isinstance(cvat_section, dict):
            logger.warning(
                f"Invalid config section in {path}; expected 'cvat' mapping."
            )
            return cls()
        return cls(**{k: v for k, v in cvat_section.items() if k in cls.model_fields})

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
        """Merge env and file: file < env. Config path from CVETA2_CONFIG or default."""
        path = config_path if config_path is not None else _config_path()
        file_cfg = cls.from_file(path)
        env_cfg = cls.from_env()
        return file_cfg.merge(env_cfg)

    def save_to_file(self, path: Path = CONFIG_PATH) -> Path:
        """Write config to a YAML file under the ``cvat`` key."""
        path.parent.mkdir(parents=True, exist_ok=True)
        cvat_data: dict[str, str] = {"host": self.host}
        if self.organization:
            cvat_data["organization"] = self.organization
        if self.token:
            cvat_data["token"] = self.token
        if self.username:
            cvat_data["username"] = self.username
        if self.password:
            cvat_data["password"] = self.password
        content = yaml.safe_dump(
            {"cvat": cvat_data},
            default_flow_style=False,
            sort_keys=False,
        )
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
            require_interactive(
                "Set CVAT_TOKEN or CVAT_USERNAME/CVAT_PASSWORD env vars."
            )
            logger.info("No credentials provided. Please enter your CVAT login:")
            username = input("Username: ")
        if not password:
            require_interactive("Set CVAT_TOKEN or CVAT_PASSWORD env vars.")
            password = getpass.getpass(f"Password for {username}: ")

        return self.model_copy(update={"username": username, "password": password})
