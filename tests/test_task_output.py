"""Retained explicit task-output cleanup adapter behavior."""

from pathlib import Path

from cveta2.adapters.files.task_output import LocalWorkflowFiles


def test_explicit_cleanup_removes_only_the_requested_tree(tmp_path: Path) -> None:
    task_directory = tmp_path / ".tasks"
    task_directory.mkdir()
    (task_directory / "task_1.csv").write_text("image_name\na.jpg\n", encoding="utf-8")
    sibling = tmp_path / "dataset.csv"
    sibling.write_bytes(b"preserved")

    LocalWorkflowFiles().cleanup_tasks(task_directory)

    assert not task_directory.exists()
    assert sibling.read_bytes() == b"preserved"


def test_explicit_cleanup_tolerates_an_already_absent_tree(tmp_path: Path) -> None:
    absent = tmp_path / "missing-tasks"

    LocalWorkflowFiles().cleanup_tasks(absent)

    assert not absent.exists()
