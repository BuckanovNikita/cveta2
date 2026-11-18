"""Print the testmon environment fingerprint of this worktree.

``Taskfile.yml`` passes the printed value to pytest as ``--testmon-env``. testmon
tracks the Python code each test executes. The fingerprint covers what testmon
cannot see, so a change in any of it starts a fresh baseline: the interpreter, the
locked dependencies and verification configuration, static test and package assets,
the set of source and test files, and the content of ``scripts/`` and of pytest
startup code (every ``conftest.py`` and each ``-p`` plugin of the pytest ``addopts``).
Run from the repository root. Standard library only.
"""

import hashlib
import itertools
import platform
import subprocess
import sys
import tomllib
from pathlib import Path

CONFIG_NAMES = {"uv.lock", "Taskfile.yml", ".pre-commit-config.yaml", ".python-version", ".coveragerc"}
CONFIG_SUFFIXES = {".toml", ".ini", ".cfg"}
TREES = {"cveta2", "tests", "scripts"}


def main() -> None:
    digest = hashlib.sha256()
    digest.update(repr((sys.version, sys.executable, platform.platform())).encode())
    listed = (
        subprocess.check_output(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"])  # noqa: S607 - git from PATH
        .decode()
        .split("\0")
    )
    paths = {Path(name) for name in listed if name}
    # Ignored downloaded fixture assets can also affect tests.
    paths.update(Path("tests/fixtures").rglob("*"))
    paths.update(Path("cveta2").rglob("*"))
    # Code that runs at pytest startup or collection is no test's dependency in
    # testmon: conftest files and the -p plugins of addopts.
    addopts = tomllib.loads(Path("pyproject.toml").read_text())["tool"]["pytest"]["ini_options"]["addopts"]
    plugins = {Path(*name.split(".")).with_suffix(".py") for flag, name in itertools.pairwise(addopts) if flag == "-p"}
    for path in sorted(paths):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
            continue
        in_tree = path.parts[0] in TREES
        config = path.name in CONFIG_NAMES or path.suffix in CONFIG_SUFFIXES
        if not (in_tree or config or path == Path("main.py")):
            continue
        digest.update(path.as_posix().encode() + b"\0")
        # Python execution dependencies stay with testmon. Scripts and pytest
        # startup code are orchestration inputs, so changes conservatively invalidate.
        startup = path.name == "conftest.py" or path in plugins
        if path.suffix != ".py" or path.parts[0] == "scripts" or startup:
            digest.update(path.read_bytes())
        digest.update(b"\0")
    print(digest.hexdigest())


if __name__ == "__main__":
    main()
