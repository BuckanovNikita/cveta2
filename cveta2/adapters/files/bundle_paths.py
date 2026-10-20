"""Local path coverage and independent S3-reference containment checks."""

import os
from pathlib import Path
from urllib.parse import urlsplit

import pandas as pd

from cveta2.domain.bundle.models import ImageRoots, UploadError
from cveta2.domain.verification.cells import is_missing


def absolute_image_path(value: object) -> Path:
    """Require an explicit absolute local path before resolving symlinks."""
    if (
        not isinstance(value, str)
        or not value
        or "\x00" in value
        or not Path(value).is_absolute()
    ):
        raise UploadError(
            f"Upload image_path must be an absolute local path: {value!r}"
        )
    try:
        return Path(value).resolve()
    except (OSError, RuntimeError, ValueError) as error:
        raise UploadError(f"Cannot resolve image_path {value!r}: {error}") from error


def _s3_parts(value: str, *, root: bool = False) -> tuple[str, tuple[str, ...]]:
    try:
        parsed = urlsplit(value)
    except ValueError as error:
        raise UploadError(f"Invalid S3 path: {value!r}") from error
    # Exactly one leading slash is the URI delimiter. Any further separator is
    # part of the object key and must not be normalized across an approved prefix.
    key = parsed.path.removeprefix("/")
    if root:
        key = key.removesuffix("/")
    parts = tuple(key.split("/")) if key else ()
    if (
        parsed.scheme != "s3"
        or not parsed.netloc
        or any(character in parsed.netloc for character in "@: \\")
        or parsed.query
        or parsed.fragment
        or "\x00" in value
        or "\\" in parsed.path
        or (not root and not key)
        or parsed.path.startswith("//")
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise UploadError(
            f"Expected an S3 bucket/prefix without traversal or credentials: {value!r}"
        )
    return parsed.netloc, parts


class LocalRoots:
    """Filesystem checks own canonicalization; S3 checks perform no remote effects."""

    def check_local_root(self, root: str) -> str:
        """Resolve and verify one accessible local root."""
        try:
            if not root or "\x00" in root:
                raise UploadError("Local roots must be nonempty directory paths")
            path = Path(root).expanduser().resolve(strict=True)
            if not path.is_dir():
                raise UploadError(f"Local root is not a directory: {root!r}")
            if not os.access(path, os.R_OK | os.X_OK):
                raise UploadError(f"Cannot access local root: {root!r}")
            # Opening a directory proves access even when no retained image uses it.
            with os.scandir(path) as entries:
                next(entries, None)
        except (OSError, RuntimeError, ValueError) as error:
            raise UploadError(f"Cannot use local root {root!r}: {error}") from error
        return str(path)

    def uncovered_paths(self, frame: pd.DataFrame, roots: ImageRoots) -> list[str]:
        """Find canonical paths outside independently approved local roots."""
        approved = [Path(self.check_local_root(root)) for root in roots.local_root]
        if "image_path" not in frame or not frame.columns.is_unique:
            raise UploadError("Upload CSV must have a unique image_path column")
        uncovered: dict[str, None] = {}
        for value in frame["image_path"]:
            path = absolute_image_path(value)
            if not any(path.is_relative_to(root) for root in approved):
                uncovered[str(path)] = None
        return list(uncovered)

    def check_s3_paths(self, frame: pd.DataFrame, roots: ImageRoots) -> None:
        """Require each remote key to identify one approved bucket and prefix."""
        approved = [_s3_parts(root, root=True) for root in roots.s3_root]
        if not frame.columns.is_unique:
            raise UploadError("Upload CSV columns must be unique")
        if "s3_image_path" not in frame:
            return
        for value in frame["s3_image_path"]:
            if is_missing(value):
                continue
            if not isinstance(value, str):
                raise UploadError(f"S3 image path must be a string: {value!r}")
            if value.startswith("s3://"):
                bucket, key = _s3_parts(value)
                matches = {
                    owner
                    for owner, prefix in approved
                    if bucket == owner and key[: len(prefix)] == prefix
                }
            else:
                # Existing cveta2 exports use bucket-relative object keys. Resolve
                # only through approved prefixes and reject ambiguous buckets.
                _, key = _s3_parts(f"s3://placeholder/{value}")
                matches = {
                    owner for owner, prefix in approved if key[: len(prefix)] == prefix
                }
            if len(matches) != 1:
                raise UploadError(
                    f"S3 image path is outside approved S3 roots: {value!r}"
                )
