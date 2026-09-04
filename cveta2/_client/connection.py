"""SDK connection lifecycle: open a CVAT SDK client wrapped in the adapter."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Protocol

from cvat_sdk import make_client
from loguru import logger

from cveta2._client.sdk_adapter import (
    _TRANSPORT_ERRORS,
    SdkCvatApiAdapter,
    _translate_api_errors,
    install_global_request_timeout,
)
from cveta2._concurrency import configure_workers
from cveta2._retry import configure_retries
from cveta2.exceptions import CvatApiError
from cveta2.s3_utils import set_default_data_timeout

if TYPE_CHECKING:
    from collections.abc import Iterator
    from contextlib import AbstractContextManager

    from cvat_sdk import Client as CvatSdkClient

    from cveta2.config import CvatConfig, NetworkConfig


def configure_data_timeout(timeout: float | None) -> None:
    """Apply the configured timeout to S3 clients and all CVAT SDK requests.

    Called at bootstrap, before any client exists, so the first S3 transfer
    and the very first CVAT request already carry the timeout.
    """
    set_default_data_timeout(timeout)
    install_global_request_timeout(timeout)


def configure_network(network: NetworkConfig) -> None:
    """Install the retry budget and the transfer fan-out width.

    Called once per client bootstrap, before any transfer starts. Values are
    local to the current runtime context; retry decorators were already bound
    at import time and read that context when a call runs.
    """
    configure_retries(network.retry_attempts, network.retry_max_wait)
    configure_workers(s3=network.s3_workers, cvat=network.cvat_workers)


class SdkClientFactory(Protocol):
    """Protocol for the SDK client factory (e.g. ``cvat_sdk.make_client``).

    The factory must accept keyword arguments (``host`` and
    ``credentials``) and return a context manager that yields an SDK
    client.
    """

    def __call__(
        self, **kwargs: str | tuple[str, str]
    ) -> AbstractContextManager[CvatSdkClient]: ...


def _build_client_kwargs(cfg: CvatConfig) -> dict[str, str | tuple[str, str]]:
    """Build keyword arguments for ``make_client``.

    ``organization`` is not passed to ``make_client`` (SDK does not
    accept it).  It is set on the client instance afterwards.
    """
    kwargs: dict[str, str | tuple[str, str]] = {"host": cfg.host or ""}
    if cfg.username and cfg.password:
        kwargs["credentials"] = (cfg.username, cfg.password)
    return kwargs


@contextmanager
def open_sdk_api(
    cfg: CvatConfig,
    client_factory: SdkClientFactory | None = None,
) -> Iterator[SdkCvatApiAdapter]:
    """Open an SDK client for *cfg* and yield an adapter wrapping it.

    Installs the current context's request timeout before ``make_client`` runs,
    so the server version check and login are covered too, and applies the
    organization slug. Credentials must already be present on *cfg*.
    ``make_client`` performs the server-about request and the login itself,
    so only that call is translated into :class:`CvatApiError`; whatever the
    caller raises inside the block passes through untouched.
    """
    install_global_request_timeout(cfg.request_timeout)
    factory = client_factory or make_client
    kwargs = _build_client_kwargs(cfg)
    try:
        sdk_cm = _translate_api_errors(factory)(**kwargs)
    except _TRANSPORT_ERRORS as e:
        msg = f"Не удалось подключиться к CVAT ({cfg.host}): {e}"
        raise CvatApiError(msg) from e
    with sdk_cm as sdk_client:
        if cfg.organization:
            sdk_client.organization_slug = cfg.organization
            logger.trace(f"Using organization: {cfg.organization}")
        yield SdkCvatApiAdapter(sdk_client)
