"""Parser-wiring and dispatch smoke tests for the cveta2 CLI."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from cveta2.cli import CliApp
from tests.helpers import parse_cli_args

if TYPE_CHECKING:
    import argparse


def _parse(argv: list[str]) -> argparse.Namespace:
    return parse_cli_args(*argv)


_PARSE_CASES: list[tuple[list[str], dict[str, object]]] = [
    (
        ["fetch", "-p", "proj", "-o", "out"],
        {
            "command": "fetch",
            "project": "proj",
            "output_dir": "out",
            "raw": False,
            "completed_only": False,
            "no_images": False,
            "images_dir": None,
            "save_tasks": False,
            "no_cache": False,
            "force": False,
        },
    ),
    (
        [
            "fetch",
            "--project",
            "1",
            "--output-dir",
            "out",
            "--raw",
            "--completed-only",
            "--no-images",
            "--images-dir",
            "imgs",
            "--save-tasks",
            "--no-cache",
            "--force",
        ],
        {
            "command": "fetch",
            "project": "1",
            "output_dir": "out",
            "raw": True,
            "completed_only": True,
            "no_images": True,
            "images_dir": "imgs",
            "save_tasks": True,
            "no_cache": True,
            "force": True,
        },
    ),
    (
        ["fetch-task", "-p", "proj", "-t", "42", "43", "-o", "out"],
        {
            "command": "fetch-task",
            "project": "proj",
            "task": ["42", "43"],
            "output_dir": "out",
            "no_cache": False,
            "force": False,
        },
    ),
    (
        ["fetch-task", "-p", "proj", "-t", "-o", "out"],
        {
            "command": "fetch-task",
            "project": "proj",
            "task": [],
            "output_dir": "out",
        },
    ),
    (
        ["convert", "--to-yolo", "-d", "ds.csv", "-o", "out"],
        {
            "command": "convert",
            "to_yolo": True,
            "from_yolo": False,
            "to_coco": False,
            "dataset": "ds.csv",
            "output": "out",
            "link_mode": "auto",
        },
    ),
    (
        [
            "convert",
            "--from-yolo",
            "-i",
            "yolo",
            "-o",
            "out.csv",
            "--names-file",
            "names.yaml",
            "--read-all-sizes",
        ],
        {
            "command": "convert",
            "to_yolo": False,
            "from_yolo": True,
            "to_coco": False,
            "input": "yolo",
            "output": "out.csv",
            "names_file": "names.yaml",
            "read_all_sizes": True,
        },
    ),
    (
        ["convert", "--to-coco", "-d", "ds.csv", "-o", "out"],
        {
            "command": "convert",
            "to_yolo": False,
            "from_yolo": False,
            "to_coco": True,
            "dataset": "ds.csv",
            "output": "out",
        },
    ),
    (
        ["merge", "--old", "a.csv", "--new", "b.csv", "-o", "m.csv", "--by-time"],
        {
            "command": "merge",
            "old": "a.csv",
            "new": "b.csv",
            "output": "m.csv",
            "deleted": None,
            "by_time": True,
        },
    ),
    (
        ["upload", "-p", "proj", "-d", "ds.csv", "--name", "t1", "--complete"],
        {
            "command": "upload",
            "project": "proj",
            "dataset": "ds.csv",
            "name": "t1",
            "complete": True,
            "mark_all_deleted": False,
            "in_progress": None,
            "image_dir": None,
            "labels": None,
        },
    ),
    (
        ["upload", "-p", "proj", "-d", "ds.csv", "--labels", "car", "person"],
        {
            "command": "upload",
            "project": "proj",
            "dataset": "ds.csv",
            "labels": ["car", "person"],
        },
    ),
    (
        ["s3-sync", "-p", "project-a", "--root", "s3://bucket/prefix"],
        {
            "command": "s3-sync",
            "project": "project-a",
            "root": "s3://bucket/prefix",
        },
    ),
    (
        ["s3-sync"],
        {"command": "s3-sync", "project": None, "root": None},
    ),
    (
        ["whats-new", "-p", "proj", "-d", "ds.csv"],
        {"command": "whats-new", "project": "proj", "dataset": "ds.csv"},
    ),
    (
        ["labels", "-p", "proj", "--list"],
        {"command": "labels", "project": "proj", "list_only": True},
    ),
    (
        [
            "task",
            "mark-deleted",
            "-p",
            "proj",
            "-t",
            "42",
            "--frame",
            "1",
            "2",
            "--image",
            "a.jpg",
        ],
        {
            "command": "task",
            "action": "mark-deleted",
            "project": "proj",
            "task": "42",
            "frame": [1, 2],
            "image": ["a.jpg"],
        },
    ),
    (
        ["task", "drop-label", "-p", "proj", "-t", "my-task", "--label", "car"],
        {
            "command": "task",
            "action": "drop-label",
            "task": "my-task",
            "label": "car",
            "yes": False,
        },
    ),
    (
        ["task", "delete", "-p", "proj", "-t", "7", "--yes"],
        {"command": "task", "action": "delete", "task": "7", "yes": True},
    ),
    (
        [
            "task",
            "status",
            "-p",
            "proj",
            "-t",
            "7",
            "--stage",
            "acceptance",
            "--state",
            "in-progress",
        ],
        {
            "command": "task",
            "action": "status",
            "task": "7",
            "stage": "acceptance",
            "state": "in-progress",
        },
    ),
    (
        ["task", "status", "-p", "proj", "-t", "7"],
        {"command": "task", "action": "status", "stage": None, "state": None},
    ),
]


@pytest.mark.parametrize(("argv", "expected"), _PARSE_CASES)
def test_parser_sets_expected_attrs(
    argv: list[str], expected: dict[str, object]
) -> None:
    args = _parse(argv)
    for attr, value in expected.items():
        assert getattr(args, attr) == value


_PARSE_ERROR_CASES: list[list[str]] = [
    ["fetch", "-p", "proj"],
    ["fetch-task", "-p", "proj", "-t", "1"],
    ["convert", "-d", "ds.csv", "-o", "out"],
    ["convert", "--to-yolo", "--from-yolo", "-o", "out"],
    ["merge", "--old", "a.csv", "--new", "b.csv"],
    ["upload", "-p", "proj"],
    ["whats-new", "-p", "proj"],
    ["task"],
    ["task", "mark-deleted", "-p", "proj", "--frame", "1"],
    ["task", "drop-label", "-p", "proj", "-t", "1"],
    ["task", "status", "-p", "proj", "-t", "7", "--state", "done"],
]


@pytest.mark.parametrize("argv", _PARSE_ERROR_CASES)
def test_parser_rejects_invalid_argv(argv: list[str]) -> None:
    with pytest.raises(SystemExit):
        _parse(argv)


_DISPATCH_CASES: list[tuple[str, list[str]]] = [
    ("run_fetch", ["fetch", "-p", "1", "-o", "out"]),
    ("run_fetch_task", ["fetch-task", "-p", "1", "-t", "1", "-o", "out"]),
    ("run_s3_sync", ["s3-sync"]),
    ("run_upload", ["upload", "-p", "1", "-d", "ds.csv"]),
    ("run_merge", ["merge", "--old", "a.csv", "--new", "b.csv", "-o", "m.csv"]),
    ("run_ignore", ["ignore", "-p", "proj", "--list"]),
    ("run_labels", ["labels", "-p", "proj", "--list"]),
    ("run_convert", ["convert", "--to-yolo", "-d", "ds.csv", "-o", "out"]),
    ("run_whats_new", ["whats-new", "-p", "proj", "-d", "ds.csv"]),
    ("run_doctor", ["doctor"]),
]


@pytest.mark.parametrize(("handler", "argv"), _DISPATCH_CASES)
def test_run_dispatches_to_handler(handler: str, argv: list[str]) -> None:
    with patch(f"cveta2.cli.{handler}") as mock_handler:
        CliApp().run(argv)
    mock_handler.assert_called_once()


_TASK_DISPATCH_CASES: list[tuple[str, list[str]]] = [
    (
        "run_task_mark_deleted",
        ["task", "mark-deleted", "-p", "1", "-t", "1", "--image", "a"],
    ),
    (
        "run_task_drop_label",
        ["task", "drop-label", "-p", "1", "-t", "1", "--label", "c"],
    ),
    ("run_task_delete", ["task", "delete", "-p", "1", "-t", "1"]),
    ("run_task_status", ["task", "status", "-p", "1", "-t", "1", "--state", "new"]),
]


@pytest.mark.parametrize(("handler", "argv"), _TASK_DISPATCH_CASES)
def test_task_run_dispatches_to_action(handler: str, argv: list[str]) -> None:
    with patch(f"cveta2.cli.{handler}") as mock_handler:
        CliApp().run(argv)
    mock_handler.assert_called_once()
