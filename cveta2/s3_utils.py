"""Shared S3 utilities used by both image_downloader and image_uploader."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any, Final, TypeVar

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError, ConnectTimeoutError, ReadTimeoutError
from loguru import logger

from cveta2._concurrency import Workers, run_concurrent
from cveta2._retry import network_retry

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator, Sequence

    from cveta2.s3_types import S3Client

_T = TypeVar("_T")

# KeyError covers malformed S3 responses (missing "Body"/"Contents" keys),
# which surface exactly like transport failures for a transfer.  ClientError
# is here so one object's 403/404 fails that object rather than the whole
# run; the retryable subset below never reaches this far.
S3_TRANSFER_ERRORS: Final = (OSError, ConnectionError, KeyError, ClientError)

# S3's throttle and transient-fault codes.  SlowDown is S3's 429, and
# without it a large parallel transfer dies with a raw traceback the moment
# the bucket pushes back.
_RETRYABLE_S3_CODES: Final = frozenset(
    {"SlowDown", "RequestTimeout", "RequestTimeTooSkewed", "InternalError", "503"}
)


def run_s3_transfers(
    items: Sequence[_T],
    transfer: Callable[[_T], None],
    describe: Callable[[_T], str],
    *,
    desc: str,
    unit: str,
) -> tuple[int, int]:
    """Transfer every item, up to ``Workers.s3`` at a time; ``(ok, failed)``.

    This is the one fan-out both directions go through — uploads and
    downloads alike — so the worker count is read from the process-wide
    setting rather than threaded through every caller. One object's failure
    is logged and counted; the rest of the batch still runs.
    """
    outcomes = run_concurrent(
        items,
        transfer,
        max_workers=Workers.s3,
        catch=S3_TRANSFER_ERRORS,
        desc=desc,
        unit=unit,
    )
    failures = [
        (item, outcome)
        for item, outcome in zip(items, outcomes, strict=True)
        if isinstance(outcome, Exception)
    ]
    for item, error in failures:
        logger.opt(exception=error).error(f"Не удалось загрузить {describe(item)}")
    return len(items) - len(failures), len(failures)


def pick_latest_duplicate(context: str, name: str, candidates: Sequence[_T]) -> _T:
    """Return the lexicographic max of *candidates*, warning when several exist.

    Both the uploader and the downloader resolve duplicate basenames the
    same way: the lexicographically last path wins (i.e. the most recent
    ``YYYY-MM`` month folder).
    """
    winner = max(candidates, key=str)
    if len(candidates) > 1:
        logger.warning(
            f"Дубликаты в {context} для {name!r}: "
            f"{sorted(str(c) for c in candidates)} — используем {winner!r}"
        )
    return winner


def names_with_basename_fallback(pairs: Iterable[tuple[str, _T]]) -> dict[str, _T]:
    """Map each name to its value, also keyed by basename (first wins).

    Basename fallback handles subfolder frame names
    (e.g. ``"2026-02/img.jpg"`` is also accessible via ``"img.jpg"``).
    """
    result: dict[str, _T] = {}
    for name, value in pairs:
        result[name] = value
        base = PurePosixPath(name).name
        if base not in result:
            result[base] = value
    return result


_S3_TRANSPORT_ERRORS: Final = (
    OSError,
    ConnectionError,
    ConnectTimeoutError,
    ReadTimeoutError,
)


def _should_retry_s3(exc: BaseException) -> bool:
    """Retry transport faults and the codes S3 uses to say "slow down"."""
    if isinstance(exc, ClientError):
        return exc.response.get("Error", {}).get("Code") in _RETRYABLE_S3_CODES
    return isinstance(exc, _S3_TRANSPORT_ERRORS)


s3_retry = network_retry(_should_retry_s3, label="S3")

_S3_CONNECT_TIMEOUT = 10.0


class _DataTimeoutDefault:
    """Process-wide default read timeout (seconds) for S3 clients."""

    value: float | None = None


_MIN_POOL_SIZE: Final = 10
"""boto3's own default; never go below it just because workers are few."""


def set_default_data_timeout(timeout: float | None) -> None:
    """Set the default S3 read timeout used by :func:`make_s3_client`.

    ``None`` or ``0`` disables the timeout (boto3 defaults apply).
    """
    _DataTimeoutDefault.value = timeout


# botocore retries sit *under* the tenacity ``s3_retry``, so the two
# multiply.  Keep this small and let tenacity own the overall budget.
_BOTO_MAX_ATTEMPTS: Final = 3


def make_s3_client(endpoint_url: str | None = None) -> S3Client:
    """Create a boto3 S3 client honoring the configured timeout and pool size.

    The config is built unconditionally.  It used to be built only when a
    read timeout was set, which quietly meant that the default install had
    no botocore retries at all and a connection pool of 10 — a ceiling that
    caps every parallel transfer regardless of the configured worker count.
    The pool is therefore sized from the worker count itself: workers past
    that ceiling only queue for a connection, which looks from the outside
    like the fan-out simply not working.
    """
    options: dict[str, Any] = {
        "connect_timeout": _S3_CONNECT_TIMEOUT,
        "max_pool_connections": max(Workers.s3, _MIN_POOL_SIZE),
        "retries": {"max_attempts": _BOTO_MAX_ATTEMPTS, "mode": "standard"},
    }
    # An unset or zero timeout means "no opinion", so the key is omitted
    # rather than passed: urllib3 rejects a read timeout of 0 outright.
    if _DataTimeoutDefault.value:
        options["read_timeout"] = _DataTimeoutDefault.value
    client: S3Client = boto3.Session().client(
        "s3", endpoint_url=endpoint_url, config=Config(**options)
    )
    return client


@s3_retry
def s3_get_bytes(s3_client: S3Client, bucket: str, key: str) -> bytes:
    """Download an S3 object body as bytes."""
    resp = s3_client.get_object(Bucket=bucket, Key=key)
    data: bytes = resp["Body"].read()
    return data


def parse_sync_root(root: str) -> tuple[str | None, str]:
    """Parse a sync root string into ``(bucket, prefix)``.

    ``s3://bucket/some/prefix`` -> ``("bucket", "some/prefix")``,
    ``s3://bucket`` -> ``("bucket", "")``, a bare ``some/prefix`` ->
    ``(None, "some/prefix")``.  Trailing slashes are stripped.

    Raises
    ------
    ValueError
        When *root* is empty or an ``s3://`` URL has no bucket name.

    """
    cleaned = root.strip()
    if cleaned.startswith("s3://"):
        bucket, _, prefix = cleaned.removeprefix("s3://").partition("/")
        if not bucket:
            msg = f"Некорректный sync root {root!r}: отсутствует имя бакета."
            raise ValueError(msg)
        return (bucket, prefix.rstrip("/"))
    prefix = cleaned.rstrip("/")
    if not prefix:
        msg = f"Некорректный sync root {root!r}: пустое значение."
        raise ValueError(msg)
    return (None, prefix)


def _key_prefix_dir(prefix: str) -> str:
    """Return *prefix* in the directory form every key comparison uses.

    A cloud-storage prefix names a folder, so it matches a key only at a
    ``/`` boundary: with ``prefix="data/proj1"``, the sibling folder
    ``data/proj10/`` is a different place, and a plain ``startswith`` would
    claim its keys.  Normalizing here also collapses a configured trailing
    slash, which otherwise produced doubled separators in built keys.
    """
    return f"{prefix.rstrip('/')}/"


def build_s3_key(prefix: str, frame_name: str) -> str:
    """Construct the S3 object key for a frame.

    If *frame_name* already sits under *prefix*, it is used as-is.
    Otherwise *prefix/frame_name* is returned (or just *frame_name*
    when *prefix* is empty).
    """
    if not prefix:
        return frame_name
    prefix_dir = _key_prefix_dir(prefix)
    if frame_name.startswith(prefix_dir):
        return frame_name
    return f"{prefix_dir}{frame_name}"


def strip_key_prefix(key: str, prefix: str) -> str:
    """Return *key* with a leading *prefix* removed, keeping subfolders.

    The folder marker — a key that *is* the prefix — strips to ``""``, which
    is how :func:`list_s3_objects` recognizes and skips it.  When *key* does
    not sit under *prefix* (or *prefix* is empty), it is returned unchanged.

    The separator comes off with the prefix, so a remaining leading ``/`` is
    a doubled separator in the key itself.  That is a distinct S3 object from
    the single-slash spelling and is deliberately left alone: collapsing it
    would map two keys onto one local file.
    """
    if not prefix:
        return key
    prefix_dir = _key_prefix_dir(prefix)
    if key.startswith(prefix_dir):
        return key[len(prefix_dir) :]
    if key == prefix_dir.removesuffix("/"):
        return ""
    return key


def _iter_list_pages(
    s3_client: S3Client,
    bucket: str,
    query: dict[str, str],
) -> Iterator[dict[str, Any]]:
    """Yield each page of a ``list_objects_v2`` call, following the token.

    The one place that speaks S3's pagination protocol, so the whole-prefix
    scan and the one-level scan below cannot drift apart on it.
    """
    kwargs: dict[str, str] = {"Bucket": bucket, **query}
    while True:
        resp = s3_client.list_objects_v2(**kwargs)
        yield resp
        if not resp.get("IsTruncated"):
            return
        kwargs["ContinuationToken"] = resp["NextContinuationToken"]


def _page_pairs(page: dict[str, Any], prefix: str) -> list[tuple[str, str]]:
    """Return one page's ``(key, name)`` pairs, dropping the folder marker."""
    pairs: list[tuple[str, str]] = []
    for obj in page.get("Contents", []):
        key: str = obj["Key"]
        name = strip_key_prefix(key, prefix)
        if name:
            pairs.append((key, name))
    return pairs


def _search_query(search: str) -> dict[str, str]:
    """Build the ``Prefix`` filter, omitted entirely when listing a whole bucket."""
    return {"Prefix": search} if search else {}


def _list_keys_under(
    s3_client: S3Client,
    bucket: str,
    prefix: str,
    search: str,
) -> list[tuple[str, str]]:
    """Page through every key under *search*, stripping *prefix* from names."""
    return [
        pair
        for page in _iter_list_pages(s3_client, bucket, _search_query(search))
        for pair in _page_pairs(page, prefix)
    ]


def _list_one_level(
    s3_client: S3Client,
    bucket: str,
    prefix: str,
    search: str,
) -> tuple[list[str], list[tuple[str, str]]]:
    """Split *search* into ``(subfolder prefixes, keys directly under it)``.

    ``Delimiter`` makes S3 collapse everything below one level into a
    ``CommonPrefixes`` entry, which is how the listing gets divided into
    independently pageable chunks.  An S3 stand-in that ignores the
    parameter reports no subfolders, and the caller falls back to a single
    sequential pass.
    """
    folders: list[str] = []
    objects: list[tuple[str, str]] = []
    query = {"Delimiter": "/", **_search_query(search)}
    for page in _iter_list_pages(s3_client, bucket, query):
        folders.extend(entry["Prefix"] for entry in page.get("CommonPrefixes", []))
        objects.extend(_page_pairs(page, prefix))
    return folders, objects


def list_s3_objects(
    s3_client: S3Client,
    bucket: str,
    prefix: str,
) -> list[tuple[str, str]]:
    """List all S3 objects under *prefix* and return ``(key, local_name)`` pairs.

    The *local_name* is the object key with the prefix stripped, suitable
    for saving as a flat file name.  Empty names (the prefix directory
    marker itself) are skipped.

    The server-side filter asks for ``prefix/`` rather than ``prefix``,
    because S3 matches ``Prefix`` as a raw substring: listing ``data/proj1``
    would otherwise hand back every key of the sibling ``data/proj10/``,
    which :func:`strip_key_prefix` then declines to strip.  A storage whose
    prefix names an object rather than a folder therefore lists nothing —
    but :func:`build_s3_key` has always joined prefix and frame with a
    ``/``, so that configuration could never round-trip anyway.

    A whole-prefix listing is a serial chain of round-trips — one per
    thousand keys — and it runs before every fetch and every upload.  When
    the storage has subfolders (the uploader's own ``YYYY-MM/`` layout does)
    they are paged concurrently instead.  The result is sorted by key so it
    is byte-for-byte what the serial listing returned: callers depend on
    that order, because :func:`names_with_basename_fallback` resolves a
    duplicate basename by keeping the first entry it sees.
    """
    search = _key_prefix_dir(prefix) if prefix else ""
    if Workers.s3 <= 1:
        return _list_keys_under(s3_client, bucket, prefix, search)

    folders, root_objects = _list_one_level(s3_client, bucket, prefix, search)
    if not folders:
        return root_objects

    listings = run_concurrent(
        folders,
        lambda folder: _list_keys_under(s3_client, bucket, prefix, folder),
        max_workers=Workers.s3,
        catch=(),
        desc="Listing S3 prefixes",
        unit="prefix",
    )
    objects = [
        pair for listing in listings if isinstance(listing, list) for pair in listing
    ]
    return sorted([*objects, *root_objects])
