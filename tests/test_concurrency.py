"""The shared fan-out primitive: ordering, failure policy, real parallelism.

Order is the property worth pinning hardest. Threads finish in whatever
order the network allows, but the fetch pipeline merges per-task results
positionally and the S3 listing resolves duplicate basenames by keeping the
first entry — both would silently produce different output for the same
input if completion order leaked through.
"""

from __future__ import annotations

import threading

import pytest

from cveta2._concurrency import Workers, configure_workers, run_concurrent

_BARRIER_TIMEOUT = 5.0


@pytest.fixture(autouse=True)
def _restore_workers() -> object:
    """Worker counts are process-wide; keep a test from leaking into others."""
    s3, cvat = Workers.s3, Workers.cvat
    yield
    configure_workers(s3=s3, cvat=cvat)


class TestOrdering:
    @pytest.mark.parametrize("max_workers", [1, 2, 8], ids=["inline", "two", "eight"])
    def test_results_follow_input_order(self, max_workers: int) -> None:
        items = list(range(20))

        results = run_concurrent(
            items,
            lambda n: n * 2,
            max_workers=max_workers,
            catch=(),
            desc="t",
            unit="item",
        )

        assert results == [n * 2 for n in items]

    def test_order_holds_when_later_items_finish_first(self) -> None:
        """The first item is the slowest, so completion order is reversed."""
        started = threading.Event()

        def work(n: int) -> int:
            if n == 0:
                started.wait(timeout=_BARRIER_TIMEOUT)
            else:
                started.set()
            return n

        results = run_concurrent(
            list(range(6)),
            work,
            max_workers=6,
            catch=(),
            desc="t",
            unit="item",
        )

        assert results == list(range(6))

    def test_an_empty_batch_is_not_an_error(self) -> None:
        assert (
            run_concurrent(
                [], lambda n: n, max_workers=4, catch=(), desc="t", unit="item"
            )
            == []
        )


class TestFailurePolicy:
    def test_a_caught_failure_lands_in_that_items_slot(self) -> None:
        """The batch continues, and the caller can still tell which item failed."""

        def work(n: int) -> int:
            if n == 2:
                raise OSError("boom")
            return n

        results = run_concurrent(
            list(range(4)),
            work,
            max_workers=4,
            catch=(OSError,),
            desc="t",
            unit="item",
        )

        assert [results[0], results[1], results[3]] == [0, 1, 3]
        assert isinstance(results[2], OSError)

    @pytest.mark.parametrize("max_workers", [1, 4], ids=["inline", "parallel"])
    def test_an_uncaught_failure_propagates(self, max_workers: int) -> None:
        """Both paths must fail the same way, or `max_workers` changes semantics."""

        def work(n: int) -> int:
            if n == 1:
                raise ValueError("boom")
            return n

        with pytest.raises(ValueError, match="boom"):
            run_concurrent(
                list(range(4)),
                work,
                max_workers=max_workers,
                catch=(OSError,),
                desc="t",
                unit="item",
            )


class TestParallelism:
    def test_work_really_overlaps(self) -> None:
        """A barrier only clears if the workers are genuinely simultaneous.

        Without this, every other test here would still pass against an
        implementation that quietly ran everything one at a time.
        """
        width = 4
        barrier = threading.Barrier(width, timeout=_BARRIER_TIMEOUT)

        results = run_concurrent(
            list(range(width)),
            lambda _n: barrier.wait() >= 0,
            max_workers=width,
            catch=(),
            desc="t",
            unit="item",
        )

        assert results == [True] * width

    def test_one_worker_does_not_overlap(self) -> None:
        """The inline path is what keeps `max_workers=1` a true no-op."""
        barrier = threading.Barrier(2, timeout=0.2)

        with pytest.raises(threading.BrokenBarrierError):
            run_concurrent(
                [0, 1],
                lambda _n: barrier.wait(),
                max_workers=1,
                catch=(),
                desc="t",
                unit="item",
            )

    def test_workers_never_exceed_the_limit(self) -> None:
        """Exceeding it would blow past the S3 pool and the CVAT rate limit."""
        limit = 3
        live = 0
        peak = 0
        lock = threading.Lock()
        release = threading.Event()

        def work(_n: int) -> None:
            nonlocal live, peak
            with lock:
                live += 1
                peak = max(peak, live)
            release.wait(timeout=0.05)
            with lock:
                live -= 1

        run_concurrent(
            list(range(24)),
            work,
            max_workers=limit,
            catch=(),
            desc="t",
            unit="item",
        )

        assert peak <= limit


class TestWorkerConfiguration:
    def test_counts_below_one_are_floored(self) -> None:
        """Zero workers would mean no work at all, not "sequential"."""
        configure_workers(s3=0, cvat=-4)

        assert (Workers.s3, Workers.cvat) == (1, 1)

    def test_both_counts_are_set_independently(self) -> None:
        configure_workers(s3=12, cvat=3)

        assert (Workers.s3, Workers.cvat) == (12, 3)
