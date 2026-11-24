"""Public verification and publication surfaces keep CVAT upload distinct."""

import inspect
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
import questionary
from pydantic import ValidationError

import cveta2
from cveta2.domain.bundle.models import Publication
from cveta2.domain.bundle.preparation import Decision, MissingDecisions, PrepareOptions
from cveta2.interfaces.cli import CliApp
from cveta2.interfaces.commands import verification
from cveta2.interfaces.commands.interactive.bundle import collect_decisions


def test_public_dataset_functions_and_typed_options_are_exported() -> None:
    for name in (
        "verify",
        "verify_dataframe",
        "schema_for",
        "prepare_dataset",
        "upload_dataset",
        "ValidationOptions",
        "ValidationResult",
        "PrepareOptions",
        "PreparedDataset",
        "MissingDecisions",
        "Publication",
    ):
        assert name in cveta2.__all__
        assert getattr(cveta2, name) is not None
    assert cveta2.upload.__module__ != cveta2.upload_dataset.__module__
    assert "project" in inspect.signature(cveta2.upload).parameters
    assert "project" not in inspect.signature(cveta2.upload_dataset).parameters


def test_verify_csv_findings_and_malformed_input_have_distinct_status(
    tmp_path: Path,
) -> None:
    path = tmp_path / "input.csv"
    path.write_text(
        "image_name,image_path,instance_label,bbox_x_tl,bbox_y_tl,bbox_x_br,bbox_y_br,split\n"
        "image.png,/abs/image.png,cat,1,1,2,2,train\n"
    )
    with pytest.raises(SystemExit) as caught:
        CliApp().run(["verify", str(path), "--profile", "clearml-yolo"])
    assert caught.value.code == 1
    path.write_text('a,b\n"unterminated,b\n')
    with pytest.raises(SystemExit) as caught:
        CliApp().run(["verify", str(path)])
    assert caught.value.code == 2


def test_upload_rejects_nonprepared_directory(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as caught:
        CliApp().run(["upload-dataset", str(tmp_path)])
    assert caught.value.code == 2


def test_clean_requires_output_directory(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as caught:
        CliApp().run(["verify", str(tmp_path / "input.csv"), "--clean"])
    assert caught.value.code == 2


def test_environment_disables_bundle_prompts_on_a_terminal(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CVETA2_NO_INTERACTIVE", "true")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    missing = MissingDecisions((Decision("dataset_name", "Choose a dataset name"),))
    monkeypatch.setattr(verification, "prepare_dataset", Mock(side_effect=missing))
    prompt = Mock(side_effect=AssertionError("Interactive prompt was reached"))
    monkeypatch.setattr(verification, "collect_decisions", prompt)
    with pytest.raises(SystemExit) as caught:
        CliApp().run(
            [
                "verify",
                str(tmp_path / "source"),
                "--bundle",
                "--project",
                "datasets",
                "--output-dir",
                str(tmp_path / "prepared"),
            ]
        )
    assert caught.value.code == 2
    prompt.assert_not_called()


@pytest.mark.parametrize(("flags", "expected"), [([], False), (["--force-resplit"], True)])
def test_upload_dataset_force_resplit_reaches_the_api(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, flags: list[str], *, expected: bool
) -> None:
    upload = Mock(return_value=Publication("child", "1.0.0"))
    monkeypatch.setattr(verification, "upload_dataset", upload)
    CliApp().run(["upload-dataset", str(tmp_path), *flags])
    upload.assert_called_once_with(tmp_path, force_resplit=expected)


def test_public_prepare_dataset_defaults() -> None:
    parameters = inspect.signature(cveta2.prepare_dataset).parameters
    assert parameters["output_dir"].default is None
    assert parameters["options"].default is None
    assert PrepareOptions().clean is True
    assert PrepareOptions().project is None
    assert "class_id" not in Decision.__dataclass_fields__


def test_collect_decisions_asks_project_by_text(monkeypatch: pytest.MonkeyPatch) -> None:
    prompt = Mock(return_value=Mock(ask=Mock(return_value="Retail/Datasets")))
    monkeypatch.setattr(questionary, "text", prompt)
    options = collect_decisions(PrepareOptions(), (Decision("project", "Укажите проект ClearML."),))
    assert options.project == "Retail/Datasets"
    prompt.assert_called_once_with("Укажите проект ClearML.")


@pytest.mark.parametrize("field", ["accept_default_classes", "accept_class_changes"])
def test_prepare_options_reject_the_removed_class_answers(field: str) -> None:
    with pytest.raises(ValidationError, match=field):
        PrepareOptions.model_validate({field: True})
