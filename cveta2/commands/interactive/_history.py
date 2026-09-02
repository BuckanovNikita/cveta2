"""Per-user prompt history powering arrow-up autofill in text prompts.

Each semantic field (task name, host, cache root, …) gets its own history
file under ``~/.cache/cveta2/prompt_history/``, so arrow-up recalls values
entered on previous runs of the same prompt.  The files are per-user on
purpose — unlike the shared image/task caches they are not group-writable.
"""

from __future__ import annotations

from prompt_toolkit.history import FileHistory

from cveta2.fs_utils import default_cache_base


def history_for(key: str) -> FileHistory:
    """Return the persistent prompt history for *key*, creating its dir."""
    directory = default_cache_base() / "prompt_history"
    directory.mkdir(parents=True, exist_ok=True)
    return FileHistory(str(directory / key))
