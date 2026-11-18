"""Local image lookup, preserving search order and duplicate selection."""

import os
from collections.abc import Iterable
from pathlib import Path, PurePosixPath

from loguru import logger

from cveta2.domain.output import preview_names
from cveta2.domain.paths import pick_latest_duplicate


def _escapes_search_dir(name: str) -> bool:
    """Whether *name* is absolute or climbs out through a ``..`` component."""
    path = PurePosixPath(name)
    return path.is_absolute() or ".." in path.parts


def _inside(path: Path, excluded: Path | None) -> bool:
    """Whether the real location of *path* lies under *excluded*."""
    return excluded is not None and path.resolve().is_relative_to(excluded)


def _build_basename_index(search_dir: Path, excluded: Path | None = None) -> dict[str, list[Path]]:
    """Walk *search_dir* recursively, mapping basename → sorted file paths.

    Directories whose real location lies under *excluded* are not entered.
    """
    index: dict[str, list[Path]] = {}
    for root, dirs, files in os.walk(search_dir):
        root_path = Path(root)
        dirs[:] = [name for name in dirs if not _inside(root_path / name, excluded)]
        for file_name in files:
            candidate = root_path / file_name
            if not _inside(candidate, excluded):
                index.setdefault(file_name, []).append(candidate)
    for paths in index.values():
        paths.sort()
    return index


def _match_recursive(
    search_dir: Path,
    name: str,
    index: dict[str, list[Path]],
) -> Path | None:
    """Match *name* by basename in the recursive *index* of *search_dir*.

    When the same basename exists at several paths the lexicographic max
    wins (mirrors the "latest month folder" convention of
    :func:`build_server_file_mapping`).
    """
    candidates = index.get(PurePosixPath(name).name)
    if not candidates:
        return None
    return pick_latest_duplicate(str(search_dir), name, candidates)


def _search_one_dir(
    search_dir: Path,
    remaining: set[str],
    found: dict[str, Path],
    excluded: Path | None,
) -> None:
    """Move names found in *search_dir* from *remaining* into *found*.

    A direct path join comes first, then a recursive basename search.
    """
    for name in list(remaining):
        candidate = search_dir / name
        if candidate.is_file() and not _inside(candidate, excluded):
            found[name] = candidate
            remaining.discard(name)
    if not remaining:
        return
    index = _build_basename_index(search_dir, excluded)
    for name in list(remaining):
        match = _match_recursive(search_dir, name, index)
        if match is not None:
            found[name] = match
            remaining.discard(name)


def resolve_images(
    image_names: Iterable[str],
    search_dirs: list[Path],
    *,
    exclude: Path | None = None,
) -> tuple[dict[str, Path], list[str]]:
    """Find image files on disk by searching *search_dirs* in order.

    Each directory is probed in two passes: a direct path join (supports
    names containing subpaths), then a recursive basename search over the
    whole tree.  Earlier search directories always win over later ones.
    Absolute names and names with a ``..`` component are never looked up:
    they are warned about and reported as missing.  Files located under
    *exclude* (an export's own output directory) are never returned.

    Returns
    -------
    found : dict[str, Path]
        Mapping ``image_name -> local_path`` for images that were found.
    missing : list[str]
        Image names that could not be located in any search directory.

    """
    found: dict[str, Path] = {}
    remaining = set(image_names)
    unsafe = sorted(name for name in remaining if _escapes_search_dir(name))
    if unsafe:
        logger.warning(f"Пропущены имена изображений вне директории поиска ({len(unsafe)}): {preview_names(unsafe)}")
    remaining.difference_update(unsafe)
    excluded = exclude.resolve() if exclude is not None else None

    for search_dir in search_dirs:
        if not remaining:
            break
        if not search_dir.is_dir():
            logger.debug(f"Директория поиска не существует: {search_dir}")
            continue
        if _inside(search_dir, excluded):
            logger.warning(f"Директория поиска внутри выходной директории пропущена: {search_dir}")
            continue
        _search_one_dir(search_dir, remaining, found, excluded)

    missing = sorted(remaining | set(unsafe))
    return found, missing
