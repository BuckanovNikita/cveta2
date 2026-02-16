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
