"""Tests for the ``cveta2 whats-new`` command and its client method."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd
import pytest

from cveta2.client import CvatClient
from cveta2.commands.whats_new import run_whats_new
from cveta2.config import CvatConfig
from cveta2.exceptions import Cveta2Error
from cveta2.services.whats_new import compute_baseline, compute_cutoff
from tests.fixtures.fake_cvat_api import FakeCvatApi
from tests.helpers import (
    CFG,
    make_task,
    parse_cli_args,
    patch_cli_client,
    write_dataset_csv,
)

if TYPE_CHECKING:
    from pathlib import Path

    from cveta2.models import TaskInfo


def _client_with_tasks(tasks: list[TaskInfo]) -> CvatClient:
    """Create a CvatClient whose fake API returns the given tasks."""
    return CvatClient(CvatConfig(), api=FakeCvatApi.from_tasks(tasks))


# ---------------------------------------------------------------------------
# Client method: list_tasks_completed_after
# ---------------------------------------------------------------------------


class TestListTasksCompletedAfter:
    """Tests for ``CvatClient.list_tasks_completed_after``."""

    @pytest.mark.parametrize(
        ("tasks", "cutoff", "expected_ids"),
        [
            (
                [
                    make_task(
                        1, status="annotation", updated="2026-01-05T00:00:00+00:00"
                    ),
                    make_task(
                        2, status="validation", updated="2026-01-05T00:00:00+00:00"
                    ),
                    make_task(
                        3, status="completed", updated="2026-01-05T00:00:00+00:00"
                    ),
                ],
                "2026-01-01T00:00:00+00:00",
                [3],
            ),
            (
                [
                    make_task(1, updated="2026-01-04T00:00:00+00:00"),
                    make_task(2, updated="2026-01-05T00:00:00+00:00"),
                    make_task(3, updated="2026-01-06T00:00:00+00:00"),
                ],
                "2026-01-05T00:00:00+00:00",
                [3],
            ),
            (
                [
                    make_task(1, updated=""),
                    make_task(2, updated="2026-01-06T00:00:00+00:00"),
                ],
                "2026-01-01T00:00:00+00:00",
                [2],
            ),
            (
                [
                    make_task(1, updated="2026-01-08T00:00:00+00:00"),
                    make_task(2, updated="2026-01-06T00:00:00+00:00"),
                    make_task(3, updated="2026-01-07T00:00:00+00:00"),
                ],
                "2026-01-01T00:00:00+00:00",
                [2, 3, 1],
            ),
        ],
    )
    def test_filters_and_sorts(
        self, tasks: list[TaskInfo], cutoff: str, expected_ids: list[int]
    ) -> None:
        client = _client_with_tasks(tasks)

        result = client.list_tasks_completed_after(1, cutoff)

        assert [t.id for t in result] == expected_ids


# ---------------------------------------------------------------------------
# Cutoff computation: compute_cutoff
# ---------------------------------------------------------------------------


class TestComputeCutoff:
    """Tests for ``compute_cutoff``."""

    def test_cutoff_from_completed_rows_only(self, tmp_path: Path) -> None:
        """Non-completed rows must not push the cutoff forward."""
        df = pd.DataFrame(
            [
                {
                    "task_id": 1,
                    "task_status": "completed",
                    "task_updated_date": "2026-01-02T00:00:00+00:00",
                },
                {
                    "task_id": 2,
                    "task_status": "annotation",
                    "task_updated_date": "2026-01-09T00:00:00+00:00",
                },
            ]
        )

        cutoff = compute_cutoff(df, tmp_path / "dataset.csv")

        assert cutoff == "2026-01-02T00:00:00+00:00"

    def test_falls_back_to_all_rows_when_no_completed(self, tmp_path: Path) -> None:
        """With no completed rows, the max over all rows is used."""
        df = pd.DataFrame(
            [
                {
                    "task_id": 1,
                    "task_status": "annotation",
                    "task_updated_date": "2026-01-04T00:00:00+00:00",
                },
                {
                    "task_id": 2,
                    "task_status": "validation",
                    "task_updated_date": "2026-01-06T00:00:00+00:00",
                },
            ]
        )

        cutoff = compute_cutoff(df, tmp_path / "dataset.csv")

        assert cutoff == "2026-01-06T00:00:00+00:00"

    def test_empty_date_column_raises(self, tmp_path: Path) -> None:
        df = pd.DataFrame(
            [
                {
                    "task_id": 1,
                    "task_status": "completed",
                    "task_updated_date": None,
                },
            ]
        )

        with pytest.raises(Cveta2Error, match="пуст"):
            compute_cutoff(df, tmp_path / "dataset.csv")

    def test_blank_dates_count_as_missing(self, tmp_path: Path) -> None:
        """Empty strings are dropped as well as NaN.

        ``dropna()`` alone does not remove ``""`` — a CSV round-trip turns a
        missing date into an empty cell, not None — so the explicit
        ``!= ""`` filters carry the behaviour. Without a blank row here they
        are unexercised and free to compare against any other literal.
        """
        df = pd.DataFrame(
            [
                {"task_id": 1, "task_status": "completed", "task_updated_date": ""},
                {"task_id": 2, "task_status": "annotation", "task_updated_date": ""},
            ]
        )

        with pytest.raises(Cveta2Error, match="пуст"):
            compute_cutoff(df, tmp_path / "dataset.csv")

    def test_blank_completed_date_falls_back_to_all_rows(self, tmp_path: Path) -> None:
        """A completed row with a blank date must not win the max().

        Pins the second ``!= ""`` filter specifically: string comparison would
        otherwise rank ``""`` below any date and quietly pick the annotation
        row anyway, hiding the bug. Here the blank row is the only completed
        one, so the fallback to all rows is what produces a usable cutoff.
        """
        df = pd.DataFrame(
            [
                {"task_id": 1, "task_status": "completed", "task_updated_date": ""},
                {
                    "task_id": 2,
                    "task_status": "annotation",
                    "task_updated_date": "2026-01-06T00:00:00+00:00",
                },
            ]
        )

        assert (
            compute_cutoff(df, tmp_path / "dataset.csv") == "2026-01-06T00:00:00+00:00"
        )

    def test_baseline_reports_the_csv_path_when_dates_are_unusable(
        self, tmp_path: Path
    ) -> None:
        """compute_baseline must forward its own path into the error message.

        The path is used nowhere else, so passing None instead is invisible
        until a user hits the error and is told the column is empty in
        ``None``.
        """
        csv_path = tmp_path / "dataset.csv"
        df = pd.DataFrame(
            [{"task_id": 1, "task_status": "completed", "task_updated_date": None}]
        )

        with pytest.raises(Cveta2Error, match=str(csv_path)):
            compute_baseline(df, csv_path)

    def test_baseline_collects_known_task_ids(self, tmp_path: Path) -> None:
        df = pd.DataFrame(
            [
                {
                    "task_id": 1,
                    "task_status": "completed",
                    "task_updated_date": "2026-01-02T00:00:00+00:00",
                },
                {
                    "task_id": 1,
                    "task_status": "completed",
                    "task_updated_date": "2026-01-03T00:00:00+00:00",
                },
                {
                    "task_id": None,
                    "task_status": "annotation",
                    "task_updated_date": "2026-01-04T00:00:00+00:00",
                },
            ]
        )

        baseline = compute_baseline(df, tmp_path / "dataset.csv")

        assert baseline.known_task_ids == {1}
        assert baseline.cutoff == "2026-01-03T00:00:00+00:00"


# ---------------------------------------------------------------------------
# CLI smoke: run_whats_new
# ---------------------------------------------------------------------------


def test_run_whats_new_empty_date_column_exits(tmp_path: Path) -> None:
    """A ``compute_cutoff`` error propagates to the CLI boundary."""
    csv_path = write_dataset_csv(
        tmp_path / "dataset.csv",
        [
            {
                "task_id": 1,
                "task_status": "completed",
                "task_updated_date": None,
            },
        ],
    )

    def make_client(cfg: CvatConfig, **_kw: object) -> CvatClient:
        return CvatClient(cfg, api=FakeCvatApi.from_tasks([]))

    args = parse_cli_args("whats-new", "-p", "1", "-d", str(csv_path))
    with (
        patch_cli_client(factory=make_client, config=CFG),
        pytest.raises(Cveta2Error, match="пуст"),
    ):
        run_whats_new(args)
