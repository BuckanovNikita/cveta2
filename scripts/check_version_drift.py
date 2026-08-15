#!/usr/bin/env python3
"""Fail a push whose `project.version` was not written by a release.

`version` in pyproject.toml belongs to python-semantic-release: it bumps the
field, regenerates the changelog, commits and tags in one step. A hand edit
therefore shows up as a version that no tag reachable from HEAD carries, and the
next real release computes its bump from a number nobody else agreed on.

This runs at pre-push rather than pre-commit on purpose. During a release the
bump and the tag land together, so at commit time the tag does not exist yet and
a commit-stage check would fail every release; by push time it does exist. On a
feature branch the nearest tag is the last release and the version is untouched,
so the two match there as well.
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path


def main() -> int:
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    version = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]

    described = subprocess.run(
        ["git", "describe", "--tags", "--abbrev=0"],
        capture_output=True,
        text=True,
        check=False,
    )
    if described.returncode != 0:
        print("No tag reachable from HEAD; nothing to compare the version against.")
        return 0

    tag = described.stdout.strip()
    if tag.removeprefix("v") == version:
        print(f"Version {version} matches tag {tag}.")
        return 0

    print(f"FAILED: pyproject.toml has version {version}, nearest tag is {tag}.")
    print("The version field is written by the release, never by hand:")
    print("    uv run semantic-release version --no-push --no-vcs-release")
    print("If this branch predates a release on main, rebase onto main instead.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
