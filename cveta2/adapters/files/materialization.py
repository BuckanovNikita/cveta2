"""Filesystem image confinement and link/copy effects."""

import shutil
from pathlib import Path

from loguru import logger

from cveta2.domain.errors import Cveta2Error


class _OnceWarner:
    """Emit a given warning at most once over its lifetime."""

    def __init__(self) -> None:
        self._warned = False

    def warn(self, message: str) -> None:
        if not self._warned:
            logger.warning(message)
            self._warned = True


_reflink_warner = _OnceWarner()


def _copy_after_reflink_failure(src: Path, dst: Path, error: OSError) -> None:
    """Fall back to plain copy after a failed reflink attempt (warn once)."""
    _reflink_warner.warn(f"reflink недоступен ({error}): используется копирование")
    dst.unlink(missing_ok=True)
    shutil.copy2(src, dst)


def _reflink_or_fallback_copy(src: Path, dst: Path, *, allow_copy: bool) -> None:
    """Reflink *src* to *dst*; *allow_copy* falls straight through to copy.

    Either way an ``OSError`` from the reflink attempt degrades to a
    plain copy with a one-time warning.
    """
    from reflink_copy import reflink, reflink_or_copy  # noqa: PLC0415

    link = reflink_or_copy if allow_copy else reflink
    try:
        link(str(src), str(dst))
    except OSError as exc:
        _copy_after_reflink_failure(src, dst, exc)


def _link_or_copy(src: Path, dst: Path, mode: str) -> None:
    """Place *src* at *dst* using the specified link mode.

    Modes: auto (reflink, falling back to copy), reflink, hardlink,
    symlink, copy.
    """
    if mode not in {"auto", "reflink", "hardlink", "symlink", "copy"}:
        raise Cveta2Error(f"Неизвестный link-mode: {mode!r}")
    if dst.exists() and src.samefile(dst) and not dst.is_symlink():
        return
    if dst.exists() or dst.is_symlink():
        dst.unlink()
    dst.parent.mkdir(parents=True, exist_ok=True)

    if mode == "symlink":
        dst.symlink_to(src.resolve())
    elif mode == "hardlink":
        dst.hardlink_to(src)
    elif mode == "copy":
        shutil.copy2(src, dst)
    elif mode in {"reflink", "auto"}:
        _reflink_or_fallback_copy(src, dst, allow_copy=mode == "auto")
    else:
        raise Cveta2Error(f"Неизвестный link-mode: {mode!r}")


def _confined_destination(target_dir: Path, local_name: str, *, original: str) -> Path:
    """Join a local name while preventing escape through existing symlinks."""
    destination = target_dir / local_name
    if not destination.resolve().is_relative_to(target_dir.resolve()):
        raise Cveta2Error(
            f"Небезопасный путь изображения {original!r}: "
            f"назначение находится вне локального кэша {target_dir}"
        )
    return destination
