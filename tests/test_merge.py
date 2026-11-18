"""Unit tests for merge: split propagation, by-task resolution, and I/O."""

import argparse
import re
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from cveta2.adapters.files.dataset import read_deleted_names as _read_deleted_names
from cveta2.adapters.files.dataset import write_partition_csvs
from cveta2.application.use_cases.merge import merge_datasets as merge_with_files
from cveta2.composition.conversion import merge_datasets
from cveta2.domain.errors import Cveta2Error
from cveta2.domain.merge import _merge_datasets, _propagate_splits, _resolve_by_task, reopened_images
from cveta2.domain.partition import partition_annotations_df
from tests.helpers import csv_row, make_args, make_deleted, make_df, write_dataset_csv

_ID_OLD = 10
_ID_NEW = 20


def _row(image: str, label: str = "cat", split: str | None = None) -> dict[str, object]:
    return csv_row(image, label=label, split=split)


def _trow(
    image: str,
    task_id: object = None,
    label: str = "cat",
    split: str | None = None,
) -> dict[str, object]:
    """Row helper that always includes task_id."""
    d = _row(image, label=label, split=split)
    d["task_id"] = task_id
    return d


def _no_task_id_row(image: str) -> dict[str, object]:
    row = _row(image)
    del row["task_id"]
    return row


# ---------------------------------------------------------------------------
# Merge precedence and split propagation — property over _merge_datasets
# ---------------------------------------------------------------------------

_IMAGES = ["a.jpg", "b.jpg", "c.jpg"]
# One annotation row: (image, task id, split).
_Row = tuple[str, int, str | None]
_side = st.lists(
    st.tuples(
        st.sampled_from(_IMAGES),
        st.integers(1, 3),
        st.sampled_from([None, "train", "val"]),
    ),
    max_size=5,
)


def _frame(side: str, rows: list[_Row]) -> pd.DataFrame:
    """Rows labelled ``<side><index>`` so each merged row names its origin."""
    return pd.DataFrame(
        [
            {
                "image_name": image,
                "task_id": task_id,
                "instance_label": f"{side}{i}",
                "split": split,
            }
            for i, (image, task_id, split) in enumerate(rows)
        ],
        columns=["image_name", "task_id", "instance_label", "split"],
    )


def _expected_labels(old: list[_Row], new: list[_Row], deleted: set[str], *, by_task: bool) -> list[str]:
    """Each surviving image keeps every row of exactly one side."""
    labels: list[str] = []
    for image in {r[0] for r in old} | {r[0] for r in new}:
        if image in deleted:
            continue
        old_ids = [task for name, task, _ in old if name == image]
        new_ids = [task for name, task, _ in new if name == image]
        old_wins = not new_ids or (by_task and bool(old_ids) and max(old_ids) > max(new_ids))
        side, rows = ("old", old) if old_wins else ("new", new)
        labels += [f"{side}{i}" for i, r in enumerate(rows) if r[0] == image]
    return sorted(labels)


@given(
    old=_side,
    new=_side,
    deleted=st.sets(st.sampled_from(_IMAGES)),
    by_task=st.booleans(),
)
# Either side, or both, may be empty.
@example(old=[], new=[], deleted=set(), by_task=True)
@example(old=[("a.jpg", 1, "train")], new=[], deleted=set(), by_task=False)
@example(old=[], new=[("a.jpg", 1, None)], deleted=set(), by_task=True)
# Default mode ignores task ids: new wins although old holds the later task.
@example(old=[("a.jpg", 3, "train")], new=[("a.jpg", 1, None)], deleted=set(), by_task=False)
# By-task mode: the later task wins, deleted images stay out even then.
@example(
    old=[("a.jpg", 3, None), ("b.jpg", 3, "val")],
    new=[("a.jpg", 1, None), ("b.jpg", 1, None), ("c.jpg", 1, None)],
    deleted={"a.jpg"},
    by_task=True,
)
# Every row of a multi-row image gets the old split; new-only rows stay empty.
@example(
    old=[("a.jpg", 1, "train")],
    new=[("a.jpg", 1, None), ("a.jpg", 2, None), ("b.jpg", 1, None)],
    deleted=set(),
    by_task=False,
)
def test_merge_keeps_one_side_per_image_and_fills_split_from_old(
    old: list[_Row], new: list[_Row], deleted: set[str], *, by_task: bool
) -> None:
    merged = _merge_datasets(_frame("old", old), _frame("new", new), deleted, by_task=by_task)

    assert sorted(merged["instance_label"]) == _expected_labels(old, new, deleted, by_task=by_task)
    assert merged.index.equals(pd.RangeIndex(len(merged)))
    first_old_split: dict[str, str] = {}
    for image, _, split in old:
        if split is not None:
            first_old_split.setdefault(image, split)
    sources = {"old": old, "new": new}
    for label, image, split in merged[["instance_label", "image_name", "split"]].itertuples(index=False):
        own = sources[label[:3]][int(label[3:])][2]
        expected = own if own is not None else first_old_split.get(image)
        assert (split if pd.notna(split) else None) == expected


# ---------------------------------------------------------------------------
# Split propagation — _propagate_splits directly
# ---------------------------------------------------------------------------


class TestPropagateSplits:
    """Tests for the _propagate_splits helper."""

    def test_partial_propagation_keeps_the_winner_split(self) -> None:
        """Rows with null split get propagated; existing split kept."""
        old = make_df([_row("a.jpg", split="train"), _row("b.jpg", split="val")])
        new = make_df([_row("a.jpg", split="test"), _row("b.jpg")])

        result = _propagate_splits(new.copy(), old, new, {"a.jpg", "b.jpg"})

        splits = result.set_index("image_name")["split"].to_dict()
        assert splits == {"a.jpg": "test", "b.jpg": "val"}

    @pytest.mark.parametrize("old_has_column", [False, True])
    def test_no_old_split_data_warns_and_changes_nothing(
        self, capture_logs: list[str], *, old_has_column: bool
    ) -> None:
        old = make_df([_row("a.jpg")])
        if not old_has_column:
            old = old.drop(columns=["split"])
        new = make_df([_row("a.jpg")])

        result = _propagate_splits(new.copy(), old, new, {"a.jpg"})

        assert pd.isna(result["split"].iloc[0])
        assert any("нет данных split" in m for m in capture_logs)

    @pytest.mark.parametrize(("new_split", "conflict"), [("test", True), (None, False)])
    def test_conflict_warning_only_when_both_sides_have_split(
        self, capture_logs: list[str], new_split: str | None, *, conflict: bool
    ) -> None:
        old = make_df([_row("a.jpg", split="train")])
        new = make_df([_row("a.jpg", split=new_split)])

        _propagate_splits(new.copy(), old, new, {"a.jpg"})

        warned = any("split задан в обоих датасетах" in m for m in capture_logs)
        assert warned is conflict

    def test_first_old_row_wins_for_duplicate_image(self) -> None:
        """When old has two split values for one image, the first one is used."""
        old = make_df([_row("a.jpg", split="train"), _row("a.jpg", split="val")])
        new = make_df([_row("a.jpg")])

        result = _propagate_splits(new.copy(), old, new, {"a.jpg"})

        assert result["split"].iloc[0] == "train"


# ---------------------------------------------------------------------------
# By-task resolution — _resolve_by_task edge cases the property cannot reach
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("old_id", "new_id", "new_wins"),
    [
        ("not-an-id", _ID_NEW, True),
        (_ID_OLD, "not-an-id", True),
        ("garbage", "garbage", True),
        # Ids read from a CSV are numbers: as text "9" sorts above "100".
        ("100", "9", False),
    ],
    ids=["unusable-old", "unusable-new", "both-unusable", "numeric-not-text"],
)
def test_resolve_by_task_edge_ids(old_id: object, new_id: object, *, new_wins: bool) -> None:
    old = make_df([_trow("a.jpg", task_id=old_id)])
    new = make_df([_trow("a.jpg", task_id=new_id)])

    assert _resolve_by_task(old, new, {"a.jpg"}) == ({"a.jpg"} if new_wins else set())


# ---------------------------------------------------------------------------
# I/O helpers — _read_deleted_names
# ---------------------------------------------------------------------------


class TestReadDeletedNames:
    """Tests for _read_deleted_names."""

    def test_none_returns_empty_set(self) -> None:
        assert _read_deleted_names(None) == set()

    @pytest.mark.parametrize(
        ("name", "content", "expected"),
        [
            # The extra column makes the CSV and line-per-name readers disagree.
            (
                "deleted.csv",
                "image_name,reason\na.jpg,dup\nb.jpg,blurred\na.jpg,dup\n",
                {"a.jpg", "b.jpg"},
            ),
            ("deleted.txt", "a.jpg\nb.jpg\n  \nc.jpg\n", {"a.jpg", "b.jpg", "c.jpg"}),
            ("deleted.txt", "\n  \n", set()),
        ],
        ids=["csv", "legacy-text", "blank-lines"],
    )
    def test_reads_names(self, tmp_path: Path, name: str, content: str, expected: set[str]) -> None:
        path = tmp_path / name
        path.write_text(content, encoding="utf-8")

        assert _read_deleted_names(path) == expected

    @pytest.mark.parametrize("content", [None, 'image_name\n"unterminated,quote\n'])
    def test_unreadable_file_error_names_the_file(self, tmp_path: Path, content: str | None) -> None:
        path = tmp_path / "deleted.csv"
        if content is not None:
            path.write_text(content, encoding="utf-8")

        with pytest.raises(Cveta2Error, match=re.escape(str(path))):
            _read_deleted_names(path)


# ---------------------------------------------------------------------------
# Application use case — in-memory dataset port
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("by_task", "label"), [(False, "new"), (True, "old")])
def test_merge_use_case_works_through_the_files_port(*, by_task: bool, label: str) -> None:
    """Paths are only handed to the port; the merged frame is what is saved."""
    old = pd.DataFrame([{"image_name": "same.jpg", "task_id": 9, "instance_label": "old"}])
    new = pd.DataFrame([{"image_name": "same.jpg", "task_id": 2, "instance_label": "new"}])
    writes: list[tuple[pd.DataFrame, Path]] = []
    reads: list[bool] = []

    def read_dataset_csv(path: Path, _columns: object, *, require_task_id_column: bool) -> pd.DataFrame:
        reads.append(require_task_id_column)
        return old if path.name == "old.csv" else new

    files = SimpleNamespace(
        read_dataset_csv=read_dataset_csv,
        read_deleted_names=lambda _path: set(),
        save_csv=lambda df, path: writes.append((df, path)),
    )
    result = merge_with_files(
        "/missing/old.csv",
        "/missing/new.csv",
        "/missing/result.csv",
        by_task=by_task,
        files=files,
    )
    assert result["instance_label"].tolist() == [label]
    assert reads == [by_task, by_task]
    assert writes == [(result, Path("/missing/result.csv"))]


# ---------------------------------------------------------------------------
# Public entry point — merge_datasets (path-based I/O)
# ---------------------------------------------------------------------------


class TestMergeDatasetsIO:
    """Tests for merge_datasets with real temp files."""

    def test_nested_output_gets_merged_rows_with_propagated_split(self, tmp_path: Path) -> None:
        old_path = tmp_path / "old.csv"
        new_path = tmp_path / "new.csv"
        out_path = tmp_path / "runs" / "2026-01" / "merged.csv"
        write_dataset_csv(old_path, [_row("a.jpg", split="train")])
        write_dataset_csv(new_path, [_row("a.jpg"), _row("b.jpg")])

        merge_datasets(old_path, new_path, out_path)

        result = pd.read_csv(out_path)
        assert set(result["image_name"]) == {"a.jpg", "b.jpg"}
        a_split = result.loc[result["image_name"] == "a.jpg", "split"].iloc[0]
        assert a_split == "train"

    def test_merge_with_deleted(self, tmp_path: Path) -> None:
        old_path = tmp_path / "old.csv"
        new_path = tmp_path / "new.csv"
        del_path = tmp_path / "deleted.csv"
        out_path = tmp_path / "merged.csv"
        write_dataset_csv(old_path, [_row("a.jpg"), _row("b.jpg")])
        write_dataset_csv(new_path, [_row("a.jpg"), _row("c.jpg")])
        del_path.write_text("image_name\na.jpg\n", encoding="utf-8")

        merge_datasets(old_path, new_path, out_path, deleted=del_path)

        assert set(pd.read_csv(out_path)["image_name"]) == {"b.jpg", "c.jpg"}

    @pytest.mark.parametrize(("by_task", "label"), [(None, "new_label"), (True, "old_label")])
    def test_by_task_flag_decides_the_winner(self, tmp_path: Path, label: str, *, by_task: bool | None) -> None:
        old_path = tmp_path / "old.csv"
        new_path = tmp_path / "new.csv"
        out_path = tmp_path / "merged.csv"
        write_dataset_csv(old_path, [_trow("a.jpg", task_id=_ID_NEW, label="old_label")])
        write_dataset_csv(new_path, [_trow("a.jpg", task_id=_ID_OLD, label="new_label")])

        if by_task is None:  # the flag left at its default
            merge_datasets(old_path, new_path, out_path)
        else:
            merge_datasets(old_path, new_path, out_path, by_task=by_task)

        assert pd.read_csv(out_path).iloc[0]["instance_label"] == label

    @pytest.mark.parametrize("missing", ["old", "new"])
    def test_by_task_missing_column_names_the_file(self, tmp_path: Path, missing: str) -> None:
        """--by-task validates both CSVs before any id is compared."""
        paths = {"old": tmp_path / "old.csv", "new": tmp_path / "new.csv"}
        for side, path in paths.items():
            row = _no_task_id_row("a.jpg") if side == missing else _trow("a.jpg", task_id=_ID_NEW)
            write_dataset_csv(path, [row])

        with pytest.raises(Cveta2Error, match=re.escape(str(paths[missing]))):
            merge_datasets(paths["old"], paths["new"], tmp_path / "merged.csv", by_task=True)


class TestMergeReopenedImages:
    """``in_progress`` drops old images the new fetch reports as reopened after a completed deletion."""

    @staticmethod
    def _fetch(tmp_path: Path, rows: list[tuple[str, int, bool]], deletions: list[tuple[str, int, bool]]) -> Path:
        """Partition fetched rows into the four CSVs, as ``cveta2 fetch`` writes them."""
        frame = make_df(
            [
                csv_row(image, task_id=task, status="completed" if done else "annotation", task_completed=done)
                for image, task, done in rows
            ]
        )
        records = [
            make_deleted(image, task, "2026-01-01", "completed" if done else "annotation").model_copy(
                update={"task_completed": done}
            )
            for image, task, done in deletions
        ]
        out = tmp_path / "new"
        write_partition_csvs(partition_annotations_df(frame, records), out)
        return out

    def _merge(self, tmp_path: Path, new: Path, *, with_in_progress: bool) -> set[str]:
        old = tmp_path / "old.csv"
        write_dataset_csv(old, [_trow("a.jpg", task_id=3, label="old_a"), _trow("b.jpg", task_id=4, label="old_b")])
        out = tmp_path / "merged.csv"
        merge_datasets(
            old,
            new / "dataset.csv",
            out,
            deleted=new / "deleted.csv",
            in_progress=new / "in_progress.csv" if with_in_progress else None,
        )
        merged = pd.read_csv(out)
        return set(merged["image_name"] + ":" + merged["instance_label"])

    @pytest.mark.parametrize(
        ("rows", "deletions"),
        [
            # Case 1: completed 3 annotates, completed 5 deletes, unfinished 9 holds it again.
            pytest.param([("a.jpg", 3, True), ("a.jpg", 9, False)], [("a.jpg", 5, True)], id="case-1"),
            # Task 5 annotated and then deleted the frame itself: no completed boxes are carried.
            pytest.param([("a.jpg", 5, True), ("a.jpg", 9, False)], [("a.jpg", 5, True)], id="deleted-by-its-own-task"),
            # No completed task ever held the frame as a non-deleted one.
            pytest.param([("a.jpg", 9, False)], [("a.jpg", 5, True)], id="no-completed-boxes"),
        ],
    )
    def test_a_reopened_image_is_dropped_only_with_the_in_progress_file(
        self, tmp_path: Path, rows: list[tuple[str, int, bool]], deletions: list[tuple[str, int, bool]]
    ) -> None:
        new = self._fetch(tmp_path, rows, deletions)

        assert self._merge(tmp_path, new, with_in_progress=False) == {"a.jpg:old_a", "b.jpg:old_b"}
        assert self._merge(tmp_path, new, with_in_progress=True) == {"b.jpg:old_b"}

    def test_the_python_api_forwards_the_in_progress_file(self, tmp_path: Path) -> None:
        import cveta2

        new = self._fetch(tmp_path, [("a.jpg", 9, False)], [("a.jpg", 5, True)])
        old = tmp_path / "old.csv"
        write_dataset_csv(old, [_trow("a.jpg", task_id=3, label="old_a"), _trow("b.jpg", task_id=4, label="old_b")])

        merged = cveta2.merge(old, new / "dataset.csv", tmp_path / "merged.csv", in_progress=new / "in_progress.csv")

        assert merged["image_name"].tolist() == ["b.jpg"]

    def test_a_pending_unfinished_deletion_drops_nothing(self, tmp_path: Path) -> None:
        """Completed 3 annotates, unfinished 9 deletes: the deletion waits, the boxes stay."""
        new = self._fetch(tmp_path, [("a.jpg", 3, True), ("a.jpg", 9, False)], [("a.jpg", 9, False)])

        assert self._merge(tmp_path, new, with_in_progress=True) == {"a.jpg:cat", "b.jpg:old_b"}

    def test_an_in_progress_file_of_an_older_cveta2_drops_nothing(self, tmp_path: Path) -> None:
        """Rows without task_completed carry no reopen marker."""
        new = self._fetch(tmp_path, [("c.jpg", 4, True)], [])
        legacy = pd.DataFrame([{"image_name": "a.jpg", "task_id": 9, "instance_shape": "box"}])
        legacy.to_csv(new / "in_progress.csv", index=False)

        assert self._merge(tmp_path, new, with_in_progress=True) == {"a.jpg:old_a", "b.jpg:old_b", "c.jpg:cat"}

    def test_the_cli_option_reaches_the_merge(self, tmp_path: Path) -> None:
        from cveta2.interfaces.commands.merge import configure_merge, run_merge

        new = self._fetch(tmp_path, [("a.jpg", 3, True), ("a.jpg", 9, False)], [("a.jpg", 5, True)])
        old = tmp_path / "old.csv"
        write_dataset_csv(old, [_trow("a.jpg", task_id=3, label="old_a")])
        parser = argparse.ArgumentParser()
        configure_merge(parser)
        out = tmp_path / "merged.csv"
        argv = ["--old", str(old), "--new", str(new / "dataset.csv"), "-o", str(out)]

        run_merge(parser.parse_args([*argv, "--in-progress", str(new / "in_progress.csv")]))

        assert pd.read_csv(out).empty

    @pytest.mark.parametrize(
        ("rows", "expected"),
        [
            # Plain re-annotation: completed 3 stays in dataset.csv, unfinished 9 waits.
            pytest.param([("a.jpg", 3, True), ("a.jpg", 9, False)], {"a.jpg:cat", "b.jpg:old_b"}, id="reannotation"),
            # The image's only task went back from completed to unfinished.
            pytest.param([("a.jpg", 3, False)], {"a.jpg:old_a", "b.jpg:old_b"}, id="task-sent-back"),
            # The new fetch has nothing for the old image at all.
            pytest.param([("c.jpg", 4, True)], {"a.jpg:old_a", "b.jpg:old_b", "c.jpg:cat"}, id="absent-from-fetch"),
        ],
    )
    def test_presence_in_progress_alone_drops_nothing(
        self, tmp_path: Path, rows: list[tuple[str, int, bool]], expected: set[str]
    ) -> None:
        new = self._fetch(tmp_path, rows, [])

        assert self._merge(tmp_path, new, with_in_progress=True) == expected
        assert self._merge(tmp_path, new, with_in_progress=False) == expected


@pytest.mark.parametrize(
    ("flags", "expected"),
    [
        pytest.param([True, False, None], {"r0"}, id="parsed-booleans"),
        pytest.param(["True", "true", "False", ""], {"r0", "r1"}, id="text"),
        pytest.param(["True", "odd", "1"], {"r0"}, id="text-with-an-odd-cell"),
        pytest.param([1, 0, 1.0], set(), id="numbers-are-not-markers"),
    ],
)
def test_only_explicitly_true_rows_mark_a_reopened_image(flags: list[object], expected: set[str]) -> None:
    """Strict: counting a non-marker would wrongly drop old boxes."""
    in_progress = pd.DataFrame({"image_name": [f"r{i}" for i in range(len(flags))], "task_completed": flags})

    assert reopened_images(in_progress) == expected


# ---------------------------------------------------------------------------
# CLI smoke — run_merge error path
# ---------------------------------------------------------------------------


def test_run_merge_by_task_missing_column_exits(tmp_path: Path) -> None:
    """A merge-logic error propagates to the CLI boundary."""
    from cveta2.interfaces.commands.merge import run_merge

    old_path = tmp_path / "old.csv"
    new_path = tmp_path / "new.csv"
    write_dataset_csv(old_path, [_no_task_id_row("a.jpg")])
    write_dataset_csv(new_path, [_no_task_id_row("a.jpg")])

    args = make_args(
        old=str(old_path),
        new=str(new_path),
        output=str(tmp_path / "merged.csv"),
        deleted=None,
        in_progress=None,
        by_task=True,
    )

    with pytest.raises(Cveta2Error):
        run_merge(args)
