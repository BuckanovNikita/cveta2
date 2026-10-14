"""Local image lookup, preserving search order and duplicate selection."""

import os
from collections.abc import Iterable
from pathlib import Path, PurePosixPath

from loguru import logger

from cveta2.domain.paths import pick_latest_duplicate


def _build_basename_index(search_dir: Path) -> dict[str, list[Path]]:
    """Walk *search_dir* recursively, mapping basename → sorted file paths."""
    index: dict[str, list[Path]] = {}
    for root, _dirs, files in os.walk(search_dir):
        root_path = Path(root)
        for file_name in files:
            index.setdefault(file_name, []).append(root_path / file_name)
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


def resolve_images(
    image_names: Iterable[str],
    search_dirs: list[Path],
) -> tuple[dict[str, Path], list[str]]:
    """Find image files on disk by searching *search_dirs* in order.

    Each directory is probed in two passes: a direct path join (supports
    names containing subpaths), then a recursive basename search over the
    whole tree.  Earlier search directories always win over later ones.

    Returns
    -------
    found : dict[str, Path]
        Mapping ``image_name -> local_path`` for images that were found.
    missing : list[str]
        Image names that could not be located in any search directory.

    """
    found: dict[str, Path] = {}
    remaining = set(image_names)

    for search_dir in search_dirs:
        if not remaining:
            break
        if not search_dir.is_dir():
            logger.debug(f"Директория поиска не существует: {search_dir}")
            continue
        for name in list(remaining):
            candidate = search_dir / name
            if candidate.is_file():
                found[name] = candidate
                remaining.discard(name)
        if not remaining:
            break
        index = _build_basename_index(search_dir)
        for name in list(remaining):
            match = _match_recursive(search_dir, name, index)
            if match is not None:
                found[name] = match
                remaining.discard(name)

    missing = sorted(remaining)
    return found, missing
