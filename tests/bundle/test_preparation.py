"""Bundle preparation writes real files once; publication runs against fake remote ports."""

import json
import os
import re
import threading
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
import yaml

from cveta2.adapters.files.archive import unpack_sources
from cveta2.adapters.files.bundle import LocalBundleFiles
from cveta2.application.use_cases.dataset_bundle import prepare_dataset, upload_dataset
from cveta2.domain.bundle.models import (
    ClassInfo,
    ClassMarkChange,
    DatasetMetadata,
    DatasetParent,
    ImageRoots,
    Publication,
    UploadError,
)
from cveta2.domain.bundle.preparation import PUBLISHED_NAMES, SOURCE_NAMES, MissingDecisions, PrepareOptions
from cveta2.domain.managed.models import (
    ClearMLDestination,
    CvatIdentity,
    DatasetDefinition,
    ManagedMetadata,
    SourceDefinition,
)
from cveta2.domain.verification.models import DatasetInputError
from tests.bundle.conftest import API_URL, DATASET, PROJECT, Scenario, Store, api_class, write_draft


def _duplicate_first_row(source: Path) -> None:
    path = source / "dataset.csv"
    original = path.read_text()
    path.write_text(original + original.splitlines()[1] + "\n")


def _read_rows(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def _edit_source(source: Path, edit: Callable[[pd.DataFrame], pd.DataFrame]) -> None:
    edit(_read_rows(source / "dataset.csv")).to_csv(source / "dataset.csv", index=False)


def _set_splits(splits: dict[str, str]) -> Callable[[pd.DataFrame], pd.DataFrame]:
    def edit(frame: pd.DataFrame) -> pd.DataFrame:
        for name, split in splits.items():
            frame.loc[frame["image_name"] == name, "split"] = split
        return frame

    return edit


def _splits(path: Path) -> dict[str, str]:
    frame = _read_rows(path)
    return dict(zip(frame["image_name"], frame["split"], strict=True))


def _set_parent(  # noqa: PLR0913 - keyword-only parent facts of one test setup.
    store: Store,
    tmp_path: Path,
    *,
    classes: dict[str, ClassInfo] | None = None,
    images: ImageRoots | None = None,
    managed: ManagedMetadata | None = None,
    published_rows: str | None = None,
) -> None:
    """Make the store's latest version of the scenario's destination a parent with these facts."""
    metadata = DatasetMetadata(
        api_url=API_URL,
        classes=classes or {"cat": ClassInfo(prod_id=7)},
        images=images or ImageRoots(),
        managed=managed,
    )
    path = tmp_path / "parent.yaml"
    path.write_text(yaml.safe_dump(metadata.model_dump(mode="json"), sort_keys=False), encoding="utf-8")
    store.parent = DatasetParent("parent-id", PROJECT, DATASET, "1", path)
    if published_rows is not None:
        rows = tmp_path / "parent.csv"
        rows.write_text(published_rows, encoding="utf-8")
        store.parent_files["dataset.csv"] = rows


def _report(directory: Path) -> dict[str, Any]:
    report: dict[str, Any] = json.loads((directory / "report.json").read_bytes())
    return report


def test_bundle_layout_has_archive_and_no_preparation_record(scenario: Scenario, tmp_path: Path) -> None:
    source, options, services, store, _classes = scenario
    original = {p.name: p.read_bytes() for p in source.iterdir()}
    prepared = tmp_path / "prepared"
    result = prepare_dataset(source, prepared, options, services)
    assert result.ready
    assert store.calls == 0
    assert {p.name for p in prepared.iterdir()} == {
        "sources.tar.gz",
        "broken-images.csv",
        "report.json",
        "dataset.csv",
        "dataset.yaml",
        "tasks.yaml",
    }
    assert unpack_sources((prepared / "sources.tar.gz").read_bytes()) == {name: original[name] for name in SOURCE_NAMES}
    metadata_text = (prepared / "dataset.yaml").read_text(encoding="utf-8")
    assert metadata_text.startswith("clearml:")
    draft = yaml.safe_load(original["dataset.yaml"])
    assert yaml.safe_load(metadata_text)["clearml"] == draft["clearml"] == {"project": PROJECT, "dataset": DATASET}
    assert result.parent is None
    report = json.loads((prepared / "report.json").read_bytes())
    assert report["parent"] is None
    assert report["destination"] == {"project": PROJECT, "dataset": DATASET}
    assert report["pending"] == []
    assert report["class_marks"] == []
    assert report["dropped_local_roots"] == []
    assert report["split_prefilled"] == 0
    assert upload_dataset(prepared, services).dataset_id == "child"
    assert store.files == PUBLISHED_NAMES
    assert set(store.published) == set(PUBLISHED_NAMES)
    assert {p.name: p.read_bytes() for p in source.iterdir()} == original


def test_draft_values_are_used_without_flags(scenario: Scenario, tmp_path: Path) -> None:
    source, options, services, _store, _classes = scenario
    images = Path(options.local_roots[0])
    link = tmp_path / "images-link"
    link.symlink_to(images)
    clearml = {"project": "Retail/Datasets", "dataset": "retail-shelves", "output_uri": "s3://bucket/.clearml"}
    write_draft(
        source,
        {
            "clearml": clearml,
            "api_url": API_URL,
            "images": {"local_root": [str(link)], "s3_root": ["s3://bucket/images"]},
        },
    )
    prepared = tmp_path / "prepared"
    result = prepare_dataset(source, prepared, PrepareOptions(), services)
    assert result.ready
    metadata = yaml.safe_load((prepared / "dataset.yaml").read_text(encoding="utf-8"))
    assert metadata["clearml"] == clearml
    assert metadata["api_url"] == API_URL
    assert metadata["images"] == {"local_root": [str(images.resolve())], "s3_root": ["s3://bucket/images"]}
    assert _report(prepared)["destination"] == {"project": "Retail/Datasets", "dataset": "retail-shelves"}


# A refused URL with credentials, its password, and how a refusal may show it.
_SECRET_URLS = {
    "output_uri": ("s3://key:se/cret@bucket/x", "se/cret", "s3://***@bucket/x"),
    "api_url": ("https://key:se/cret@host/api", "se/cret", "https://***@host/api"),
}


@pytest.mark.parametrize("where", ["flag", "draft"])
@pytest.mark.parametrize("key", ["output_uri", "api_url"])
def test_refused_url_option_hides_its_credentials(scenario: Scenario, tmp_path: Path, where: str, key: str) -> None:
    source, options, services, store, _classes = scenario
    secret, password, hidden = _SECRET_URLS[key]
    if where == "flag":
        options = options.model_copy(update={key: secret})
    else:
        clearml: dict[str, str] = {"project": PROJECT, "dataset": DATASET}
        draft: dict[str, object] = {"clearml": clearml, "api_url": API_URL}
        (clearml if key == "output_uri" else draft)[key] = secret
        write_draft(source, draft)
    with pytest.raises(UploadError) as caught:
        prepare_dataset(source, tmp_path / "prepared", options, services)
    shown = "".join(traceback.format_exception(caught.value))
    assert hidden in str(caught.value)
    assert password not in shown
    assert "key:" not in shown
    assert store.calls == 0
    assert not (tmp_path / "prepared").exists()


def test_missing_destination_raises_project_and_dataset_decisions(scenario: Scenario, tmp_path: Path) -> None:
    source, options, services, store, _classes = scenario
    (source / "dataset.yaml").unlink()
    prepared = tmp_path / "prepared"
    with pytest.raises(MissingDecisions) as caught:
        prepare_dataset(source, prepared, options, services)
    assert {decision.kind for decision in caught.value.decisions} == {"project", "dataset_name"}
    assert not prepared.exists()
    assert not list(tmp_path.glob(".cveta2-prepare-*"))
    assert store.calls == 0


def test_no_class_questions_and_changes_are_reported(scenario: Scenario, tmp_path: Path) -> None:
    source, options, services, store, classes = scenario
    _set_parent(store, tmp_path)
    classes.records = [api_class(7, "kitty"), api_class(9, "dog")]
    _edit_source(source, lambda frame: frame.assign(instance_label=["kitty", "dog", "kitty"]))
    prepared = tmp_path / "prepared"
    result = prepare_dataset(source, prepared, options, services)
    assert result.ready
    assert sorted((change.kind, change.prod_id, change.name) for change in result.changes) == [
        ("added", 9, "dog"),
        ("renamed", 7, "kitty"),
    ]
    assert sorted(change["kind"] for change in _report(prepared)["class_changes"]) == ["added", "renamed"]
    assert result.metadata.classes["kitty"].alt_names == ["cat"]


@pytest.mark.parametrize(
    ("draft_marks", "class_empty", "cat_empty", "dog_empty", "mark_changes"),
    [
        pytest.param(None, {}, False, True, (), id="parent-mark-kept"),
        pytest.param([7], {}, True, True, (ClassMarkChange(7, "cat", empty=True),), id="draft-adds"),
        pytest.param(None, {9: False}, False, False, (ClassMarkChange(9, "dog", empty=False),), id="include-clears"),
    ],
)
def test_parent_marks_kept_draft_adds_include_clears(  # noqa: PLR0913 - parametrized expectations.
    scenario: Scenario,
    tmp_path: Path,
    draft_marks: list[int] | None,
    class_empty: dict[int, bool],
    mark_changes: tuple[ClassMarkChange, ...],
    *,
    cat_empty: bool,
    dog_empty: bool,
) -> None:
    source, options, services, store, classes = scenario
    _set_parent(store, tmp_path, classes={"cat": ClassInfo(prod_id=7), "dog": ClassInfo(prod_id=9, empty=True)})
    classes.records.append(api_class(9, "dog"))
    draft: dict[str, object] = {"clearml": {"project": PROJECT, "dataset": DATASET}}
    if draft_marks is not None:
        draft["empty_classes"] = draft_marks
    write_draft(source, draft)
    prepared = tmp_path / "prepared"
    result = prepare_dataset(source, prepared, options.model_copy(update={"class_empty": class_empty}), services)
    assert result.metadata.classes["cat"].empty is cat_empty
    assert result.metadata.classes["dog"].empty is dog_empty
    assert result.mark_changes == mark_changes
    assert _report(prepared)["class_marks"] == [
        {"prod_id": mark.prod_id, "name": mark.name, "empty": mark.empty} for mark in mark_changes
    ]


def test_unknown_excluded_class_number_is_error(scenario: Scenario, tmp_path: Path) -> None:
    source, options, services, _store, _classes = scenario
    write_draft(
        source, {"clearml": {"project": PROJECT, "dataset": DATASET}, "api_url": API_URL, "empty_classes": [99]}
    )
    with pytest.raises(UploadError, match="99"):
        prepare_dataset(source, tmp_path / "prepared", options, services)
    assert not (tmp_path / "prepared").exists()


def test_missing_parent_local_root_is_dropped(scenario: Scenario, tmp_path: Path) -> None:
    source, options, services, store, _classes = scenario
    _set_parent(store, tmp_path, images=ImageRoots(local_root=["/nonexistent/root"]))
    prepared = tmp_path / "prepared"
    result = prepare_dataset(source, prepared, options, services)
    assert result.ready
    assert result.dropped_local_roots == ("/nonexistent/root",)
    assert "/nonexistent/root" not in result.metadata.images.local_root
    assert "/nonexistent/root" not in yaml.safe_load((prepared / "dataset.yaml").read_text())["images"]["local_root"]
    assert _report(prepared)["dropped_local_roots"] == ["/nonexistent/root"]


def test_missing_draft_local_root_is_an_error(scenario: Scenario, tmp_path: Path) -> None:
    source, options, services, _store, _classes = scenario
    write_draft(
        source,
        {
            "clearml": {"project": PROJECT, "dataset": DATASET},
            "api_url": API_URL,
            "images": {"local_root": ["/nonexistent/root"]},
        },
    )
    with pytest.raises(UploadError, match="/nonexistent/root"):
        prepare_dataset(source, tmp_path / "prepared", options, services)
    assert not (tmp_path / "prepared").exists()


def test_managed_parent_is_refused_at_preparation(scenario: Scenario, tmp_path: Path) -> None:
    source, options, services, store, _classes = scenario
    managed = ManagedMetadata(
        name="demo",
        definition_hash="0" * 64,
        definition=DatasetDefinition(
            sources=[SourceDefinition(name="cvat", type="cvat", project="demo")],
            clearml=ClearMLDestination(project=PROJECT, dataset=DATASET),
            api_url=API_URL,
        ),
        cvat=CvatIdentity(host="https://cvat.example.org"),
    )
    _set_parent(store, tmp_path, managed=managed)
    with pytest.raises(UploadError, match=r"parent-id.*управляем"):
        prepare_dataset(source, tmp_path / "prepared", options, services)
    assert not (tmp_path / "prepared").exists()


def test_empty_split_prepares_payload_with_pending(scenario: Scenario, tmp_path: Path) -> None:
    source, options, services, _store, _classes = scenario
    _edit_source(source, lambda frame: frame.assign(split=""))
    prepared = tmp_path / "prepared"
    result = prepare_dataset(source, prepared, options, services)
    assert result.ready
    assert (prepared / "dataset.csv").exists()
    pending = "заполните split у 3 изображений в " + str(prepared / "dataset.csv")
    assert result.pending == (pending,)
    assert _report(prepared)["pending"] == [pending]


@pytest.mark.parametrize("parent", [None, "val"], ids=["no-parent", "parent-publishes-val"])
def test_image_with_one_valid_and_one_empty_split_row_is_pending(
    scenario: Scenario, tmp_path: Path, parent: str | None
) -> None:
    source, options, services, store, _classes = scenario
    if parent is not None:
        # The parent disagrees with the user's ``train``: the image is left as written, never half-filled.
        _set_parent(store, tmp_path, published_rows=f"image_name,split\ntrain.png,{parent}\n")

    def add_second_box(frame: pd.DataFrame) -> pd.DataFrame:
        extra = frame[frame["image_name"] == "train.png"].assign(split="", bbox_x_tl="21", bbox_x_br="30")
        return pd.concat([frame, extra], ignore_index=True)

    _edit_source(source, add_second_box)
    prepared = tmp_path / "prepared"
    result = prepare_dataset(source, prepared, options, services)
    assert result.ready
    assert result.blockers == ()
    missing = "заполните split у 1 изображений в " + str(prepared / "dataset.csv")
    changed = (
        "у 1 изображений split отличается от опубликованного в родителе parent-id: "
        "upload-dataset откажет без --force-resplit"
    )
    assert result.pending == ((missing,) if parent is None else (missing, changed))
    assert result.split_prefilled == 0
    assert _read_rows(prepared / "broken-images.csv").empty
    assert list(_read_rows(prepared / "dataset.csv")["split"]) == ["train", "val", "val", ""]
    with pytest.raises(UploadError, match="split"):
        upload_dataset(prepared, services)
    assert store.calls == 0


def test_split_prefilled_from_parent_only_in_empty_cells(scenario: Scenario, tmp_path: Path) -> None:
    source, options, services, store, _classes = scenario
    _edit_source(source, _set_splits({"train.png": "", "val.png": "test", "val2.png": ""}))
    fetched = (source / "dataset.csv").read_bytes()
    _set_parent(store, tmp_path, published_rows="image_name,split\ntrain.png,train\nval.png,val\n")
    prepared = tmp_path / "prepared"
    result = prepare_dataset(source, prepared, options, services)
    assert result.ready
    assert _splits(prepared / "dataset.csv") == {"train.png": "train", "val.png": "test", "val2.png": ""}
    assert result.split_prefilled == 1
    assert result.parent == store.parent
    assert _report(prepared)["split_prefilled"] == 1
    assert unpack_sources((prepared / "sources.tar.gz").read_bytes())["dataset.csv"] == fetched
    assert (source / "dataset.csv").read_bytes() == fetched


@pytest.mark.parametrize("parent", ["none", "no-dataset-csv"])
def test_nothing_is_prefilled_without_a_published_dataset_csv(scenario: Scenario, tmp_path: Path, parent: str) -> None:
    source, options, services, store, _classes = scenario
    _edit_source(source, _set_splits({"train.png": ""}))
    if parent == "no-dataset-csv":
        _set_parent(store, tmp_path)
    prepared = tmp_path / "prepared"
    result = prepare_dataset(source, prepared, options, services)
    assert result.split_prefilled == 0
    assert _report(prepared)["split_prefilled"] == 0
    assert _splits(prepared / "dataset.csv")["train.png"] == ""


def test_changed_split_of_a_published_image_is_pending(scenario: Scenario, tmp_path: Path) -> None:
    source, options, services, store, _classes = scenario

    def add_second_box(frame: pd.DataFrame) -> pd.DataFrame:
        # Each image is counted once, however many of its rows changed.
        extra = frame[frame["image_name"] == "val2.png"].assign(bbox_x_tl="21", bbox_x_br="30")
        return pd.concat([frame, extra], ignore_index=True)

    _edit_source(source, add_second_box)
    _set_parent(store, tmp_path, published_rows="image_name,split\ntrain.png,train\nval.png,test\nval2.png,train\n")
    prepared = tmp_path / "prepared"
    result = prepare_dataset(source, prepared, options, services)
    assert result.ready
    pending = (
        "у 2 изображений split отличается от опубликованного в родителе parent-id: "
        "upload-dataset откажет без --force-resplit"
    )
    assert result.pending == (pending,)
    assert _report(prepared)["pending"] == [pending]


def test_trainability_gaps_are_pending(scenario: Scenario, tmp_path: Path) -> None:
    source, options, services, _store, _classes = scenario
    _edit_source(source, lambda frame: frame.assign(split="train"))
    result = prepare_dataset(source, tmp_path / "prepared", options, services)
    assert result.ready
    assert result.pending == ("в val нет изображений",)


def test_missing_active_class_blocks_until_excluded(scenario: Scenario, tmp_path: Path) -> None:
    source, options, services, _store, classes = scenario
    classes.records.append(api_class(9, "dog"))
    blocked = tmp_path / "blocked"
    result = prepare_dataset(source, blocked, options, services)
    assert not result.ready
    assert not (blocked / "dataset.csv").exists()
    assert any("dog" in blocker for blocker in result.blockers)
    assert not any("dog" in item for item in result.pending)
    excluded = tmp_path / "excluded"
    result = prepare_dataset(source, excluded, options.model_copy(update={"class_empty": {9: True}}), services)
    assert result.ready
    assert yaml.safe_load((excluded / "dataset.yaml").read_text())["classes"]["dog"]["empty"] is True
    _edit_source(
        source,
        lambda frame: frame.assign(
            instance_label=frame["instance_label"].where(frame["image_name"] != "val2.png", "dog"),
            split=frame["split"].where(frame["image_name"] != "val2.png", "test"),
        ),
    )
    assert prepare_dataset(source, tmp_path / "boxed", options, services).ready


def test_cleanup_dropping_rows_is_still_ready(scenario: Scenario, tmp_path: Path) -> None:
    source, options, services, _store, _classes = scenario
    _duplicate_first_row(source)
    prepared = tmp_path / "prepared"
    result = prepare_dataset(source, prepared, options, services)
    assert options.clean
    assert result.ready
    assert len(result.validation.result.broken) == 1
    assert list(_read_rows(prepared / "dataset.csv")["image_name"]) == ["train.png", "val.png", "val2.png"]
    assert set(_read_rows(prepared / "broken-images.csv")["image_name"]) == {"train.png"}


def test_no_clean_with_rejected_rows_blocks(scenario: Scenario, tmp_path: Path) -> None:
    source, options, services, _store, _classes = scenario
    _duplicate_first_row(source)
    prepared = tmp_path / "prepared"
    result = prepare_dataset(source, prepared, options.model_copy(update={"clean": False}), services)
    assert not result.ready
    assert not (prepared / "dataset.csv").exists()
    assert any("--no-clean" in blocker for blocker in result.blockers)


@pytest.mark.parametrize("problem", ["empty", "relative", "deleted"])
def test_unusable_image_path_stops_preparation_without_writing(
    scenario: Scenario, tmp_path: Path, problem: str
) -> None:
    source, options, services, _store, _classes = scenario
    image = Path(options.local_roots[0]) / "val.png"
    named = {"empty": "image_path", "relative": "images/val.png", "deleted": str(image)}[problem]
    if problem == "deleted":
        image.unlink()
    else:
        value = "" if problem == "empty" else "images/val.png"
        _edit_source(
            source,
            lambda frame: frame.assign(image_path=frame["image_path"].where(frame["image_name"] != "val.png", value)),
        )
    prepared = tmp_path / "prepared"
    with pytest.raises(UploadError, match=re.escape(named)):
        prepare_dataset(source, prepared, options, services)
    assert not prepared.exists()
    assert not list(tmp_path.glob(".cveta2-prepare-*"))


def test_duplicate_source_columns_stop_preparation_before_prefill(scenario: Scenario, tmp_path: Path) -> None:
    source, options, services, store, _classes = scenario
    _set_parent(store, tmp_path, published_rows="image_name,split\ntrain.png,train\n")
    header, *rows = (source / "dataset.csv").read_text().splitlines()
    # A second, empty ``split`` column: the prefill reader cannot handle it, so the CSV reader must refuse it.
    (source / "dataset.csv").write_text("\n".join([f"{header},split", *(f"{row}," for row in rows)]) + "\n")
    prepared = tmp_path / "prepared"
    with pytest.raises(DatasetInputError, match="unique"):
        prepare_dataset(source, prepared, options, services)
    assert not prepared.exists()


def test_default_output_directory_is_next_free_sibling(
    scenario: Scenario, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, options, services, _store, _classes = scenario
    first = prepare_dataset(source, None, options, services)
    assert first.directory == tmp_path / "source-prepared"
    files = {p.name: p.read_bytes() for p in first.directory.iterdir()}
    second = prepare_dataset(source, None, options, services)
    assert second.directory == tmp_path / "source-prepared-2"
    assert {p.name: p.read_bytes() for p in first.directory.iterdir()} == files
    monkeypatch.chdir(source)
    third = prepare_dataset(Path(), None, options, services)
    assert third.directory == tmp_path / "source-prepared-3"
    assert third.directory.is_dir()
    assert not (source / "source-prepared-3").exists()
    with pytest.raises(UploadError):
        prepare_dataset(source, first.directory, options, services)


def test_report_only_does_not_create_uploadable_cleaned_bundle(scenario: Scenario, tmp_path: Path) -> None:
    source, options, services, store, _classes = scenario
    _duplicate_first_row(source)
    result = prepare_dataset(source, tmp_path / "report", options.model_copy(update={"clean": False}), services)
    assert not result.ready
    assert result.validation.result.requires_cleanup
    assert not (tmp_path / "report" / "dataset.csv").exists()
    clean = options.model_copy(update={"clean": True})
    result = prepare_dataset(source, tmp_path / "prepared", clean, services)
    assert result.ready
    assert upload_dataset(tmp_path / "prepared", services).dataset_id == "child"
    assert store.calls == 1


def test_blocked_preparation_writes_archive_and_report_only(scenario: Scenario, tmp_path: Path) -> None:
    source, options, services, _store, _classes = scenario
    _duplicate_first_row(source)
    prepared = tmp_path / "blocked"
    result = prepare_dataset(source, prepared, options.model_copy(update={"clean": False}), services)
    assert not result.ready
    assert any(blocker.startswith("Нужна очистка:") for blocker in result.blockers)
    assert {p.name for p in prepared.iterdir()} == {"sources.tar.gz", "broken-images.csv", "report.json"}
    report = json.loads((prepared / "report.json").read_bytes())
    assert report["ready"] is False
    assert report["blockers"] == list(result.blockers)


def test_existing_destination_is_preserved(scenario: Scenario, tmp_path: Path) -> None:
    source, options, services, _store, _classes = scenario
    directory = tmp_path / "prepared"
    directory.mkdir()
    (directory / "owned.txt").write_text("keep")
    with pytest.raises(UploadError):
        prepare_dataset(source, directory, options, services)
    assert (directory / "owned.txt").read_text() == "keep"


@pytest.mark.parametrize("filename", ["dataset.csv", "obsolete.csv", "in_progress.csv", "deleted.csv"])
def test_header_only_sources_require_evidence_columns(scenario: Scenario, tmp_path: Path, filename: str) -> None:
    source, options, services, store, _classes = scenario
    (source / filename).write_text("unexpected\n")
    with pytest.raises(UploadError, match=r"column|header"):
        prepare_dataset(source, tmp_path / "prepared", options, services)
    assert store.calls == 0


def test_invalid_api_configuration_is_a_library_error(scenario: Scenario, tmp_path: Path) -> None:
    source, options, services, store, _classes = scenario
    with pytest.raises(UploadError, match=r"API|metadata|URL"):
        prepare_dataset(
            source,
            tmp_path / "prepared",
            options.model_copy(update={"api_url": "bad-url"}),
            services,
        )
    assert store.calls == 0


def test_private_stage_is_removed_on_publication_failure(
    scenario: Scenario, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, options, services, store, _classes = scenario
    prepared = tmp_path / "prepared"
    prepare_dataset(source, prepared, options, services)
    stages: list[Path] = []

    def fail_publish(
        _project: str,
        _name: str,
        _parent: str | None,
        directory: Path,
        *,
        files: tuple[str, ...],
        output_uri: str | None = None,
    ) -> Publication:
        assert files
        assert output_uri is None
        stages.append(directory)
        assert directory.is_dir()
        raise UploadError("child creation failed")

    monkeypatch.setattr(store, "publish", fail_publish)
    with pytest.raises(UploadError, match="creation failed"):
        upload_dataset(prepared, services)
    assert len(stages) == 1
    assert not stages[0].exists()
    assert not (prepared / "publication.json").exists()


@pytest.mark.parametrize("artifact", ["dataset.csv", "dataset.yaml", "sources.tar.gz"])
def test_symlinked_prepared_artifacts_are_rejected(scenario: Scenario, tmp_path: Path, artifact: str) -> None:
    source, options, services, store, _classes = scenario
    prepared = tmp_path / "prepared"
    prepare_dataset(source, prepared, options, services)
    target = prepared / artifact
    outside = tmp_path / "original"
    target.rename(outside)
    target.symlink_to(outside)
    with pytest.raises(UploadError, match="nonsymlink"):
        upload_dataset(prepared, services)
    assert store.calls == 0


@pytest.mark.parametrize(
    "text",
    [
        "api_url: x\napi_url: y\n",
        "classes: &classes {cat: *classes}\n",
        "[invalid",
        "true: invalid\n",
        "api_url: https://example.org/classes\nclasses: {}\nimages: " + "[" * 5000 + "]" * 5000 + "\n",
    ],
    ids=["duplicate-key", "recursive-alias", "syntax", "non-text-key", "deep-nesting"],
)
def test_strict_metadata_rejects_ambiguous_yaml(tmp_path: Path, text: str) -> None:
    metadata = tmp_path / "dataset.yaml"
    metadata.write_text(text)
    with pytest.raises(UploadError):
        LocalBundleFiles().read_metadata(metadata)


def test_strict_metadata_checks_reused_aliases_once(tmp_path: Path) -> None:
    levels = 60
    lines = ["api_url: https://example.org/classes", "classes: {}", "x0: &a0 [x, x]"]
    lines += [f"x{level}: &a{level} [*a{level - 1}, *a{level - 1}]" for level in range(1, levels + 1)]
    metadata = tmp_path / "dataset.yaml"
    metadata.write_text("\n".join(lines) + "\n")
    outcome: list[BaseException] = []

    def read() -> None:
        try:
            LocalBundleFiles().read_metadata(metadata)
        except UploadError as error:
            outcome.append(error)

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    reader.join(timeout=10)
    assert not reader.is_alive(), "alias fan-out is re-walked on every reference"
    assert len(outcome) == 1
    assert "x0" in str(outcome[0])


def test_interrupted_write_leaves_no_bundle(
    scenario: Scenario, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, options, services, store, _classes = scenario
    prepared = tmp_path / "prepared"

    def fail_rename(_source: object, _destination: object) -> None:
        raise OSError("bundle could not be moved into place")

    monkeypatch.setattr(os, "rename", fail_rename)
    with pytest.raises(UploadError, match="could not be moved"):
        prepare_dataset(source, prepared, options, services)
    assert not prepared.exists()
    assert not list(tmp_path.glob(".cveta2-prepare-*"))
    monkeypatch.undo()
    with pytest.raises(UploadError):
        upload_dataset(prepared, services)
    assert store.calls == 0
