"""Tests for the ``upload`` command adapter: prompts, echo, request assembly."""

from __future__ import annotations

import argparse
import shlex
from dataclasses import dataclass
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from cveta2.domain.errors import Cveta2Error
from cveta2.interfaces.commands import upload as upload_command
from cveta2.interfaces.commands._helpers import echo_cli_command
from cveta2.interfaces.commands.upload import (
    _NO_ANNOTATION_LABEL,
    _resolve_labels,
    _resolve_task_name,
    run_upload,
)
from tests.helpers import write_config_yaml

if TYPE_CHECKING:
    from pathlib import Path

    from cveta2.application.use_cases.upload import UploadRequest

_SELECT_MANY = "cveta2.interfaces.commands.interactive.select_many"
_ASK_TASK_NAME = "cveta2.interfaces.commands.interactive.text"
_NO_ANNOTATION = (upload_command._NO_ANNOTATION_TITLE, _NO_ANNOTATION_LABEL)


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
        "resume": False,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _labels_df(*labels: str | None) -> pd.DataFrame:
    return pd.DataFrame({"instance_label": pd.Series(list(labels), dtype=object)})


@pytest.fixture
def isolated_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CVETA2_CONFIG", str(tmp_path / "missing-config.yaml"))


class TestResolveLabels:
    """``--labels`` resolution and validation, and the interactive picker."""

    @pytest.mark.parametrize(
        ("labels_arg", "dataset", "has_deleted", "expected"),
        [
            # ``all`` selects every dataset label, sorted and deduplicated.
            pytest.param(["all"], ["person", "car", "person"], False, ["car", "person"], id="all"),
            pytest.param(["all"], ["all", "car"], False, ["all"], id="literal-all-wins"),
            # NaN is never offered verbatim; the sentinel stands for it.
            pytest.param(
                ["all"],
                ["car", None],
                False,
                ["car", _NO_ANNOTATION_LABEL],
                id="all-with-unannotated",
            ),
            pytest.param(
                [_NO_ANNOTATION_LABEL],
                ["car", None],
                False,
                [_NO_ANNOTATION_LABEL],
                id="sentinel-accepted",
            ),
            # A deleted-only dataset reaches label resolution as an empty frame.
            pytest.param(["all"], [], True, [], id="all-on-deleted-only"),
        ],
    )
    def test_flag_values(
        self,
        labels_arg: list[str],
        dataset: list[str | None],
        has_deleted: bool,  # noqa: FBT001
        expected: list[str],
    ) -> None:
        resolved = _resolve_labels(labels_arg, _labels_df(*dataset), has_deleted=has_deleted)
        assert resolved == expected

    @pytest.mark.parametrize(
        ("labels_arg", "dataset", "match"),
        [
            pytest.param(
                ["all", "car"],
                ["car", "person"],
                "all",
                id="all-with-others-is-literal",
            ),
            pytest.param(
                [_NO_ANNOTATION_LABEL],
                ["car"],
                _NO_ANNOTATION_LABEL,
                id="sentinel-without-unannotated",
            ),
        ],
    )
    def test_unknown_flag_values_are_rejected(
        self, labels_arg: list[str], dataset: list[str | None], match: str
    ) -> None:
        with pytest.raises(Cveta2Error, match=match):
            _resolve_labels(labels_arg, _labels_df(*dataset))

    def test_error_names_only_the_unknown_labels_and_lists_the_available(self) -> None:
        """``available - requested`` would name ``person``, never asked for."""
        with pytest.raises(Cveta2Error) as excinfo:
            _resolve_labels(["car", "zebra", "bicycle"], _labels_df("car", "person"))
        message = str(excinfo.value)
        unknown_line = message.splitlines()[0]
        assert "bicycle, zebra" in unknown_line
        assert "person" not in unknown_line
        assert "car, person" in message

    @pytest.mark.parametrize(
        ("dataset", "has_deleted", "choices"),
        [
            pytest.param(
                ["person", "car", "car"],
                False,
                [("car", "car"), ("person", "person")],
                id="labels",
            ),
            # The extra choice shows a caption but returns the sentinel.
            pytest.param(["car", None], False, [("car", "car"), _NO_ANNOTATION], id="unannotated"),
            pytest.param([None, None], False, [_NO_ANNOTATION], id="only-unannotated"),
            # ``has_deleted`` only rescues the *empty* case.
            pytest.param(["car"], True, [("car", "car")], id="deleted-rows-still-prompt"),
        ],
    )
    def test_picker_offers_the_dataset_labels(
        self,
        dataset: list[str | None],
        has_deleted: bool,  # noqa: FBT001
        choices: list[tuple[str, str]],
    ) -> None:
        picked = [choices[-1][1]]
        with patch(_SELECT_MANY, return_value=picked) as picker:
            resolved = _resolve_labels(None, _labels_df(*dataset), has_deleted=has_deleted)

        assert resolved == picked
        offered = picker.call_args.args[1]
        assert [(choice.title, choice.value) for choice in offered] == choices

    def test_cancelled_picker_yields_no_labels(self) -> None:
        with patch(_SELECT_MANY, return_value=None):
            assert _resolve_labels(None, _labels_df("car")) == []

    def test_picker_is_skipped_on_a_deleted_only_dataset(self) -> None:
        with patch(_SELECT_MANY, side_effect=AssertionError("picker must not run")):
            assert _resolve_labels(None, _labels_df(), has_deleted=True) == []

    def test_an_empty_dataset_without_deleted_rows_is_rejected(self) -> None:
        """Called without the flag, so the default must mean "no deleted rows"."""
        with pytest.raises(Cveta2Error, match="instance_label"):
            _resolve_labels(None, _labels_df())


class TestResolveTaskName:
    def test_explicit_name_skips_the_prompt(self) -> None:
        with patch(_ASK_TASK_NAME) as prompt:
            assert _resolve_task_name("given") == "given"
        prompt.assert_not_called()

    def test_prompt_requires_a_name_and_keeps_history(self) -> None:
        """An empty task name must be refused; arrow-up recall needs the key."""
        with patch(_ASK_TASK_NAME, return_value="t1") as prompt:
            assert _resolve_task_name(None) == "t1"

        assert prompt.call_args.kwargs["allow_empty"] is False
        assert prompt.call_args.kwargs["history_key"] == upload_command._TASK_NAME_HISTORY_KEY


_RICH_DATASET = (
    "image_name,instance_label,instance_shape\n"
    "a.jpg,car,rectangle\n"
    "b.jpg,person,rectangle\n"
    "c.jpg,,\n"
    "d.jpg,,deleted\n"
    "e.jpg,car,rectangle\n"
)


@dataclass
class _UploadRun:
    """Everything :func:`run_upload` handed to its collaborators."""

    client: object = None
    resolve_client: object = None
    request: UploadRequest | None = None


def _run_upload_capturing(
    args: argparse.Namespace,
    *,
    project: tuple[int, str] = (7, "proj"),
    project_spec: str | None = None,
    calls: list[str] | None = None,
) -> _UploadRun:
    """Run ``upload`` with the client boundary faked, recording the request.

    *project_spec* is the only spec ``resolve_project`` will resolve; any
    other value yields a recognisably wrong project.  *calls* records when
    the project was resolved, for prompt-order checks.
    """
    run = _UploadRun()

    def fake_resolve_project(client: object, spec: object) -> tuple[int, str]:
        run.resolve_client = client
        if calls is not None:
            calls.append("project")
        return project if spec == project_spec else (0, "unresolved")

    def fake_upload_cvat_dataset(client: object, request: UploadRequest) -> None:
        run.client = client
        run.request = request

    with (
        patch("cveta2.interfaces.commands.upload.open_client") as open_client,
        patch(
            "cveta2.interfaces.commands.upload.resolve_project",
            side_effect=fake_resolve_project,
        ),
        patch(
            "cveta2.interfaces.commands.upload.upload_cvat_dataset",
            side_effect=fake_upload_cvat_dataset,
        ),
    ):
        client = MagicMock()
        client.organization = None
        client.default_organization = None
        open_client.return_value.__enter__.return_value = client
        run_upload(args)

    assert run.client is client
    assert run.resolve_client is client
    return run


@pytest.mark.usefixtures("isolated_config")
def test_run_upload_prompts_project_then_name_then_labels(tmp_path: Path) -> None:
    calls: list[str] = []

    def fake_task_name(_arg: object) -> str:
        calls.append("name")
        return "t1"

    def fake_labels(_df: pd.DataFrame, *, has_deleted: bool) -> list[str]:
        calls.append("labels")
        assert has_deleted is False
        return ["car"]

    with (
        patch(
            "cveta2.interfaces.commands.upload._resolve_task_name",
            side_effect=fake_task_name,
        ),
        patch("cveta2.interfaces.commands.upload._select_labels", side_effect=fake_labels),
    ):
        _run_upload_capturing(_upload_args(_write_dataset(tmp_path)), calls=calls)

    assert calls == ["project", "name", "labels"]


@pytest.mark.usefixtures("isolated_config")
def test_run_upload_rejects_unknown_cli_labels(tmp_path: Path) -> None:
    args = _upload_args(_write_dataset(tmp_path), project="proj", name="t1", labels=["bicycle"])
    with pytest.raises(Cveta2Error, match="bicycle"):
        _run_upload_capturing(args, project_spec="proj")


@pytest.mark.usefixtures("isolated_config")
def test_run_upload_uploads_a_dataset_of_only_deleted_rows(tmp_path: Path) -> None:
    """End-to-end: ``upload -d deleted.csv`` without ``--labels``.

    The plan carries the deleted frame and no images, and nothing prompts
    for a class the file cannot offer.
    """
    csv = tmp_path / "deleted.csv"
    csv.write_text(
        "image_name,instance_label,instance_shape\nd.jpg,,deleted\n",
        encoding="utf-8",
    )
    args = _upload_args(csv, project="proj", name="t1")

    with patch(_SELECT_MANY, side_effect=AssertionError("picker must not run")):
        run = _run_upload_capturing(args, project_spec="proj", project=(1, "proj"))

    assert run.request is not None
    assert run.request.plan.deleted_names == ["d.jpg"]
    assert run.request.plan.image_names == []


def test_run_upload_assembles_the_whole_request(tmp_path: Path, isolated_config_path: Path) -> None:
    """Everything ``run_upload`` hands to :func:`upload_cvat_dataset`.

    ``resolve_project`` is faked on the spec, so a dropped spec shows up in
    the project fields.  ``b.jpg`` carries only ``person`` and ``e.jpg`` is
    listed in ``--in-progress``, so the label filter, the sentinel and the
    exclusions each change the image list.  Search dirs combine
    ``--image-dir`` with the project's ``image_cache`` entry (keyed by the
    project *name*), and segmentation and quality come from the config,
    which uses non-default values.
    """
    csv = tmp_path / "dataset.csv"
    csv.write_text(_RICH_DATASET, encoding="utf-8")
    in_progress = tmp_path / "in_progress.csv"
    in_progress.write_text("image_name\ne.jpg\n", encoding="utf-8")
    image_dir = tmp_path / "imgs"
    image_dir.mkdir()
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    write_config_yaml(
        isolated_config_path,
        upload={"images_per_job": 7, "image_quality": 42},
        image_cache={"proj": str(cache_dir)},
    )
    args = _upload_args(
        csv,
        project="acme/proj",
        name="t1",
        labels=["car", _NO_ANNOTATION_LABEL],
        in_progress=str(in_progress),
        image_dir=str(image_dir),
        complete=True,
        mark_all_deleted=True,
    )

    request = _run_upload_capturing(args, project_spec="acme/proj").request

    assert request is not None
    assert (request.project_id, request.project_name) == (7, "proj")
    assert request.task_name == "t1"
    assert request.plan.image_names == ["a.jpg", "c.jpg"]
    assert request.plan.deleted_names == ["d.jpg"]
    assert request.options.search_dirs == [image_dir.resolve(), cache_dir]
    assert request.options.segment_size == 7
    assert request.options.image_quality == 42
    assert request.options.mark_all_deleted is True
    assert request.options.complete is True
    # Resuming is keyed on the dataset and the labels; a plain upload must
    # never adopt a stranded task.
    assert request.dataset_path == str(csv)
    assert request.labels == ("car", _NO_ANNOTATION_LABEL)
    assert request.resume is False


@pytest.mark.usefixtures("isolated_config")
def test_run_upload_echoes_every_flag_it_was_given(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The echoed command must be a faithful, re-runnable invocation.

    Parsing it back with ``shlex.split`` is what a shell would do, and it
    is the only place the flag spellings in the echo mapping are checked.
    """
    csv = tmp_path / "dataset.csv"
    csv.write_text(_RICH_DATASET, encoding="utf-8")
    in_progress = tmp_path / "in_progress.csv"
    in_progress.write_text("image_name\ne.jpg\n", encoding="utf-8")
    image_dir = tmp_path / "imgs"
    image_dir.mkdir()

    args = _upload_args(
        csv,
        name="t1",
        labels=["car"],
        in_progress=str(in_progress),
        image_dir=str(image_dir),
        complete=True,
        mark_all_deleted=True,
        resume=True,
    )
    run = _run_upload_capturing(args, project=(1, "proj"))

    assert run.request is not None
    assert run.request.resume is True
    assert shlex.split(capsys.readouterr().out) == [
        "cveta2",
        "upload",
        "-p",
        "proj",
        "-d",
        str(csv),
        "--labels",
        "car",
        "--in-progress",
        str(in_progress),
        "--image-dir",
        str(image_dir),
        "--name",
        "t1",
        "--complete",
        "--mark-all-deleted",
        "--resume",
    ]


class TestRunUploadPromptedPredicate:
    """``prompted`` decides whether the re-run command is echoed."""

    @pytest.fixture
    def csv(self, tmp_path: Path) -> Path:
        path = tmp_path / "dataset.csv"
        path.write_text(_RICH_DATASET, encoding="utf-8")
        return path

    @pytest.mark.parametrize(
        ("project", "name", "labels"),
        [
            pytest.param("proj", "t1", None, id="labels-prompted"),
            pytest.param(None, "t1", ["car"], id="project-prompted"),
            pytest.param("proj", None, ["car"], id="name-prompted"),
            pytest.param(None, None, None, id="all-prompted"),
        ],
    )
    @pytest.mark.usefixtures("isolated_config")
    def test_any_prompted_input_echoes_the_full_command(
        self,
        csv: Path,
        capsys: pytest.CaptureFixture[str],
        project: str | None,
        name: str | None,
        labels: list[str] | None,
    ) -> None:
        """Each disjunct of ``prompted`` must stand on its own."""
        args = _upload_args(csv, project=project, name=name, labels=labels)
        with (
            patch("cveta2.interfaces.commands.upload._select_labels", return_value=["car"]),
            patch(
                "cveta2.interfaces.commands.upload._resolve_task_name",
                return_value="t1",
            ),
        ):
            _run_upload_capturing(args, project_spec=project, project=(1, "proj"))

        assert capsys.readouterr().out == f"cveta2 upload -p proj -d {csv} --labels car --name t1\n"

    @pytest.mark.parametrize("labels", [["car"], []], ids=["all-given", "empty-labels"])
    @pytest.mark.usefixtures("isolated_config")
    def test_nothing_is_echoed_without_a_prompt(
        self, csv: Path, capsys: pytest.CaptureFixture[str], labels: list[str]
    ) -> None:
        """``--labels`` with no values is still an explicit choice."""
        args = _upload_args(csv, project="proj", name="t1", labels=labels)
        with patch(_SELECT_MANY, side_effect=AssertionError("picker must not run")):
            _run_upload_capturing(args, project_spec="proj", project=(1, "proj"))

        assert capsys.readouterr().out == ""


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
