"""Controlled HTTP regressions for CVAT failure diagnostics and SDK retries."""

import json
import socket
import threading
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlsplit

import pytest
import urllib3.exceptions
from cvat_sdk import Client
from cvat_sdk.api_client.exceptions import ApiException
from urllib3.util import Retry

from cveta2.adapters.config.settings import CvatConfig
from cveta2.adapters.cvat.connection import open_sdk_api
from cveta2.adapters.cvat.diagnostics import _response_summary, _safe_endpoint
from cveta2.adapters.cvat.sdk_adapter import SdkCvatApiAdapter
from cveta2.adapters.cvat.transport import cvat_read
from cveta2.adapters.execution.retry import RetryPolicy, configure_retries
from cveta2.application.client.fetch import _FetchMixin
from cveta2.application.client.shared import FetchContext
from cveta2.domain.errors import CvatApiError, CvatRequestDiagnostics, Cveta2Error
from cveta2.exceptions import CvatRequestDiagnostics as PublicDiagnostics
from tests.helpers import make_task

Reply = tuple[int, dict[str, str], bytes]
Route = Callable[[str, str], Reply]


@contextmanager
def _server(route: Route) -> Iterator[tuple[str, list[tuple[str, str]]]]:
    calls: list[tuple[str, str]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.respond()

        def do_POST(self) -> None:
            self.respond()

        def respond(self) -> None:
            calls.append((self.command, self.path))
            status, headers, body = route(self.command, self.path)
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            for name, value in headers.items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    )
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _json_reply(status: int, data: object, request_id: str = "request-123") -> Reply:
    return (
        status,
        {"Content-Type": "application/json", "X-Request-Id": request_id},
        json.dumps(data).encode(),
    )


@pytest.fixture(autouse=True)
def _retry_budget() -> Iterator[None]:
    previous = (RetryPolicy.attempts, RetryPolicy.max_wait)
    configure_retries(attempts=1, max_wait=0)
    yield
    configure_retries(*previous)


@pytest.mark.parametrize("status", [500, 502, 503, 504, 429])
def test_exhausted_sdk_response_retains_status_request_and_cause(status: int) -> None:
    with (
        _server(lambda _method, _path: _json_reply(status, {"detail": "busy"})) as (
            host,
            calls,
        ),
        Client(host, check_server_version=False) as client,
    ):
        manager = client.api_client.rest_client.pool_manager
        pool = manager.connection_from_url(host)
        original = Retry(total=1, status_forcelist=[status], backoff_factor=0)
        pool.retries = original
        with pytest.raises(CvatApiError) as caught:
            SdkCvatApiAdapter(client).get_task_annotations(7)

        error = caught.value
        assert error.status_code == status
        assert error.__cause__ is not None
        assert error.diagnostics is not None
        assert error.diagnostics.operation == "get_task_annotations"
        assert error.diagnostics.method == "GET"
        assert urlsplit(error.diagnostics.endpoint).path == "/api/tasks/7/annotations/"
        assert ("task_id", 7) in error.diagnostics.resource_ids
        assert ("X-Request-Id", "request-123") in error.diagnostics.request_ids
        assert error.diagnostics.timestamp_utc.utcoffset() == timedelta(0)
        assert len(calls) == 2
        assert pool.retries is original
        assert original.raise_on_status


def test_public_exception_constructor_and_diagnostics_identity() -> None:
    old = CvatApiError("old", 503, 1.5)
    assert old.args == ("old",)
    assert old.status_code == 503
    assert old.retry_after == 1.5
    assert old.diagnostics is None
    assert PublicDiagnostics is CvatRequestDiagnostics


def test_failure_inside_pagination_names_the_failed_page() -> None:
    def route(_method: str, path: str) -> Reply:
        if parse_qs(urlsplit(path).query).get("page") == ["1"]:
            return _json_reply(
                200, {"results": [], "next": "page-2", "previous": None, "count": 1}
            )
        return _json_reply(500, {"detail": "page failed"}, "page-two")

    with (
        _server(route) as (host, calls),
        Client(host, check_server_version=False) as client,
    ):
        with pytest.raises(CvatApiError) as caught:
            SdkCvatApiAdapter(client).list_organizations()
        diagnostic = caught.value.diagnostics
        assert diagnostic is not None
        assert diagnostic.operation == "list_organizations"
        assert parse_qs(urlsplit(diagnostic.endpoint).query) == {"page": ["2"]}
        assert ("X-Request-Id", "page-two") in diagnostic.request_ids
        assert len(calls) == 2


def test_issue_comments_failure_names_issue_and_originating_task() -> None:
    def route(_method: str, path: str) -> Reply:
        if urlsplit(path).path == "/api/issues":
            return _json_reply(
                200,
                {
                    "results": [
                        {
                            "id": 12,
                            "frame": 0,
                            "resolved": False,
                            "position": [0, 0],
                            "comments": {
                                "count": 1,
                                "url": "/api/comments?issue_id=12",
                            },
                        }
                    ],
                    "next": None,
                    "previous": None,
                    "count": 1,
                },
            )
        return _json_reply(500, {"detail": "comments failed"})

    with (
        _server(route) as (host, _calls),
        Client(host, check_server_version=False) as client,
    ):
        with pytest.raises(CvatApiError) as caught:
            SdkCvatApiAdapter(client).get_task_issues(7)
        diagnostic = caught.value.diagnostics
        assert diagnostic is not None
        assert urlsplit(diagnostic.endpoint).path == "/api/comments"
        assert diagnostic.resource_ids == (("issue_id", 12), ("task_id", 7))
        assert parse_qs(urlsplit(diagnostic.endpoint).query) == {
            "issue_id": ["12"],
            "page": ["1"],
        }


def test_retry_logs_distinguish_cveta2_attempts_and_wait(
    capture_logs: list[str],
) -> None:
    configure_retries(attempts=2, max_wait=0)
    with (
        _server(lambda _method, _path: _json_reply(500, {"detail": "busy"})) as (
            host,
            calls,
        ),
        Client(host, check_server_version=False) as client,
        pytest.raises(CvatApiError),
    ):
        SdkCvatApiAdapter(client).get_task_annotations(42)
    assert len(calls) == 2
    retry_messages = [
        message for message in capture_logs if "попытка cveta2" in message
    ]
    assert len(retry_messages) == 1
    assert "1/2" in retry_messages[0]
    assert "через 0.00 с" in retry_messages[0]
    assert "get_task_annotations" in retry_messages[0]
    assert "/api/tasks/42/annotations/" in retry_messages[0]


@pytest.mark.parametrize("strict", [False, True])
@pytest.mark.parametrize("status", [500, 502, 503, 504, 429])
def test_controlled_task_failure_preserves_default_strict_and_429_policy(
    *, strict: bool, status: int
) -> None:
    with (
        _server(lambda _method, _path: _json_reply(status, {"detail": "busy"})) as (
            host,
            _calls,
        ),
        Client(host, check_server_version=False) as client,
    ):
        client.api_client.rest_client.pool_manager.connection_from_url(
            host
        ).retries = Retry(total=0)
        adapter = SdkCvatApiAdapter(client)
        task = make_task(7, name="sample", status="completed")
        context = FetchContext([task], {}, {}, raise_on_failure=strict)
        if strict or status == 429:
            with pytest.raises(Cveta2Error) as caught:
                _FetchMixin.fetch_one_task(adapter, task, context)
            if status == 429:
                assert "НЕ пропущена" in str(caught.value)
            else:
                assert isinstance(caught.value, CvatApiError)
                assert caught.value.status_code == status
        else:
            assert _FetchMixin.fetch_one_task(adapter, task, context) is None


def test_redaction_bounds_response_and_allowlists_request_metadata() -> None:
    body = {
        "detail": "password=plain-secret Bearer bearer-secret " + "busy " * 250,
        "token": "json-secret",
        "cookies": "session-secret",
    }

    def route(_method: str, _path: str) -> Reply:
        status, headers, content = _json_reply(500, body)
        headers.update(
            {"Set-Cookie": "session=cookie-secret", "X-Private": "private-secret"}
        )
        return status, headers, content

    with (
        _server(route) as (host, _calls),
        Client(host, check_server_version=False) as client,
    ):
        adapter = SdkCvatApiAdapter(client)

        @cvat_read
        def fetch(task_id: int) -> None:
            adapter.client.api_client.rest_client.GET(
                host
                + f"/api/tasks/7/annotations/?token=url-secret&page=2&task_id={task_id}"
                "&password=query-secret#fragment-secret",
                headers={
                    "Authorization": "Bearer request-secret",
                    "Cookie": "request-cookie",
                },
            )

        with pytest.raises(CvatApiError) as caught:
            fetch(7)
        diagnostic = caught.value.diagnostics
        assert diagnostic is not None
        text = str(caught.value) + repr(diagnostic)
        for secret in (
            "plain-secret",
            "bearer-secret",
            "json-secret",
            "session-secret",
            "cookie-secret",
            "private-secret",
            "url-secret",
            "fragment-secret",
            "query-secret",
            "request-secret",
            "request-cookie",
        ):
            assert secret not in text
        assert len(diagnostic.response_summary) <= 512
        assert diagnostic.request_ids == (("X-Request-Id", "request-123"),)
        assert parse_qs(urlsplit(diagnostic.endpoint).query) == {
            "page": ["2"],
            "task_id": ["7"],
        }


def test_raw_html_and_cookies_do_not_reach_sdk_advisory_version_warning(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Retry, "sleep", lambda _self, _response=None: None)

    def route(_method: str, path: str) -> Reply:
        if urlsplit(path).path == "/api/server/about":
            return (
                503,
                {"Content-Type": "text/html", "Set-Cookie": "secret-cookie"},
                b"<html>secret-html</html>",
            )
        return _json_reply(401, {"detail": "login denied"}, "login-id")

    with _server(route) as (host, calls):
        config = CvatConfig(host=host, username="user", password="password")
        with pytest.raises(CvatApiError) as caught, open_sdk_api(config):
            pass
        assert caught.value.status_code == 401
        assert caught.value.diagnostics is not None
        assert urlsplit(caught.value.diagnostics.endpoint).path == "/api/auth/login"
        assert len(calls) == 5
        assert "server API version" in caplog.text
        assert "secret-html" not in caplog.text
        assert "secret-cookie" not in caplog.text


def test_concurrent_calls_keep_resources_independent_and_clear_stale_context() -> None:
    barrier = threading.Barrier(2, timeout=5)

    def route(_method: str, path: str) -> Reply:
        barrier.wait()
        task_id = urlsplit(path).path.split("/")[3]
        return _json_reply(500, {"detail": "failed"}, f"request-{task_id}")

    def fetch(adapter: SdkCvatApiAdapter, task_id: int) -> CvatApiError:
        configure_retries(attempts=1, max_wait=0)
        try:
            adapter.get_task_annotations(task_id)
        except CvatApiError as error:
            return error
        raise AssertionError("Expected failure")

    with (
        _server(route) as (host, _calls),
        Client(host, check_server_version=False) as client,
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        adapter = SdkCvatApiAdapter(client)
        futures = [pool.submit(fetch, adapter, task_id) for task_id in (7, 8)]
        for task_id, future in zip((7, 8), futures, strict=True):
            diagnostic = future.result().diagnostics
            assert diagnostic is not None
            assert diagnostic.resource_ids == (("task_id", task_id),)
            assert diagnostic.request_ids == (("X-Request-Id", f"request-{task_id}"),)

    fake = MagicMock()
    fake.api_client.tasks_api.retrieve_annotations.side_effect = ApiException(
        status=404
    )
    with pytest.raises(CvatApiError) as caught:
        SdkCvatApiAdapter(fake).get_task_annotations(99)
    assert caught.value.diagnostics is None
    assert "request-7" not in str(caught.value)


def test_non_idempotent_write_keeps_sdk_method_restriction() -> None:
    with (
        _server(lambda _method, _path: _json_reply(503, {"detail": "ambiguous"})) as (
            host,
            calls,
        ),
        Client(host, check_server_version=False) as client,
    ):
        adapter = SdkCvatApiAdapter(client)

        @cvat_read
        def post_once() -> None:
            adapter.client.api_client.rest_client.POST(host + "/api/task", body={})

        with pytest.raises(CvatApiError) as caught:
            post_once()
        assert caught.value.status_code == 503
        assert calls == [("POST", "/api/task")]


def test_warm_injected_pool_keeps_policy_and_connection_configuration() -> None:
    def route(_method: str, path: str) -> Reply:
        return _json_reply(200 if path == "/warm" else 503, {"detail": "busy"})

    with (
        _server(route) as (host, calls),
        Client(host, check_server_version=False) as client,
    ):
        manager = client.api_client.rest_client.pool_manager
        pool = manager.connection_from_url(host)
        policy = Retry(
            total=1,
            status=1,
            read=2,
            connect=2,
            status_forcelist=[503],
            allowed_methods=frozenset({"GET"}),
        )
        pool.retries = policy
        before = dict(manager.connection_pool_kw)
        assert manager.request("GET", host + "/warm").status == 200
        with pytest.raises(CvatApiError) as caught:
            SdkCvatApiAdapter(client).get_task_annotations(7)
        assert caught.value.status_code == 503
        assert len(calls) == 3
        assert manager.connection_pool_kw == before
        assert pool.retries is policy
        assert policy.raise_on_status
        assert policy.allowed_methods == frozenset({"GET"})


@pytest.mark.parametrize("content_type", ["text/plain", "text/html", ""])
def test_html_fragments_are_omitted_even_without_html_content_type(
    content_type: str,
) -> None:
    assert (
        _response_summary(b"<h1>gateway</h1><pre>secret</pre>", content_type)
        == "HTML-ответ скрыт"
    )


def test_url_userinfo_and_nonidentifier_queries_are_removed() -> None:
    assert (
        _safe_endpoint(
            "https://user:password@example.test/api/tasks/7?token=secret&page=2&task_id=7#secret"
        )
        == "https://example.test/api/tasks/7?page=2&task_id=7"
    )


def test_bootstrap_redacts_unlabeled_echoed_request_credentials() -> None:
    def route(_method: str, path: str) -> Reply:
        if urlsplit(path).path == "/api/server/about":
            return _json_reply(
                200,
                {
                    "version": "2.59.1",
                    "name": "CVAT",
                    "description": "test",
                    "logo_url": "",
                    "subtitle": "test",
                },
            )
        return _json_reply(401, {"detail": "Refused login for alice with s3cret-value"})

    with _server(route) as (host, _calls):
        config = CvatConfig(host=host, username="alice", password="s3cret-value")
        with pytest.raises(CvatApiError) as caught, open_sdk_api(config):
            pass
        assert "alice" not in str(caught.value)
        assert "s3cret-value" not in str(caught.value)
        assert caught.value.diagnostics is not None
        assert "[redacted]" in caught.value.diagnostics.response_summary


def test_request_context_does_not_survive_a_swallowed_failure_or_success() -> None:
    with (
        _server(lambda _method, _path: _json_reply(500, {"detail": "failed"})) as (
            host,
            _calls,
        ),
        Client(host, check_server_version=False) as client,
    ):
        with pytest.raises(CvatApiError):
            SdkCvatApiAdapter(client).get_task_annotations(7)

        @cvat_read
        def later(task_id: int) -> None:
            raise ApiException(status=404, reason=f"Missing task {task_id}")

        with pytest.raises(CvatApiError) as caught:
            later(99)
        assert caught.value.diagnostics is None
        assert "request-123" not in str(caught.value)


def test_exhausted_connection_failure_retains_actual_request_and_cause(
    capture_logs: list[str],
) -> None:
    configure_retries(attempts=2, max_wait=0)
    # A bound but non-listening owned socket reliably refuses connections and
    # prevents another process from reusing the chosen port during the test.
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        host = f"http://127.0.0.1:{reserved.getsockname()[1]}"
        with Client(host, check_server_version=False) as client:
            pool = client.api_client.rest_client.pool_manager.connection_from_url(host)
            pool.retries = Retry(total=0)
            with pytest.raises(CvatApiError) as caught:
                SdkCvatApiAdapter(client).get_task_annotations(11)
        error = caught.value
        assert error.status_code == 0
        assert isinstance(error.__cause__, urllib3.exceptions.MaxRetryError)
        assert error.diagnostics is not None
        assert error.diagnostics.endpoint == host + "/api/tasks/11/annotations/"
        assert error.diagnostics.resource_ids == (("task_id", 11),)
        assert error.diagnostics.status_code == 0
        assert error.diagnostics.request_ids == ()
        assert any("попытка cveta2 1/2" in message for message in capture_logs)

    @cvat_read
    def unrelated() -> None:
        raise ApiException(status=404)

    with pytest.raises(CvatApiError) as next_error:
        unrelated()
    assert next_error.value.diagnostics is None


def test_explicit_request_retry_policy_overrides_warm_pool_without_mutation() -> None:
    with (
        _server(lambda _method, _path: _json_reply(503, {"detail": "busy"})) as (
            host,
            calls,
        ),
        Client(host, check_server_version=False) as client,
    ):
        manager = client.api_client.rest_client.pool_manager
        pool = manager.connection_from_url(host)
        pool_policy = Retry(total=0)
        pool.retries = pool_policy
        with pytest.raises(CvatApiError):
            SdkCvatApiAdapter(client).get_task_annotations(7)
        request_policy = Retry(total=1, status_forcelist=[503], backoff_factor=0)
        response = manager.request("GET", host + "/api/tasks/8", retries=request_policy)
        assert response.status == 503
        assert len(calls) == 3
        assert pool.retries is pool_policy
        assert request_policy.raise_on_status
        assert request_policy.total == 1


@pytest.mark.parametrize(
    ("headers", "query", "url_query", "secret"),
    [
        (
            {"Cookie": "sessionid=session-private-value"},
            [],
            "",
            "session-private-value",
        ),
        (
            {"Cookie": 'sessionid="quoted-private-value"; csrftoken=csrf-value'},
            [],
            "",
            "quoted-private-value",
        ),
        (
            {"Cookie": "sessionid=session-value; csrftoken=csrf-private-value"},
            [],
            "",
            "csrf-private-value",
        ),
        ({"X-API-Key": "header-private-value"}, [], "", "header-private-value"),
        (
            {"X-CSRFToken": "csrf-header-private-value"},
            [],
            "",
            "csrf-header-private-value",
        ),
        (
            {"Proxy-Authorization": "Bearer proxy-private-value"},
            [],
            "",
            "proxy-private-value",
        ),
        ({}, [("token", "query-private-value")], "", "query-private-value"),
        (
            {},
            [("opaque_credential", "opaque-private-value")],
            "",
            "opaque-private-value",
        ),
        ({}, [], "?token=url-private-value", "url-private-value"),
    ],
)
def test_echoed_cookie_header_and_query_secrets_are_redacted(
    headers: dict[str, str], query: list[tuple[str, str]], url_query: str, secret: str
) -> None:
    def route(_method: str, _path: str) -> Reply:
        status, response_headers, body = _json_reply(
            500, {"detail": f"Refused cookie {secret}"}
        )
        response_headers["X-Correlation-Id"] = secret
        return status, response_headers, body

    with (
        _server(route) as (host, _calls),
        Client(host, check_server_version=False) as client,
    ):
        SdkCvatApiAdapter(client)

        @cvat_read
        def fetch() -> None:
            client.api_client.rest_client.GET(
                host + "/api/tasks/7" + url_query, query_params=query, headers=headers
            )

        with pytest.raises(CvatApiError) as caught:
            fetch()
        diagnostic = caught.value.diagnostics
        assert diagnostic is not None
        assert secret not in str(caught.value)
        assert secret not in repr(diagnostic)
        assert "[redacted]" in diagnostic.response_summary
        assert ("X-Correlation-Id", "[redacted]") in diagnostic.request_ids
        assert urlsplit(diagnostic.endpoint).query == ""
