"""Bounded request diagnostics and per-request SDK retry overrides.

Only this boundary reads HTTP data. Operation context is scoped to a call;
request context is scoped to one REST invocation and attached to its exception.
No response or failed-request context is retained globally between calls.
"""

import functools
import inspect
import json
import re
import threading
from collections.abc import Callable, Mapping
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from http.cookies import CookieError, SimpleCookie
from itertools import pairwise
from typing import ParamSpec, TypeVar, cast
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import urllib3
from cvat_sdk.api_client.exceptions import ApiException
from urllib3.util import Retry

from cveta2.domain.errors import CvatApiError, CvatRequestDiagnostics

_P = ParamSpec("_P")
_R = TypeVar("_R")
_SUMMARY_LIMIT = 512
_ENDPOINT_LIMIT = 1024
_HEADER_LIMIT = 128
_BODY_LIMIT = 4096
_RESOURCE_NAMES = frozenset(
    {"project_id", "task_id", "job_id", "issue_id", "cloud_storage_id", "org_id"}
)
_QUERY_NAMES = _RESOURCE_NAMES | {"page", "page_size"}
_SECRET_NAMES = frozenset(
    {
        "username",
        "password",
        "passwd",
        "secret",
        "token",
        "api_key",
        "access_token",
        "refresh_token",
    }
)
_REQUEST_HEADERS = {
    "x-request-id": "X-Request-Id",
    "x-correlation-id": "X-Correlation-Id",
    "traceparent": "Traceparent",
}
_SECRET_HEADERS = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "x-api-key",
        "api-key",
        "x-auth-token",
        "x-access-token",
        "x-csrftoken",
        "x-csrf-token",
    }
)
_PATH_RESOURCES = {
    "projects": "project_id",
    "tasks": "task_id",
    "jobs": "job_id",
    "issues": "issue_id",
    "cloudstorages": "cloud_storage_id",
    "organizations": "org_id",
}
_CREDENTIAL = re.compile(
    r"(?i)\b(password|passwd|secret|token|api[_-]?key|authorization|cookie|"
    r"access[_-]?token|refresh[_-]?token)\b[\"']?\s*[:=]\s*"
    r"(?:\"[^\"]*\"|'[^']*'|[^\s,;}]+)"
)
_AUTH = re.compile(r"(?i)\b(bearer|basic|token)\s+[a-z0-9._~+/=-]+")
_URL = re.compile(r"https?://[^\s<>\"']+")
_POOL_LOCK = threading.Lock()


@dataclass(frozen=True)
class _Operation:
    name: str
    resource_ids: tuple[tuple[str, int], ...]


_OPERATION: ContextVar[_Operation | None] = ContextVar(
    "cveta2_cvat_operation", default=None
)
_REQUEST_FAILURE: ContextVar[CvatRequestDiagnostics | None] = ContextVar(
    "cveta2_cvat_request_failure", default=None
)
_REQUEST_ACTIVE: ContextVar[bool] = ContextVar(
    "cveta2_cvat_request_active", default=False
)


def operation_context(func: Callable[_P, _R]) -> Callable[_P, _R]:
    """Scope an operation name and its typed resource arguments to this call."""
    signature = inspect.signature(func)

    @functools.wraps(func)
    def wrapped(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        values = signature.bind(*args, **kwargs).arguments
        ids = tuple(
            (name, value)
            for name, value in values.items()
            if name in _RESOURCE_NAMES and isinstance(value, int)
        )
        token = _OPERATION.set(_Operation(func.__name__, ids))
        try:
            return func(*args, **kwargs)
        finally:
            _OPERATION.reset(token)

    return wrapped


def _query_items(url: str, fields: object) -> list[tuple[str, str]]:
    query: list[tuple[str, str]] = parse_qsl(urlsplit(url).query)
    if isinstance(fields, Mapping):
        query.extend((str(key), str(value)) for key, value in fields.items())
    elif isinstance(fields, (list, tuple)):
        query.extend(
            (str(item[0]), str(item[1]))
            for item in fields
            if isinstance(item, (list, tuple)) and len(item) == 2  # noqa: PLR2004
        )
    return query


def _safe_endpoint(url: str, fields: object = None) -> str:
    parts = urlsplit(url)
    # Keep the network location, never URL credentials or fragments. Query
    # values are restricted to numeric pagination/resource identifiers.
    authority = parts.netloc.rsplit("@", 1)[-1]
    allowed = [
        (key, value)
        for key, value in _query_items(url, fields)
        if key in _QUERY_NAMES and value.isdecimal()
    ]
    path = re.sub(r"[\x00-\x20\x7f]", "", parts.path)
    return urlunsplit((parts.scheme, authority, path, urlencode(allowed), ""))[
        :_ENDPOINT_LIMIT
    ]


def _safe_text(
    value: str, limit: int = _SUMMARY_LIMIT, *, secrets: tuple[str, ...] = ()
) -> str:
    value = _URL.sub(lambda match: _safe_endpoint(match.group()), value)
    value = _AUTH.sub(r"\1 [redacted]", value)
    value = _CREDENTIAL.sub(r"\1=[redacted]", value)
    value = re.sub(r"(?i)\b(?:set-cookie|cookie)\s*[:=].*", "cookie=[redacted]", value)
    for secret in secrets:
        value = value.replace(secret, "[redacted]")
    return " ".join(value.split())[:limit]


def _response_summary(
    data: object, content_type: str, secrets: tuple[str, ...] = ()
) -> str:
    if not isinstance(data, (str, bytes)):
        return ""
    sample = data[:_BODY_LIMIT]
    text = (
        sample.decode("utf-8", errors="replace")
        if isinstance(sample, bytes)
        else sample
    )
    if "html" in content_type.lower() or re.search(r"(?i)</?[a-z!][^>]*>", text):
        return "HTML-ответ скрыт"
    if "json" in content_type.lower():
        try:
            payload = json.loads(text)
        except (ValueError, TypeError):
            return "JSON-ответ скрыт: неполный или некорректный"
        # Error messages are useful; unrelated payload fields can contain
        # credentials or private data and are never copied into diagnostics.
        if isinstance(payload, dict):
            messages = [
                f"{key}: {_safe_text(value, secrets=secrets)}"
                for key in ("detail", "message", "error")
                if isinstance(value := payload.get(key), str)
            ]
            return "; ".join(messages)[:_SUMMARY_LIMIT]
        return "JSON-ответ без краткого сообщения об ошибке"
    return _safe_text(text, secrets=secrets)


def _request_secrets(url: str, request: Mapping[str, object]) -> tuple[str, ...]:
    """Redact known request credentials even when an error echoes them unlabeled."""
    parts = urlsplit(url)
    values = [parts.username, parts.password]
    values.extend(
        value
        for name, value in _query_items(url, request.get("fields"))
        if name not in _QUERY_NAMES or not value.isdecimal()
    )
    values.extend(_header_secrets(request.get("headers")))
    body = request.get("body")
    if isinstance(body, (str, bytes)) and len(body) <= _BODY_LIMIT:
        try:
            payload = json.loads(body)
        except (ValueError, TypeError):
            payload = None
        if isinstance(payload, dict):
            values.extend(
                value
                for key, value in payload.items()
                if key.lower() in _SECRET_NAMES and isinstance(value, str)
            )
    return tuple(sorted({value for value in values if value}, key=len, reverse=True))


def _header_secrets(headers: object) -> list[str]:
    if not isinstance(headers, Mapping):
        return []
    values: list[str] = []
    for name, value in headers.items():
        if not isinstance(value, str):
            continue
        header = str(name).lower()
        if header in _SECRET_HEADERS:
            values.extend((value, value.rsplit(" ", 1)[-1]))
        elif header == "cookie":
            values.append(value)
            # Component fallback also handles malformed cookies rejected by
            # SimpleCookie. These transient values never enter diagnostics.
            values.extend(
                component.partition("=")[2].strip().strip('"')
                for component in value.split(";")
            )
            cookie = SimpleCookie()
            try:
                cookie.load(value)
            except CookieError:
                continue
            values.extend(morsel.value for morsel in cookie.values())
    return values


def _resource_ids(endpoint: str) -> tuple[tuple[str, int], ...]:
    operation = _OPERATION.get()
    ids = dict(operation.resource_ids) if operation else {}
    parts = urlsplit(endpoint)
    segments = parts.path.split("/")
    for kind, value in pairwise(segments):
        if kind in _PATH_RESOURCES and value.isdecimal():
            ids[_PATH_RESOURCES[kind]] = int(value)
    ids.update(
        (key, int(value))
        for key, value in parse_qsl(parts.query)
        if key in _RESOURCE_NAMES and value.isdecimal()
    )
    return tuple(sorted(ids.items()))


def _capture(
    method: str,
    url: str,
    request: Mapping[str, object],
    response: urllib3.BaseHTTPResponse | None,
) -> CvatRequestDiagnostics:
    endpoint = _safe_endpoint(
        url, request.get("fields") if method in {"GET", "HEAD"} else None
    )
    secrets = _request_secrets(url, request)
    status = 0
    request_ids: tuple[tuple[str, str], ...] = ()
    summary = ""
    if response is not None:
        status = response.status
        # geturl reflects the final URL after redirects when urllib3 supplies it.
        final_url = response.geturl()
        if final_url:
            endpoint = _safe_endpoint(urljoin(url, final_url))
        request_ids = tuple(
            (canonical, _safe_text(value, _HEADER_LIMIT, secrets=secrets))
            for name, canonical in _REQUEST_HEADERS.items()
            if (value := response.headers.get(name))
        )
        # Reading .data can consume an unbounded streaming response. SDK REST
        # errors normally preload; otherwise omit the body instead of reading it.
        data = response._body if isinstance(response, urllib3.HTTPResponse) else None  # noqa: SLF001
        summary = _response_summary(
            data, response.headers.get("Content-Type", ""), secrets
        )
    operation = _OPERATION.get()
    return CvatRequestDiagnostics(
        operation=operation.name if operation else "cvat_request",
        method=method,
        endpoint=endpoint,
        resource_ids=_resource_ids(endpoint),
        timestamp_utc=datetime.now(UTC),
        status_code=status,
        request_ids=request_ids,
        response_summary=summary,
    )


def format_diagnostics(diagnostic: CvatRequestDiagnostics) -> str:
    """Render bounded Russian failure context and an evidence-aware next step."""
    ids = ", ".join(f"{key}={value}" for key, value in diagnostic.request_ids)
    resources = ", ".join(f"{key}={value}" for key, value in diagnostic.resource_ids)
    context = (
        f"CVAT: операция {diagnostic.operation}, {diagnostic.method} "
        f"{diagnostic.endpoint}; HTTP {diagnostic.status_code or 'неизвестен'}; "
        f"UTC {diagnostic.timestamp_utc.isoformat()}"
    )
    if resources:
        context += f"; {resources}"
    if ids:
        context += f"; {ids}"
    if diagnostic.response_summary:
        context += f"; {diagnostic.response_summary}"
    if diagnostic.status_code in {502, 503, 504}:
        return context + (
            ". Проверьте proxy/ingress и доступность backend; "
            "источник сбоя по одному статусу не установлен."
        )
    return context + ". Проверьте логи backend CVAT по времени и ID запроса."


def exception_diagnostics(error: BaseException) -> CvatRequestDiagnostics | None:
    """Read only the neutral value attached at the opaque SDK boundary."""
    if isinstance(error, CvatApiError):
        return error.diagnostics
    value = getattr(error, "_cveta2_diagnostics", None)
    return value if isinstance(value, CvatRequestDiagnostics) else None


def describe_error(error: BaseException) -> str:
    """Keep retry warnings safe even before transport errors are translated."""
    diagnostic = exception_diagnostics(error)
    if diagnostic is not None:
        return format_diagnostics(diagnostic)
    if isinstance(error, ApiException):
        # Generated exception strings include raw headers and bodies.
        return f"CVAT HTTP {error.status or 0}: {_safe_text(str(error.reason or ''))}"
    return _safe_text(str(error))


class _DiagnosticApiException(ApiException):  # type: ignore[misc]
    """SDK-compatible error whose string is safe for its version-check logger."""

    def __init__(self, error: ApiException, diagnostic: CvatRequestDiagnostics) -> None:
        super().__init__(status=error.status, reason=error.reason)
        self.headers = error.headers
        self.body = error.body
        self._cveta2_diagnostics = diagnostic

    def __str__(self) -> str:
        return format_diagnostics(self._cveta2_diagnostics)


def install_pool_capture(manager: urllib3.PoolManager) -> None:
    """Wrap this manager once; request-local retry copies leave pools untouched."""
    with _POOL_LOCK:
        original = manager.request
        # PoolManager has a Python instance dictionary. Mark the function rather
        # than the pool policy; no per-call global settings are changed.
        if getattr(original, "_cveta2_capture", False):
            return

        # SDK callers forward different urllib3 keyword shapes. Preserve that
        # opaque call signature while retaining a concrete response type.
        forward = cast("Callable[..., urllib3.BaseHTTPResponse]", original)

        @functools.wraps(original)
        def request(
            method: str, url: str, *args: object, **kwargs: object
        ) -> urllib3.BaseHTTPResponse:
            pool = manager.connection_from_url(url)
            supplied = cast("Retry | bool | int | None", kwargs.get("retries"))
            policy = Retry.from_int(supplied, default=pool.retries)
            kwargs["retries"] = policy.new(raise_on_status=False)
            try:
                response = forward(method, url, *args, **kwargs)
            except (OSError, urllib3.exceptions.HTTPError):
                if _REQUEST_ACTIVE.get():
                    _REQUEST_FAILURE.set(_capture(method, url, kwargs, None))
                raise
            if _REQUEST_ACTIVE.get() and not 200 <= response.status < 300:  # noqa: PLR2004
                _REQUEST_FAILURE.set(_capture(method, url, kwargs, response))
            return response

        request._cveta2_capture = True  # type: ignore[attr-defined]  # noqa: SLF001
        manager.request = request  # type: ignore[method-assign]


def capture_rest_call(func: Callable[[], _R]) -> _R:
    """Attach diagnostics to this REST failure and always clear request context."""
    token = _REQUEST_FAILURE.set(None)
    active_token = _REQUEST_ACTIVE.set(True)
    try:
        return func()
    except ApiException as error:
        diagnostic = _REQUEST_FAILURE.get()
        if diagnostic is not None:
            raise _DiagnosticApiException(error, diagnostic) from error
        raise
    except (OSError, urllib3.exceptions.HTTPError) as error:
        diagnostic = _REQUEST_FAILURE.get()
        if diagnostic is not None:
            error._cveta2_diagnostics = diagnostic  # type: ignore[union-attr]  # noqa: SLF001
        raise
    finally:
        _REQUEST_FAILURE.reset(token)
        _REQUEST_ACTIVE.reset(active_token)
