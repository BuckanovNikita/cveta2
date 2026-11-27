"""ClearML configuration inspection for ``cveta2 doctor``; the SDK is imported lazily.

The settings are resolved offline the way the SDK resolves them. The credentials are
then verified with one bounded login request sent through ``requests``, the HTTP stack
of the SDK, so certificates, ``REQUESTS_CA_BUNDLE`` and proxies behave as in the SDK.
The SDK session itself is not used: its login retries 240 times with backoff and can
wait forever on server maintenance.
"""

import json
import threading
import warnings
from dataclasses import dataclass, field
from http import HTTPStatus
from pathlib import Path

from loguru import logger

from cveta2.domain.errors import Cveta2Error

_TIMEOUT_SECONDS = 10.0
"""Time limit of the login request: requests' connect and read timeouts, and the whole exchange."""

_MAX_RESPONSE_BYTES = 1 << 20

_FIX = (
    "Создайте файл конфигурации ClearML (~/clearml.conf или путь в CLEARML_CONFIG_FILE) "
    "или задайте переменные CLEARML_API_HOST, CLEARML_API_ACCESS_KEY и CLEARML_API_SECRET_KEY."
)


@dataclass(frozen=True)
class _Settings:
    """Resolved ClearML settings; the credentials never reach a log line."""

    host: str
    host_note: str
    files_host: str
    sources: str
    method: str
    uses_token: bool
    verify: bool | str | None
    """requests' ``verify`` when the SDK setting is explicit; ``None`` keeps requests' default."""
    keys: tuple[str, str] | None = field(repr=False)
    """Access and secret key, sent as HTTP Basic auth like ``Session._do_refresh_token``."""
    token: str | None = field(repr=False)
    """``CLEARML_AUTH_TOKEN``, sent as a Bearer token instead of the keys."""


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
    files_host, missing_hosts = _derived_hosts(config)
    missing.extend(missing_hosts)
    if missing_hosts:
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
    if malformed := _malformed_credentials(token, access_key, secret_key):
        logger.warning(
            f"ClearML: ключи некорректны — {malformed}: есть пробелы, переводы строк или символы не из ASCII. "
            f"Задайте значение заново (источник: {', '.join(sources)})."
        )
        return None
    configured_host = ENV_HOST.get() or config.get("api.api_server", None) or config.get("api.host", None)
    # Session._send_request uses Request.def_method; Session._update_default_api_method lets the file override it.
    method = ENV_API_DEFAULT_REQ_METHOD.get(default=None) or config.get("api.http.default_method", None) or "get"
    return _Settings(
        host=host,
        host_note="" if configured_host else " (адрес SDK по умолчанию)",
        files_host=files_host,
        sources=", ".join(sources),
        method=str(method).strip().upper(),
        uses_token=bool(token),
        verify=_verify_argument(ENV_HOST_VERIFY_CERT.get(default=config.get("api.verify_certificate", True))),
        keys=None if token else (str(access_key), str(secret_key)),
        token=token or None,
    )


def _derived_hosts(config: object) -> tuple[str | None, list[str]]:
    """Return the files host and the hosts the SDK cannot derive from *config*.

    The SDK derives the web and files hosts from an ``api.*`` or ``:8008`` API host only.
    """
    from clearml.backend_api import Session  # noqa: PLC0415 - the SDK stays lazy

    missing: list[str] = []
    try:
        # The SDK's own session passes its Config to these helpers although they are annotated ConfigTree.
        Session.get_app_server_host(config=config)  # type: ignore[arg-type]
    except ValueError:
        missing.append("адрес веб-приложения (CLEARML_WEB_HOST или api.web_server)")
    files_host = None
    try:
        files_host = Session.get_files_server_host(config=config)  # type: ignore[arg-type]
    except ValueError:
        missing.append("адрес сервера файлов (CLEARML_FILES_HOST или api.files_server)")
    return files_host, missing


def _malformed_credentials(token: str | None, access_key: str | None, secret_key: str | None) -> str:
    """Name the credentials that cannot travel in an HTTP header, without their values.

    requests refuses such a header with an error that quotes it, so they are caught here.
    """

    def malformed(value: str | None) -> bool:
        return value is not None and not all("!" <= character <= "~" for character in value)

    if token:
        return "CLEARML_AUTH_TOKEN" if malformed(token) else ""
    names = [name for name, value in (("ключ доступа", access_key), ("секретный ключ", secret_key)) if malformed(value)]
    return ", ".join(names)


def _verify_argument(setting: object) -> bool | str | None:
    """Translate the SDK's TLS setting into requests' ``verify``.

    As in ``get_http_session_with_retry`` (``clearml/backend_api/utils.py``), a boolean-like
    string switches verification on or off and any other string is a CA bundle path. Only
    an explicit choice is passed on: verification on returns ``None``, which leaves requests
    its default (certifi, or ``REQUESTS_CA_BUNDLE`` / ``CURL_CA_BUNDLE``).
    """
    if isinstance(setting, str):
        from clearml.backend_config.converters import strtobool  # noqa: PLC0415 - the SDK stays lazy

        try:
            setting = bool(strtobool(setting))
        except ValueError:
            return setting
    return None if setting else False


def _request_login(settings: _Settings) -> tuple[int, bytes]:
    """Send one login request and return the HTTP status and at most ``_MAX_RESPONSE_BYTES`` of body.

    A plain ``requests.request`` has no retrying adapter and follows no redirect, so the
    credentials never leave the configured host. They always go through ``auth=``: without
    it requests would take ``~/.netrc`` credentials for the host and replace the header.
    requests' timeout bounds the connection and each read separately, not name resolution
    or the whole answer; the worker thread bounds those to ``_TIMEOUT_SECONDS`` as well.
    """
    import requests  # noqa: PLC0415 - imported lazily, like the SDK

    token = settings.token

    def bearer(request: requests.PreparedRequest) -> requests.PreparedRequest:
        request.headers["Authorization"] = f"Bearer {token}"
        return request

    outcome: list[tuple[int, bytes] | BaseException] = []

    def send() -> None:
        try:
            with requests.request(
                settings.method,
                f"{settings.host}/auth.login",
                auth=settings.keys if settings.keys is not None else bearer,
                timeout=(_TIMEOUT_SECONDS, _TIMEOUT_SECONDS),
                allow_redirects=False,
                stream=True,
                verify=settings.verify,
            ) as response:
                body = b""
                for chunk in response.iter_content(64 * 1024):
                    body += chunk
                    if len(body) >= _MAX_RESPONSE_BYTES:
                        break
                outcome.append((response.status_code, body))
        except Exception as error:  # noqa: BLE001 - the caller classifies every failure.
            outcome.append(error)

    worker = threading.Thread(target=send, name="clearml-login-check", daemon=True)
    with warnings.catch_warnings():
        # Verification off is the user's explicit SDK setting; the SDK silences this warning too.
        warnings.filterwarnings("ignore", message="Unverified HTTPS request")
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


def _root_cause(error: BaseException) -> BaseException:
    """Follow requests' and urllib3's wrapping down to the error that started the failure."""
    seen: set[int] = set()
    while id(error) not in seen:
        seen.add(id(error))
        reason = getattr(error, "reason", None)
        following = reason if isinstance(reason, BaseException) else error.__cause__ or error.__context__
        if following is None:
            break
        error = following
    return error


def _network_reason(error: Exception) -> str:
    """Name a failed request by the class of its root error only.

    Exception messages are never printed: requests quotes the request in some of them,
    for example the Authorization header in ``InvalidHeader``.
    """
    import requests  # noqa: PLC0415 - imported lazily, like the SDK

    if isinstance(error, requests.Timeout | TimeoutError):
        return f"нет ответа за {_TIMEOUT_SECONDS:g} с"
    return type(_root_cause(error)).__name__


def _status_problem(settings: _Settings, status: int, body: bytes) -> str | None:
    """Return the warning for a login answer, or ``None`` when the server issued a token."""
    unreachable = f"ClearML: сервер недоступен — {settings.host}"
    problem = None
    if status in {HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN}:
        what = "токен CLEARML_AUTH_TOKEN" if settings.uses_token else "ключ доступа и секретный ключ"
        problem = (
            f"ClearML: ключи отклонены — сервер API {settings.host} ответил HTTP {status}. "
            f"Проверьте {what} (источник: {settings.sources})."
        )
    elif HTTPStatus.MULTIPLE_CHOICES <= status < HTTPStatus.BAD_REQUEST:
        problem = f"{unreachable}: перенаправление HTTP {status} не выполняется, проверьте адрес сервера API."
    elif status != HTTPStatus.OK:
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
    try:
        status, body = _request_login(settings)
    except Exception as error:  # noqa: BLE001 - every failure to get an answer is a warning, by class only.
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
