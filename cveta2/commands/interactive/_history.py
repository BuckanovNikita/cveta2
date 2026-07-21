"""Per-user prompt history powering arrow-up autofill in text prompts.

Each semantic field (task name, host, cache root, …) gets its own history
file under ``~/.cache/cveta2/prompt_history/``, so arrow-up recalls values
entered on previous runs of the same prompt.  The files are per-user on
purpose — unlike the shared image/task caches they are not group-writable.
"""

from __future__ import annotations

import os
from pathlib import Path

from prompt_toolkit.history import FileHistory


def _history_dir() -> Path:
    xdg_cache = os.environ.get("XDG_CACHE_HOME")
    root = Path(xdg_cache) if xdg_cache else Path.home() / ".cache"
    return root / "cveta2" / "prompt_history"


def history_for(key: str) -> FileHistory:
    """Return the persistent prompt history for *key*, creating its dir."""
    directory = _history_dir()
    directory.mkdir(parents=True, exist_ok=True)
    return FileHistory(str(directory / key))
