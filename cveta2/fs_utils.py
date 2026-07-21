"""Best-effort group-shared permissions for multi-user cache dirs.

Shared caches (task annotations, images) may be written by several OS
users in one group.  ``mkdir``/``write_bytes`` honour the process umask,
which usually drops group write, so freshly created cache entries are
explicitly chmod-ed to ``rwxrwxr-x`` / ``rw-rw-r--``.  Pre-existing
paths (possibly owned by other users) are never touched.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from pathlib import Path

_DIR_MODE = 0o775
_FILE_MODE = 0o664


def _chmod_quiet(path: Path, mode: int) -> None:
    try:
        path.chmod(mode)
    except OSError as exc:
        logger.debug(f"Не удалось выставить права {oct(mode)} на {path}: {exc}")


def ensure_shared_dir(path: Path) -> Path:
    """Create *path* (with parents) and chmod newly created levels to 775."""
    missing: list[Path] = []
    current = path
    while not current.exists():
        missing.append(current)
        if current.parent == current:
            break
        current = current.parent
    path.mkdir(parents=True, exist_ok=True)
    for level in missing:
        _chmod_quiet(level, _DIR_MODE)
    return path


def write_shared_bytes(path: Path, data: bytes) -> None:
    """Write *data* to *path* and chmod the file to 664."""
    path.write_bytes(data)
    _chmod_quiet(path, _FILE_MODE)
