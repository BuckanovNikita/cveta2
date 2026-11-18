"""Tests for the ``cveta2 whats-new`` command and its client method."""

from pathlib import Path

import pandas as pd
import pytest

from cveta2.adapters.config.settings import CvatConfig
from cveta2.composition.client import CvatClient
from cveta2.composition.conversion import compute_baseline
from cveta2.composition.files import read_dataset_csv
from cveta2.domain.baseline import REQUIRED_COLUMNS, compute_cutoff
from cveta2.domain.errors import Cveta2Error
from cveta2.domain.models import TaskInfo
from cveta2.interfaces.commands.whats_new import run_whats_new
from tests.fixtures.fake_cvat_api import FakeCvatApi
from tests.helpers import (
    CFG,
    make_task,
    parse_cli_args,
    patch_cli_client,
    write_dataset_csv,
)


def _client_with_tasks(tasks: list[TaskInfo]) -> CvatClient:
    """Create a CvatClient whose fake API returns the given tasks."""
    return CvatClient(CvatConfig(), api=FakeCvatApi.from_tasks(tasks))


def _row(task_id: object, *, completed: bool = True) -> dict[str, object]:
    """Build the three columns ``compute_cutoff`` reads."""
    stage, state = ("acceptance", "completed") if completed else ("annotation", "new")
    return {"task_id": task_id, "job_stage": stage, "job_state": state}


# ---------------------------------------------------------------------------
# Client method: list_new_completed_tasks
# ---------------------------------------------------------------------------


class TestListNewCompletedTasks:
    """Tests for ``CvatClient.list_new_completed_tasks``."""

    @pytest.mark.parametrize(
        ("tasks", "cutoff", "known", "expected_ids"),
        [
            pytest.param(
                [
                    make_task(1, status="annotation"),
                    make_task(2, status="validation"),
                    make_task(3, status="completed"),
                ],
                0,
                set(),
                [3],
                id="only-completed-tasks-qualify",
            ),
            pytest.param(
                [make_task(1), make_task(2), make_task(3)],
                2,
                {1, 2},
                [3],
                id="ids-at-or-below-the-cutoff-are-known",
            ),
            pytest.param(
                [make_task(40), make_task(58)],
                57,
                {57},
                [40, 58],
                id="a-task-the-fetch-never-saw-is-reported-below-the-cutoff",
            ),
            pytest.param(
                [make_task(8), make_task(6), make_task(7)],
                0,
                set(),
                [6, 7, 8],
                id="result-is-sorted-by-id",
            ),
        ],
    )
    def test_filters_and_sorts(
        self,
        tasks: list[TaskInfo],
        cutoff: int,
        known: set[int],
        expected_ids: list[int],
    ) -> None:
        client = _client_with_tasks(tasks)

        result = client.list_new_completed_tasks(1, cutoff, known)

        assert [t.id for t in result] == expected_ids

    def test_a_bumped_updated_date_reports_nothing(self) -> None:
        """Editing project labels must not resurrect every completed task.

        A label edit rewrites ``updated_date`` on every task at once, which
        is what made a date cutoff report the whole project as new.
        """
        tasks = [
            make_task(1, updated="2026-09-09T00:00:00+00:00"),
            make_task(2, updated="2026-09-09T00:00:00+00:00"),
        ]
        client = _client_with_tasks(tasks)

        assert client.list_new_completed_tasks(1, 2, {1, 2}) == []


# ---------------------------------------------------------------------------
# Cutoff computation: compute_cutoff
# ---------------------------------------------------------------------------


class TestComputeCutoff:
    """Tests for ``compute_cutoff``."""

    @pytest.mark.parametrize(
        ("rows", "expected"),
        [
            # Non-completed rows must not push the cutoff forward.
            ([_row(1), _row(2, completed=False)], 1),
            ([_row(1, completed=False), _row(2, completed=False)], 2),
            # As text "9" would rank above "100".
            ([_row("9"), _row("100")], 100),
            # An id-less completed row must not win; all rows are the fallback.
            ([_row(None), _row(6, completed=False)], 6),
        ],
        ids=["completed-only", "no-completed", "numeric", "id-less-completed"],
    )
    def test_cutoff(self, tmp_path: Path, rows: list[dict[str, object]], expected: int) -> None:
        assert compute_cutoff(pd.DataFrame(rows), tmp_path / "dataset.csv") == expected

    @pytest.mark.parametrize(
        "rows",
        [[_row(None)], [_row("not-an-id"), _row("also-not", completed=False)]],
        ids=["missing", "non-numeric"],
    )
    def test_unusable_task_ids_raise(self, tmp_path: Path, rows: list[dict[str, object]]) -> None:
        with pytest.raises(Cveta2Error, match="пуст"):
            compute_cutoff(pd.DataFrame(rows), tmp_path / "dataset.csv")

    def test_baseline_reports_the_csv_path_when_ids_are_unusable(self, tmp_path: Path) -> None:
        """compute_baseline must forward its own path into the error message.

        The path is used nowhere else, so passing None instead is invisible
        until a user hits the error and is told the column is empty in
        ``None``.
        """
        csv_path = tmp_path / "dataset.csv"
        df = pd.DataFrame([_row(None)])

        with pytest.raises(Cveta2Error, match=str(csv_path)):
            compute_baseline(df, csv_path)

    def test_baseline_collects_known_task_ids(self, tmp_path: Path) -> None:
        df = pd.DataFrame([_row(1), _row(1), _row(None, completed=False)])

        baseline = compute_baseline(df, tmp_path / "dataset.csv")

        assert baseline.known_task_ids == {1}
        assert baseline.cutoff == 1

    def test_baseline_also_reads_obsolete_and_deleted_but_not_in_progress(self, tmp_path: Path) -> None:
        """A task living only in obsolete.csv or deleted.csv is known, not new.

        Reading dataset.csv alone would leave every superseded task absent
        from ``known_task_ids``, so the unknown-id sweep would report them
        on every single run.  An unfinished task in ``in_progress.csv``
        stays unknown: once it completes it is exactly what whats-new
        exists to report.
        """
        write_dataset_csv(tmp_path / "obsolete.csv", [_row(4)])
        write_dataset_csv(tmp_path / "in_progress.csv", [_row(5, completed=False)])
        write_dataset_csv(tmp_path / "deleted.csv", [_row(6)])
        df = pd.DataFrame([_row(7)])

        baseline = compute_baseline(df, tmp_path / "dataset.csv")

        assert baseline.known_task_ids == {4, 6, 7}
        assert baseline.cutoff == 7

    def test_completed_boxes_waiting_in_progress_are_known(self, tmp_path: Path) -> None:
        """A completed task whose boxes wait in in_progress.csv is not new.

        Its image was deleted by a completed task and reopened by a newer
        unfinished one, so task 3 now appears only in in_progress.csv.
        Only rows that explicitly say their task completed count: task 4
        has an unfinished row too, and task 5's legacy row says nothing
        about the whole task.
        """
        write_dataset_csv(
            tmp_path / "in_progress.csv",
            [
                {**_row(3), "task_completed": True},
                {**_row(4), "task_completed": True},
                {**_row(4, completed=False), "task_completed": False},
                _row(5),
                {**_row(9, completed=False), "task_completed": False},
            ],
        )
        baseline = compute_baseline(pd.DataFrame([_row(7)]), tmp_path / "dataset.csv")
        client = _client_with_tasks([make_task(3), make_task(4), make_task(5), make_task(7), make_task(9)])

        assert baseline.known_task_ids == {3, 7}
        result = client.list_new_completed_tasks(1, baseline.cutoff, baseline.known_task_ids)
        assert [task.id for task in result] == [4, 5, 9]

    def test_a_task_in_progress_at_fetch_time_is_reported_once_completed(self, tmp_path: Path) -> None:
        """The baseline and the client together must surface the promised case.

        Task 5 sat in ``in_progress.csv`` when the dataset was written and
        has a lower id than the cutoff, so only the unknown-id half of the
        filter can report it after CVAT marks it completed.
        """
        write_dataset_csv(tmp_path / "in_progress.csv", [_row(5, completed=False)])
        df = pd.DataFrame([_row(7)])
        client = _client_with_tasks([make_task(5), make_task(7)])

        baseline = compute_baseline(df, tmp_path / "dataset.csv")
        result = client.list_new_completed_tasks(1, baseline.cutoff, baseline.known_task_ids)

        assert [t.id for t in result] == [5]

    @pytest.mark.parametrize("sibling", ["obsolete.csv", "deleted.csv"])
    def test_known_task_above_dataset_cutoff_is_not_reported(self, tmp_path: Path, sibling: str) -> None:
        write_dataset_csv(tmp_path / sibling, [_row(20)])
        baseline = compute_baseline(pd.DataFrame([_row(10)]), tmp_path / "dataset.csv")
        client = _client_with_tasks([make_task(5), make_task(10), make_task(20), make_task(30)])

        result = client.list_new_completed_tasks(1, baseline.cutoff, baseline.known_task_ids)

        assert baseline.cutoff == 10
        assert baseline.known_task_ids == {10, 20}
        assert [task.id for task in result] == [5, 30]

    @pytest.mark.parametrize("source", ["dataset.csv", "deleted.csv", "obsolete.csv"])
    def test_unfinished_rows_remain_eligible_after_completion(self, tmp_path: Path, source: str) -> None:
        rows = [_row(1)]
        unfinished = _row(2, completed=False)
        if source == "dataset.csv":
            rows.append(unfinished)
        else:
            write_dataset_csv(tmp_path / source, [unfinished])
        baseline = compute_baseline(pd.DataFrame(rows), tmp_path / "dataset.csv")
        client = _client_with_tasks([make_task(1), make_task(2)])

        assert baseline.known_task_ids == {1}
        assert [task.id for task in client.list_new_completed_tasks(1, baseline.cutoff, baseline.known_task_ids)] == [2]

    @pytest.mark.parametrize("legacy", [True, False])
    def test_unfinished_evidence_overrides_known_sibling_membership(self, tmp_path: Path, *, legacy: bool) -> None:
        write_dataset_csv(tmp_path / "obsolete.csv", [{"task_id": 2}] if legacy else [_row(2)])
        write_dataset_csv(tmp_path / "deleted.csv", [_row(2, completed=False)])
        baseline = compute_baseline(pd.DataFrame([_row(1)]), tmp_path / "dataset.csv")

        assert baseline.known_task_ids == {1}

    @pytest.mark.parametrize("source", ["dataset.csv", "obsolete.csv"])
    def test_later_completed_sibling_preserves_earlier_unfinished_evidence(self, tmp_path: Path, source: str) -> None:
        rows = [_row(1)]
        unfinished = _row(2, completed=False)
        if source == "dataset.csv":
            rows.append(unfinished)
        else:
            write_dataset_csv(tmp_path / source, [unfinished])
        write_dataset_csv(tmp_path / "deleted.csv", [_row(2)])

        baseline = compute_baseline(pd.DataFrame(rows), tmp_path / "dataset.csv")

        assert baseline.known_task_ids == {1}

    def test_legacy_id_only_sibling_still_records_completed_task(self, tmp_path: Path) -> None:
        write_dataset_csv(tmp_path / "deleted.csv", [{"task_id": 20}])
        baseline = compute_baseline(pd.DataFrame([_row(1)]), tmp_path / "dataset.csv")
        assert baseline.known_task_ids == {1, 20}

    @pytest.mark.parametrize(
        "obsolete",
        [None, 'a,b\n"unclosed\n', b"image_name,task_id\n\xff\xfe,6\n"],
        ids=["missing", "malformed", "invalid-utf8"],
    )
    def test_a_missing_or_unreadable_sibling_does_not_stop_the_later_ones(
        self, tmp_path: Path, obsolete: str | bytes | None
    ) -> None:
        """A bad obsolete.csv costs its own ids; deleted.csv after it is still read."""
        if isinstance(obsolete, bytes):
            (tmp_path / "obsolete.csv").write_bytes(obsolete)
        elif obsolete is not None:
            (tmp_path / "obsolete.csv").write_text(obsolete, encoding="utf-8")
        write_dataset_csv(tmp_path / "deleted.csv", [_row(6)])
        df = pd.DataFrame([_row(7)])

        baseline = compute_baseline(df, tmp_path / "dataset.csv")

        assert baseline.known_task_ids == {6, 7}

    @pytest.mark.parametrize("bad_cell", ["abc", "13.5", "inf", "-inf"])
    def test_unusable_task_id_cells_are_ignored(self, tmp_path: Path, bad_cell: str) -> None:
        """One unusable cell must neither fail the run nor hide the completed tasks.

        A string cell turns the column into text, so the completed-task match
        must compare numbers or the cutoff silently falls back to unfinished 20.
        """
        header = "image_name,task_id,job_stage,job_state\n"
        csv_path = tmp_path / "dataset.csv"
        csv_path.write_text(
            header
            + "a.jpg,12,acceptance,completed\n"
            + "b.jpg,15,acceptance,completed\n"
            + "c.jpg,20,annotation,new\n"
            + f"d.jpg,{bad_cell},acceptance,completed\n",
            encoding="utf-8",
        )
        (tmp_path / "obsolete.csv").write_text(header + f"e.jpg,{bad_cell},acceptance,completed\n", encoding="utf-8")

        baseline = compute_baseline(read_dataset_csv(csv_path, REQUIRED_COLUMNS), csv_path)

        assert baseline.cutoff == 15
        assert baseline.known_task_ids == {12, 15}


# ---------------------------------------------------------------------------
# CLI smoke: run_whats_new
# ---------------------------------------------------------------------------


def test_run_whats_new_empty_task_id_column_exits(tmp_path: Path) -> None:
    """A ``compute_cutoff`` error propagates to the CLI boundary."""
    csv_path = write_dataset_csv(tmp_path / "dataset.csv", [_row(None)])

    def make_client(cfg: CvatConfig, **_kw: object) -> CvatClient:
        return CvatClient(cfg, api=FakeCvatApi.from_tasks([]))

    args = parse_cli_args("whats-new", "-p", "1", "-d", str(csv_path))
    with (
        patch_cli_client(factory=make_client, config=CFG),
        pytest.raises(Cveta2Error, match="пуст"),
    ):
        run_whats_new(args)
