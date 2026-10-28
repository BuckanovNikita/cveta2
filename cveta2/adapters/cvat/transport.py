"""CVAT-specific timeout injection, error translation and operation retry policies.

SDK errors are translated before retry decisions. Raw transport errors stay
visible to the retry policy and are translated only after the budget is spent.
Connection setup shares the translation and timeout machinery without replaying
login or translating exceptions raised inside a caller's connection block.
"""

import functools
import threading
from collections.abc import Callable
from contextvars import ContextVar
from typing import Final, ParamSpec, TypeVar

import urllib3.exceptions
from cvat_sdk.api_client.exceptions import ApiException
from loguru import logger

from cveta2.adapters.cvat.diagnostics import (
    capture_rest_call,
    describe_error,
    exception_diagnostics,
    install_pool_capture,
    operation_context,
)
from cveta2.adapters.execution.retry import network_retry
from cveta2.domain.errors import CvatApiError

_P = ParamSpec("_P")
_R = TypeVar("_R")


def _parse_retry_after(exc: ApiException) -> float | None:
    """Read the ``Retry-After`` header off an SDK exception, in seconds.

    ``ApiException`` is an opaque generated type whose ``headers`` is
    ``None`` unless the failure carried an HTTP response, so the attributes
    are read defensively.  Only the delta-seconds form is understood; the
    HTTP-date spelling falls back to the normal backoff.
    """
    headers = getattr(exc, "headers", None)
    if headers is None:
        return None
    raw = headers.get("Retry-After")
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        logger.debug("Retry-After не распознан; используется стандартная задержка")
        return None


def _translate_api_errors(func: "Callable[_P, _R]") -> "Callable[_P, _R]":
    """Convert SDK ``ApiException`` into :class:`CvatApiError`."""

    @functools.wraps(func)
    def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        try:
            return func(*args, **kwargs)
        except ApiException as e:
            status = int(getattr(e, "status", 0) or 0)
            raise CvatApiError(
                describe_error(e),
                status_code=status,
                retry_after=_parse_retry_after(e),
                diagnostics=exception_diagnostics(e),
            ) from e

    return wrapper


TOO_MANY_REQUESTS: Final = 429
SERVICE_UNAVAILABLE: Final = 503
_READ_RETRY_STATUS: Final = frozenset({TOO_MANY_REQUESTS, 500, 502, 503, 504})

# urllib3 timeout errors are not OSError, hence urllib3.exceptions.HTTPError.
_TRANSPORT_ERRORS: Final = (OSError, ConnectionError, urllib3.exceptions.HTTPError)


def _should_retry_read(exc: BaseException) -> bool:
    """Retry anything transient: a read is always safe to repeat."""
    if isinstance(exc, _TRANSPORT_ERRORS):
        return True
    return isinstance(exc, CvatApiError) and exc.status_code in _READ_RETRY_STATUS


def _should_retry_write(exc: BaseException) -> bool:
    """Retry only a proven refusal; Retry-After does not prove non-application."""
    if not isinstance(exc, CvatApiError):
        return False
    if exc.status_code == SERVICE_UNAVAILABLE:
        logger.warning(
            "CVAT вернул 503: результат записи неизвестен, запрос не повторяется. "
            "Проверьте состояние в CVAT; продолжайте только после сверки."
        )
    return exc.status_code == TOO_MANY_REQUESTS


def _should_retry_idempotent_write(exc: BaseException) -> bool:
    """Retry status failures for explicit replacement of the same values."""
    return isinstance(exc, CvatApiError) and exc.status_code in _READ_RETRY_STATUS


def _translate_transport_errors(func: "Callable[_P, _R]") -> "Callable[_P, _R]":
    """Convert a transport failure that outlived the retry budget into ``CvatApiError``.

    Sits *outside* the retry decorator: ``_should_retry_read`` must still see
    the raw urllib3 types, and only what escapes the budget is translated.
    """

    @functools.wraps(func)
    def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        try:
            return func(*args, **kwargs)
        except _TRANSPORT_ERRORS as e:
            raise CvatApiError(
                f"Сетевая ошибка при обращении к CVAT: {describe_error(e)}",
                diagnostics=exception_diagnostics(e),
            ) from e

    return wrapper


_api_retry = network_retry(
    _should_retry_read, label="CVAT API", describe=describe_error
)
_write_retry = network_retry(
    _should_retry_write, label="CVAT write", describe=describe_error
)
_idempotent_write_retry = network_retry(
    _should_retry_idempotent_write,
    label="CVAT idempotent write",
    describe=describe_error,
)

_CONNECT_TIMEOUT = 10.0


class _GlobalTimeout:
    """One-time SDK patch state; timeout values themselves are context-local."""

    installed: bool = False
    lock = threading.Lock()


_REQUEST_TIMEOUT: ContextVar[float | None] = ContextVar(
    "cveta2_cvat_request_timeout", default=None
)


def install_global_request_timeout(timeout: float | None) -> None:
    """Install the SDK hook and set this context's request timeout.

    ``make_client`` performs requests (server version check, login) before
    it returns a client that could be wrapped; a black-holed host hangs
    there forever. Patching ``RESTClientObject.request`` at class level
    covers that window too. The class hook is process-wide and idempotent;
    its timeout value is context-local. ``None`` or ``0`` switches injection
    off for the caller without unpatching the SDK.
    """
    _REQUEST_TIMEOUT.set(timeout)
    install_request_capture()


def install_request_capture() -> None:
    """Install capture without changing this context's configured timeout."""
    from cvat_sdk.api_client.rest import RESTClientObject  # noqa: PLC0415

    if _GlobalTimeout.installed:
        return
    with _GlobalTimeout.lock:
        if _GlobalTimeout.installed:
            return
        original_request = RESTClientObject.request

        @functools.wraps(original_request)
        def request_with_timeout(
            self: RESTClientObject, *args: object, **kwargs: object
        ) -> object:
            request_timeout = _REQUEST_TIMEOUT.get()
            if kwargs.get("_request_timeout") is None and request_timeout:
                kwargs["_request_timeout"] = (_CONNECT_TIMEOUT, request_timeout)
            # The SDK type is opaque; narrow to real pool managers, leaving
            # custom SDK substitutes and test doubles usable without guessing.
            manager = getattr(self, "pool_manager", None)
            if isinstance(manager, urllib3.PoolManager):
                install_pool_capture(manager)
            return capture_rest_call(lambda: original_request(self, *args, **kwargs))

        RESTClientObject.request = request_with_timeout
        _GlobalTimeout.installed = True


def cvat_read(func: Callable[_P, _R]) -> Callable[_P, _R]:
    """Retry transient reads, translating exhausted transport failures last."""
    return operation_context(
        _translate_transport_errors(_api_retry(_translate_api_errors(func)))
    )


def cvat_non_idempotent_write(func: Callable[_P, _R]) -> Callable[_P, _R]:
    """Retry writes only after a proven refusal, never after an ambiguous result."""
    return operation_context(
        _translate_transport_errors(_write_retry(_translate_api_errors(func)))
    )


def cvat_idempotent_write(func: Callable[_P, _R]) -> Callable[_P, _R]:
    """Retry transient status failures while replacing the same explicit values."""
    return operation_context(
        _translate_transport_errors(
            _idempotent_write_retry(_translate_api_errors(func))
        )
    )
