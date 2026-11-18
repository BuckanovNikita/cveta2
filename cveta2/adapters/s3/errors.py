"""Name the S3 resource behind a botocore failure, and translate it for the CLI.

The public Python API keeps raising the original botocore exceptions, so the
adapter entry points only *annotate* them: :func:`s3_operation` adds a note
naming the operation, bucket and prefix and re-raises the same object.  The
command line alone turns them into a :class:`Cveta2Error` through
:func:`s3_failures_as_errors`, which composition hands to the CLI boundary;
the interfaces layer may not import botocore itself.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Final

from boto3.exceptions import S3UploadFailedError
from botocore.exceptions import (
    ClientError,
    CredentialRetrievalError,
    HTTPClientError,
    IncompleteReadError,
    NoAuthTokenError,
    NoCredentialsError,
    NoRegionError,
    PartialCredentialsError,
    ProfileNotFound,
    SSOError,
    TokenRetrievalError,
)
from botocore.exceptions import ConnectionError as BotoConnectionError

from cveta2.domain.errors import Cveta2Error

S3_FAILURES: Final = (
    ClientError,
    NoCredentialsError,
    PartialCredentialsError,
    ProfileNotFound,
    CredentialRetrievalError,
    TokenRetrievalError,
    SSOError,
    NoAuthTokenError,
    NoRegionError,
    BotoConnectionError,
    HTTPClientError,
    IncompleteReadError,
    S3UploadFailedError,
)
"""Operational S3 failures: refusals, credentials, region and transport.

SDK errors that reveal a defect in the caller, such as
``ParamValidationError``, are deliberately absent so they keep surfacing
as unexpected errors with their traceback.
"""

_CONTEXT_MARK: Final = "S3: "


def _context_of(error: BaseException) -> str | None:
    """Return the resource note :func:`s3_operation` attached, if any."""
    # ``__notes__`` exists only once a note was added (PEP 678).
    notes: list[str] = getattr(error, "__notes__", [])
    for note in notes:
        if note.startswith(_CONTEXT_MARK):
            return note.removeprefix(_CONTEXT_MARK)
    return None


@contextmanager
def s3_operation(operation: str, bucket: str, prefix: str) -> Iterator[None]:
    """Attach *operation* and ``s3://bucket/prefix`` to an escaping S3 failure.

    The exception itself is re-raised unchanged, so API callers still catch
    the botocore class they expect.  The innermost operation wins.
    """
    try:
        yield
    except S3_FAILURES as error:
        if _context_of(error) is None:
            error.add_note(f"{_CONTEXT_MARK}{operation} s3://{bucket}/{prefix}")
        raise


@contextmanager
def s3_failures_as_errors() -> Iterator[None]:
    """Report an S3 failure as a :class:`Cveta2Error` caused by the original."""
    try:
        yield
    except S3_FAILURES as error:
        context = _context_of(error) or "операция S3"
        raise Cveta2Error(f"Ошибка S3 ({context}): {error}") from error
