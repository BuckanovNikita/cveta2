"""Shared CLI bootstrap: config load, host check, timeout, credential prompts.

Every network command opens its client through :func:`open_client`, so
config is loaded exactly once per run and interactive credential prompts
live only in the CLI layer.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from cveta2._client.connection import configure_data_timeout
from cveta2.client import CvatClient
from cveta2.commands._helpers import require_host
from cveta2.commands.interactive import prompt_credentials
from cveta2.config import CvatConfig

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@contextmanager
def open_client(config_path: Path | None = None) -> Iterator[CvatClient]:
    """Load config once, check host, set timeout, prompt, yield entered client."""
    cfg = CvatConfig.load(config_path=config_path)
    require_host(cfg)
    configure_data_timeout(cfg.request_timeout)
    cfg = prompt_credentials(cfg)
    with CvatClient(cfg) as client:
        yield client
