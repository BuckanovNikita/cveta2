"""ClearML configuration inspection for ``cveta2 doctor``; the SDK is imported lazily.

The settings are resolved offline the way the SDK resolves them. The credentials are
then verified with one bounded login request. The SDK session is not used for that:
its login retries 240 times with backoff and can wait forever on server maintenance.
"""

import base64
import http.client
import json
import ssl
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from importlib import import_module
from pathlib import Path
from typing import override

from loguru import logger

from cveta2.domain.errors import Cveta2Error

_TIMEOUT_SECONDS = 10.0
"""Total time limit of the login request, name resolution included."""

_MAX_RESPONSE_BYTES = 1 << 20

_FIX = (
    "Создайте файл конфигурации ClearML (~/clearml.conf или путь в CLEARML_CONFIG_FILE) "
    "или задайте переменные CLEARML_API_HOST, CLEARML_API_ACCESS_KEY и CLEARML_API_SECRET_KEY."
)


@dataclass(frozen=True)
class _Settings:
    """Resolved ClearML settings; the authorization header never reaches a log line."""

    host: str
    host_note: str
    files_host: str
    sources: str
    method: str
    uses_token: bool
    verify: object
    authorization: str = field(repr=False)


def _config_files() -> list[str]:
    """Return the existing configuration files the SDK merges, in its own order.

    A set ``CLEARML_CONFIG_FILE`` replaces the home-directory files even when the
    file it names does not exist, exactly as ``Config._reload`` does.
    """
    from clearml.backend_config.defs import (  # noqa: PLC0415 - the SDK stays lazy
        LOCAL_CONFIG_FILE_OVERRIDE_VAR,
        LOCAL_CONFIG_FILES,
    )

    override = LOCAL_CONFIG_FILE_OVERRIDE_VAR.get()
    candidates = [Path(override).expanduser()] if override else [Path(item) for item in LOCAL_CONFIG_FILES]
    return [str(path) for path in candidates if path.is_file()]


def _resolve() -> _Settings | None:
    """Resolve credentials and the API, web and files hosts as the SDK does.

    The SDK derives the web and files hosts from an ``api.*`` or ``:8008`` API host
    only; otherwise an upload fails, so a host it cannot derive is a missing setting.
    Returns ``None`` after one warning when something is missing. Never logs a key.
    """
    from clearml.backend_api import Session, load_config  # noqa: PLC0415 - the SDK stays lazy
    from clearml.backend_api.session.defs import (  # noqa: PLC0415 - the SDK stays lazy
        ENV_ACCESS_KEY,
        ENV_API_DEFAULT_REQ_METHOD,
        ENV_AUTH_TOKEN,
        ENV_FILES_HOST,
        ENV_HOST,
        ENV_HOST_VERIFY_CERT,
        ENV_SECRET_KEY,
        ENV_WEB_HOST,
    )

    files = _config_files()
    # A fresh configuration, not the SDK's process-wide one, so the files are read now.
    config = load_config()
    # The SDK's own session passes its Config to these helpers although they are annotated ConfigTree.
    host = Session.get_api_server_host(config=config)  # type: ignore[arg-type]
    token = ENV_AUTH_TOKEN.get()
    access_key = ENV_ACCESS_KEY.get(default=config.get("api.credentials.access_key", None) or Session.default_key)
    secret_key = ENV_SECRET_KEY.get(default=config.get("api.credentials.secret_key", None) or Session.default_secret)

    missing: list[str] = []
    fixes: list[str] = []
    if not token and not (access_key and secret_key):
        if not access_key:
            missing.append("ключ доступа (CLEARML_API_ACCESS_KEY или api.credentials.access_key)")
        if not secret_key:
            missing.append("секретный ключ (CLEARML_API_SECRET_KEY или api.credentials.secret_key)")
        fixes.append(_FIX)
    missing_credentials = len(missing)
    try:
        Session.get_app_server_host(config=config)  # type: ignore[arg-type]
    except ValueError:
        missing.append("адрес веб-приложения (CLEARML_WEB_HOST или api.web_server)")
    files_host = None
    try:
        files_host = Session.get_files_server_host(config=config)  # type: ignore[arg-type]
    except ValueError:
        missing.append("адрес сервера файлов (CLEARML_FILES_HOST или api.files_server)")
    if len(missing) > missing_credentials:
        fixes.append(
            f"ClearML SDK выводит эти адреса только из адреса сервера API вида api.<домен> или с портом 8008, "
            f"а адрес {host} не такой: задайте их явно."
        )
    if missing or files_host is None:
        logger.warning(f"ClearML: не настроен — не найдены: {', '.join(missing)}. {' '.join(fixes)}")
        return None

    sources = [f"файл {path}" for path in files]
    environment = (ENV_HOST, ENV_WEB_HOST, ENV_FILES_HOST, ENV_ACCESS_KEY, ENV_SECRET_KEY, ENV_AUTH_TOKEN)
    if any(entry.get() for entry in environment):
        sources.append("переменные окружения")
    configured_host = ENV_HOST.get() or config.get("api.api_server", None) or config.get("api.host", None)
    # Session._send_request uses Request.def_method; Session._update_default_api_method lets the file override it.
    method = ENV_API_DEFAULT_REQ_METHOD.get(default=None) or config.get("api.http.default_method", None) or "get"
    if token:
        authorization = f"Bearer {token}"
    else:
        authorization = "Basic " + base64.b64encode(f"{access_key}:{secret_key}".encode()).decode("ascii")
    return _Settings(
        host=host,
        host_note="" if configured_host else " (адрес SDK по умолчанию)",
        files_host=files_host,
        sources=", ".join(sources),
        method=str(method).strip().upper(),
        uses_token=bool(token),
        verify=ENV_HOST_VERIFY_CERT.get(default=config.get("api.verify_certificate", True)),
        authorization=authorization,
    )


def _default_ca_file() -> str | None:
    """Return certifi's CA bundle, the only default of the SDK's ``requests``; ``None`` without certifi.

    certifi is a transitive dependency (through the SDK's ``requests``), so it is imported
    by name: deptry treats a static import of an undeclared transitive package as an error.
    """
    try:
        certifi = import_module("certifi")
    except ImportError:
        return None
    return str(certifi.where())


def _ssl_context(verify: object) -> ssl.SSLContext:
    """Build the TLS context the SDK's HTTP session would use for *verify*.

    Like ``get_http_session_with_retry``, a boolean-like string switches verification on
    or off, and any other string is handed on as a CA bundle path. Without a CA file the
    certificates are checked against certifi's bundle, as ``requests`` does, or against
    the system store when certifi is missing.
    """
    if isinstance(verify, str):
        from clearml.backend_config.converters import strtobool  # noqa: PLC0415 - the SDK stays lazy

        try:
            enabled = bool(strtobool(verify))
        except ValueError:
            return ssl.create_default_context(cafile=verify)
    else:
        enabled = bool(verify)
    context = ssl.create_default_context(cafile=_default_ca_file() if enabled else None)
    if not enabled:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    return context


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Keep the authorization header on the configured host: a redirect is reported, not followed."""

    @override
    def redirect_request(self, *_args: object, **_kwargs: object) -> None:
        return None


def _request_login(request: urllib.request.Request, context: ssl.SSLContext) -> tuple[int, bytes]:
    """Send *request* once and return the HTTP status and body.

    The socket timeout bounds each blocking step; the worker thread bounds the whole
    request, name resolution included, to ``_TIMEOUT_SECONDS``.
    """
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=context), _NoRedirect)
    outcome: list[tuple[int, bytes] | BaseException] = []

    def send() -> None:
        try:
            with opener.open(request, timeout=_TIMEOUT_SECONDS) as response:
                outcome.append((response.status, response.read(_MAX_RESPONSE_BYTES)))
        except urllib.error.HTTPError as error:
            with error:
                outcome.append((error.code, error.read(_MAX_RESPONSE_BYTES)))
        except Exception as error:  # noqa: BLE001 - the caller classifies every failure.
            outcome.append(error)

    worker = threading.Thread(target=send, name="clearml-login-check", daemon=True)
    worker.start()
    worker.join(_TIMEOUT_SECONDS)
    if not outcome:
        raise TimeoutError
    result = outcome[0]
    if isinstance(result, BaseException):
        raise result
    return result


def _has_token(body: bytes) -> bool:
    try:
        data = json.loads(body).get("data")
    except (ValueError, AttributeError):
        return False
    return isinstance(data, dict) and isinstance(data.get("token"), str)


def _network_reason(error: OSError | ValueError | http.client.HTTPException) -> str:
    """Describe a failed request without the request itself, which carries the credentials."""
    reason: object = error.reason if isinstance(error, urllib.error.URLError) else error
    if isinstance(reason, TimeoutError):
        return f"нет ответа за {_TIMEOUT_SECONDS:g} с"
    return f"{type(reason).__name__}: {reason}"


def _status_problem(settings: _Settings, status: int, body: bytes) -> str | None:
    """Return the warning for a login answer, or ``None`` when the server issued a token."""
    unreachable = f"ClearML: сервер недоступен — {settings.host}"
    problem = None
    if status in {401, 403}:
        what = "токен CLEARML_AUTH_TOKEN" if settings.uses_token else "ключ доступа и секретный ключ"
        problem = (
            f"ClearML: ключи отклонены — сервер API {settings.host} ответил HTTP {status}. "
            f"Проверьте {what} (источник: {settings.sources})."
        )
    elif 300 <= status < 400:  # noqa: PLR2004 - the HTTP redirect range.
        problem = f"{unreachable}: перенаправление HTTP {status} не выполняется, проверьте адрес сервера API."
    elif status != 200:  # noqa: PLR2004 - the login success status.
        problem = f"{unreachable}: HTTP {status}."
    elif not _has_token(body):
        problem = f"{unreachable}: ответ не похож на ответ сервера API ClearML, проверьте адрес."
    return problem


def _login_problem(settings: _Settings) -> str | None:
    """Log in once, as ``Session._do_refresh_token`` does; return the warning, if any."""
    if not settings.host.startswith(("http://", "https://")):
        return (
            f"ClearML: сервер недоступен — {settings.host}: адрес сервера API должен начинаться с http:// или https://."
        )
    request = urllib.request.Request(  # noqa: S310 - the scheme is checked above.
        f"{settings.host}/auth.login",
        method=settings.method,
        headers={"Authorization": settings.authorization},
    )
    try:
        status, body = _request_login(request, _ssl_context(settings.verify))
    except (OSError, ValueError, http.client.HTTPException) as error:  # HTTPException: a non-HTTP answer.
        return f"ClearML: сервер недоступен — {settings.host}: {_network_reason(error)}."
    return _status_problem(settings, status, body)


def _verify(settings: _Settings) -> bool:
    """Verify the credentials against the server and log one result line."""
    problem = _login_problem(settings)
    if problem is not None:
        logger.warning(problem)
        return False
    logger.info(
        f"ClearML: проверено — вход на сервер API {settings.host}{settings.host_note} выполнен; "
        f"сервер файлов {settings.files_host}, источник: {settings.sources}"
    )
    return True


def check_clearml_configuration() -> bool:
    """Report whether ClearML is configured and the server accepts the credentials.

    The SDK's parser fails with many unrelated exception types (``ConfigurationError``,
    pyhocon errors, ``UnicodeDecodeError`` for a binary file), so every failure while
    resolving the settings is translated here. The error names the files and the error
    class only: the parser message can quote the file, and the file holds the secret key.
    """
    logger.info("doctor: checking ClearML configuration …")
    try:
        settings = _resolve()
    except Exception as error:  # the adapter boundary translates any SDK failure
        files = ", ".join(_config_files())
        raise Cveta2Error(f"ClearML: файл конфигурации не читается ({files}): {type(error).__name__}") from error
    return settings is not None and _verify(settings)
