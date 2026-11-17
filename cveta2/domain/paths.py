"""Pure filename and object-key rules."""

from collections.abc import Iterable, Sequence
from pathlib import PurePosixPath, PureWindowsPath
from typing import TypeVar

from loguru import logger

from cveta2.domain.errors import Cveta2Error
from cveta2.domain.output import preview_names

_T = TypeVar("_T")


def pick_latest_duplicate(context: str, name: str, candidates: Sequence[_T]) -> _T:
    """Return the lexicographic max of *candidates*, warning when several exist.

    Both the uploader and the downloader resolve duplicate basenames the
    same way: the lexicographically last path wins (i.e. the most recent
    ``YYYY-MM`` month folder).
    """
    winner = max(candidates, key=str)
    if len(candidates) > 1:
        logger.warning(
            f"Дубликаты в {context} для {name!r}: {sorted(str(c) for c in candidates)} — используем {winner!r}"
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


def join_s3_key(prefix: str, relative: str) -> str:
    """Join a path known to be relative to *prefix* onto it.

    Unlike :func:`build_s3_key`, a *relative* that itself starts with the
    prefix folder is not mistaken for a full key: the server file
    ``images/a.jpg`` under prefix ``images`` is ``images/images/a.jpg``.
    """
    if not prefix:
        return relative
    return f"{_key_prefix_dir(prefix)}{relative}"


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


def _is_unsafe_image_name(name: str) -> bool:
    """Whether *name* could leave a search root or storage prefix."""
    return (
        not name
        or "\x00" in name
        or "\\" in name
        or PurePosixPath(name).is_absolute()
        or bool(PureWindowsPath(name).drive)
        or ".." in name.split("/")
    )


def validate_upload_image_names(names: Iterable[str]) -> None:
    """Reject image names that are not plain relative paths.

    An upload looks each name up below local search roots and binds it below
    the storage prefix, so an absolute path, a ``..`` component, a backslash,
    a NUL byte or an empty name would reach outside both. Subfolders such as
    ``2026-02/img.jpg`` stay valid.
    """
    unsafe = list(dict.fromkeys(name for name in names if _is_unsafe_image_name(str(name))))
    if unsafe:
        raise Cveta2Error(
            f"Небезопасные имена изображений: {preview_names([repr(name) for name in unsafe])}. "
            "Имя должно быть относительным путём "
            "без '..', обратной косой черты и нулевого байта. Загрузка не начата."
        )


def _validate_relative_key(value: str, *, original: str) -> str:
    """Return a safe relative POSIX key, rejecting filesystem traversal."""
    parts = value.split("/")
    if not value or any(part in {"", ".", ".."} for part in parts):
        raise Cveta2Error(
            f"Небезопасный путь изображения {original!r}: путь должен оставаться внутри настроенного корня хранилища"
        )
    return PurePosixPath(*parts).as_posix()


def _canonical_frame_key(prefix: str, frame_ref: str) -> str:
    """Resolve a relative or rooted frame reference within an S3 prefix."""
    if PurePosixPath(frame_ref).is_absolute():
        unrooted = frame_ref.lstrip("/")
        if prefix:
            prefix_dir = f"{prefix.rstrip('/')}/"
            if unrooted != prefix.rstrip("/") and not unrooted.startswith(prefix_dir):
                raise Cveta2Error(
                    f"Абсолютный путь изображения {frame_ref!r} находится вне настроенного корня {prefix!r}"
                )
        key = unrooted
    else:
        key = build_s3_key(prefix, frame_ref)
    return _validate_relative_key(key, original=frame_ref)


def _local_name_from_key(key: str, root: str, *, original: str) -> str:
    """Turn a canonical S3 key into a safe path below the local cache root."""
    relative = strip_key_prefix(key, root)
    return _validate_relative_key(relative, original=original)
