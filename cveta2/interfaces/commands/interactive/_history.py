"""Per-user prompt history powering arrow-up autofill in text prompts.

Each semantic field (task name, host, cache root, …) gets its own history
file under ``~/.cache/cveta2/prompt_history/``, so arrow-up recalls values
entered on previous runs of the same prompt.  The files are per-user on
purpose — unlike the shared image/task caches they are not group-writable.
"""

from pathlib import Path

from prompt_toolkit.history import FileHistory

from cveta2.composition.files import default_cache_base


def prompt_history_dir() -> Path:
    """Return the per-user prompt-history directory (``doctor`` leaves it alone)."""
    return default_cache_base() / "prompt_history"


def history_for(key: str) -> FileHistory:
    """Return the persistent prompt history for *key*, creating its dir."""
    directory = prompt_history_dir()
    directory.mkdir(parents=True, exist_ok=True)
    return FileHistory(str(directory / key))
