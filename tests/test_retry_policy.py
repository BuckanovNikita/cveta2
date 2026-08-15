"""Retry policy: which failures are repeated, how long, and how often.

The read/write split is the load-bearing decision here. Before this policy
existed, ``_api_retry`` was handed a ``CvatApiError`` it did not list, so
every 429 and 5xx was retried exactly zero times; underneath, the SDK's own
urllib3 ``Retry`` covers neither 429 nor POST/PATCH. These tests pin both
halves: that status failures now retry at all, and that a write never
repeats a request the server might already have applied.
"""

from __future__ import annotations

import pytest
from botocore.exceptions import ClientError
from cvat_sdk.api_client.exceptions import ApiException

from cveta2._client.sdk_adapter import (
    _should_retry_read,
    _should_retry_write,
    _translate_api_errors,
)
from cveta2._retry import (
    _JITTER,
    DEFAULT_RETRY_ATTEMPTS,
    RetryPolicy,
    _backoff,
    configure_retries,
    network_retry,
)
from cveta2.exceptions import CvatApiError
from cveta2.s3_utils import _should_retry_s3

_AMBIGUOUS_WRITE_STATUS = (500, 502, 504)


@pytest.fixture(autouse=True)
def _restore_retry_policy() -> object:
    """Keep a test's retry budget from leaking into the rest of the run."""
    attempts, max_wait = RetryPolicy.attempts, RetryPolicy.max_wait
    yield
    configure_retries(attempts, max_wait)


def _client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": code}}, "GetObject")


class TestReadPredicate:
    @pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
    def test_transient_statuses_are_retried(self, status: int) -> None:
        assert _should_retry_read(CvatApiError("boom", status_code=status))

    @pytest.mark.parametrize("status", [400, 401, 403, 404, 409])
    def test_client_errors_are_not_retried(self, status: int) -> None:
        """Repeating a 404 or a 401 only spends the budget to fail again."""
        assert not _should_retry_read(CvatApiError("boom", status_code=status))

    def test_transport_failures_are_retried(self) -> None:
        assert _should_retry_read(ConnectionError("reset"))


class TestWritePredicate:
    def test_rate_limiting_is_retried(self) -> None:
        """A 429 is a refusal, so the write provably never landed."""
        assert _should_retry_write(CvatApiError("slow down", status_code=429))

    def test_unavailable_is_retried_only_when_it_asks_to_be(self) -> None:
        """``Retry-After`` is what separates a throttle from a crash."""
        throttled = CvatApiError("busy", status_code=503, retry_after=2.0)
        crashed = CvatApiError("busy", status_code=503)

        assert _should_retry_write(throttled)
        assert not _should_retry_write(crashed)

    @pytest.mark.parametrize("status", _AMBIGUOUS_WRITE_STATUS)
    def test_ambiguous_server_errors_are_never_retried(self, status: int) -> None:
        """The server may have applied the write before failing to say so.

        ``put_task_shapes`` appends rather than replaces, so a retry here
        would silently double every bbox. These abort instead, and
        ``upload --resume`` recovers by reading back what CVAT stored.
        """
        assert not _should_retry_write(CvatApiError("boom", status_code=status))

    def test_transport_failures_are_not_retried(self) -> None:
        """A dropped connection cannot tell us whether the write was applied."""
        assert not _should_retry_write(ConnectionError("reset"))


class TestS3Predicate:
    @pytest.mark.parametrize(
        "code", ["SlowDown", "RequestTimeout", "InternalError", "503"]
    )
    def test_throttle_and_transient_codes_are_retried(self, code: str) -> None:
        assert _should_retry_s3(_client_error(code))

    @pytest.mark.parametrize("code", ["NoSuchKey", "AccessDenied", "404"])
    def test_permanent_codes_fail_fast(self, code: str) -> None:
        assert not _should_retry_s3(_client_error(code))

    def test_transport_failures_are_retried(self) -> None:
        assert _should_retry_s3(OSError("broken pipe"))


class TestRetryLoop:
    def test_it_retries_until_the_call_succeeds(self) -> None:
        configure_retries(attempts=5, max_wait=0.01)
        calls: list[int] = []

        @network_retry(_should_retry_write, label="test")
        def flaky() -> str:
            calls.append(1)
            if len(calls) < 3:
                raise CvatApiError("throttled", status_code=429)
            return "ok"

        assert flaky() == "ok"
        assert len(calls) == 3

    def test_it_gives_up_after_the_configured_attempts(self) -> None:
        """The budget is a count of attempts, not of retries after the first."""
        configure_retries(attempts=3, max_wait=0.01)
        calls: list[int] = []

        @network_retry(_should_retry_write, label="test")
        def always_throttled() -> None:
            calls.append(1)
            raise CvatApiError("throttled", status_code=429)

        with pytest.raises(CvatApiError):
            always_throttled()
        assert len(calls) == 3

    def test_an_unretryable_failure_is_raised_on_the_first_attempt(self) -> None:
        configure_retries(attempts=5, max_wait=0.01)
        calls: list[int] = []

        @network_retry(_should_retry_write, label="test")
        def fails_hard() -> None:
            calls.append(1)
            raise CvatApiError("gone", status_code=404)

        with pytest.raises(CvatApiError):
            fails_hard()
        assert len(calls) == 1

    def test_configure_retries_changes_a_decorator_bound_earlier(self) -> None:
        """Decorators bind at import time, before any config has been read.

        If the budget were captured at decoration time instead of consulted
        per attempt, ``network.retry_attempts`` would silently do nothing.
        """
        calls: list[int] = []

        @network_retry(_should_retry_write, label="test")
        def always_throttled() -> None:
            calls.append(1)
            raise CvatApiError("throttled", status_code=429)

        configure_retries(attempts=2, max_wait=0.01)
        with pytest.raises(CvatApiError):
            always_throttled()

        assert len(calls) == 2


class _FakeOutcome:
    """Stand-in for the tenacity outcome that only carries the exception."""

    def __init__(self, exc: BaseException | None) -> None:
        self._exc = exc

    def exception(self) -> BaseException | None:
        return self._exc


class _FakeRetryState:
    """Minimal ``RetryCallState`` shape: what ``_backoff`` actually reads."""

    def __init__(self, exc: BaseException | None, attempt_number: int = 1) -> None:
        self.outcome = _FakeOutcome(exc)
        self.attempt_number = attempt_number


class TestBackoff:
    def test_retry_after_is_honoured_over_exponential_backoff(self) -> None:
        """A server that names its own delay knows better than our curve."""
        configure_retries(attempts=3, max_wait=30.0)
        state = _FakeRetryState(
            CvatApiError("busy", status_code=503, retry_after=7.0), attempt_number=1
        )

        assert _backoff(state) == 7.0  # type: ignore[arg-type]

    def test_retry_after_is_capped_by_max_wait(self) -> None:
        """A server asking for an hour must not hang the run for an hour."""
        configure_retries(attempts=3, max_wait=5.0)
        state = _FakeRetryState(
            CvatApiError("busy", status_code=503, retry_after=3600.0), attempt_number=1
        )

        assert _backoff(state) == 5.0  # type: ignore[arg-type]

    def test_backoff_without_a_header_stays_within_max_wait(self) -> None:
        configure_retries(attempts=8, max_wait=4.0)
        waits = [
            _backoff(_FakeRetryState(ConnectionError("reset"), attempt))  # type: ignore[arg-type]
            for attempt in range(1, 8)
        ]

        assert all(0 < wait <= 4.0 + _JITTER for wait in waits)

    def test_backoff_grows_with_the_attempt_number(self) -> None:
        """Without growth a rate-limited server just gets hammered harder."""
        configure_retries(attempts=8, max_wait=1000.0)
        early = _backoff(_FakeRetryState(ConnectionError("reset"), 1))  # type: ignore[arg-type]
        late = _backoff(_FakeRetryState(ConnectionError("reset"), 6))  # type: ignore[arg-type]

        assert late > early


def test_default_attempt_count_allows_a_real_retry() -> None:
    """A budget of 1 would make every predicate above dead code."""
    assert DEFAULT_RETRY_ATTEMPTS > 1


class _FakeHttpResponse:
    """The four attributes ``ApiException`` reads off an HTTP response."""

    def __init__(self, status: int, headers: dict[str, str] | None) -> None:
        self.status = status
        self.reason = "Too Many Requests"
        self.data = b""
        self.headers = headers


class TestRetryAfterParsing:
    def test_a_delta_seconds_header_reaches_the_exception(self) -> None:
        """The backoff prefers this value over its own curve."""

        @_translate_api_errors
        def throttled() -> None:
            raise ApiException(http_resp=_FakeHttpResponse(429, {"Retry-After": "12"}))

        with pytest.raises(CvatApiError) as caught:
            throttled()
        assert caught.value.retry_after == 12.0
        assert caught.value.status_code == 429

    @pytest.mark.parametrize(
        "headers",
        [None, {}, {"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}],
        ids=["no_headers", "no_retry_after", "http_date_form"],
    )
    def test_an_absent_or_unparseable_header_leaves_retry_after_unset(
        self, headers: dict[str, str] | None
    ) -> None:
        """Falling back to the normal backoff beats guessing a delay."""

        @_translate_api_errors
        def failed() -> None:
            raise ApiException(http_resp=_FakeHttpResponse(503, headers))

        with pytest.raises(CvatApiError) as caught:
            failed()
        assert caught.value.retry_after is None

    def test_a_503_without_the_header_is_not_retried_as_a_write(self) -> None:
        """The header is the entire difference for an ambiguous write.

        Ties the parsing above to the decision it exists to feed: a bare
        503 stays unretryable, so a half-applied write is never repeated.
        """

        @_translate_api_errors
        def failed() -> None:
            raise ApiException(http_resp=_FakeHttpResponse(503, {}))

        with pytest.raises(CvatApiError) as caught:
            failed()
        assert not _should_retry_write(caught.value)
