"""Tests for the ClearML check of ``cveta2 doctor``: offline resolution and one bounded login.

No test contacts a real server. Resolution tests replace the single network call; login
tests talk to a local HTTP server on 127.0.0.1 or to a port that refuses or never answers.
"""

import base64
import json
import os
import socket
import ssl
import threading
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import override

import pytest

from cveta2.adapters.clearml import diagnostics
from cveta2.adapters.clearml.diagnostics import check_clearml_configuration
from cveta2.domain.errors import Cveta2Error

# The ClearML SDK parses its configuration with deprecated pyparsing calls; that is the SDK's noise.
pytestmark = pytest.mark.filterwarnings("ignore::pyparsing.warnings.PyparsingDeprecationWarning")

_ACCESS_KEY = "AKCLEARMLACCESS0001"
_SECRET_KEY = "SKCLEARMLSECRET0002"
_SESSION_TOKEN = "eyJTOKENFROMSERVER0003"
_AUTH_TOKEN = "eyJAUTHTOKENFROMENV0004"
_BASIC = "Basic " + base64.b64encode(f"{_ACCESS_KEY}:{_SECRET_KEY}".encode()).decode()


@pytest.fixture
def no_clearml_configuration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Hide the developer's ClearML setup: no ``CLEARML_*`` variables and an absent config file.

    ``CLEARML_CONFIG_FILE`` replaces the home-directory files even when it does not
    exist, so pointing it into *tmp_path* keeps ``~/clearml.conf`` out of the check.
    """
    for name in list(os.environ):
        if name.startswith(("CLEARML_", "TRAINS_")):
            monkeypatch.delenv(name)
    config_file = tmp_path / "clearml.conf"
    monkeypatch.setenv("CLEARML_CONFIG_FILE", str(config_file))
    return config_file


def _assert_no_secret(text: str) -> None:
    for secret in (_ACCESS_KEY, _SECRET_KEY, _SESSION_TOKEN, _AUTH_TOKEN, _BASIC.split()[1]):
        assert secret not in text


def _report(messages: list[str]) -> str:
    lines = [message for message in messages if message.startswith("ClearML:")]
    assert len(lines) == 1, messages
    return lines[0]


def _set_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLEARML_API_ACCESS_KEY", _ACCESS_KEY)
    monkeypatch.setenv("CLEARML_API_SECRET_KEY", _SECRET_KEY)


def _token_body() -> bytes:
    return json.dumps({"meta": {"result_code": 200}, "data": {"token": _SESSION_TOKEN}}).encode()


@dataclass
class _FakeLogin:
    """Stands in for the one network call; records what would be sent."""

    status: int = 200
    body: bytes = field(default_factory=_token_body)
    calls: list[tuple[urllib.request.Request, ssl.SSLContext]] = field(default_factory=list)

    def __call__(self, request: urllib.request.Request, context: ssl.SSLContext) -> tuple[int, bytes]:
        self.calls.append((request, context))
        return self.status, self.body


@pytest.fixture
def fake_login(monkeypatch: pytest.MonkeyPatch) -> _FakeLogin:
    fake = _FakeLogin()
    monkeypatch.setattr(diagnostics, "_request_login", fake)
    return fake


# ---------------------------------------------------------------------------
# Offline resolution
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("no_clearml_configuration")
def test_configured_from_environment_logs_in_with_basic_auth(
    monkeypatch: pytest.MonkeyPatch,
    fake_login: _FakeLogin,
    capture_info_logs: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("CLEARML_API_HOST", "https://api.clearml.example")
    _set_keys(monkeypatch)

    assert check_clearml_configuration() is True

    [(request, context)] = fake_login.calls
    assert request.full_url == "https://api.clearml.example/auth.login"
    assert request.get_method() == "GET"
    assert request.get_header("Authorization") == _BASIC
    assert context.verify_mode == ssl.CERT_REQUIRED
    report = _report(capture_info_logs)
    assert report.startswith("ClearML: проверено")
    assert "https://api.clearml.example" in report
    assert "сервер файлов https://files.clearml.example" in report
    assert "переменные окружения" in report
    _assert_no_secret("\n".join(capture_info_logs) + capsys.readouterr().out)


def test_configured_from_config_file(
    no_clearml_configuration: Path,
    fake_login: _FakeLogin,
    capture_info_logs: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    no_clearml_configuration.write_text(
        "api {\n"
        '  api_server: "https://api.from-file.example"\n'
        "  verify_certificate: false\n"
        "  http { default_method: put }\n"
        f'  credentials {{ access_key: "{_ACCESS_KEY}", secret_key: "{_SECRET_KEY}" }}\n'
        "}\n"
    )

    assert check_clearml_configuration() is True

    [(request, context)] = fake_login.calls
    assert request.full_url == "https://api.from-file.example/auth.login"
    assert request.get_method() == "PUT"
    assert context.verify_mode == ssl.CERT_NONE
    report = _report(capture_info_logs)
    assert "https://api.from-file.example" in report
    assert str(no_clearml_configuration) in report
    assert "переменные окружения" not in report
    _assert_no_secret("\n".join(capture_info_logs) + capsys.readouterr().out)


@pytest.mark.usefixtures("no_clearml_configuration")
def test_environment_tls_and_method_settings_override_the_defaults(
    monkeypatch: pytest.MonkeyPatch, fake_login: _FakeLogin
) -> None:
    monkeypatch.setenv("CLEARML_API_HOST", "https://api.clearml.example")
    monkeypatch.setenv("CLEARML_API_HOST_VERIFY_CERT", "false")
    monkeypatch.setenv("CLEARML_API_DEFAULT_REQ_METHOD", "post")
    _set_keys(monkeypatch)

    assert check_clearml_configuration() is True

    [(request, context)] = fake_login.calls
    assert request.get_method() == "POST"
    assert context.verify_mode == ssl.CERT_NONE
    assert context.check_hostname is False


@pytest.mark.usefixtures("no_clearml_configuration")
def test_not_configured_warns_how_to_configure_without_contacting_the_server(
    fake_login: _FakeLogin, capture_logs: list[str]
) -> None:
    assert check_clearml_configuration() is False

    assert fake_login.calls == []
    assert len(capture_logs) == 1
    warning = capture_logs[0]
    assert warning.startswith("ClearML: не настроен")
    assert "файл конфигурации ClearML" in warning
    assert "CLEARML_API_HOST" in warning
    assert "CLEARML_API_ACCESS_KEY" in warning
    assert "CLEARML_API_SECRET_KEY" in warning


@pytest.mark.usefixtures("no_clearml_configuration")
def test_api_host_the_sdk_cannot_derive_other_hosts_from_is_not_configured(
    monkeypatch: pytest.MonkeyPatch, fake_login: _FakeLogin, capture_logs: list[str]
) -> None:
    """An upload needs the files host; the SDK derives it only from ``api.*`` or ``:8008`` hosts."""
    monkeypatch.setenv("CLEARML_API_HOST", "https://clearml-api.example.com")
    _set_keys(monkeypatch)

    assert check_clearml_configuration() is False

    assert fake_login.calls == []
    assert len(capture_logs) == 1
    warning = capture_logs[0]
    assert warning.startswith("ClearML: не настроен")
    assert "CLEARML_WEB_HOST" in warning
    assert "CLEARML_FILES_HOST" in warning
    assert "https://clearml-api.example.com" in warning
    assert "ключ доступа" not in warning
    _assert_no_secret(warning)


@pytest.mark.usefixtures("no_clearml_configuration")
def test_explicit_web_and_files_hosts_complete_the_configuration(
    monkeypatch: pytest.MonkeyPatch, fake_login: _FakeLogin, capture_info_logs: list[str]
) -> None:
    monkeypatch.setenv("CLEARML_API_HOST", "https://clearml-api.example.com")
    monkeypatch.setenv("CLEARML_WEB_HOST", "https://clearml.example.com")
    monkeypatch.setenv("CLEARML_FILES_HOST", "https://clearml-files.example.com")
    _set_keys(monkeypatch)

    assert check_clearml_configuration() is True

    assert len(fake_login.calls) == 1
    assert "сервер файлов https://clearml-files.example.com" in _report(capture_info_logs)


@pytest.mark.usefixtures("no_clearml_configuration")
def test_only_an_access_key_names_the_missing_secret(
    monkeypatch: pytest.MonkeyPatch, fake_login: _FakeLogin, capture_logs: list[str]
) -> None:
    monkeypatch.setenv("CLEARML_API_ACCESS_KEY", _ACCESS_KEY)

    assert check_clearml_configuration() is False

    assert fake_login.calls == []
    assert len(capture_logs) == 1
    assert "секретный ключ" in capture_logs[0]
    assert "ключ доступа" not in capture_logs[0]
    _assert_no_secret(capture_logs[0])


@pytest.mark.parametrize(
    ("content", "error_class"),
    [
        (f'api {{ credentials {{ secret_key: "{_SECRET_KEY}"\n'.encode(), "ConfigurationError"),
        (b"\xff\xfe\x00\x81" + _SECRET_KEY.encode(), "UnicodeDecodeError"),
    ],
    ids=["syntax-error", "binary"],
)
def test_unreadable_file_is_translated_at_adapter_boundary(
    no_clearml_configuration: Path, content: bytes, error_class: str
) -> None:
    no_clearml_configuration.write_bytes(content)

    with pytest.raises(Cveta2Error, match="ClearML") as error:
        check_clearml_configuration()
    assert str(no_clearml_configuration) in str(error.value)
    assert str(error.value).endswith(f": {error_class}")
    _assert_no_secret(str(error.value))


# ---------------------------------------------------------------------------
# One bounded login against a local server
# ---------------------------------------------------------------------------


@dataclass
class _LoginServer:
    """A local stand-in for the ClearML API server's ``auth.login``."""

    url: str
    status: int = 200
    body: bytes = field(default_factory=_token_body)
    headers: dict[str, str] = field(default_factory=dict)
    requests: list[tuple[str, str, str | None]] = field(default_factory=list)


@pytest.fixture
def login_server() -> Iterator[_LoginServer]:
    state = _LoginServer(url="")

    class Handler(BaseHTTPRequestHandler):
        def _answer(self) -> None:
            state.requests.append((self.command, self.path, self.headers.get("Authorization")))
            self.send_response(state.status)
            for name, value in state.headers.items():
                self.send_header(name, value)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(state.body)))
            self.end_headers()
            self.wfile.write(state.body)

        do_GET = do_POST = do_PUT = _answer  # noqa: N815 - http.server dispatches on these names.

        @override
        def log_message(self, *_args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state.url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()


def _point_at(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    """Use a local API host; it is not ``api.*``, so the web and files hosts are explicit."""
    monkeypatch.setenv("CLEARML_API_HOST", url)
    monkeypatch.setenv("CLEARML_WEB_HOST", "http://clearml.local")
    monkeypatch.setenv("CLEARML_FILES_HOST", "http://clearml-files.local")


@pytest.mark.usefixtures("no_clearml_configuration")
def test_server_accepting_the_keys_is_verified(
    monkeypatch: pytest.MonkeyPatch,
    login_server: _LoginServer,
    capture_info_logs: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    _point_at(monkeypatch, login_server.url)
    _set_keys(monkeypatch)

    assert check_clearml_configuration() is True

    assert login_server.requests == [("GET", "/auth.login", _BASIC)]
    report = _report(capture_info_logs)
    assert report.startswith(f"ClearML: проверено — вход на сервер API {login_server.url} выполнен")
    _assert_no_secret("\n".join(capture_info_logs) + capsys.readouterr().out)


@pytest.mark.usefixtures("no_clearml_configuration")
def test_auth_token_is_sent_as_a_bearer_token(
    monkeypatch: pytest.MonkeyPatch,
    login_server: _LoginServer,
    capture_info_logs: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    _point_at(monkeypatch, login_server.url)
    monkeypatch.setenv("CLEARML_AUTH_TOKEN", _AUTH_TOKEN)

    assert check_clearml_configuration() is True

    assert login_server.requests == [("GET", "/auth.login", f"Bearer {_AUTH_TOKEN}")]
    _assert_no_secret("\n".join(capture_info_logs) + capsys.readouterr().out)


@pytest.mark.parametrize("status", [401, 403])
@pytest.mark.usefixtures("no_clearml_configuration")
def test_server_rejecting_the_keys_is_reported(
    monkeypatch: pytest.MonkeyPatch,
    login_server: _LoginServer,
    capture_info_logs: list[str],
    capsys: pytest.CaptureFixture[str],
    status: int,
) -> None:
    login_server.status = status
    login_server.body = json.dumps(
        {"meta": {"result_code": status, "result_msg": f"Unauthorized (invalid credentials) {_ACCESS_KEY}"}}
    ).encode()
    _point_at(monkeypatch, login_server.url)
    _set_keys(monkeypatch)

    assert check_clearml_configuration() is False

    report = _report(capture_info_logs)
    assert report.startswith(f"ClearML: ключи отклонены — сервер API {login_server.url} ответил HTTP {status}")
    assert "ключ доступа и секретный ключ" in report
    _assert_no_secret("\n".join(capture_info_logs) + capsys.readouterr().out)


@pytest.mark.parametrize(
    ("status", "body", "headers", "reason"),
    [
        (200, b"<html>not the API</html>", {}, "ответ не похож на ответ сервера API ClearML"),
        (502, b"", {}, "HTTP 502"),
        (301, b"", {"Location": "https://elsewhere.example/auth.login"}, "перенаправление HTTP 301 не выполняется"),
    ],
    ids=["not-clearml", "server-error", "redirect"],
)
@pytest.mark.usefixtures("no_clearml_configuration")
def test_server_answering_without_a_login_is_unreachable(  # noqa: PLR0913 - fixtures plus one case.
    monkeypatch: pytest.MonkeyPatch,
    login_server: _LoginServer,
    capture_logs: list[str],
    *,
    status: int,
    body: bytes,
    headers: dict[str, str],
    reason: str,
) -> None:
    login_server.status, login_server.body, login_server.headers = status, body, headers
    _point_at(monkeypatch, login_server.url)
    _set_keys(monkeypatch)

    assert check_clearml_configuration() is False

    assert len(login_server.requests) == 1
    assert len(capture_logs) == 1
    assert capture_logs[0].startswith(f"ClearML: сервер недоступен — {login_server.url}: {reason}")
    _assert_no_secret("\n".join(capture_logs))


@pytest.mark.usefixtures("no_clearml_configuration")
def test_non_http_answer_is_unreachable(monkeypatch: pytest.MonkeyPatch, capture_logs: list[str]) -> None:
    """A server that speaks another protocol (here an SSH banner) is reported, not raised."""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)

        def answer() -> None:
            connection, _address = listener.accept()
            with connection:
                connection.recv(65536)
                connection.sendall(b"SSH-2.0-test\r\n")

        thread = threading.Thread(target=answer, daemon=True)
        thread.start()
        url = f"http://127.0.0.1:{listener.getsockname()[1]}"
        _point_at(monkeypatch, url)
        _set_keys(monkeypatch)

        assert check_clearml_configuration() is False
        thread.join(5)

    assert len(capture_logs) == 1
    assert capture_logs[0].startswith(f"ClearML: сервер недоступен — {url}: ")
    _assert_no_secret(capture_logs[0])


@pytest.mark.usefixtures("no_clearml_configuration")
def test_refused_connection_is_unreachable(monkeypatch: pytest.MonkeyPatch, capture_logs: list[str]) -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        url = f"http://127.0.0.1:{probe.getsockname()[1]}"
    _point_at(monkeypatch, url)
    _set_keys(monkeypatch)

    assert check_clearml_configuration() is False

    assert len(capture_logs) == 1
    assert capture_logs[0].startswith(f"ClearML: сервер недоступен — {url}: ConnectionRefusedError")
    _assert_no_secret(capture_logs[0])


@pytest.mark.usefixtures("no_clearml_configuration")
def test_server_that_never_answers_hits_the_time_limit(
    monkeypatch: pytest.MonkeyPatch, capture_logs: list[str]
) -> None:
    monkeypatch.setattr(diagnostics, "_TIMEOUT_SECONDS", 0.3)
    with socket.socket() as silent:
        silent.bind(("127.0.0.1", 0))
        silent.listen(1)  # accepted by the kernel, never answered
        url = f"http://127.0.0.1:{silent.getsockname()[1]}"
        _point_at(monkeypatch, url)
        _set_keys(monkeypatch)

        assert check_clearml_configuration() is False

    assert capture_logs == [f"ClearML: сервер недоступен — {url}: нет ответа за 0.3 с."]
