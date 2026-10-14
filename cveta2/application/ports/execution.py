"""Application-owned ordered execution contract."""

from collections.abc import Callable, Sequence
from typing import Protocol, TypeVar

_T = TypeVar("_T")
_R = TypeVar("_R")


class ConcurrentRunner(Protocol):
    """Return input-ordered outcomes, cancelling queued work on uncaught errors."""

    def __call__(  # noqa: PLR0913
        self,
        items: Sequence[_T],
        work: Callable[[_T], _R],
        *,
        max_workers: int,
        catch: tuple[type[Exception], ...],
        desc: str,
        unit: str,
    ) -> list[_R | Exception]:
        """Run ordered work with the supplied failure and worker policies."""
        ...
