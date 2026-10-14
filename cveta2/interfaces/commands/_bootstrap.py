"""Shared CLI bootstrap: config load, host check, timeout, credential prompts.

Every network command opens its client through :func:`open_client`, so
config is loaded exactly once per run and interactive credential prompts
live only in the CLI layer.
"""

from contextlib import contextmanager
from typing import TYPE_CHECKING

from cveta2.composition.client import CvatClient
from cveta2.composition.configuration import CvatConfig, NetworkConfig
from cveta2.composition.runtime import configure_data_timeout, configure_network
from cveta2.interfaces.commands._helpers import require_host
from cveta2.interfaces.commands.interactive import prompt_credentials

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@contextmanager
def open_client(config_path: "Path | None" = None) -> "Iterator[CvatClient]":
    """Load config once, check host, set timeout, prompt, yield entered client."""
    cfg = CvatConfig.load(config_path=config_path)
    require_host(cfg)
    configure_data_timeout(cfg.request_timeout)
    configure_network(NetworkConfig.resolve(config_path))
    cfg = prompt_credentials(cfg)
    with CvatClient(cfg) as client:
        yield client
