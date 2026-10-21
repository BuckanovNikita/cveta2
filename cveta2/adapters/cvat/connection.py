"""SDK connection lifecycle: open a CVAT SDK client wrapped in the adapter."""

from contextlib import contextmanager
from typing import TYPE_CHECKING, Protocol

from cvat_sdk import make_client
from loguru import logger

from cveta2.adapters.cvat.sdk_adapter import SdkCvatApiAdapter
from cveta2.adapters.cvat.transport import (
    _TRANSPORT_ERRORS,
    _translate_api_errors,
    install_global_request_timeout,
)
from cveta2.application.ports.client import CvatConnectionSettings
from cveta2.domain.errors import CvatApiError

if TYPE_CHECKING:
    from collections.abc import Iterator
    from contextlib import AbstractContextManager

    from cvat_sdk import Client as CvatSdkClient


class SdkClientFactory(Protocol):
    """Protocol for the SDK client factory (e.g. ``cvat_sdk.make_client``).

    The factory must accept keyword arguments (``host`` and
    ``credentials``) and return a context manager that yields an SDK
    client.
    """

    def __call__(
        self, **kwargs: str | tuple[str, str]
    ) -> "AbstractContextManager[CvatSdkClient]":
        """Construct the SDK context manager for the resolved credentials."""
        ...


def _build_client_kwargs(
    cfg: CvatConnectionSettings,
) -> dict[str, str | tuple[str, str]]:
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
    cfg: CvatConnectionSettings,
    client_factory: SdkClientFactory | None = None,
) -> "Iterator[SdkCvatApiAdapter]":
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
