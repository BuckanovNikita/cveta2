"""Configuration loading with priority: CLI > env > config file > interactive."""

from __future__ import annotations

import getpass
import os
from pathlib import Path

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # pyright: ignore[reportMissingImports]

from loguru import logger
from pydantic import BaseModel

CONFIG_DIR = Path.home() / ".config" / "cveta2"
CONFIG_PATH = CONFIG_DIR / "config.toml"


class CvatConfig(BaseModel):
    """CVAT connection settings."""

    host: str = ""
    token: str | None = None
    username: str | None = None
    password: str | None = None

    @classmethod
    def from_file(cls, path: Path = CONFIG_PATH) -> CvatConfig:
        """Load config from a TOML file.  Returns empty config if file is missing."""
        if not path.is_file():
            return cls()
        logger.debug(f"Loading config from {path}")
        with path.open("rb") as fh:
            data = tomllib.load(fh)
        cvat_section = data.get("cvat", {})
        return cls(**{k: v for k, v in cvat_section.items() if k in cls.model_fields})

    @classmethod
    def from_env(cls) -> CvatConfig:
        """Build config from environment variables."""
        return cls(
            host=os.environ.get("CVAT_HOST", ""),
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
            token=override.token or self.token,
            username=override.username or self.username,
            password=override.password or self.password,
        )

    @classmethod
    def load(
        cls,
        *,
        cli_host: str = "",
        cli_token: str | None = None,
        cli_username: str | None = None,
        cli_password: str | None = None,
        config_path: Path = CONFIG_PATH,
    ) -> CvatConfig:
        """Merge all sources respecting priority: CLI > env > file > defaults."""
        file_cfg = cls.from_file(config_path)
        env_cfg = cls.from_env()
        cli_cfg = cls(
            host=cli_host,
            token=cli_token,
            username=cli_username,
            password=cli_password,
        )
        # file < env < cli
        return file_cfg.merge(env_cfg).merge(cli_cfg)

    def save_to_file(self, path: Path = CONFIG_PATH) -> Path:
        """Write config to a TOML file under the ``[cvat]`` section."""
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = ["[cvat]", f'host = "{self.host}"']
        if self.token:
            lines.append(f'token = "{self.token}"')
        if self.username:
            lines.append(f'username = "{self.username}"')
        if self.password:
            lines.append(f'password = "{self.password}"')
        lines.append("")  # trailing newline
        path.write_text("\n".join(lines))
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
            logger.info("No credentials provided. Please enter your CVAT login:")
            username = input("Username: ")
        if not password:
            password = getpass.getpass(f"Password for {username}: ")

        return self.model_copy(update={"username": username, "password": password})
