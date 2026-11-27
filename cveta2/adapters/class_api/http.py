"""Network effects for the opt-in upload workflow; importing this module is offline."""

import json
from http.client import HTTPException, HTTPMessage
from typing import IO, override
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from pydantic import TypeAdapter, ValidationError

from cveta2.domain.bundle.models import (
    ApiClass,
    UploadError,
)

_INVALID = "Class API must return a JSON list of valid class definitions"
_SHOWN_PLACES = 5


def _public_http(url: str) -> None:
    try:
        parsed = urlsplit(url)
        valid = parsed.scheme in {"http", "https"} and parsed.hostname
        credentials = parsed.username is not None or parsed.password is not None
    except ValueError as exc:
        raise UploadError("Class API URL is malformed") from exc
    if not valid or credentials:
        raise UploadError("Class API requires an HTTP(S) URL without embedded credentials")


class _PublicRedirect(HTTPRedirectHandler):
    @override
    def redirect_request(
        self,
        req: Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> Request | None:
        _public_http(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class HttpClassApi:
    """Unauthenticated HTTP registry requests, with strict response validation."""

    def __init__(self, timeout: float = 30.0) -> None:
        """Set a finite request timeout."""
        if timeout <= 0:
            raise ValueError("HTTP timeout must be positive")
        self.timeout = timeout

    def fetch(self, url: str) -> list[ApiClass]:
        """Fetch strict public class records without authentication."""
        _public_http(url)
        # The initial URL and all redirect targets are checked above.
        request = Request(  # noqa: S310
            url, headers={"Accept": "application/json"}, method="GET"
        )
        try:
            with build_opener(_PublicRedirect()).open(request, timeout=self.timeout) as response:
                body = response.read()
        except HTTPError as exc:
            raise UploadError(f"Class API returned HTTP {exc.code}; check the public endpoint") from exc
        except (URLError, OSError, HTTPException, ValueError) as exc:
            raise UploadError("Class API request failed; check its URL, connectivity and timeout") from exc
        try:
            value: object = json.loads(body)
            return TypeAdapter(list[ApiClass]).validate_python(value, strict=True)
        except ValidationError as exc:
            raise UploadError(_invalid_records(exc)) from exc
        except (ValueError, UnicodeError, RecursionError) as exc:
            raise UploadError(_INVALID) from exc


def _invalid_records(error: ValidationError) -> str:
    """Name each invalid record by its index, field and problem, never by its value (ADR 0004)."""
    places = list(
        dict.fromkeys(
            _place(detail["loc"], detail["msg"])
            for detail in error.errors(include_input=False, include_url=False)
            if detail["loc"] and isinstance(detail["loc"][0], int)
        )
    )
    if not places:
        return _INVALID
    shown = "; ".join(places[:_SHOWN_PLACES])
    more = f"; and {len(places) - _SHOWN_PLACES} more" if len(places) > _SHOWN_PLACES else ""
    return f"{_INVALID}: {shown}{more}"


def _place(loc: tuple[int | str, ...], msg: str) -> str:
    index, *field = loc
    return f"record {index}: {'.'.join(map(str, field))}: {msg}" if field else f"record {index}: {msg}"
