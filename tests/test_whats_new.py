"""Tests for the ``cveta2 whats-new`` command and its client method."""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING
from unittest.mock import patch

import pandas as pd
import pytest

from cveta2.client import CvatClient
from cveta2.commands.whats_new import run_whats_new
from cveta2.config import CvatConfig
from cveta2.exceptions import Cveta2Error
from cveta2.services.whats_new import compute_cutoff
from tests.fixtures.fake_cvat_api import FakeCvatApi
from tests.helpers import CFG, make_task, write_dataset_csv

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


# ---------------------------------------------------------------------------
# CLI smoke: run_whats_new
# ---------------------------------------------------------------------------


def test_run_whats_new_empty_date_column_exits(tmp_path: Path) -> None:
    """The adapter maps a ``compute_cutoff`` error onto ``SystemExit``."""
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

    args = argparse.Namespace(project="1", dataset=str(csv_path))
    with (
        patch("cveta2.commands._bootstrap.CvatConfig.load", return_value=CFG),
        patch("cveta2.commands._bootstrap.require_host"),
        patch("cveta2.commands._helpers.load_projects_cache", return_value=[]),
        patch("cveta2.commands._bootstrap.CvatClient", side_effect=make_client),
        pytest.raises(SystemExit, match="пуст"),
    ):
        run_whats_new(args)
