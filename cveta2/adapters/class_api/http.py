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


def _public_http(url: str) -> None:
    try:
        parsed = urlsplit(url)
        valid = parsed.scheme in {"http", "https"} and parsed.hostname
        credentials = parsed.username is not None or parsed.password is not None
    except ValueError as exc:
        raise UploadError("Class API URL is malformed") from exc
    if not valid or credentials:
        raise UploadError(
            "Class API requires an HTTP(S) URL without embedded credentials"
        )


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
            with build_opener(_PublicRedirect()).open(
                request, timeout=self.timeout
            ) as response:
                body = response.read()
        except HTTPError as exc:
            raise UploadError(
                f"Class API returned HTTP {exc.code}; check the public endpoint"
            ) from exc
        except (URLError, OSError, HTTPException, ValueError) as exc:
            raise UploadError(
                "Class API request failed; check its URL, connectivity and timeout"
            ) from exc
        try:
            value: object = json.loads(body)
            return TypeAdapter(list[ApiClass]).validate_python(value, strict=True)
        except (ValueError, UnicodeError, ValidationError) as exc:
            raise UploadError(
                "Class API must return a JSON list of valid class definitions"
            ) from exc
