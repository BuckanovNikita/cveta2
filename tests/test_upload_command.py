"""Tests for the ``upload`` command adapter: prompts, echo, staging order."""

from __future__ import annotations

import argparse
import shlex
from dataclasses import dataclass
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from cveta2.commands import upload as upload_command
from cveta2.commands._helpers import echo_cli_command
from cveta2.commands.upload import (
    _NO_ANNOTATION_LABEL,
    _resolve_labels,
    _resolve_task_name,
    _select_labels,
    run_upload,
)
from cveta2.exceptions import Cveta2Error
from cveta2.services.upload import (
    UploadOptions,
    UploadPlan,
    UploadRequest,
    _stage_images,
)
from tests.helpers import make_cs_info, write_config_yaml

if TYPE_CHECKING:
    from pathlib import Path

_SELECT_MANY = "cveta2.commands.interactive.select_many"
_ASK_TASK_NAME = "cveta2.commands.interactive.text"


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


class TestAvailableLabels:
    """``--labels`` validation is driven by ``_available_labels``."""

    def test_labels_are_sorted_and_deduplicated(self) -> None:
        df = pd.DataFrame({"instance_label": ["person", "car", "person"]})
        assert _resolve_labels(["all"], df) == ["car", "person"]

    def test_nan_is_not_offered_as_a_label(self) -> None:
        """A dropped ``dropna()`` would put a float NaN in the label list.

        ``--labels all`` returns that list verbatim, so the sentinel is the
        only legitimate way an unannotated frame can be selected.
        """
        df = pd.DataFrame({"instance_label": ["car", None]})
        assert _resolve_labels(["all"], df) == ["car", _NO_ANNOTATION_LABEL]


class TestResolveLabelsValidation:
    def test_picker_runs_on_the_dataset_when_no_flag_is_given(self) -> None:
        """The dataframe must reach the picker.

        ``_select_labels(None)`` raises inside pandas only because the
        dataframe is indexed immediately — nothing else observes the
        argument, so the offered choices are what pins it.
        """
        df = pd.DataFrame({"instance_label": ["car", "person"]})
        with patch(_SELECT_MANY, return_value=["car"]) as picker:
            assert _resolve_labels(None, df) == ["car"]
        assert [choice.value for choice in picker.call_args.args[1]] == [
            "car",
            "person",
        ]

    def test_unannotated_sentinel_is_accepted_from_the_command_line(self) -> None:
        """``--labels __no_annotation__`` must validate.

        The sentinel is added to the available set only when the dataset
        really has NaN labels; adding ``None`` instead rejects it.
        """
        df = pd.DataFrame({"instance_label": ["car", None]})
        assert _resolve_labels([_NO_ANNOTATION_LABEL], df) == [_NO_ANNOTATION_LABEL]

    def test_unannotated_sentinel_is_rejected_without_unannotated_frames(self) -> None:
        df = pd.DataFrame({"instance_label": ["car"]})
        with pytest.raises(Cveta2Error, match=_NO_ANNOTATION_LABEL):
            _resolve_labels([_NO_ANNOTATION_LABEL], df)

    def test_only_the_unknown_label_is_reported(self) -> None:
        """Pins the direction of the set difference.

        ``available - set(labels_arg)`` would name ``person`` — a label the
        user never asked for — and stay silent about ``zebra``.
        """
        df = pd.DataFrame({"instance_label": ["car", "person"]})
        with pytest.raises(Cveta2Error) as excinfo:
            _resolve_labels(["car", "zebra"], df)
        unknown_line = str(excinfo.value).splitlines()[0]
        assert "zebra" in unknown_line
        assert "person" not in unknown_line

    def test_error_lists_unknown_and_available_labels_readably(self) -> None:
        """Both lists are comma-separated so the message can be acted on."""
        df = pd.DataFrame({"instance_label": ["car", "person"]})
        with pytest.raises(Cveta2Error) as excinfo:
            _resolve_labels(["zebra", "bicycle"], df)
        message = str(excinfo.value)
        assert "bicycle, zebra" in message
        assert "car, person" in message


class TestSelectLabels:
    def test_every_dataset_label_becomes_a_choice(self) -> None:
        """Pins the whole ``select_many`` call and the returned selection.

        The picker is a ``MagicMock``: it accepts a ``None`` message, a
        ``None`` choice list, or a call missing either positional argument
        without complaining, so only the recorded call catches those.
        """
        df = pd.DataFrame({"instance_label": ["person", "car", "car"]})
        with patch(_SELECT_MANY, return_value=["car"]) as picker:
            assert _select_labels(df) == ["car"]

        assert picker.call_args.args[0] == upload_command._LABELS_PROMPT
        assert [
            (choice.title, choice.value) for choice in picker.call_args.args[1]
        ] == [("car", "car"), ("person", "person")]
        assert picker.call_args.kwargs["hint"] == upload_command._LABELS_HINT
        assert (
            picker.call_args.kwargs["empty_message"]
            == upload_command._LABELS_EMPTY_MESSAGE
        )

    def test_unannotated_frames_get_a_sentinel_choice(self) -> None:
        """The extra choice must show a caption but return the sentinel.

        ``questionary.Choice`` falls back to the title when no value is
        given, so a dropped ``value=`` would hand ``"(без аннотаций)"``
        back to :func:`run_upload`, which compares against the sentinel.
        """
        df = pd.DataFrame({"instance_label": ["car", None]})
        with patch(_SELECT_MANY, return_value=[_NO_ANNOTATION_LABEL]) as picker:
            assert _select_labels(df) == [_NO_ANNOTATION_LABEL]

        assert [
            (choice.title, choice.value) for choice in picker.call_args.args[1]
        ] == [
            ("car", "car"),
            (upload_command._NO_ANNOTATION_TITLE, _NO_ANNOTATION_LABEL),
        ]

    def test_cancelled_picker_yields_no_labels(self) -> None:
        df = pd.DataFrame({"instance_label": ["car"]})
        with patch(_SELECT_MANY, return_value=None):
            assert _select_labels(df) == []

    def test_dataset_without_labels_or_unannotated_frames_is_rejected(self) -> None:
        """Only a dataset that offers *nothing* is an error.

        Pins both halves of ``not all_labels and not has_no_annotation``:
        each mutation of that conjunction either raises on a perfectly
        usable dataset or lets an empty one through to an empty picker.
        """
        df = pd.DataFrame({"instance_label": pd.Series([], dtype=object)})
        with (
            patch(_SELECT_MANY, return_value=[]),
            pytest.raises(Cveta2Error, match="instance_label"),
        ):
            _select_labels(df)

    def test_dataset_with_only_unannotated_frames_is_accepted(self) -> None:
        df = pd.DataFrame({"instance_label": [None, None]})
        with patch(_SELECT_MANY, return_value=[_NO_ANNOTATION_LABEL]):
            assert _select_labels(df) == [_NO_ANNOTATION_LABEL]


class TestDeletedOnlyDataset:
    """A CSV whose rows are all deleted frames is still uploadable.

    ``split_deleted_rows`` hands the picker the *remaining* rows, so a
    ``deleted.csv`` reaches label resolution as an empty frame.  Rejecting
    it there made the whole file unuploadable even though the pipeline
    below accepts a plan of nothing but deleted names.
    """

    @staticmethod
    def _empty() -> pd.DataFrame:
        return pd.DataFrame({"instance_label": pd.Series([], dtype=object)})

    def test_picker_is_skipped_when_the_dataset_has_deleted_rows(self) -> None:
        with patch(_SELECT_MANY, side_effect=AssertionError("picker must not run")):
            assert _resolve_labels(None, self._empty(), has_deleted=True) == []

    def test_an_empty_dataset_without_deleted_rows_is_still_rejected(self) -> None:
        """The rescue must not leak into datasets that offer nothing at all.

        Called without the flag, so the default also has to mean "no
        deleted rows" — defaulting it to ``True`` would swallow this error
        for every caller that omits it.
        """
        with pytest.raises(Cveta2Error, match="instance_label"):
            _resolve_labels(None, self._empty())

    def test_labels_all_selects_nothing_on_a_deleted_only_dataset(self) -> None:
        assert _resolve_labels(["all"], self._empty(), has_deleted=True) == []

    def test_deleted_rows_do_not_suppress_a_picker_that_has_choices(self) -> None:
        """``has_deleted`` only rescues the *empty* case.

        A dataset with both labels and deleted rows must still prompt;
        returning early on ``has_deleted`` alone would silently drop every
        annotated frame from the upload.
        """
        df = pd.DataFrame({"instance_label": ["car"]})
        with patch(_SELECT_MANY, return_value=["car"]):
            assert _resolve_labels(None, df, has_deleted=True) == ["car"]


class TestResolveTaskName:
    def test_explicit_name_skips_the_prompt(self) -> None:
        with patch(_ASK_TASK_NAME) as prompt:
            assert _resolve_task_name("given") == "given"
        prompt.assert_not_called()

    def test_prompt_is_configured_for_a_mandatory_name(self) -> None:
        """Pins every argument of the ``text`` prompt.

        The prompt is mocked, so a dropped ``allow_empty=False`` or
        ``history_key`` changes nothing the return value can show — yet the
        first would let an empty task name through and the second would
        lose arrow-up recall.
        """
        with patch(_ASK_TASK_NAME, return_value="t1") as prompt:
            assert _resolve_task_name(None) == "t1"

        assert prompt.call_args.args == (upload_command._TASK_NAME_PROMPT,)
        assert prompt.call_args.kwargs == {
            "hint": upload_command._TASK_NAME_HINT,
            "allow_empty": False,
            "empty_message": upload_command._TASK_NAME_EMPTY_MESSAGE,
            "history_key": upload_command._TASK_NAME_HISTORY_KEY,
        }


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

    def fake_labels(_df: pd.DataFrame, *, has_deleted: bool) -> list[str]:
        calls.append("labels")
        assert has_deleted is False
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
) -> _UploadRun:
    """Run ``upload`` with the client boundary faked, recording the request.

    *project_spec* is the only spec ``resolve_project`` will resolve; any
    other value (including the ``None`` a mutant would pass) yields a
    recognisably wrong project.
    """
    run = _UploadRun()

    def fake_resolve_project(client: object, spec: object) -> tuple[int, str]:
        run.resolve_client = client
        return project if spec == project_spec else (0, "unresolved")

    def fake_upload_dataset(client: object, request: UploadRequest) -> None:
        run.client = client
        run.request = request

    with (
        patch("cveta2.commands.upload.open_client") as open_client,
        patch(
            "cveta2.commands.upload.resolve_project", side_effect=fake_resolve_project
        ),
        patch("cveta2.commands.upload.upload_dataset", side_effect=fake_upload_dataset),
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


class TestRunUploadRequest:
    """Everything ``run_upload`` assembles for :func:`upload_dataset`."""

    @pytest.fixture
    def paths(self, tmp_path: Path, isolated_config_path: Path) -> dict[str, Path]:
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
        return {
            "csv": csv,
            "in_progress": in_progress,
            "image_dir": image_dir,
            "cache_dir": cache_dir,
        }

    @pytest.fixture
    def request_built(self, paths: dict[str, Path]) -> UploadRequest:
        args = _upload_args(
            paths["csv"],
            project="acme/proj",
            name="t1",
            labels=["car", _NO_ANNOTATION_LABEL],
            in_progress=str(paths["in_progress"]),
            image_dir=str(paths["image_dir"]),
            complete=True,
            mark_all_deleted=True,
        )
        run = _run_upload_capturing(args, project_spec="acme/proj")
        assert run.request is not None
        return run.request

    def test_project_and_task_name_are_carried_through(
        self, request_built: UploadRequest
    ) -> None:
        """The resolved project must be the one that reaches the pipeline.

        ``resolve_project`` is faked on the spec, so passing ``None`` for
        the spec (or nulling a ``UploadRequest`` field) shows up here.
        """
        assert request_built.project_id == 7
        assert request_built.project_name == "proj"
        assert request_built.task_name == "t1"

    def test_selected_labels_choose_frames_and_the_sentinel_adds_the_rest(
        self, request_built: UploadRequest
    ) -> None:
        """``--labels car __no_annotation__`` uploads car frames plus NaN ones.

        ``b.jpg`` carries only ``person``; ``e.jpg`` is a car frame listed
        in ``--in-progress``.  Dropping the exclude set, the sentinel flag
        or inverting it changes exactly this list.
        """
        assert request_built.plan.image_names == ["a.jpg", "c.jpg"]

    def test_deleted_rows_are_split_out_and_forwarded(
        self, request_built: UploadRequest
    ) -> None:
        assert request_built.plan.deleted_names == ["d.jpg"]

    def test_search_dirs_combine_the_flag_and_the_configured_cache(
        self, request_built: UploadRequest, paths: dict[str, Path]
    ) -> None:
        """``--image-dir`` and the project's ``image_cache`` entry both count.

        The cache entry is keyed by project *name*, so a call that forgets
        to pass it silently loses that directory.
        """
        assert request_built.options.search_dirs == [
            paths["image_dir"].resolve(),
            paths["cache_dir"],
        ]

    def test_upload_config_supplies_segmentation_and_quality(
        self, request_built: UploadRequest
    ) -> None:
        """Both come from the ``upload`` config section, not the dataclass.

        ``UploadOptions`` defaults both to 100, so the config file has to
        use other values for a dropped keyword to be visible.
        """
        assert request_built.options.segment_size == 7
        assert request_built.options.image_quality == 42

    def test_task_flags_reach_the_options(self, request_built: UploadRequest) -> None:
        assert request_built.options.mark_all_deleted is True
        assert request_built.options.complete is True


@pytest.mark.usefixtures("isolated_config")
def test_run_upload_echoes_every_flag_it_was_given(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
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
    )
    _run_upload_capturing(args, project=(1, "proj"))

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
        ],
    )
    @pytest.mark.usefixtures("isolated_config")
    def test_any_single_prompted_input_triggers_the_echo(
        self,
        csv: Path,
        capsys: pytest.CaptureFixture[str],
        project: str | None,
        name: str | None,
        labels: list[str] | None,
    ) -> None:
        """Each disjunct of ``prompted`` must stand on its own.

        Turning either ``or`` into an ``and`` still echoes when *several*
        inputs were prompted, so only these one-at-a-time cases separate
        them.
        """
        args = _upload_args(csv, project=project, name=name, labels=labels)
        with (
            patch("cveta2.commands.upload._select_labels", return_value=["car"]),
            patch("cveta2.commands.upload._resolve_task_name", return_value="t1"),
        ):
            _run_upload_capturing(args, project_spec=project, project=(1, "proj"))

        assert capsys.readouterr().out.startswith("cveta2 upload ")

    @pytest.mark.usefixtures("isolated_config")
    def test_empty_labels_list_does_not_count_as_prompted(
        self, csv: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """``--labels`` with no values is still an explicit choice.

        The predicate tests ``args.labels is None``, not falsiness; a
        truthiness check would echo here as if the user had been prompted.
        """
        args = _upload_args(csv, project="proj", name="t1", labels=[])
        _run_upload_capturing(args, project_spec="proj", project=(1, "proj"))

        assert capsys.readouterr().out == ""

    @pytest.mark.usefixtures("isolated_config")
    def test_prompted_resume_echo_keeps_resume_flag(
        self, csv: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        args = _upload_args(csv, project=None, name="t1", labels=["car"], resume=True)
        _run_upload_capturing(args, project=(1, "proj"))

        assert "--resume" in shlex.split(capsys.readouterr().out)


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
            return_value=(mapping, {f"images/{n}" for n in mapping}),
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


class TestResumeWiring:
    """The three fields that decide which upload ``--resume`` continues."""

    @pytest.mark.usefixtures("isolated_config")
    def test_the_dataset_labels_and_resume_flag_reach_the_request(
        self, tmp_path: Path
    ) -> None:
        """Resuming is keyed on the frames and labels, not on the flag alone.

        A dropped label selection would fingerprint a different upload and
        either find nothing or continue the wrong task.
        """
        csv = _write_dataset(tmp_path)
        args = _upload_args(csv, labels=["car"], resume=True, name="t")

        run = _run_upload_capturing(args)

        assert run.request is not None
        assert run.request.dataset_path == str(csv)
        assert run.request.labels == ("car",)
        assert run.request.resume is True

    @pytest.mark.usefixtures("isolated_config")
    def test_resume_defaults_to_off(self, tmp_path: Path) -> None:
        """A plain upload must never adopt a stranded task by accident."""
        args = _upload_args(_write_dataset(tmp_path), labels=["car"], name="t")

        run = _run_upload_capturing(args)

        assert run.request is not None
        assert run.request.resume is False
