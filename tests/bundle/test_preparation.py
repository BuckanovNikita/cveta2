"""Immutable preparation and publication exercise real files with fake remote ports."""

import hashlib
import json
from pathlib import Path
from typing import cast

import pandas as pd
import pytest
from PIL import Image

from cveta2.adapters.files.bundle import LocalBundleFiles
from cveta2.adapters.files.bundle_paths import LocalRoots
from cveta2.adapters.files.media import LocalMediaInspector
from cveta2.application.ports.dataset_bundle import BundleServices
from cveta2.application.use_cases.dataset_bundle import prepare_dataset, upload_dataset
from cveta2.domain.bundle.models import (
    ApiClass,
    DatasetParent,
    Publication,
    UploadError,
)
from cveta2.domain.bundle.preparation import MissingDecisions, PrepareOptions


class Classes:
    """An observable class API whose response can change between calls."""

    def __init__(self) -> None:
        """Initialize one stable class identity."""
        self.records = [
            ApiClass(
                id=100,
                number=7,
                name="cat",
                techClass=False,
                isPeriodical=False,
                isCritical=False,
                threshold=0.5,
            )
        ]

    def fetch(self, _url: str) -> list[ApiClass]:
        return self.records


class Store:
    """Capture actual bytes supplied at the publication boundary."""

    def __init__(self) -> None:
        """Initialize an empty remote lineage."""
        self.directory: Path | None = None
        self.parent: DatasetParent | None = None
        self.published: dict[str, bytes] = {}
        self.calls = 0

    def names(self, _project: str) -> list[str]:
        return []

    def latest(self, _project: str, _name: str) -> DatasetParent | None:
        return self.parent

    def publish(
        self, _project: str, _name: str, _parent_id: str | None, directory: Path
    ) -> Publication:
        self.directory = directory
        self.calls += 1
        self.published = {p.name: p.read_bytes() for p in directory.iterdir()}
        return Publication("child", "1.0.0")


class Storage:
    """Record configured root checks and simulate an inaccessible root."""

    def __init__(self) -> None:
        """Track root checks without accessing a remote bucket."""
        self.fail = False
        self.checked: list[str] = []

    def check_root(self, root: str) -> None:
        if self.fail:
            raise UploadError("unavailable root")
        self.checked.append(root)


Scenario = tuple[Path, PrepareOptions, BundleServices, Store, Classes]


@pytest.fixture
def scenario(
    tmp_path: Path,
) -> Scenario:
    """Build a completed train/validation fetch with literal CSV evidence."""
    source = tmp_path / "source"
    source.mkdir()
    images = tmp_path / "images"
    images.mkdir()
    rows = []
    for task, split in enumerate(("train", "val"), start=1):
        name = f"{split}.png"
        Image.new("RGB", (32, 32)).save(images / name)
        rows.append(
            {
                "image_name": name,
                "image_path": str(images / name),
                "split": split,
                "instance_label": "cat",
                "bbox_x_tl": "1",
                "bbox_y_tl": "1",
                "bbox_x_br": "20",
                "bbox_y_br": "20",
                "task_id": task,
                "task_completed": True,
                "s3_image_path": f"images/{name}",
            }
        )
    frame = pd.DataFrame(rows)
    frame.to_csv(source / "dataset.csv", index=False)
    for name in ("obsolete", "in_progress", "deleted"):
        frame.iloc[:0].to_csv(source / f"{name}.csv", index=False)
    options = PrepareOptions(
        project="inspection",
        dataset_name="training",
        api_url="https://example.org/classes",
        local_roots=(str(images),),
        s3_roots=("s3://bucket/images",),
        accept_default_classes=True,
    )
    store, classes = Store(), Classes()
    services = BundleServices(
        api=classes,
        datasets=store,
        s3=Storage(),
        roots=LocalRoots(),
        files=LocalBundleFiles(),
        media=LocalMediaInspector(),
    )
    return source, options, services, store, classes


def test_preparation_copies_four_sources_and_publishes_exact_payload(
    scenario: Scenario, tmp_path: Path
) -> None:
    source, options, services, store, _classes = scenario
    original = {p.name: p.read_bytes() for p in source.iterdir()}
    prepared = tmp_path / "prepared"
    result = prepare_dataset(source, prepared, options, services)
    assert result.ready
    assert store.calls == 0
    assert {
        p.name: p.read_bytes() for p in (prepared / "sources").iterdir()
    } == original
    assert (prepared / "preparation.json").is_file()
    assert upload_dataset(prepared, services).dataset_id == "child"
    assert set(store.published) == {"dataset.csv", "dataset.yaml", "tasks.yaml"}
    assert {p.name: p.read_bytes() for p in source.iterdir()} == original


@pytest.mark.parametrize(
    "relative",
    [
        "dataset.csv",
        "dataset.yaml",
        "tasks.yaml",
        "sources/dataset.csv",
        "sources/obsolete.csv",
        "sources/in_progress.csv",
        "sources/deleted.csv",
    ],
)
def test_modified_bound_files_block_before_remote_creation(
    scenario: Scenario, tmp_path: Path, relative: str
) -> None:
    source, options, services, store, _classes = scenario
    prepared = tmp_path / "prepared"
    prepare_dataset(source, prepared, options, services)
    path = prepared / relative
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(UploadError, match=r"changed|hash|измен"):
        upload_dataset(prepared, services)
    assert store.calls == 0


def test_new_parent_and_class_drift_block(scenario: Scenario, tmp_path: Path) -> None:
    source, options, services, store, classes = scenario
    prepared = tmp_path / "prepared"
    prepare_dataset(source, prepared, options, services)
    store.parent = DatasetParent("new", "inspection", "training", "2", None)
    with pytest.raises(UploadError, match=r"parent|родител"):
        upload_dataset(prepared, services)
    store.parent = None
    classes.records = [classes.records[0].model_copy(update={"name": "renamed"})]
    with pytest.raises(UploadError, match=r"[Cc]lass|класс"):
        upload_dataset(prepared, services)
    assert store.calls == 0


def test_missing_retained_image_blocks(scenario: Scenario, tmp_path: Path) -> None:
    source, options, services, store, _classes = scenario
    prepared = tmp_path / "prepared"
    prepare_dataset(source, prepared, options, services)
    (Path(options.local_roots[0]) / "train.png").unlink()
    with pytest.raises(UploadError):
        upload_dataset(prepared, services)
    assert store.calls == 0


def test_missing_class_decisions_are_structured_and_prompt_free(
    scenario: Scenario, tmp_path: Path
) -> None:
    source, options, services, store, _classes = scenario
    options = options.model_copy(update={"accept_default_classes": False})
    with pytest.raises(MissingDecisions) as caught:
        prepare_dataset(source, tmp_path / "prepared", options, services)
    assert any(
        d.kind == "class_empty" and d.class_id == 7 for d in caught.value.decisions
    )
    assert store.calls == 0


def test_report_only_does_not_create_uploadable_cleaned_bundle(
    scenario: Scenario, tmp_path: Path
) -> None:
    source, options, services, store, _classes = scenario
    path = source / "dataset.csv"
    original = path.read_text()
    path.write_text(original + original.splitlines()[1] + "\n")
    result = prepare_dataset(source, tmp_path / "report", options, services)
    assert not result.ready
    assert result.validation.result.requires_cleanup
    assert not (tmp_path / "report" / "preparation.json").exists()
    assert not (tmp_path / "report" / "dataset.csv").exists()
    clean = options.model_copy(update={"clean": True})
    result = prepare_dataset(source, tmp_path / "prepared", clean, services)
    assert result.ready
    assert upload_dataset(tmp_path / "prepared", services).dataset_id == "child"
    assert store.calls == 1


def test_existing_destination_is_preserved(scenario: Scenario, tmp_path: Path) -> None:
    source, options, services, _store, _classes = scenario
    directory = tmp_path / "prepared"
    directory.mkdir()
    (directory / "owned.txt").write_text("keep")
    with pytest.raises(UploadError):
        prepare_dataset(source, directory, options, services)
    assert (directory / "owned.txt").read_text() == "keep"


@pytest.mark.parametrize(
    "filename", ["dataset.csv", "obsolete.csv", "in_progress.csv", "deleted.csv"]
)
def test_header_only_sources_require_evidence_columns(
    scenario: Scenario, tmp_path: Path, filename: str
) -> None:
    source, options, services, store, _classes = scenario
    (source / filename).write_text("unexpected\n")
    with pytest.raises(UploadError, match=r"column|header"):
        prepare_dataset(source, tmp_path / "prepared", options, services)
    assert store.calls == 0


def test_invalid_api_configuration_is_a_library_error(
    scenario: Scenario, tmp_path: Path
) -> None:
    source, options, services, store, _classes = scenario
    with pytest.raises(UploadError, match=r"API|metadata|URL"):
        prepare_dataset(
            source,
            tmp_path / "prepared",
            options.model_copy(update={"api_url": "bad-url"}),
            services,
        )
    assert store.calls == 0


@pytest.mark.parametrize("field", ["project", "parent_id", "clean"])
def test_record_decision_edits_are_detected(
    scenario: Scenario, tmp_path: Path, field: str
) -> None:
    source, options, services, store, _classes = scenario
    prepared = tmp_path / "prepared"
    prepare_dataset(source, prepared, options, services)
    path = prepared / "preparation.json"
    record = json.loads(path.read_bytes())
    if field == "parent_id":
        record[field] = "different"
    else:
        record["options"][field] = True if field == "clean" else "redirected"
    path.write_text(json.dumps(record))
    with pytest.raises(UploadError, match=r"record|hash|changed"):
        upload_dataset(prepared, services)
    assert store.calls == 0


def test_publication_uses_captured_bytes_after_reviewed_files_change(
    scenario: Scenario, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, options, services, store, classes = scenario
    prepared = tmp_path / "prepared"
    prepare_dataset(source, prepared, options, services)
    expected = {
        name: (prepared / name).read_bytes()
        for name in ("dataset.csv", "dataset.yaml", "tasks.yaml")
    }

    def mutate_after_staging(_url: str) -> list[ApiClass]:
        (prepared / "dataset.csv").write_bytes(b"changed after stable capture")
        (prepared / "sources" / "dataset.csv").write_bytes(
            b"changed source after capture"
        )
        return classes.records

    monkeypatch.setattr(classes, "fetch", mutate_after_staging)
    upload_dataset(prepared, services)
    assert store.published == expected
    assert store.directory is not None
    assert not store.directory.exists()


def test_private_stage_is_removed_on_publication_failure(
    scenario: Scenario, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, options, services, store, _classes = scenario
    prepared = tmp_path / "prepared"
    prepare_dataset(source, prepared, options, services)
    stages: list[Path] = []

    def fail_publish(
        _project: str, _name: str, _parent: str | None, directory: Path
    ) -> Publication:
        stages.append(directory)
        assert directory.is_dir()
        raise UploadError("child creation failed")

    monkeypatch.setattr(store, "publish", fail_publish)
    with pytest.raises(UploadError, match="creation failed"):
        upload_dataset(prepared, services)
    assert len(stages) == 1
    assert not stages[0].exists()


def test_new_parent_during_validation_blocks_final_publication(
    scenario: Scenario, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, options, services, store, _classes = scenario
    prepared = tmp_path / "prepared"
    prepare_dataset(source, prepared, options, services)
    checks = 0

    def latest(_project: str, _name: str) -> DatasetParent | None:
        nonlocal checks
        checks += 1
        return (
            None
            if checks == 1
            else DatasetParent("new", "inspection", "training", "2", None)
        )

    monkeypatch.setattr(store, "latest", latest)
    with pytest.raises(UploadError, match="parent changed"):
        upload_dataset(prepared, services)
    assert checks == 2
    assert store.calls == 0


def test_unavailable_s3_root_blocks_preparation_and_upload(
    scenario: Scenario, tmp_path: Path
) -> None:
    source, options, services, store, _classes = scenario
    prepared = tmp_path / "prepared"
    prepare_dataset(source, prepared, options, services)
    cast("Storage", services.s3).fail = True
    with pytest.raises(UploadError, match="unavailable root"):
        prepare_dataset(source, tmp_path / "unavailable", options, services)
    with pytest.raises(UploadError, match="unavailable root"):
        upload_dataset(prepared, services)
    assert store.calls == 0


@pytest.mark.parametrize(
    "artifact",
    ["preparation.json", "preparation.sha256", "dataset.csv", "sources/dataset.csv"],
)
def test_symlinked_prepared_artifacts_are_rejected(
    scenario: Scenario, tmp_path: Path, artifact: str
) -> None:
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


def test_symlinked_source_directory_is_rejected(
    scenario: Scenario, tmp_path: Path
) -> None:
    source, options, services, store, _classes = scenario
    prepared = tmp_path / "prepared"
    prepare_dataset(source, prepared, options, services)
    (prepared / "sources").rename(tmp_path / "evidence")
    (prepared / "sources").symlink_to(tmp_path / "evidence", target_is_directory=True)
    with pytest.raises(UploadError, match="symlink"):
        upload_dataset(prepared, services)
    assert store.calls == 0


@pytest.mark.parametrize("text", ["{malformed", "{}", '{"format_version":2}'])
def test_malformed_record_blocks_even_with_matching_digest(
    scenario: Scenario, tmp_path: Path, text: str
) -> None:
    source, options, services, store, _classes = scenario
    prepared = tmp_path / "prepared"
    prepare_dataset(source, prepared, options, services)
    (prepared / "preparation.json").write_bytes(text.encode())
    (prepared / "preparation.sha256").write_text(
        hashlib.sha256(text.encode()).hexdigest()
    )
    with pytest.raises(UploadError, match="Cannot read prepared"):
        upload_dataset(prepared, services)
    assert store.calls == 0


def test_invalid_file_inventory_blocks_even_with_matching_record_digest(
    scenario: Scenario, tmp_path: Path
) -> None:
    source, options, services, store, _classes = scenario
    prepared = tmp_path / "prepared"
    prepare_dataset(source, prepared, options, services)
    record = json.loads((prepared / "preparation.json").read_bytes())
    record["payload_hashes"].pop("dataset.yaml")
    content = json.dumps(record).encode()
    (prepared / "preparation.json").write_bytes(content)
    (prepared / "preparation.sha256").write_text(hashlib.sha256(content).hexdigest())
    with pytest.raises(UploadError, match="inventory"):
        upload_dataset(prepared, services)
    assert store.calls == 0


@pytest.mark.parametrize(
    "text",
    [
        "api_url: x\napi_url: y\n",
        "classes: &classes {cat: *classes}\n",
        "[invalid",
        "true: invalid\n",
    ],
)
def test_strict_metadata_rejects_ambiguous_yaml(tmp_path: Path, text: str) -> None:
    metadata = tmp_path / "dataset.yaml"
    metadata.write_text(text)
    with pytest.raises(UploadError):
        LocalBundleFiles().read_metadata(metadata)


def test_failed_preparation_never_leaves_uploadable_marker(
    scenario: Scenario, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    source, options, services, store, _classes = scenario
    prepared = tmp_path / "prepared"
    original_link = os.link

    def fail_payload_link(source_path: Path, destination_path: Path) -> None:
        if destination_path.name == "dataset.yaml":
            raise OSError("publication files could not be linked")
        original_link(source_path, destination_path)

    monkeypatch.setattr(os, "link", fail_payload_link)
    with pytest.raises(UploadError, match="could not be linked"):
        prepare_dataset(source, prepared, options, services)
    assert not (prepared / "preparation.sha256").exists()
    assert not list(tmp_path.glob(".cveta2-prepare-*"))
    with pytest.raises(UploadError):
        upload_dataset(prepared, services)
    assert store.calls == 0


def test_source_cleanup_authorization_is_rechecked(
    scenario: Scenario, tmp_path: Path
) -> None:
    source, options, services, store, _classes = scenario
    source_csv = source / "dataset.csv"
    original = source_csv.read_text()
    source_csv.write_text(original + original.splitlines()[1] + "\n")
    prepared = tmp_path / "prepared"
    prepare_dataset(
        source, prepared, options.model_copy(update={"clean": True}), services
    )
    # Exercise the semantic authorization check independently from checksum rejection.
    record = json.loads((prepared / "preparation.json").read_bytes())
    record["options"]["clean"] = False
    content = json.dumps(record).encode()
    (prepared / "preparation.json").write_bytes(content)
    (prepared / "preparation.sha256").write_text(hashlib.sha256(content).hexdigest())
    with pytest.raises(UploadError, match="не была разрешена"):
        upload_dataset(prepared, services)
    assert store.calls == 0
