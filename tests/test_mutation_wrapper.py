"""The shell gate must propagate profile resolution before starting work."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(
    not (ROOT / "scripts/mutation_test.sh").is_file(),
    reason="mutation workspace does not copy operator scripts",
)


@pytest.mark.parametrize("profile", ["unknown-review-profile", "", "fast", "full"])
def test_profile_resolution_precedes_mutation(tmp_path: Path, profile: str) -> None:
    """An invalid profile must not sync scope or invoke the mutation engine."""
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    for name in ("mutation_test.sh", "mutation_config.py"):
        shutil.copyfile(ROOT / "scripts" / name, scripts / name)
    shutil.copyfile(ROOT / "pyproject.toml", tmp_path / "pyproject.toml")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    shim = bin_dir / "uv"
    shim.write_text(
        "#!/bin/bash\n"
        'if [[ "$*" == *"globs --profile"* ]]; then\n'
        '  exec "$TEST_PYTHON" "$3" "${@:4}"\n'
        "fi\n"
        'printf "%s\\n" "$*" >> "$CALL_LOG"\n'
        'if [[ "$*" == *"mutmut run"* ]]; then exit 91; fi\n',
        encoding="utf-8",
    )
    shim.chmod(0o755)
    calls = tmp_path / "calls"
    result = subprocess.run(  # noqa: S603 — task-owned script and fixed profile cases
        ["/bin/bash", str(scripts / "mutation_test.sh"), "--profile", profile],
        env=os.environ
        | {
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "TEST_PYTHON": sys.executable,
            "CALL_LOG": str(calls),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    if profile not in {"fast", "full"}:
        assert result.returncode == 1
        assert profile in result.stderr
        assert not calls.exists()
        assert not (tmp_path / "mutants").exists()
    else:
        assert result.returncode == 91
        assert "mutmut run" in calls.read_text()
