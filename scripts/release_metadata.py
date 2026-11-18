"""Synchronize only the root lock version during semantic-release preparation.

semantic-release runs this as its ``build_command`` with ``NEW_VERSION`` set, after it
has written ``project.version``. It rewrites the ``cveta2`` entry of ``uv.lock`` without
resolving dependencies and stages the file, so the release commit carries a lock that
agrees with the new version. Standard library only.
"""

import os
import re
import subprocess
import tomllib
from pathlib import Path

from scripts.release_lock_guard import PACKAGE, lock_problems


def main() -> None:
    version = os.environ["NEW_VERSION"]
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    if project["project"]["version"] != version or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise ValueError("semantic-release version must match project.version and be a stable version")
    path = Path("uv.lock")
    original = path.read_text(encoding="utf-8")
    before = tomllib.loads(original)
    roots = [package for package in before["package"] if package["name"] == PACKAGE]
    if len(roots) != 1:
        raise ValueError("lock must contain exactly one root package")
    pattern = rf'(?m)(^\[\[package\]\]\nname = "{re.escape(PACKAGE)}"\nversion = ")[^"]+("$)'
    updated, count = re.subn(pattern, lambda match: f"{match[1]}{version}{match[2]}", original)
    if count != 1:
        raise ValueError("cannot locate the root lock version unambiguously")
    problems = lock_problems(before, tomllib.loads(updated))
    if problems:
        raise ValueError("; ".join(problems))
    path.write_text(updated, encoding="utf-8")
    subprocess.run(["git", "add", "--", "uv.lock"], check=True)  # noqa: S607 - git from PATH


if __name__ == "__main__":
    main()
