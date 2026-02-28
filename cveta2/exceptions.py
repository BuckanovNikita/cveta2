"""Custom exception hierarchy for cveta2.

All library-specific exceptions inherit from ``Cveta2Error`` so consumers
can catch ``except Cveta2Error`` to handle any cveta2 failure.
"""


class Cveta2Error(Exception):
    """Base exception for all cveta2 errors."""


class ProjectNotFoundError(Cveta2Error):
    """Raised when a requested project cannot be found."""


class TaskNotFoundError(Cveta2Error):
    """Raised when a requested task cannot be found."""


class InteractiveModeRequiredError(Cveta2Error):
    """Raised when interactive input is needed but disabled."""


class LabelsMismatchError(Cveta2Error):
    """Raised when CSV labels don't match project labels."""

    def __init__(
        self,
        unknown_labels: list[str],
        project_name: str,
        available_labels: list[str],
    ) -> None:
        """Initialize with mismatched and available label lists."""
        self.unknown_labels = unknown_labels
        self.available_labels = available_labels
        super().__init__(
            f"Метки из CSV не найдены в проекте {project_name!r}: "
            f"{', '.join(unknown_labels)}. "
            f"Доступные метки: {', '.join(available_labels)}."
        )
