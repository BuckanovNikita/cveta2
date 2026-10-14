"""Optional publication of a completed local dataset."""

from pathlib import Path
from typing import Protocol


class DatasetPublisher(Protocol):
    """Publish completed dataset outputs without changing fetch policy."""

    def __call__(self, project_name: str, output_dir: Path) -> None:
        """Perform the explicitly supplied outgoing operation."""
        ...
