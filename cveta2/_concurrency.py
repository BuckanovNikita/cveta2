"""Bounded parallelism for the transfer and fetch loops.

One primitive, deliberately. Every fan-out site here has the same shape —
independent units of network I/O, a progress bar, and a policy for what a
single unit's failure means for the batch. Only the last part differs, so
it is the caller's to supply.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from contextvars import ContextVar, copy_context
from typing import TYPE_CHECKING, TypeVar

from tqdm import tqdm

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

_T = TypeVar("_T")
_R = TypeVar("_R")


_WORKERS: ContextVar[tuple[int, int]] = ContextVar("cveta2_workers", default=(1, 1))


class _WorkersMeta(type):
    @property
    def s3(cls) -> int:
        return _WORKERS.get()[0]

    @property
    def cvat(cls) -> int:
        return _WORKERS.get()[1]


class Workers(metaclass=_WorkersMeta):
    """Context-local fan-out width installed at client bootstrap.

    Both default to 1 — fully sequential — so an entry point that never
    went through ``configure_network`` behaves exactly as it did before
    concurrency existed. ``cvat`` is expected to stay well below ``s3``:
    CVAT rate-limits long before object storage does. Worker threads inherit
    the context that submitted their work.
    """


def configure_workers(*, s3: int, cvat: int) -> None:
    """Set the current context's fan-out width for S3 and CVAT calls."""
    _WORKERS.set((max(s3, 1), max(cvat, 1)))


def _capture(
    work: Callable[[_T], _R],
    item: _T,
    catch: tuple[type[Exception], ...],
) -> _R | Exception:
    """Run *work*, returning a caught failure instead of raising it."""
    try:
        return work(item)
    except catch as error:
        return error


def run_concurrent(  # noqa: PLR0913
    items: Sequence[_T],
    work: Callable[[_T], _R],
    *,
    max_workers: int,
    catch: tuple[type[Exception], ...],
    desc: str,
    unit: str,
) -> list[_R | Exception]:
    """Run *work* over *items* with at most *max_workers* threads.

    Results line up positionally with *items* however the threads happen to
    finish, so a caller that merges them keeps a deterministic order. A
    failure whose type is listed in *catch* is returned in that item's
    place; anything else cancels the pending work and propagates.

    ``max_workers=1`` runs inline with no pool at all, which keeps the
    sequential path — and the tracebacks it produces — unchanged.
    """
    if max_workers <= 1:
        return [
            _capture(work, item, catch)
            for item in tqdm(items, desc=desc, unit=unit, leave=False)
        ]

    outcomes: dict[int, _R | Exception] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        pending = {
            pool.submit(copy_context().run, work, item): index
            for index, item in enumerate(items)
        }
        try:
            with tqdm(total=len(items), desc=desc, unit=unit, leave=False) as bar:
                for future in as_completed(pending):
                    error = future.exception()
                    if error is not None and not isinstance(error, catch):
                        raise error
                    outcomes[pending[future]] = (
                        error if error is not None else future.result()
                    )
                    bar.update(1)
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
    return [outcomes[index] for index in range(len(items))]
