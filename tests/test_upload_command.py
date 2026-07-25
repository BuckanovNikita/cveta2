"""Tests for the ``upload`` command adapter: prompts, echo, staging order."""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from cveta2.commands._helpers import echo_cli_command
from cveta2.commands.upload import _NO_ANNOTATION_LABEL, _resolve_labels, run_upload
from cveta2.exceptions import Cveta2Error
from cveta2.services.upload import (
    UploadOptions,
    UploadPlan,
    UploadRequest,
    _stage_images,
)
from tests.helpers import make_cs_info

if TYPE_CHECKING:
    from pathlib import Path


def _write_dataset(tmp_path: Path) -> Path:
    csv = tmp_path / "dataset.csv"
    csv.write_text(
        "image_name,instance_label\nb.jpg,car\na.jpg,car\nc.jpg,person\n",
        encoding="utf-8",
    )
    return csv


def _upload_args(csv: Path, **overrides: object) -> argparse.Namespace:
    defaults: dict[str, object] = {
        "project": None,
        "dataset": str(csv),
        "labels": None,
        "in_progress": None,
        "image_dir": None,
        "name": None,
        "complete": False,
        "mark_all_deleted": False,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


@pytest.fixture
def isolated_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CVETA2_CONFIG", str(tmp_path / "missing-config.yaml"))


class TestResolveLabelsAll:
    """``--labels all`` selects every dataset label."""

    def test_all_selects_every_label(self) -> None:
        df = pd.DataFrame({"instance_label": ["car", "person", "car"]})
        assert _resolve_labels(["all"], df) == ["car", "person"]

    def test_all_includes_unannotated_frames(self) -> None:
        df = pd.DataFrame({"instance_label": ["car", None]})
        assert _resolve_labels(["all"], df) == ["car", _NO_ANNOTATION_LABEL]

    def test_literal_all_label_wins_over_shortcut(self) -> None:
        df = pd.DataFrame({"instance_label": ["all", "car"]})
        assert _resolve_labels(["all"], df) == ["all"]

    def test_all_with_other_labels_is_validated_literally(self) -> None:
        df = pd.DataFrame({"instance_label": ["car", "person"]})
        with pytest.raises(Cveta2Error, match="all"):
            _resolve_labels(["all", "car"], df)


@pytest.mark.usefixtures("isolated_config")
def test_run_upload_prompts_project_then_name_then_labels(tmp_path: Path) -> None:
    csv = _write_dataset(tmp_path)
    calls: list[str] = []

    def fake_resolve_project(_client: object, _arg: object) -> tuple[int, str]:
        calls.append("project")
        return 1, "proj"

    def fake_task_name(_arg: object) -> str:
        calls.append("name")
        return "t1"

    def fake_labels(_df: pd.DataFrame) -> list[str]:
        calls.append("labels")
        return ["car"]

    with (
        patch("cveta2.commands.upload.open_client") as open_client,
        patch(
            "cveta2.commands.upload.resolve_project",
            side_effect=fake_resolve_project,
        ),
        patch(
            "cveta2.commands.upload._resolve_task_name",
            side_effect=fake_task_name,
        ),
        patch("cveta2.commands.upload._select_labels", side_effect=fake_labels),
        patch("cveta2.commands.upload.build_search_dirs", return_value=[]),
        patch("cveta2.commands.upload.upload_dataset"),
    ):
        open_client.return_value.__enter__.return_value = MagicMock()
        run_upload(_upload_args(csv))

    assert calls == ["project", "name", "labels"]


@pytest.mark.usefixtures("isolated_config")
def test_run_upload_echoes_full_command_after_prompts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    csv = _write_dataset(tmp_path)
    with (
        patch("cveta2.commands.upload.open_client") as open_client,
        patch(
            "cveta2.commands.upload.resolve_project",
            return_value=(1, "proj"),
        ),
        patch("cveta2.commands.upload._resolve_task_name", return_value="t1"),
        patch("cveta2.commands.upload._select_labels", return_value=["car"]),
        patch("cveta2.commands.upload.build_search_dirs", return_value=[]),
        patch("cveta2.commands.upload.upload_dataset"),
    ):
        client = MagicMock()
        client.organization = None
        client.default_organization = None
        open_client.return_value.__enter__.return_value = client
        run_upload(_upload_args(csv))

    out = capsys.readouterr().out
    assert f"cveta2 upload -p proj -d {csv} --labels car --name t1" in out


@pytest.mark.usefixtures("isolated_config")
def test_run_upload_no_echo_when_all_args_given(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    csv = _write_dataset(tmp_path)
    args = _upload_args(csv, project="proj", name="t1", labels=["car"])
    with (
        patch("cveta2.commands.upload.open_client") as open_client,
        patch(
            "cveta2.commands.upload.resolve_project",
            return_value=(1, "proj"),
        ),
        patch("cveta2.commands.upload.build_search_dirs", return_value=[]),
        patch("cveta2.commands.upload.upload_dataset"),
    ):
        open_client.return_value.__enter__.return_value = MagicMock()
        run_upload(args)

    assert capsys.readouterr().out == ""


@pytest.mark.usefixtures("isolated_config")
def test_run_upload_rejects_unknown_cli_labels(tmp_path: Path) -> None:
    csv = _write_dataset(tmp_path)
    args = _upload_args(csv, project="proj", name="t1", labels=["bicycle"])
    with (
        patch("cveta2.commands.upload.open_client") as open_client,
        patch(
            "cveta2.commands.upload.resolve_project",
            return_value=(1, "proj"),
        ),
    ):
        open_client.return_value.__enter__.return_value = MagicMock()
        with pytest.raises(Cveta2Error, match="bicycle"):
            run_upload(args)


def test_stage_images_keeps_plan_order() -> None:
    plan = UploadPlan(
        annotations=pd.DataFrame({"image_name": [], "instance_label": []}),
        image_names=["b.jpg", "a.jpg", "c.jpg"],
        deleted_names=["z.jpg"],
    )
    request = UploadRequest(
        project_id=1,
        project_name="proj",
        task_name="t1",
        plan=plan,
        options=UploadOptions(),
    )
    client = MagicMock()
    client.detect_project_cloud_storage.return_value = make_cs_info(prefix="images")
    mapping = {n: n for n in ["b.jpg", "a.jpg", "c.jpg", "z.jpg"]}
    with (
        patch(
            "cveta2.services.upload.resolve_images",
            return_value=({}, ["b.jpg", "a.jpg", "c.jpg", "z.jpg"]),
        ),
        patch(
            "cveta2.services.upload.build_server_file_mapping",
            return_value=(mapping, set()),
        ),
    ):
        staged = _stage_images(client, request)

    assert staged.task_image_names == [
        "images/b.jpg",
        "images/a.jpg",
        "images/c.jpg",
        "images/z.jpg",
    ]


def test_echo_cli_command_formats_flags_lists_and_quoting(
    capsys: pytest.CaptureFixture[str],
) -> None:
    echo_cli_command(
        "upload",
        {
            "-p": "my proj",
            "--labels": ["car", "no annotation"],
            "--skip": None,
            "--off": False,
            "--complete": True,
            "--empty-list": [],
        },
    )
    out = capsys.readouterr().out
    assert out == "cveta2 upload -p 'my proj' --labels car 'no annotation' --complete\n"
