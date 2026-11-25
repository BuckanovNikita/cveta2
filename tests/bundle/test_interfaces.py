"""Public verification and publication surfaces keep CVAT upload distinct."""

import inspect
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pandas as pd
import pytest
import questionary

import cveta2
from cveta2.domain.bundle.models import (
    BundleValidation,
    ClassChange,
    ClassInfo,
    ClassMarkChange,
    DatasetMetadata,
    DatasetParent,
    Publication,
    TaskManifest,
    UploadError,
)
from cveta2.domain.bundle.preparation import Decision, MissingDecisions, PreparedDataset, PrepareOptions
from cveta2.domain.verification.models import ValidationResult
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
    prepare = Mock(side_effect=missing)
    monkeypatch.setattr(verification, "prepare_dataset", prepare)
    prompt = Mock(side_effect=AssertionError("Interactive prompt was reached"))
    monkeypatch.setattr(verification, "collect_decisions", prompt)
    source = tmp_path / "source"
    source.mkdir()
    with pytest.raises(SystemExit) as caught:
        CliApp().run(["verify", str(source), "--clearml-project", "datasets"])
    assert caught.value.code == 2
    prepare.assert_called_once()
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


_PARENT = DatasetParent("parent-id", "Retail/Datasets", "retail-shelves", "1.0.0", None)


def _prepared(directory: Path, *, broken_rows: int = 0, **fields: Any) -> PreparedDataset:
    """Return a ready preparation result whose validation dropped ``broken_rows`` rows of one image."""
    broken = pd.DataFrame({"image_name": ["bad.jpg"] * broken_rows})
    validation = BundleValidation(
        result=ValidationResult(
            profile="clearml-yolo",
            clean=pd.DataFrame({"image_name": ["good.jpg"]}),
            broken=broken,
            clean_row_positions=(0,),
            broken_row_positions=tuple(range(1, broken_rows + 1)),
            issues=(),
            input_row_count=broken_rows + 1,
        ),
        broken_images=broken,
    )
    base = PreparedDataset(
        directory=directory,
        ready=True,
        validation=validation,
        metadata=DatasetMetadata(api_url="https://classes.example/api", classes={}),
        tasks=TaskManifest(included=[], obsolete=[]),
        parent=_PARENT,
    )
    return replace(base, **fields)


def _fake_prepare(monkeypatch: pytest.MonkeyPatch, result: PreparedDataset | Exception) -> Mock:
    prepare = Mock(side_effect=result) if isinstance(result, Exception) else Mock(return_value=result)
    monkeypatch.setattr(verification, "prepare_dataset", prepare)
    return prepare


def _run_verify(argv: list[str]) -> int:
    with pytest.raises(SystemExit) as caught:
        CliApp().run(["verify", *argv])
    return 0 if caught.value.code is None else int(caught.value.code)


def _source(tmp_path: Path) -> Path:
    source = tmp_path / "fetch"
    source.mkdir()
    return source


def test_verify_directory_prepares_with_cleanup_by_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = _source(tmp_path)
    prepare = _fake_prepare(monkeypatch, _prepared(tmp_path / "fetch-prepared"))
    CliApp().run(["verify", str(source)])
    prepare.assert_called_once()
    assert prepare.call_args.args == (str(source),)
    assert prepare.call_args.kwargs["output_dir"] is None
    assert prepare.call_args.kwargs["options"].clean is True


def test_verify_maps_preparation_flags(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = _source(tmp_path)
    prepare = _fake_prepare(monkeypatch, _prepared(tmp_path / "X"))
    CliApp().run(
        [
            "verify",
            str(source),
            "--clearml-project",
            "P",
            "--dataset-name",
            "D",
            "--output-uri",
            "s3://b/.clearml",
            "--api-url",
            "https://a/api",
            "--local-root",
            "/images",
            "--s3-root",
            "s3://b/images",
            "--empty-class",
            "3",
            "--include-class",
            "5",
            "--no-clean",
            "--output-dir",
            "X",
        ]
    )
    options = prepare.call_args.kwargs["options"]
    assert options == PrepareOptions(
        project="P",
        dataset_name="D",
        output_uri="s3://b/.clearml",
        api_url="https://a/api",
        local_roots=("/images",),
        s3_roots=("s3://b/images",),
        class_empty={3: True, 5: False},
        clean=False,
    )
    assert prepare.call_args.kwargs["output_dir"] == Path("X")


def test_verify_same_class_in_empty_and_include_is_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capture_info_logs: list[str]
) -> None:
    source = _source(tmp_path)
    prepare = _fake_prepare(monkeypatch, _prepared(tmp_path / "out"))
    assert _run_verify([str(source), "--empty-class", "3", "--include-class", "3"]) == 2
    prepare.assert_not_called()
    assert "Ошибка проверки: Класс 3 указан и в --empty-class, и в --include-class." in capture_info_logs


@pytest.mark.parametrize(
    "flags",
    [
        ["--clearml-project", "P"],
        ["--dataset-name", "D"],
        ["--output-uri", "s3://b/.clearml"],
        ["--api-url", "https://a/api"],
        ["--local-root", "/images"],
        ["--s3-root", "s3://b/images"],
        ["--empty-class", "1"],
        ["--include-class", "1"],
        ["--no-clean"],
    ],
)
def test_verify_file_rejects_preparation_flags(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capture_info_logs: list[str], flags: list[str]
) -> None:
    path = tmp_path / "input.csv"
    path.write_text("image_name\nimage.png\n")
    csv_check = Mock(side_effect=AssertionError("The CSV check was reached"))
    monkeypatch.setattr(verification, "verify", csv_check)
    assert _run_verify([str(path), *flags]) == 2
    csv_check.assert_not_called()
    assert "Ошибка проверки: Настройки подготовки относятся к каталогу полной выгрузки." in capture_info_logs


@pytest.mark.parametrize("flags", [[], ["--clearml-project", "P"]], ids=["no-flag", "preparation-flag"])
def test_verify_names_a_missing_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capture_info_logs: list[str], flags: list[str]
) -> None:
    missing = tmp_path / "run2" / "nope"
    csv_check = Mock(side_effect=AssertionError("The CSV check was reached"))
    monkeypatch.setattr(verification, "verify", csv_check)
    assert _run_verify([str(missing), *flags]) == 2
    csv_check.assert_not_called()
    assert capture_info_logs == [f"Ошибка проверки: Нет такого файла или каталога: {missing}"]


def test_verify_prints_prepared_path_pending_and_next_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capture_info_logs: list[str]
) -> None:
    source = _source(tmp_path)
    directory = tmp_path / "fetch-prepared"
    _fake_prepare(
        monkeypatch,
        _prepared(
            directory,
            pending=("заполните split у 120 изображений в out/fetch-prepared/dataset.csv",),
            changes=(ClassChange("added", 4, "bowl"), ClassChange("renamed", 3, "canine", "dog")),
            mark_changes=(ClassMarkChange(10, "umbrella", empty=True), ClassMarkChange(12, "cup", empty=False)),
            dropped_local_roots=("/home/other/images",),
        ),
    )
    CliApp().run(["verify", str(source)])
    assert capture_info_logs[-3:] == [
        f"Набор подготовлен: {directory}",
        "Перед публикацией: заполните split у 120 изображений в out/fetch-prepared/dataset.csv",
        f"Затем: cveta2 upload-dataset {directory}",
    ]
    assert capture_info_logs[1:-3] == [
        "Класс добавлен: 4 bowl",
        "Класс переименован: 3 dog → canine",
        "Класс 10 umbrella исключён",
        "Класс 12 cup возвращён",
        "Корень родителя /home/other/images не найден на этой машине и не перенесён",
    ]


def test_verify_blocked_preparation_exits_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capture_info_logs: list[str]
) -> None:
    source = _source(tmp_path)
    directory = tmp_path / "fetch-prepared"
    blocker = "Нет ни одного bbox классов dog: исключите их (--empty-class N)."
    _fake_prepare(
        monkeypatch,
        _prepared(
            directory,
            ready=False,
            blockers=(blocker,),
            pending=(f"заполните split у 3 изображений в {directory / 'dataset.csv'}",),
        ),
    )
    assert _run_verify([str(source)]) == 1
    assert capture_info_logs[-2:] == [blocker, f"Набор не подготовлен; отчёт: {directory / 'report.json'}"]
    assert not any(message.startswith(("Перед публикацией", "Набор подготовлен")) for message in capture_info_logs)


def test_verify_exit_zero_when_cleanup_dropped_rows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capture_info_logs: list[str]
) -> None:
    source = _source(tmp_path)
    directory = tmp_path / "fetch-prepared"
    _fake_prepare(monkeypatch, _prepared(directory, broken_rows=5))
    CliApp().run(["verify", str(source)])
    assert capture_info_logs[0] == "Проверка: 6 строк; допустимых 1, отклонённых 5."
    broken_line = (
        f"В broken-images.csv записано 5 строк 1 изображений с отклонёнными строками: {directory / 'broken-images.csv'}"
    )
    assert broken_line in capture_info_logs
    assert capture_info_logs[-2:] == [f"Набор подготовлен: {directory}", f"Затем: cveta2 upload-dataset {directory}"]


def test_verify_prints_split_prefilled_count(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capture_info_logs: list[str]
) -> None:
    source = _source(tmp_path)
    directory = tmp_path / "fetch-prepared"
    _fake_prepare(monkeypatch, _prepared(directory, split_prefilled=7))
    CliApp().run(["verify", str(source)])
    assert capture_info_logs[1:] == [
        "split заполнен из родителя у 7 изображений",
        f"Набор подготовлен: {directory}",
        f"Затем: cveta2 upload-dataset {directory}",
    ]


def test_verify_operational_error_exits_two(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capture_info_logs: list[str]
) -> None:
    source = _source(tmp_path)
    _fake_prepare(monkeypatch, UploadError("Нет файлов изображений из image_path (1):\n  /images/missing.jpg"))
    assert _run_verify([str(source)]) == 2
    assert capture_info_logs[-1].startswith("Ошибка проверки: Нет файлов изображений из image_path (1)")


def test_verify_counts_broken_rows_without_image_names(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capture_info_logs: list[str]
) -> None:
    source = _source(tmp_path)
    directory = tmp_path / "fetch-prepared"
    prepared = _prepared(directory, ready=False, blockers=("Input CSV has structural validation errors.",))
    rows = pd.DataFrame({"label": ["cat", "dog"]})
    _fake_prepare(monkeypatch, replace(prepared, validation=replace(prepared.validation, broken_images=rows)))
    assert _run_verify([str(source)]) == 1
    assert f"В broken-images.csv записано 2 строк: {directory / 'broken-images.csv'}" in capture_info_logs


def test_verify_summarises_the_classes_of_a_first_preparation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capture_info_logs: list[str]
) -> None:
    source = _source(tmp_path)
    directory = tmp_path / "fetch-prepared"
    classes = {
        "bowl": ClassInfo(prod_id=1),
        "cup": ClassInfo(prod_id=2),
        "umbrella": ClassInfo(prod_id=10, empty=True),
    }
    prepared = _prepared(
        directory,
        parent=None,
        metadata=DatasetMetadata(api_url="https://classes.example/api", classes=classes),
        changes=tuple(ClassChange("added", info.prod_id, name) for name, info in classes.items()),
        mark_changes=(ClassMarkChange(10, "umbrella", empty=True),),
    )
    _fake_prepare(monkeypatch, prepared)
    CliApp().run(["verify", str(source)])
    assert capture_info_logs[1:-2] == [
        "Родительской версии нет: 3 классов из API, исключено 1",
        "Класс 10 umbrella исключён",
    ]
    assert not any(message.startswith("Класс добавлен") for message in capture_info_logs)
