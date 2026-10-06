"""Mutation children must not share pytest's numbered-directory cleanup root."""

import os
import subprocess
import sys
from pathlib import Path


def test_mutation_child_uses_process_owned_temp_directory(tmp_path: Path) -> None:
    probe = tmp_path / "test_probe.py"
    probe.write_text(
        "import os\n"
        "def test_root(tmp_path):\n"
        "    assert tmp_path.parent.name == f'worker-{os.getpid()}'\n",
        encoding="utf-8",
    )
    root = tmp_path / "mutation-temp"
    root.mkdir()
    result = subprocess.run(  # noqa: S603 — fixed pytest command and owned probe
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "tests.env_isolation",
            "--noconftest",
            "-o",
            "addopts=",
            str(probe),
        ],
        env=os.environ
        | {"MUTANT_UNDER_TEST": "isolation-probe", "PYTEST_DEBUG_TEMPROOT": str(root)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
