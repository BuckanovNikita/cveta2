"""Tests for opt-in request timeouts and host URL normalization."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pytest
import yaml

from cveta2._client.connection import configure_network
from cveta2._client.sdk_adapter import apply_request_timeout
from cveta2._concurrency import Workers, configure_workers
from cveta2._retry import RetryPolicy, configure_retries
from cveta2.config import CvatConfig, NetworkConfig
from cveta2.s3_utils import make_s3_client, set_default_data_timeout

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from cvat_sdk import Client as CvatSdkClient


# ---------------------------------------------------------------------------
# CVETA2_DATA_TIMEOUT env parsing
# ---------------------------------------------------------------------------


def test_from_env_parses_valid_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CVETA2_DATA_TIMEOUT", "30.5")
    assert CvatConfig.from_env().request_timeout == 30.5


def test_from_env_unset_timeout_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CVETA2_DATA_TIMEOUT", raising=False)
    assert CvatConfig.from_env().request_timeout is None


def test_from_env_garbage_timeout_warns(
    monkeypatch: pytest.MonkeyPatch,
    capture_logs: list[str],
) -> None:
    monkeypatch.setenv("CVETA2_DATA_TIMEOUT", "not-a-number")
    assert CvatConfig.from_env().request_timeout is None
    assert any("CVETA2_DATA_TIMEOUT" in msg for msg in capture_logs)


# ---------------------------------------------------------------------------
# merge precedence
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("override_timeout", "expected"),
    [
        (None, 30.0),
        (0.0, 0.0),
        (60.0, 60.0),
    ],
    ids=["missing_keeps_base", "zero_override_wins", "value_override_wins"],
)
def test_merge_timeout_precedence(
    override_timeout: float | None,
    expected: float,
) -> None:
    base = CvatConfig(request_timeout=30.0)
    merged = base.merge(CvatConfig(request_timeout=override_timeout))
    assert merged.request_timeout == expected


# ---------------------------------------------------------------------------
# host trailing-slash normalization
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw_host", "expected"),
    [
        ("https://x.example/", "https://x.example"),
        ("https://x.example//", "https://x.example"),
        ("https://x.example", "https://x.example"),
        ("", ""),
    ],
    ids=["single_slash", "double_slash", "no_slash", "empty"],
)
def test_host_trailing_slash_stripped(raw_host: str, expected: str) -> None:
    assert CvatConfig(host=raw_host).host == expected


# ---------------------------------------------------------------------------
# save_to_file persistence
# ---------------------------------------------------------------------------


def test_save_to_file_persists_timeout(tmp_path: Path) -> None:
    cfg = CvatConfig(host="https://x.example", request_timeout=45.0)
    path = cfg.save_to_file(tmp_path / "config.yaml")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["cvat"]["request_timeout"] == 45.0


def test_save_to_file_omits_unset_timeout(tmp_path: Path) -> None:
    cfg = CvatConfig(host="https://x.example")
    path = cfg.save_to_file(tmp_path / "config.yaml")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert "request_timeout" not in data["cvat"]


def test_saved_timeout_roundtrips_through_load(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for var in (
        "CVAT_HOST",
        "CVAT_ORGANIZATION",
        "CVAT_USERNAME",
        "CVAT_PASSWORD",
        "CVETA2_DATA_TIMEOUT",
    ):
        monkeypatch.delenv(var, raising=False)
    cfg_path = tmp_path / "config.yaml"
    CvatConfig(host="https://x.example", request_timeout=45.0).save_to_file(cfg_path)
    assert CvatConfig.load(config_path=cfg_path).request_timeout == 45.0


# ---------------------------------------------------------------------------
# apply_request_timeout wrapper
# ---------------------------------------------------------------------------


class _FakeRestClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> str:
        self.calls.append({"method": method, "url": url, **kwargs})
        return "response"


class _FakeApiClient:
    def __init__(self) -> None:
        self.rest_client = _FakeRestClient()


class _FakeSdkClient:
    def __init__(self) -> None:
        self.api_client = _FakeApiClient()


def test_apply_request_timeout_injects_default_tuple() -> None:
    fake = _FakeSdkClient()
    apply_request_timeout(cast("CvatSdkClient", fake), 30.0)
    fake.api_client.rest_client.request("GET", "http://x")
    (call,) = fake.api_client.rest_client.calls
    assert call["_request_timeout"] == (10.0, 30.0)


def test_apply_request_timeout_preserves_explicit_value() -> None:
    fake = _FakeSdkClient()
    apply_request_timeout(cast("CvatSdkClient", fake), 30.0)
    fake.api_client.rest_client.request("GET", "http://x", _request_timeout=5)
    (call,) = fake.api_client.rest_client.calls
    assert call["_request_timeout"] == 5


# ---------------------------------------------------------------------------
# make_s3_client
# ---------------------------------------------------------------------------


@pytest.fixture
def s3_env(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test-key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test-secret")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    yield
    set_default_data_timeout(None)


@pytest.mark.usefixtures("s3_env")
def test_make_s3_client_applies_default_timeout() -> None:
    set_default_data_timeout(123.0)
    client: Any = make_s3_client()
    assert client.meta.config.read_timeout == 123.0
    assert client.meta.config.connect_timeout == 10.0
    assert client.meta.config.retries["mode"] == "standard"
    assert client.meta.config.retries["total_max_attempts"] == 4


@pytest.mark.parametrize("timeout", [None, 0.0], ids=["none", "zero"])
@pytest.mark.usefixtures("s3_env")
def test_make_s3_client_without_timeout(timeout: float | None) -> None:
    set_default_data_timeout(timeout)
    client: Any = make_s3_client(endpoint_url="http://localhost:9000")
    assert client.meta.endpoint_url == "http://localhost:9000"
    assert client.meta.config.read_timeout != 123.0


# ---------------------------------------------------------------------------
# CLI global SDK timeout backstop
# ---------------------------------------------------------------------------


_BOTO3_DEFAULT_READ_TIMEOUT = 60.0


@pytest.mark.parametrize(
    ("timeout", "expected_calls", "expected_read_timeout"),
    [
        (45.0, [45.0], 45.0),
        (None, [], _BOTO3_DEFAULT_READ_TIMEOUT),
        (0.0, [], _BOTO3_DEFAULT_READ_TIMEOUT),
    ],
    ids=["value_installs_global", "none_skips", "zero_skips"],
)
@pytest.mark.usefixtures("s3_env")
def test_configure_data_timeout_installs_global_backstop(
    monkeypatch: pytest.MonkeyPatch,
    timeout: float | None,
    expected_calls: list[float],
    expected_read_timeout: float,
) -> None:
    from cveta2._client import connection

    calls: list[float] = []
    monkeypatch.setattr(connection, "install_global_request_timeout", calls.append)
    connection.configure_data_timeout(timeout)
    assert calls == expected_calls

    # The S3 half of the same call. Asserting only the SDK backstop above left
    # `set_default_data_timeout(timeout)` free to become
    # `set_default_data_timeout(None)`, silently dropping the timeout from every
    # S3 transfer while CVAT requests kept theirs.
    client: Any = make_s3_client()
    assert client.meta.config.read_timeout == pytest.approx(expected_read_timeout)
    set_default_data_timeout(None)


# ---------------------------------------------------------------------------
# SDK client kwargs
# ---------------------------------------------------------------------------


def test_build_client_kwargs_sends_credentials_only_when_both_are_set() -> None:
    """A half-filled credential pair must not turn into an anonymous session.

    ``if cfg.username and cfg.password`` guards this. An ``and`` -> ``or``
    mutant sends ``(username, None)`` to the SDK, and dropping the guard opens
    an unauthenticated CVAT session that fails much later and confusingly.
    """
    from cveta2._client.connection import _build_client_kwargs

    both = CvatConfig(host="https://cvat.example.com", username="u", password="p")
    assert _build_client_kwargs(both) == {
        "host": "https://cvat.example.com",
        "credentials": ("u", "p"),
    }

    username_only = CvatConfig(host="https://cvat.example.com", username="u")
    assert _build_client_kwargs(username_only) == {"host": "https://cvat.example.com"}

    password_only = CvatConfig(host="https://cvat.example.com", password="p")
    assert _build_client_kwargs(password_only) == {"host": "https://cvat.example.com"}


def test_build_client_kwargs_maps_a_missing_host_to_empty_string() -> None:
    """``cfg.host or ""`` — make_client rejects None but accepts an empty host."""
    from cveta2._client.connection import _build_client_kwargs

    assert _build_client_kwargs(CvatConfig()) == {"host": ""}


def test_install_global_request_timeout_covers_new_rest_clients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cvat_sdk.api_client.rest import RESTClientObject

    from cveta2._client import sdk_adapter

    recorded: dict[str, object] = {}

    def fake_request(_self: object, *_args: object, **kwargs: object) -> None:
        recorded.update(kwargs)

    monkeypatch.setattr(RESTClientObject, "request", fake_request)
    try:
        sdk_adapter.install_global_request_timeout(7.0)
        sdk_adapter.install_global_request_timeout(9.0)

        instance = object.__new__(RESTClientObject)
        RESTClientObject.request(instance, "GET", "http://x")
        installed_timeout = recorded["_request_timeout"]
        assert installed_timeout == (10.0, 9.0)

        recorded.clear()
        RESTClientObject.request(instance, "GET", "http://x", _request_timeout=5)
        caller_timeout = recorded["_request_timeout"]
        assert caller_timeout == 5
    finally:
        delattr(RESTClientObject, sdk_adapter._GLOBAL_TIMEOUT_MARKER)


# ---------------------------------------------------------------------------
# Connection pool sizing and the retry budget
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("s3_env")
def test_make_s3_client_configures_retries_without_a_timeout() -> None:
    """Botocore retries used to be reachable only by setting a timeout.

    The config object was built only in the timeout branch, so the default
    install silently had neither retries nor a raised pool ceiling.
    """
    set_default_data_timeout(None)
    client: Any = make_s3_client()

    assert client.meta.config.retries["mode"] == "standard"
    assert client.meta.config.max_pool_connections >= 10


@pytest.mark.usefixtures("s3_env")
def test_pool_size_follows_the_worker_count() -> None:
    """Workers beyond the pool size queue for a connection instead of running."""
    try:
        configure_workers(s3=48, cvat=4)
        client: Any = make_s3_client()
        assert client.meta.config.max_pool_connections == 48
    finally:
        configure_workers(s3=1, cvat=1)


@pytest.mark.usefixtures("s3_env")
def test_pool_size_never_drops_below_the_boto_default() -> None:
    """A small worker count must not make unrelated S3 calls contend."""
    try:
        configure_workers(s3=2, cvat=1)
        client: Any = make_s3_client()
        assert client.meta.config.max_pool_connections == 10
    finally:
        configure_workers(s3=1, cvat=1)


def test_configure_network_installs_the_whole_retry_budget() -> None:
    """The decorators bind at import time and read this budget per attempt.

    Both halves matter: the attempt count decides whether a throttled call
    is repeated at all, and the cap decides how long a server that asks for
    an hour is allowed to stall the run.
    """
    attempts, max_wait = RetryPolicy.attempts, RetryPolicy.max_wait
    try:
        configure_network(
            NetworkConfig(s3_workers=7, retry_attempts=9, retry_max_wait=12.5)
        )
        assert (RetryPolicy.attempts, RetryPolicy.max_wait) == (9, 12.5)
    finally:
        configure_retries(attempts, max_wait)
        configure_workers(s3=1, cvat=1)


def test_configure_network_installs_both_worker_counts() -> None:
    """S3 and CVAT fan out at different widths and must not be conflated."""
    attempts, max_wait = RetryPolicy.attempts, RetryPolicy.max_wait
    try:
        configure_network(NetworkConfig(s3_workers=64, cvat_workers=3))
        assert (Workers.s3, Workers.cvat) == (64, 3)
    finally:
        configure_retries(attempts, max_wait)
        configure_workers(s3=1, cvat=1)
