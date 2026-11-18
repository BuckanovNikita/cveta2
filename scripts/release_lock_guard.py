"""Refuse a release commit that changes more than the root version.

The GitHub release runner (``scripts/release.py``) compares its selected source with
the commit semantic-release generated:

* ``uv.lock``: every top-level key and every ``[[package]]`` entry is identical, except
  the single ``cveta2`` entry whose only change is ``version``;
* ``pyproject.toml``: identical apart from ``project.version`` and free of
  ``[tool.uv.sources]`` overrides;
* the released lock root version equals the released ``project.version``.

Standard library only: the release job installs nothing but semantic-release.
"""

import subprocess
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any, TypeAlias

PACKAGE = "cveta2"

Document: TypeAlias = dict[str, Any]


def _load(root: Path, revision: str, path: str) -> Document:
    content = subprocess.run(  # noqa: S603 - fixed git argv, no shell
        ["git", "-C", str(root), "show", f"{revision}:{path}"],  # noqa: S607 - git from PATH
        check=True,
        capture_output=True,
    ).stdout
    document: Document = tomllib.loads(content.decode())
    return document


def _split_root(lock: Mapping[str, Any], side: str, problems: list[str]) -> tuple[Document | None, list[Any]]:
    packages: list[Any] = list(lock.get("package", []))
    roots = [package for package in packages if package.get("name") == PACKAGE]
    if len(roots) != 1:
        problems.append(f"{side} uv.lock must contain exactly one {PACKAGE} package, found {len(roots)}")
        return None, packages
    return roots[0], [package for package in packages if package.get("name") != PACKAGE]


def _describe(package: Mapping[str, Any]) -> str:
    return f"{package.get('name')} {package.get('version')}"


def lock_problems(base: Document, released: Document) -> list[str]:
    """Return why the released lock is not a root-version-only change of ``base``."""
    problems = [
        f"uv.lock top-level key {key!r} changed"
        for key in sorted((set(base) | set(released)) - {"package"})
        if base.get(key) != released.get(key)
    ]
    base_root, base_others = _split_root(base, "source", problems)
    released_root, released_others = _split_root(released, "released", problems)
    if base_others != released_others:
        base_names = [_describe(package) for package in base_others]
        released_names = [_describe(package) for package in released_others]
        added = [name for name in released_names if name not in base_names]
        removed = [name for name in base_names if name not in released_names]
        changed = sorted(
            name
            for name in set(base_names) & set(released_names)
            if [package for package in base_others if _describe(package) == name]
            != [package for package in released_others if _describe(package) == name]
        )
        problems.extend(f"uv.lock package added: {name}" for name in added)
        problems.extend(f"uv.lock package removed: {name}" for name in removed)
        problems.extend(f"uv.lock package changed: {name}" for name in changed)
        if not (added or removed or changed):
            problems.append("uv.lock package order changed")
    if base_root is not None and released_root is not None:
        before = {key: value for key, value in base_root.items() if key != "version"}
        after = {key: value for key, value in released_root.items() if key != "version"}
        problems.extend(
            f"uv.lock {PACKAGE} field {key!r} changed"
            for key in sorted(set(before) | set(after))
            if before.get(key) != after.get(key)
        )
    return problems


def pyproject_problems(base: Document, released: Document) -> list[str]:
    """Return why the released project is not a version-only change of ``base``."""
    problems: list[str] = []
    if "sources" in released.get("tool", {}).get("uv", {}):
        problems.append("released pyproject.toml contains [tool.uv.sources]; releases carry no local overrides")
    before = {**base, "project": {**base.get("project", {}), "version": None}}
    after = {**released, "project": {**released.get("project", {}), "version": None}}
    if before != after:
        keys = sorted(key for key in set(before) | set(after) if before.get(key) != after.get(key))
        problems.append(f"released pyproject.toml differs from the source beyond project.version in: {', '.join(keys)}")
    return problems


def check(root: Path, base: str, released: str) -> list[str]:
    """Compare the ``base`` and ``released`` commits and return every release-policy violation."""
    lock_base = _load(root, base, "uv.lock")
    lock_released = _load(root, released, "uv.lock")
    project_released = _load(root, released, "pyproject.toml")
    problems = lock_problems(lock_base, lock_released)
    problems.extend(pyproject_problems(_load(root, base, "pyproject.toml"), project_released))
    version = project_released.get("project", {}).get("version")
    roots = [package for package in lock_released.get("package", []) if package.get("name") == PACKAGE]
    if len(roots) == 1 and roots[0].get("version") != version:
        problems.append(f"released uv.lock {PACKAGE} version {roots[0].get('version')} differs from project {version}")
    return problems
