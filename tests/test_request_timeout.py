"""Tests for opt-in request timeouts and host URL normalization."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pytest
import yaml

from cveta2._client.sdk_adapter import apply_request_timeout
from cveta2.config import CvatConfig
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
