"""ClearML configuration inspection for ``cveta2 doctor``; the SDK is imported lazily.

The settings are resolved offline the way the SDK resolves them. The credentials are
then verified with one bounded login request sent through ``requests``, the HTTP stack
of the SDK, so certificates, ``REQUESTS_CA_BUNDLE`` and proxies behave as in the SDK.
The SDK session itself is not used: its login retries 240 times with backoff and can
wait forever on server maintenance.
"""

import base64
import json
import threading
import warnings
from dataclasses import dataclass, field
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
    """Resolved ClearML settings; the authorization header never reaches a log line."""

    host: str
    host_note: str
    files_host: str
    sources: str
    method: str
    uses_token: bool
    verify: bool | str | None
    """requests' ``verify`` when the SDK setting is explicit; ``None`` keeps requests' default."""
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
        verify=_verify_argument(ENV_HOST_VERIFY_CERT.get(default=config.get("api.verify_certificate", True))),
        authorization=authorization,
    )


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
    authorization header never leaves the configured host. requests' timeout bounds the
    connection and each read separately, not name resolution or the whole answer; the
    worker thread bounds those to ``_TIMEOUT_SECONDS`` as well.
    """
    import requests  # noqa: PLC0415 - imported lazily, like the SDK

    outcome: list[tuple[int, bytes] | BaseException] = []

    def send() -> None:
        try:
            with requests.request(
                settings.method,
                f"{settings.host}/auth.login",
                headers={"Authorization": settings.authorization},
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
    """Describe a failed request without the request itself, which carries the credentials."""
    import requests  # noqa: PLC0415 - imported lazily, like the SDK

    if isinstance(error, requests.Timeout | TimeoutError):
        return f"нет ответа за {_TIMEOUT_SECONDS:g} с"
    root = _root_cause(error)
    return f"{type(root).__name__}: {root}"


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
    try:
        status, body = _request_login(settings)
    except (OSError, ValueError) as error:  # requests' errors are OSError; TimeoutError is the deadline.
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
