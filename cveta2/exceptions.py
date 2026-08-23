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


class MissingCredentialsError(Cveta2Error):
    """Raised when CVAT credentials are required but not configured."""


class MissingHostError(Cveta2Error):
    """Raised when the CVAT host is required but not configured."""


class CvatApiError(Cveta2Error):
    """CVAT API returned an error response.

    Wraps SDK-level API exceptions so no ``cvat_sdk`` types leak above
    the ``_client`` layer.  ``status_code`` is the HTTP status (0 when
    unknown).  ``retry_after`` carries the ``Retry-After`` header in
    seconds when the server sent one: its presence is what distinguishes a
    deliberate throttle from a crash, which is the difference between a
    write that is safe to repeat and one that is not.
    """

    def __init__(
        self,
        message: str,
        status_code: int = 0,
        retry_after: float | None = None,
    ) -> None:
        """Store the HTTP status code and throttle hint alongside the message."""
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


class ClearmlPublishError(Cveta2Error):
    """Raised when publishing a dataset to ClearML fails.

    The ClearML SDK raises a wide and undocumented range of types, so the
    publish call converts whatever it gets into this one.  That is what
    lets the caller stay narrow instead of catching bare ``Exception``.
    """


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
