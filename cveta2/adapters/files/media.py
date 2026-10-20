"""Local path identity and cached image inspection at the filesystem boundary."""

import re
from pathlib import Path

import pandas as pd
from PIL import Image, UnidentifiedImageError

from cveta2.domain.verification.cells import is_missing
from cveta2.domain.verification.models import (
    Issue,
    MediaInspection,
    MediaRowFact,
    Profile,
    ValidationOptions,
)

_URI_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")


def resolve_image_path(
    name: str, value: object, options: ValidationOptions
) -> Path | None:
    """Resolve explicitly local paths; roots fill only absent path cells."""
    if isinstance(value, (str, Path)) and str(value):
        raw = str(value)
        if _URI_SCHEME.match(raw) and not Path(raw).drive:
            return None
        path = Path(raw).expanduser()
    elif options.image_root is not None:
        if _URI_SCHEME.match(name) or _URI_SCHEME.match(str(options.image_root)):
            return None
        path = options.image_root.expanduser() / name
    else:
        return None
    if not path.is_absolute():
        path = (options.base_dir or Path.cwd()).expanduser() / path
    return path.resolve()


def _decode(
    path: Path,
) -> tuple[tuple[int, int] | None, str | None, str | None, str | None]:
    try:
        with Image.open(path) as image:
            width, height = image.size
            image_format = image.format
            if image.getexif().get(274) in (5, 6, 7, 8):
                width, height = height, width
            image.load()
    except FileNotFoundError as error:
        return None, None, "media_missing", f"Image does not exist: {path}: {error}"
    except (
        OSError,
        UnidentifiedImageError,
        Image.DecompressionBombError,
        ValueError,
        SyntaxError,
    ) as error:
        return None, None, "media_unreadable", f"Cannot read image {path}: {error}"

    else:
        return (width, height), image_format, None, None


def inspect_images(
    frame: pd.DataFrame, *, profile: Profile, options: ValidationOptions
) -> MediaInspection:
    """Resolve every row and decode each canonical file once when requested."""
    facts: list[MediaRowFact] = []
    cache: dict[
        Path, tuple[tuple[int, int] | None, str | None, str | None, str | None]
    ] = {}
    if not frame.columns.is_unique or "image_name" not in frame:
        return MediaInspection()
    for position, row in enumerate(frame.to_dict(orient="records")):
        name = row["image_name"]
        value = row.get("image_path")
        issues: list[Issue] = []
        path = None
        try:
            path = resolve_image_path(str(name), value, options)
            if path is None and not is_missing(value):
                issues.append(
                    Issue(
                        code="invalid_local_path",
                        message="image_path must be a local path, not a remote URI.",
                        row_position=position,
                        columns=("image_path",),
                    )
                )
            if path is not None and isinstance(name, str) and path.name != name:
                issues.append(
                    Issue(
                        code="path_name_mismatch",
                        message="Image name does not match the resolved path basename.",
                        row_position=position,
                        columns=("image_path",),
                    )
                )
        except (OSError, RuntimeError, ValueError) as error:
            issues.append(
                Issue(
                    code="invalid_local_path",
                    message=f"Cannot resolve local image path: {error}",
                    row_position=position,
                    columns=("image_path",),
                )
            )
        size, image_format = None, None
        shape = row.get("instance_shape")
        deleted = profile == "cveta2" and isinstance(shape, str) and shape == "deleted"
        if options.check_images and not deleted:
            if path is None:
                issues.append(
                    Issue(
                        code="media_unreadable",
                        message=(
                            "No local image path is available; remote "
                            "URIs are not read."
                        ),
                        row_position=position,
                        columns=("image_path",),
                    )
                )
            else:
                if path not in cache:
                    cache[path] = _decode(path)
                size, image_format, code, message = cache[path]
                if code is not None and message is not None:
                    issues.append(
                        Issue(
                            code=code,
                            message=message,
                            row_position=position,
                            columns=("image_path",),
                        )
                    )
        facts.append(
            MediaRowFact(
                position,
                str(path) if path is not None else None,
                size,
                image_format,
                tuple(issues),
            )
        )
    return MediaInspection(tuple(facts))


class LocalMediaInspector:
    """Inject filesystem inspection into application orchestration."""

    def inspect(
        self, frame: pd.DataFrame, *, profile: Profile, options: ValidationOptions
    ) -> MediaInspection:
        """Read canonical path and optional decoded image facts."""
        return inspect_images(frame, profile=profile, options=options)
