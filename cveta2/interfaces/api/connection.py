"""Prompt-free connection resolution and caller-owned client lifetime."""

from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from cveta2.composition.client import CvatClient
from cveta2.composition.configuration import (
    CvatConfig,
    NetworkConfig,
    optional_project_config,
)
from cveta2.composition.runtime import configure_data_timeout, configure_network
from cveta2.domain.errors import Cveta2Error, MissingHostError
from cveta2.interfaces.api.types import Connection

if TYPE_CHECKING:
    from collections.abc import Iterator


@contextmanager
def _open(connection: "Connection | None") -> "Iterator[CvatClient]":
    """Yield a ready CvatClient: injected as-is, or opened from config.

    Resolution order: explicit settings > env vars > config file >
    preset.  Never prompts.
    """
    conn = connection or Connection()
    shared = optional_project_config(conn.config_path)
    if shared is not None:
        if conn.host is not None and conn.host.rstrip("/") != shared.cvat.host:
            raise Cveta2Error("Explicit host cannot override shared CVAT identity")
        if (
            conn.organization is not None
            and (conn.organization or None) != shared.cvat.organization
        ):
            raise Cveta2Error(
                "Explicit organization cannot override shared CVAT identity"
            )
        if conn.client is not None and (
            conn.client.host.rstrip("/") != shared.cvat.host
            or conn.client.organization != shared.cvat.organization
        ):
            raise Cveta2Error("Injected client conflicts with shared CVAT identity")
    if conn.client is not None:
        if not conn.client.is_ready:
            raise Cveta2Error(
                "Переданный client не готов к работе: войдите в его контекст "
                "(with CvatClient(cfg) as client: ...) или создайте его "
                "с фейковым api=."
            )
        yield conn.client
        return
    cfg = CvatConfig.load(conn.config_path)
    cfg = cfg.merge(
        CvatConfig(
            host=conn.host or "",
            username=conn.username,
            password=conn.password,
            organization=conn.organization,
        )
    )
    if conn.organization is not None:
        cfg = cfg.model_copy(update={"organization": conn.organization or None})
    if not cfg.host:
        raise MissingHostError(
            "Хост CVAT не настроен. Передайте host= или задайте CVAT_HOST "
            "(либо cvat.host в конфигурации)."
        )
    configure_data_timeout(cfg.request_timeout)
    configure_network(NetworkConfig.resolve(conn.config_path))
    with CvatClient(cfg) as opened:
        yield opened


def _config_path(connection: "Connection | None") -> Path | None:
    """Explicit config file from the connection, or None for the default."""
    return connection.config_path if connection else None
