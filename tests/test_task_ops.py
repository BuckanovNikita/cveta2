"""Unit tests for the ``cveta2 task`` write operations (CLI + client)."""

from __future__ import annotations

import argparse
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from cvat_sdk.api_client import models as cvat_models

from cveta2._client.dtos import RawDataMeta, RawFrame
from cveta2.cli import CliApp
from cveta2.client import CvatClient
from cveta2.commands.task_ops import (
    STATE_CLI_TO_CVAT,
    _confirm_or_exit,
    run_task_mark_deleted,
    run_task_status,
)
from cveta2.config import CvatConfig
from cveta2.models import TaskInfo


def _parse(argv: list[str]) -> argparse.Namespace:
    return CliApp()._parser.parse_args(argv)


# ---------------------------------------------------------------------------
# _confirm_or_exit
# ---------------------------------------------------------------------------


class TestConfirmOrExit:
    def test_yes_flag_skips_prompt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fail_input(_prompt: str) -> str:
            pytest.fail("input() must not be called with --yes")

        monkeypatch.setattr("builtins.input", fail_input)
        _confirm_or_exit("Удалить?", yes=True)

    def test_noninteractive_exits_with_yes_hint(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CVETA2_NO_INTERACTIVE", "true")
        with pytest.raises(SystemExit) as exc_info:
            _confirm_or_exit("Удалить?", yes=False)
        assert "--yes" in str(exc_info.value)

    @pytest.mark.parametrize("answer", ["y", "Y", "yes", " y "])
    def test_interactive_yes_proceeds(
        self, monkeypatch: pytest.MonkeyPatch, answer: str
    ) -> None:
        monkeypatch.delenv("CVETA2_NO_INTERACTIVE", raising=False)
        monkeypatch.setattr("builtins.input", lambda _prompt: answer)
        _confirm_or_exit("Удалить?", yes=False)

    @pytest.mark.parametrize("answer", ["", "n", "no", "nope"])
    def test_interactive_no_exits(
        self, monkeypatch: pytest.MonkeyPatch, answer: str
    ) -> None:
        monkeypatch.delenv("CVETA2_NO_INTERACTIVE", raising=False)
        monkeypatch.setattr("builtins.input", lambda _prompt: answer)
        with pytest.raises(SystemExit):
            _confirm_or_exit("Удалить?", yes=False)


# ---------------------------------------------------------------------------
# CLI parser wiring
# ---------------------------------------------------------------------------


class TestTaskCliParsing:
    def test_mark_deleted_parses_frames_and_images(self) -> None:
        args = _parse(
            [
                "task",
                "mark-deleted",
                "-p",
                "proj",
                "-t",
                "42",
                "--frame",
                "1",
                "--frame",
                "2",
                "--image",
                "a.jpg",
            ]
        )
        assert args.command == "task"
        assert args.action == "mark-deleted"
        assert args.project == "proj"
        assert args.task == "42"
        assert args.frame == [1, 2]
        assert args.image == ["a.jpg"]

    def test_mark_deleted_requires_task(self) -> None:
        with pytest.raises(SystemExit):
            _parse(["task", "mark-deleted", "-p", "proj", "--frame", "1"])

    def test_drop_label_parses(self) -> None:
        args = _parse(
            ["task", "drop-label", "-p", "proj", "-t", "my-task", "--label", "car"]
        )
        assert args.action == "drop-label"
        assert args.label == "car"
        assert args.yes is False

    def test_drop_label_requires_label(self) -> None:
        with pytest.raises(SystemExit):
            _parse(["task", "drop-label", "-p", "proj", "-t", "1"])

    def test_delete_parses_yes_flag(self) -> None:
        args = _parse(["task", "delete", "-p", "proj", "-t", "7", "--yes"])
        assert args.action == "delete"
        assert args.yes is True

    def test_status_parses_stage_and_state(self) -> None:
        args = _parse(
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
            ]
        )
        assert args.action == "status"
        assert args.stage == "acceptance"
        assert args.state == "in-progress"

    def test_status_rejects_unknown_state(self) -> None:
        with pytest.raises(SystemExit):
            _parse(["task", "status", "-p", "proj", "-t", "7", "--state", "done"])

    def test_task_requires_action(self) -> None:
        with pytest.raises(SystemExit):
            _parse(["task"])


# ---------------------------------------------------------------------------
# Command validation and state mapping
# ---------------------------------------------------------------------------


def _mock_client_with_task(task: TaskInfo) -> MagicMock:
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.resolve_project_id.return_value = 1
    client.list_project_tasks.return_value = [task]
    client.resolve_task_selectors = CvatClient.resolve_task_selectors
    return client


class TestRunTaskCommands:
    def test_mark_deleted_requires_frame_or_image(self) -> None:
        args = argparse.Namespace(project="p", task="1", frame=None, image=None)
        with pytest.raises(SystemExit):
            run_task_mark_deleted(args)

    def test_status_requires_stage_or_state(self) -> None:
        args = argparse.Namespace(project="p", task="1", stage=None, state=None)
        with pytest.raises(SystemExit):
            run_task_status(args)

    def test_state_mapping_covers_all_cli_values(self) -> None:
        assert STATE_CLI_TO_CVAT["in-progress"] == "in progress"
        assert STATE_CLI_TO_CVAT["new"] == "new"
        assert STATE_CLI_TO_CVAT["completed"] == "completed"
        assert STATE_CLI_TO_CVAT["rejected"] == "rejected"

    @pytest.mark.usefixtures("test_config")
    def test_status_passes_mapped_state_to_client(self) -> None:
        task = TaskInfo(
            id=42, name="task-a", status="annotation", subset="", updated_date=""
        )
        client = _mock_client_with_task(task)
        args = argparse.Namespace(
            project="1", task="task-a", stage=None, state="in-progress"
        )
        with (
            patch("cveta2.commands.task_ops.CvatClient", return_value=client),
            patch("cveta2.commands._helpers.load_projects_cache", return_value=[]),
        ):
            run_task_status(args)
        client.set_task_jobs_status.assert_called_once_with(
            42, stage=None, state="in progress"
        )


# ---------------------------------------------------------------------------
# Client write methods at the SDK boundary
# ---------------------------------------------------------------------------


def _client_with_mocked_sdk(
    sdk: MagicMock, adapter: MagicMock | None = None
) -> CvatClient:
    client = CvatClient(CvatConfig(host="http://cvat.test"))
    client._sdk_client = sdk
    persistent = adapter if adapter is not None else MagicMock()
    persistent.client = sdk
    client._persistent_api = persistent
    return client


def _label(label_id: int, name: str) -> SimpleNamespace:
    return SimpleNamespace(id=label_id, name=name)


class TestDropLabelAnnotations:
    def test_unknown_label_raises_value_error_with_available(self) -> None:
        sdk = MagicMock()
        task_obj = MagicMock()
        task_obj.get_labels.return_value = [_label(1, "person"), _label(2, "car")]
        sdk.tasks.retrieve.return_value = task_obj
        client = _client_with_mocked_sdk(sdk)

        with pytest.raises(ValueError, match="person") as exc_info:
            client.count_task_label_shapes(5, "ghost")
        assert "car" in str(exc_info.value)
        assert "'ghost'" in str(exc_info.value)

    def test_drop_deletes_only_matching_shapes(self) -> None:
        sdk = MagicMock()
        task_obj = MagicMock()
        task_obj.get_labels.return_value = [_label(1, "person"), _label(2, "car")]
        sdk.tasks.retrieve.return_value = task_obj
        shapes = [
            SimpleNamespace(
                id=10,
                type=cvat_models.ShapeType("rectangle"),
                frame=0,
                label_id=1,
                points=[1.0, 2.0, 3.0, 4.0],
            ),
            SimpleNamespace(
                id=11,
                type=cvat_models.ShapeType("rectangle"),
                frame=1,
                label_id=2,
                points=[5.0, 6.0, 7.0, 8.0],
            ),
        ]
        sdk.api_client.tasks_api.retrieve_annotations.return_value = (
            SimpleNamespace(shapes=shapes),
            None,
        )
        client = _client_with_mocked_sdk(sdk)

        deleted = client.drop_label_annotations(5, "person")

        assert deleted == 1
        call = sdk.api_client.tasks_api.partial_update_annotations.call_args
        assert call.args == ("delete", 5)
        request = call.kwargs["patched_labeled_data_request"]
        assert len(request.shapes) == 1
        assert request.shapes[0].id == 10
        assert request.shapes[0].label_id == 1

    def test_drop_with_no_matching_shapes_returns_zero(self) -> None:
        sdk = MagicMock()
        task_obj = MagicMock()
        task_obj.get_labels.return_value = [_label(1, "person")]
        sdk.tasks.retrieve.return_value = task_obj
        sdk.api_client.tasks_api.retrieve_annotations.return_value = (
            SimpleNamespace(shapes=[]),
            None,
        )
        client = _client_with_mocked_sdk(sdk)

        assert client.drop_label_annotations(5, "person") == 0
        sdk.api_client.tasks_api.partial_update_annotations.assert_not_called()


class TestMarkFramesDeletedByIds:
    def test_skips_unknown_frame_ids_with_warning(
        self, capture_logs: list[str]
    ) -> None:
        sdk = MagicMock()
        adapter = MagicMock()
        adapter.get_task_data_meta.return_value = RawDataMeta(
            frames=[
                RawFrame(name="a.jpg", width=10, height=10),
                RawFrame(name="b.jpg", width=10, height=10),
                RawFrame(name="c.jpg", width=10, height=10),
            ],
            deleted_frames=[0],
        )
        client = _client_with_mocked_sdk(sdk, adapter)

        marked = client.mark_frames_deleted_by_ids(7, [1, 5, -1])

        assert marked == 1
        call = sdk.api_client.tasks_api.partial_update_data_meta.call_args
        assert call.args == (7,)
        request = call.kwargs["patched_data_meta_write_request"]
        assert request.deleted_frames == [0, 1]
        assert any("5" in msg and "-1" in msg for msg in capture_logs)

    def test_all_unknown_ids_makes_no_api_call(self) -> None:
        sdk = MagicMock()
        adapter = MagicMock()
        adapter.get_task_data_meta.return_value = RawDataMeta(
            frames=[RawFrame(name="a.jpg", width=10, height=10)],
            deleted_frames=[],
        )
        client = _client_with_mocked_sdk(sdk, adapter)

        assert client.mark_frames_deleted_by_ids(7, [3, 4]) == 0
        sdk.api_client.tasks_api.partial_update_data_meta.assert_not_called()


class TestSetTaskJobsStatus:
    def test_requires_stage_or_state(self) -> None:
        client = _client_with_mocked_sdk(MagicMock())
        with pytest.raises(ValueError, match="stage"):
            client.set_task_jobs_status(1)

    def test_patches_only_provided_fields(self) -> None:
        sdk = MagicMock()
        task_obj = MagicMock()
        task_obj.get_jobs.return_value = [SimpleNamespace(id=100)]
        sdk.tasks.retrieve.return_value = task_obj
        client = _client_with_mocked_sdk(sdk)

        num_jobs = client.set_task_jobs_status(1, state="in progress")

        assert num_jobs == 1
        call = sdk.api_client.jobs_api.partial_update.call_args
        assert call.args == (100,)
        request = call.kwargs["patched_job_write_request"]
        assert request.to_dict() == {"state": "in progress"}

    def test_complete_task_sets_acceptance_completed(self) -> None:
        sdk = MagicMock()
        task_obj = MagicMock()
        task_obj.get_jobs.return_value = [
            SimpleNamespace(id=100),
            SimpleNamespace(id=101),
        ]
        sdk.tasks.retrieve.return_value = task_obj
        client = _client_with_mocked_sdk(sdk)

        num_jobs = client.complete_task(1)

        assert num_jobs == 2
        assert sdk.api_client.jobs_api.partial_update.call_count == 2
        request = sdk.api_client.jobs_api.partial_update.call_args.kwargs[
            "patched_job_write_request"
        ]
        assert request.to_dict() == {"stage": "acceptance", "state": "completed"}
