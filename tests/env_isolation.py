"""Redirect HOME away from the developer's real one, before cveta2 is imported.

Loaded via ``-p tests.env_isolation`` in ``[tool.pytest.ini_options].addopts``
so it runs during pytest startup, ahead of every conftest and test module.

The timing is the whole point. ``cveta2/config.py`` evaluates
``CONFIG_DIR = Path.home() / ".config" / "cveta2"`` at import time and then
bakes ``CONFIG_PATH`` into the default arguments of ``CvatConfig.from_file``
and ``CvatConfig.save``. Default arguments bind at function-definition time, so
a fixture that sets ``HOME`` later cannot reach them — ``CvatConfig.save()``
with no path would still write to the real ``~/.config/cveta2/config.yaml``.
Setting HOME here freezes those constants inside a throwaway directory instead.

Per-test isolation of ``CVETA2_CONFIG`` still happens in the ``_isolate_config``
fixture; this module only guarantees the fallback is harmless.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

_FAKE_HOME = Path(tempfile.mkdtemp(prefix="cveta2-test-home-"))

os.environ["HOME"] = str(_FAKE_HOME)
os.environ["USERPROFILE"] = str(_FAKE_HOME)
os.environ["XDG_CONFIG_HOME"] = str(_FAKE_HOME / ".config")
os.environ["XDG_CACHE_HOME"] = str(_FAKE_HOME / ".cache")


def pytest_unconfigure(config: pytest.Config) -> None:  # noqa: ARG001
    """Remove the throwaway home once the session (or xdist worker) finishes."""
    shutil.rmtree(_FAKE_HOME, ignore_errors=True)
