"""Tests for the ``cveta2 whats-new`` command and its client method."""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from loguru import logger

from cveta2.client import CvatClient
from cveta2.commands.whats_new import run_whats_new
from cveta2.config import CvatConfig
from tests.fixtures.fake_cvat_api import FakeCvatApi
from tests.helpers import CFG, make_task, write_dataset_csv

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from cveta2.models import TaskInfo

_MODULE = "cveta2.commands.whats_new"


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
# Command tests: run_whats_new
# ---------------------------------------------------------------------------


@pytest.fixture
def info_logs() -> Generator[list[str], None, None]:
    """Capture loguru messages at INFO+ level into a list of strings."""
    messages: list[str] = []
    handler_id = logger.add(
        lambda msg: messages.append(msg.record["message"]), level="INFO"
    )
    try:
        yield messages
    finally:
        logger.remove(handler_id)


def _run_whats_new_with_fake(
    tasks: list[TaskInfo],
    dataset_path: Path,
) -> None:
    """Execute ``run_whats_new`` backed by fake CVAT data."""
    fake_api = FakeCvatApi.from_tasks(tasks)

    def make_client(cfg: CvatConfig, **_kw: object) -> CvatClient:
        return CvatClient(cfg, api=fake_api)

    args = argparse.Namespace(project="1", dataset=str(dataset_path))
    with (
        patch("cveta2.commands._bootstrap.CvatConfig.load", return_value=CFG),
        patch("cveta2.commands._bootstrap.require_host"),
        patch("cveta2.commands._helpers.load_projects_cache", return_value=[]),
        patch("cveta2.commands._bootstrap.CvatClient", side_effect=make_client),
    ):
        run_whats_new(args)


class TestRunWhatsNew:
    """Tests for the ``run_whats_new`` command."""

    def test_cutoff_computed_from_completed_rows_only(
        self, tmp_path: Path, info_logs: list[str]
    ) -> None:
        """Non-completed CSV rows must not push the cutoff forward."""
        csv_path = write_dataset_csv(
            tmp_path / "dataset.csv",
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
            ],
        )
        tasks = [make_task(5, updated="2026-01-03T00:00:00+00:00")]

        _run_whats_new_with_fake(tasks, csv_path)

        assert any(
            "2026-01-02T00:00:00+00:00" in m and "отсечки" in m for m in info_logs
        )
        assert any(m.startswith("id=5 task-5") for m in info_logs)

    def test_marks_tasks_already_present_in_csv(
        self, tmp_path: Path, info_logs: list[str]
    ) -> None:
        csv_path = write_dataset_csv(
            tmp_path / "dataset.csv",
            [
                {
                    "task_id": 1,
                    "task_status": "completed",
                    "task_updated_date": "2026-01-02T00:00:00+00:00",
                },
            ],
        )
        tasks = [
            make_task(1, updated="2026-01-05T00:00:00+00:00"),
            make_task(7, updated="2026-01-06T00:00:00+00:00"),
        ]

        _run_whats_new_with_fake(tasks, csv_path)

        line_for_1 = next(m for m in info_logs if m.startswith("id=1 "))
        line_for_7 = next(m for m in info_logs if m.startswith("id=7 "))
        assert line_for_1.endswith("(обновлена)")
        assert "(обновлена)" not in line_for_7

    def test_no_new_tasks_logs_info_message(
        self, tmp_path: Path, info_logs: list[str]
    ) -> None:
        csv_path = write_dataset_csv(
            tmp_path / "dataset.csv",
            [
                {
                    "task_id": 1,
                    "task_status": "completed",
                    "task_updated_date": "2026-01-05T00:00:00+00:00",
                },
            ],
        )
        tasks = [
            make_task(1, updated="2026-01-05T00:00:00+00:00"),
            make_task(2, status="annotation", updated="2026-01-09T00:00:00+00:00"),
        ]

        _run_whats_new_with_fake(tasks, csv_path)

        assert any("не найдено" in m for m in info_logs)
        assert not any(m.startswith("id=") for m in info_logs)

    def test_falls_back_to_all_rows_when_no_completed(
        self, tmp_path: Path, info_logs: list[str]
    ) -> None:
        csv_path = write_dataset_csv(
            tmp_path / "dataset.csv",
            [
                {
                    "task_id": 1,
                    "task_status": "annotation",
                    "task_updated_date": "2026-01-04T00:00:00+00:00",
                },
            ],
        )
        tasks = [
            make_task(2, updated="2026-01-03T00:00:00+00:00"),
            make_task(3, updated="2026-01-05T00:00:00+00:00"),
        ]

        _run_whats_new_with_fake(tasks, csv_path)

        assert not any(m.startswith("id=2 ") for m in info_logs)
        assert any(m.startswith("id=3 ") for m in info_logs)

    def test_missing_date_column_exits(self, tmp_path: Path) -> None:
        csv_path = write_dataset_csv(
            tmp_path / "dataset.csv",
            [{"task_id": 1, "task_status": "completed"}],
        )

        with pytest.raises(SystemExit, match="task_updated_date"):
            _run_whats_new_with_fake([], csv_path)

    def test_empty_date_column_exits(self, tmp_path: Path) -> None:
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

        with pytest.raises(SystemExit, match="пуст"):
            _run_whats_new_with_fake([], csv_path)
