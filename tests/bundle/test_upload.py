"""``upload-dataset`` validates the bundle's current files and publishes them as they are."""

import json
import re
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pandas as pd
import pytest
import yaml

from cveta2.application.use_cases.dataset_bundle import prepare_dataset, upload_dataset
from cveta2.domain.bundle.models import ClassInfo, DatasetMetadata, DatasetParent, UploadError
from cveta2.domain.bundle.preparation import PUBLISHED_NAMES, PrepareOptions
from cveta2.domain.managed.models import (
    ClearMLDestination,
    CvatIdentity,
    DatasetDefinition,
    ManagedMetadata,
    SourceDefinition,
)
from tests.bundle.conftest import Scenario, Storage, api_class

API_URL = "https://example.org/classes"


def _prepare(scenario: Scenario, tmp_path: Path, options: PrepareOptions | None = None) -> Path:
    source, default, services, _store, _classes = scenario
    prepared = tmp_path / "prepared"
    assert prepare_dataset(source, prepared, options or default, services).ready
    return prepared


def _edit_rows(prepared: Path, edit: Callable[[pd.DataFrame], pd.DataFrame]) -> None:
    path = prepared / "dataset.csv"
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    edit(frame).to_csv(path, index=False)


def _edit_metadata(prepared: Path, edit: Callable[[dict[str, object]], object]) -> None:
    path = prepared / "dataset.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    edit(data)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _edit_report(prepared: Path, edit: Callable[[dict[str, object]], None]) -> None:
    path = prepared / "report.json"
    data = json.loads(path.read_bytes())
    edit(data)
    path.write_text(json.dumps(data), encoding="utf-8")


def _set_split(name: str, split: str) -> Callable[[pd.DataFrame], pd.DataFrame]:
    def edit(frame: pd.DataFrame) -> pd.DataFrame:
        frame.loc[frame["image_name"] == name, "split"] = split
        return frame

    return edit


def _clearml(data: dict[str, object]) -> dict[str, str]:
    return cast("dict[str, str]", data["clearml"])


def _parent_metadata(path: Path, *, managed: ManagedMetadata | None = None) -> Path:
    metadata = DatasetMetadata(api_url=API_URL, classes={"cat": ClassInfo(prod_id=7)}, managed=managed)
    path.write_text(yaml.safe_dump(metadata.model_dump(mode="json"), sort_keys=False), encoding="utf-8")
    return path


def test_upload_publishes_four_files_with_output_uri_and_writes_publication_json(
    scenario: Scenario, tmp_path: Path
) -> None:
    _source, options, services, store, _classes = scenario
    prepared = _prepare(scenario, tmp_path)
    _edit_metadata(prepared, lambda data: _clearml(data).update(output_uri="s3://bucket/.clearml"))
    expected = {name: (prepared / name).read_bytes() for name in ("dataset.csv", "dataset.yaml", "sources.tar.gz")}
    publication = upload_dataset(prepared, services)
    assert publication.dataset_id == "child"
    assert store.files == PUBLISHED_NAMES
    assert set(store.published) == set(PUBLISHED_NAMES)
    assert {name: store.published[name] for name in expected} == expected
    assert store.published["tasks.yaml"] == (prepared / "tasks.yaml").read_bytes()
    assert store.output_uri == "s3://bucket/.clearml"
    assert store.parent_id is None
    assert "s3://bucket" in cast("Storage", services.s3).checked
    record = json.loads((prepared / "publication.json").read_bytes())
    assert record["dataset_id"] == "child"
    assert record["version"] == "1.0.0"
    assert (record["project"], record["dataset"]) == (options.project, options.dataset_name)
    assert record["published_at"]


def test_upload_accepts_edits_and_rederives_tasks(scenario: Scenario, tmp_path: Path) -> None:
    _source, _options, services, store, _classes = scenario
    prepared = _prepare(scenario, tmp_path)
    assert yaml.safe_load((prepared / "tasks.yaml").read_text())["included"] == [1, 2, 3]

    def edit(frame: pd.DataFrame) -> pd.DataFrame:
        frame = frame[frame["image_name"] != "val2.png"].copy()
        frame.loc[frame["image_name"] == "train.png", "bbox_x_br"] = "25"
        return frame

    _edit_rows(prepared, edit)
    upload_dataset(prepared, services)
    assert store.calls == 1
    assert yaml.safe_load((prepared / "tasks.yaml").read_text())["included"] == [1, 2]
    assert b"val2.png" not in store.published["dataset.csv"]
    assert store.published["tasks.yaml"] == (prepared / "tasks.yaml").read_bytes()


def test_upload_refuses_rows_without_split(scenario: Scenario, tmp_path: Path) -> None:
    _source, _options, services, store, _classes = scenario
    prepared = _prepare(scenario, tmp_path)
    _edit_rows(prepared, _set_split("val2.png", ""))
    with pytest.raises(UploadError, match="split"):
        upload_dataset(prepared, services)
    assert store.calls == 0


def test_upload_refuses_missing_active_class_naming_both_fixes(scenario: Scenario, tmp_path: Path) -> None:
    _source, options, services, store, classes = scenario
    classes.records.append(api_class(8, "cup"))
    prepared = _prepare(scenario, tmp_path, options.model_copy(update={"class_empty": {8: True}}))

    def include_cup(empty: bool) -> Callable[[dict[str, object]], None]:  # noqa: FBT001
        def edit(data: dict[str, object]) -> None:
            cast("dict[str, object]", data["classes"])["cup"] = {"prod_id": 8, "empty": empty, "alt_names": []}

        return edit

    _edit_metadata(prepared, include_cup(empty=False))
    with pytest.raises(UploadError, match=r"cup(.|\n)*empty: true"):
        upload_dataset(prepared, services)
    assert store.calls == 0
    _edit_metadata(prepared, include_cup(empty=True))
    assert upload_dataset(prepared, services).dataset_id == "child"


def test_changed_split_of_published_image_is_refused_unless_forced(scenario: Scenario, tmp_path: Path) -> None:
    _source, _options, services, store, _classes = scenario
    store.parent = DatasetParent("parent-id", "inspection", "training", "1", _parent_metadata(tmp_path / "parent.yaml"))
    published = tmp_path / "parent.csv"
    published.write_text("image_name,split\nval.png,val\n", encoding="utf-8")
    store.parent_files["dataset.csv"] = published
    prepared = _prepare(scenario, tmp_path)
    _edit_rows(prepared, _set_split("val.png", "test"))
    with pytest.raises(UploadError, match=r"val\.png: val → test(.|\n)*--force-resplit"):
        upload_dataset(prepared, services)
    assert store.calls == 0
    assert upload_dataset(prepared, services, force_resplit=True).dataset_id == "child"
    assert store.parent_id == "parent-id"
    # An image the parent does not hold may have any split.
    _edit_rows(prepared, _set_split("val.png", "val"))
    _edit_rows(prepared, _set_split("val2.png", "test"))
    upload_dataset(prepared, services)
    assert store.calls == 2


def test_untraceable_rows_are_accepted_and_counted(
    scenario: Scenario, tmp_path: Path, capture_info_logs: list[str]
) -> None:
    _source, _options, services, store, _classes = scenario
    prepared = _prepare(scenario, tmp_path)

    def add_untraced(frame: pd.DataFrame) -> pd.DataFrame:
        row = frame[frame["image_name"] == "val2.png"].iloc[0].copy()
        row[["bbox_x_tl", "bbox_y_tl", "bbox_x_br", "bbox_y_br", "task_id"]] = ["22", "22", "30", "30", "99"]
        return pd.concat([frame, row.to_frame().T], ignore_index=True)

    _edit_rows(prepared, add_untraced)
    upload_dataset(prepared, services)
    assert store.calls == 1
    tasks = yaml.safe_load((prepared / "tasks.yaml").read_text())
    assert tasks["included"] == [1, 2, 3]
    assert 99 not in tasks["included"]
    assert any(line.startswith("1 строк dataset.csv") for line in capture_info_logs)


def test_missing_image_file_is_refused_naming_it(scenario: Scenario, tmp_path: Path) -> None:
    _source, options, services, store, _classes = scenario
    prepared = _prepare(scenario, tmp_path)
    missing = Path(options.local_roots[0]) / "val.png"
    missing.unlink()
    with pytest.raises(UploadError, match=r"Нет файлов изображений(.|\n)*" + re.escape(str(missing))):
        upload_dataset(prepared, services)
    assert store.calls == 0


def test_missing_files_listing_is_capped(scenario: Scenario, tmp_path: Path) -> None:
    _source, options, services, store, _classes = scenario
    prepared = _prepare(scenario, tmp_path)
    root = Path(options.local_roots[0])

    def add_missing(frame: pd.DataFrame) -> pd.DataFrame:
        rows = frame.iloc[[0] * 21].copy()
        rows["image_name"] = [f"gone-{index}.png" for index in range(21)]
        rows["image_path"] = [str(root / f"gone-{index}.png") for index in range(21)]
        return pd.concat([frame, rows], ignore_index=True)

    _edit_rows(prepared, add_missing)
    with pytest.raises(UploadError, match=r"\(21\)") as caught:
        upload_dataset(prepared, services)
    assert "gone-19.png" in str(caught.value)
    assert "gone-20.png" not in str(caught.value)
    assert "и ещё 1" in str(caught.value)
    assert store.calls == 0


def test_upload_refuses_rejected_or_repaired_rows(scenario: Scenario, tmp_path: Path) -> None:
    _source, _options, services, store, _classes = scenario
    prepared = _prepare(scenario, tmp_path)
    _edit_rows(prepared, lambda frame: pd.concat([frame, frame.iloc[[0]]], ignore_index=True))
    with pytest.raises(UploadError, match="не проходит проверку"):
        upload_dataset(prepared, services)
    assert store.calls == 0


@pytest.mark.parametrize("where", ["dataset.yaml", "registry"])
def test_upload_refuses_class_identity_mismatch(scenario: Scenario, tmp_path: Path, where: str) -> None:
    _source, _options, services, store, classes = scenario
    prepared = _prepare(scenario, tmp_path)
    if where == "dataset.yaml":
        _edit_metadata(
            prepared,
            lambda data: data.update(classes={"kitty": {"prod_id": 7, "empty": False, "alt_names": []}}),
        )
    else:
        classes.records = [api_class(7, "kitty")]
    with pytest.raises(UploadError, match="kitty"):
        upload_dataset(prepared, services)
    assert store.calls == 0


@pytest.mark.parametrize("metadata", ["copy", "absent"])
def test_newer_parent_after_verify_refuses(scenario: Scenario, tmp_path: Path, metadata: str) -> None:
    _source, options, services, store, _classes = scenario
    prepared = _prepare(scenario, tmp_path)
    metadata_path = None
    if metadata == "copy":
        metadata_path = tmp_path / "parent.yaml"
        shutil.copyfile(prepared / "dataset.yaml", metadata_path)
    store.parent = DatasetParent("new", options.project, options.dataset_name or "", "2", metadata_path)
    with pytest.raises(UploadError, match="verify"):
        upload_dataset(prepared, services)
    assert store.calls == 0


def _drop_record(prepared: Path) -> None:
    def edit(data: dict[str, object]) -> None:
        del data["parent"], data["destination"]

    _edit_report(prepared, edit)


@pytest.mark.parametrize(
    "damage",
    [
        _drop_record,
        lambda prepared: (prepared / "report.json").unlink(),
        lambda prepared: _edit_metadata(prepared, lambda data: _clearml(data).update(dataset="renamed")),
    ],
    ids=["no-record", "no-report", "changed-destination"],
)
def test_missing_record_or_changed_destination_warns_and_publishes(
    scenario: Scenario, tmp_path: Path, capture_logs: list[str], damage: Callable[[Path], None]
) -> None:
    _source, _options, services, store, _classes = scenario
    prepared = _prepare(scenario, tmp_path)
    damage(prepared)
    upload_dataset(prepared, services)
    assert store.calls == 1
    assert any("verify" in message for message in capture_logs)


def test_parent_change_during_checks_refuses(
    scenario: Scenario, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _source, _options, services, store, _classes = scenario
    prepared = _prepare(scenario, tmp_path)
    checks = 0

    def latest(_project: str, _name: str) -> DatasetParent | None:
        nonlocal checks
        checks += 1
        return None if checks == 1 else DatasetParent("new", "inspection", "training", "2", None)

    monkeypatch.setattr(store, "latest", latest)
    with pytest.raises(UploadError, match="изменился во время проверок"):
        upload_dataset(prepared, services)
    assert checks == 2
    assert store.calls == 0


def test_managed_parent_is_refused(scenario: Scenario, tmp_path: Path) -> None:
    _source, options, services, store, _classes = scenario
    prepared = _prepare(scenario, tmp_path)
    destination = ClearMLDestination(project=options.project, dataset=options.dataset_name or "")
    managed = ManagedMetadata(
        name="demo",
        definition_hash="0" * 64,
        definition=DatasetDefinition(
            sources=[SourceDefinition(name="cvat", type="cvat", project="demo")],
            clearml=destination,
            api_url=API_URL,
        ),
        cvat=CvatIdentity(host="https://cvat.example.org"),
    )
    path = _parent_metadata(tmp_path / "parent.yaml", managed=managed)
    store.parent = DatasetParent("managed-id", options.project, options.dataset_name or "", "3", path)
    _edit_report(prepared, lambda data: data.update(parent={"id": "managed-id", "version": "3"}))
    with pytest.raises(UploadError, match="managed"):
        upload_dataset(prepared, services)
    assert store.calls == 0


def test_missing_clearml_destination_is_refused(scenario: Scenario, tmp_path: Path) -> None:
    _source, _options, services, store, _classes = scenario
    prepared = _prepare(scenario, tmp_path)
    _edit_metadata(prepared, lambda data: data.pop("clearml"))
    with pytest.raises(UploadError, match=r"clearml\.project"):
        upload_dataset(prepared, services)
    assert store.calls == 0


@pytest.mark.parametrize(
    "damage",
    [
        lambda path: path.write_bytes(b"not a gzip archive"),
        lambda path: path.unlink(),
    ],
    ids=["garbage", "deleted"],
)
def test_corrupt_or_missing_archive_is_refused(
    scenario: Scenario, tmp_path: Path, damage: Callable[[Path], None]
) -> None:
    _source, _options, services, store, _classes = scenario
    prepared = _prepare(scenario, tmp_path)
    damage(prepared / "sources.tar.gz")
    with pytest.raises(UploadError, match=r"sources\.tar\.gz"):
        upload_dataset(prepared, services)
    assert store.calls == 0


def test_unwritable_publication_record_only_warns(
    scenario: Scenario, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capture_logs: list[str]
) -> None:
    _source, _options, services, store, _classes = scenario
    prepared = _prepare(scenario, tmp_path)

    def fail(*_args: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(services.files, "write_publication", fail)
    assert upload_dataset(prepared, services).dataset_id == "child"
    assert store.calls == 1
    assert any("publication.json" in message and "disk full" in message for message in capture_logs)


def test_second_upload_warns_about_earlier_publication(
    scenario: Scenario, tmp_path: Path, capture_logs: list[str]
) -> None:
    _source, _options, services, store, _classes = scenario
    prepared = _prepare(scenario, tmp_path)
    (prepared / "publication.json").write_text(json.dumps({"dataset_id": "earlier-id", "version": "1.0.0"}))
    upload_dataset(prepared, services)
    assert store.calls == 1
    assert any("earlier-id" in message for message in capture_logs)
    assert json.loads((prepared / "publication.json").read_bytes())["dataset_id"] == "child"


@pytest.mark.parametrize("refused", ["roots", "output-bucket"])
def test_unlisted_s3_root_or_output_bucket_is_refused(scenario: Scenario, tmp_path: Path, refused: str) -> None:
    source, options, services, store, _classes = scenario
    prepared = _prepare(scenario, tmp_path)
    storage = cast("Storage", services.s3)
    if refused == "roots":
        storage.fail = True
        with pytest.raises(UploadError, match="unavailable root"):
            prepare_dataset(source, tmp_path / "unavailable", options, services)
    else:
        _edit_metadata(prepared, lambda data: _clearml(data).update(output_uri="s3://output/.clearml"))
        storage.refused = {"s3://output"}
    with pytest.raises(UploadError, match="unavailable root"):
        upload_dataset(prepared, services)
    assert store.calls == 0
