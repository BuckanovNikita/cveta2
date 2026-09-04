"""Shared network retry policy for S3 and CVAT API calls.

The mechanism lives here — how many attempts, how long to back off, what
gets logged.  *Which* failures are worth retrying is the caller's decision
and arrives as a predicate, because the answer differs sharply between
reads (retry anything transient) and writes (retry only what the server
provably never applied).
"""

from __future__ import annotations

import functools
from contextvars import ContextVar
from typing import TYPE_CHECKING, Final

from loguru import logger
from tenacity import RetryCallState, retry, retry_if_exception, wait_exponential_jitter

from cveta2.exceptions import CvatApiError

if TYPE_CHECKING:
    from collections.abc import Callable

    from tenacity import WrappedFn

DEFAULT_RETRY_ATTEMPTS: Final = 5
DEFAULT_RETRY_MAX_WAIT: Final = 30.0

_INITIAL_BACKOFF: Final = 1.0
_JITTER: Final = 1.0


_RETRY_POLICY: ContextVar[tuple[int, float]] = ContextVar(
    "cveta2_retry_policy",
    default=(DEFAULT_RETRY_ATTEMPTS, DEFAULT_RETRY_MAX_WAIT),
)


class _RetryPolicyMeta(type):
    @property
    def attempts(cls) -> int:
        return _RETRY_POLICY.get()[0]

    @property
    def max_wait(cls) -> float:
        return _RETRY_POLICY.get()[1]


class RetryPolicy(metaclass=_RetryPolicyMeta):
    """Context-local retry budget, set at client bootstrap.

    Decorators are applied before configuration is loaded and consult this
    context-local view on every retry decision.
    """


def configure_retries(attempts: int, max_wait: float) -> None:
    """Set the retry budget used by calls in the current context."""
    _RETRY_POLICY.set((attempts, max_wait))


def _budget_exhausted(retry_state: RetryCallState) -> bool:
    """Stop once the configured attempt count has been spent."""
    return retry_state.attempt_number >= RetryPolicy.attempts


def _backoff(retry_state: RetryCallState) -> float:
    """Sleep for what ``Retry-After`` asked, else exponential with jitter.

    Jitter matters as soon as several workers are in flight: without it a
    rate-limit burst puts every one of them back on the wire at the same
    instant and the server throttles them all over again.
    """
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exc, CvatApiError) and exc.retry_after is not None:
        return min(exc.retry_after, RetryPolicy.max_wait)
    jittered = wait_exponential_jitter(
        initial=_INITIAL_BACKOFF, max=RetryPolicy.max_wait, jitter=_JITTER
    )
    return jittered(retry_state)


def _log_retry(label: str, retry_state: RetryCallState) -> None:
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    logger.warning(
        f"{label} call failed (attempt {retry_state.attempt_number}), retrying: {exc!r}"
    )


def network_retry(
    should_retry: Callable[[BaseException], bool],
    label: str,
) -> Callable[[WrappedFn], WrappedFn]:
    """Build a retry decorator that fires whenever *should_retry* says so.

    Backs off per :func:`_backoff`, logs a warning (prefixed with *label*)
    before each sleep, and re-raises the last error once the budget is
    spent.
    """
    return retry(
        retry=retry_if_exception(should_retry),
        stop=_budget_exhausted,
        wait=_backoff,
        before_sleep=functools.partial(_log_retry, label),
        reraise=True,
    )
