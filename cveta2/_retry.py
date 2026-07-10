"""Shared network retry policy for S3 and CVAT API calls."""

from __future__ import annotations

import functools
from typing import TYPE_CHECKING, Final

from loguru import logger
from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from tenacity import WrappedFn

RETRY_ATTEMPTS: Final = 3


def network_retry(
    exc_types: tuple[type[BaseException], ...],
    label: str,
) -> Callable[[WrappedFn], WrappedFn]:
    """Build a retry decorator: 3 attempts, exponential backoff 1..10s.

    Retries only on *exc_types*, logs a warning before each retry
    (prefixed with *label*), and re-raises the last error.
    """
    return retry(
        retry=retry_if_exception_type(exc_types),
        stop=stop_after_attempt(RETRY_ATTEMPTS),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        before_sleep=functools.partial(_log_retry, label),
        reraise=True,
    )


def _log_retry(label: str, retry_state: RetryCallState) -> None:
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    logger.warning(
        f"{label} call failed (attempt {retry_state.attempt_number}), retrying: {exc!r}"
    )
