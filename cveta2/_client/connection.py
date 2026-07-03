"""SDK connection lifecycle: open a CVAT SDK client wrapped in the adapter."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Protocol

from cvat_sdk import make_client
from loguru import logger

from cveta2._client.sdk_adapter import (
    SdkCvatApiAdapter,
    apply_request_timeout,
    install_global_request_timeout,
)
from cveta2.s3_utils import set_default_data_timeout

if TYPE_CHECKING:
    from collections.abc import Iterator
    from contextlib import AbstractContextManager

    from cvat_sdk import Client as CvatSdkClient

    from cveta2.config import CvatConfig


def configure_data_timeout(timeout: float | None) -> None:
    """Apply the configured timeout to S3 clients and all CVAT SDK requests.

    The class-level SDK patch covers requests made while the client is still
    being created (server version check, login), where the per-instance
    ``apply_request_timeout`` wrapper cannot reach yet.
    """
    set_default_data_timeout(timeout)
    if timeout:
        install_global_request_timeout(timeout)


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

    Applies the configured request timeout and organization slug.
    Credentials must already be present on *cfg*.
    """
    factory = client_factory or make_client
    kwargs = _build_client_kwargs(cfg)
    with factory(**kwargs) as sdk_client:
        if cfg.request_timeout:
            apply_request_timeout(sdk_client, cfg.request_timeout)
        if cfg.organization:
            sdk_client.organization_slug = cfg.organization
            logger.trace(f"Using organization: {cfg.organization}")
        yield SdkCvatApiAdapter(sdk_client)
