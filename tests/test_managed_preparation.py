"""Managed preparation binds opaque transformations and original source evidence."""

import hashlib
from pathlib import Path

import pandas as pd
import pytest
import yaml
from PIL import Image

from cveta2.adapters.files.managed_preparation import LocalManagedPreparationFiles
from cveta2.adapters.files.media import LocalMediaInspector
from cveta2.application.use_cases.managed_preparation import prepare_managed
from cveta2.domain.bundle.models import ClassInfo, DatasetMetadata, ImageRoots
from cveta2.domain.managed.models import (
    ClearMLDestination,
    CvatIdentity,
    DatasetDefinition,
    ManagedError,
    ManagedSnapshot,
    ProjectConfig,
    ProjectDefinition,
    SourceDefinition,
    SourceSnapshot,
    TaskSnapshot,
    definition_fingerprint,
)
from cveta2.domain.managed.preparation import PreparationSummary


def _fixture(tmp_path: Path) -> tuple[ProjectConfig, Path, Path, DatasetMetadata]:
    images = tmp_path / "images"
    images.mkdir()
    rows = []
    hashes = {}
    for index, color in enumerate(("red", "blue")):
        image = images / f"{index}.png"
        Image.new("RGB", (32, 32), color).save(image)
        hashes[str(image)] = hashlib.sha256(image.read_bytes()).hexdigest()
        rows.append(
            {
                "image_name": image.name,
                "image_path": str(image),
                "instance_label": "helmet",
                "bbox_x_tl": "1",
                "bbox_y_tl": "1",
                "bbox_x_br": "20",
                "bbox_y_br": "20",
                "task_id": "11",
                "frame_id": str(index),
                "task_completed": "true",
                "source_id": "main",
                "source_project_id": "7",
                "source_task_id": "11",
                "source_frame_id": str(index),
            }
        )
    frame = pd.DataFrame(rows)
    raw = frame.drop(columns=[c for c in frame if isinstance(c, str) and c.startswith("source_")])
    tables = {
        "dataset.csv": raw.to_csv(index=False),
        **{name: raw.iloc[0:0].to_csv(index=False) for name in ("obsolete.csv", "in_progress.csv", "deleted.csv")},
    }
    config = ProjectConfig(
        cvat=CvatIdentity(host="https://cvat.example"),
        projects={"p": ProjectDefinition(id=7)},
        datasets={
            "demo": DatasetDefinition(
                sources=[SourceDefinition(name="main", type="cvat", project="p")],
                clearml=ClearMLDestination(project="CV/demo", dataset="annotations"),
                api_url="https://classes.example/api",
            )
        },
    )
    snapshot = ManagedSnapshot(
        definition_hash=definition_fingerprint(config, "demo"),
        registry_hash="registry",
        sources=[
            SourceSnapshot(
                name="main",
                type="cvat",
                project_id=7,
                tasks={"11": TaskSnapshot(id=11, updated_date="time", completed=True, tables=tables)},
                tables=tables,
            )
        ],
        assignments={
            hashes[rows[0]["image_path"]]: "train",
            hashes[rows[1]["image_path"]]: "val",
        },
    )
    source = tmp_path / "source"
    source.mkdir()
    (source / "source-snapshot.yaml").write_text(yaml.safe_dump(snapshot.model_dump(mode="json")))
    transformed = tmp_path / "transformed.csv"
    frame.to_csv(transformed, index=False)
    metadata = DatasetMetadata(
        api_url="https://classes.example/api",
        classes={"helmet": ClassInfo(prod_id=1)},
        images=ImageRoots(local_root=[str(images)]),
    )
    return config, transformed, source, metadata


def _prepare(
    tmp_path: Path, *, clean: bool = False
) -> tuple[PreparationSummary, ProjectConfig, Path, Path, DatasetMetadata]:
    config, transformed, source, metadata = _fixture(tmp_path)
    directory = tmp_path / "prepared"
    result = prepare_managed(
        config,
        "demo",
        transformed,
        source,
        directory,
        metadata,
        registry_hash="registry",
        files=LocalManagedPreparationFiles(),
        media=LocalMediaInspector(),
        clean=clean,
    )
    return result, config, transformed, source, metadata


def test_prepare_binds_inputs_and_exact_three_file_payload(tmp_path: Path) -> None:
    """Publication gets full source evidence and clean training rows, no ZIP."""
    summary, _config, transformed, source, _metadata = _prepare(tmp_path)
    assert summary.ready
    files = LocalManagedPreparationFiles()
    loaded = files.load_prepared(summary.directory)
    assert set(loaded.payload) == {"dataset.csv", "dataset.yaml", "tasks.yaml"}
    assert loaded.record.input_hash == hashlib.sha256(transformed.read_bytes()).hexdigest()
    assert loaded.record.source_hash == hashlib.sha256((source / "source-snapshot.yaml").read_bytes()).hexdigest()
    assert loaded.tasks is not None
    assert loaded.tasks.included == [11]
    assert loaded.tasks.managed is not None
    assert loaded.tasks.managed.sources[0].tasks["11"].tables
    assert loaded.metadata is not None
    assert loaded.metadata.managed is not None
    assert loaded.frame["split"].tolist() == ["train", "val"]
    with files.stage_payload(loaded.payload) as staged:
        assert (staged / "dataset.csv").read_bytes() == loaded.payload["dataset.csv"]


def test_missing_media_is_reported_and_can_be_removed_with_explicit_cleanup(
    tmp_path: Path,
) -> None:
    """Hashing unavailable input does not bypass image quarantine diagnostics."""
    config, transformed, source, metadata = _fixture(tmp_path)
    frame = pd.read_csv(transformed, keep_default_na=False)
    bad = frame.iloc[[0]].copy()
    bad["image_name"] = "missing.png"
    bad["image_path"] = str(tmp_path / "images" / "missing.png")
    bad["source_frame_id"] = "500"
    pd.concat([frame, bad], ignore_index=True).to_csv(transformed, index=False)
    result = prepare_managed(
        config,
        "demo",
        transformed,
        source,
        tmp_path / "prepared",
        metadata,
        registry_hash="registry",
        files=LocalManagedPreparationFiles(),
        media=LocalMediaInspector(),
        clean=True,
    )
    assert result.ready
    assert result.report["unmapped_errors"] == 1
    issues = result.report["issues"]
    assert isinstance(issues, list)
    assert any(isinstance(issue, dict) and issue.get("code") == "media_missing" for issue in issues)
    loaded = LocalManagedPreparationFiles().load_prepared(result.directory)
    assert len(loaded.record.image_hashes) == 2
    assert str(tmp_path / "images" / "missing.png") not in loaded.record.image_hashes


def test_bad_box_produces_attested_feedback_and_requires_cleanup(
    tmp_path: Path,
) -> None:
    """Mapped errors refer to original CVAT frames without trusting task-like extras."""
    config, transformed, source, metadata = _fixture(tmp_path)
    frame = pd.read_csv(transformed, keep_default_na=False)
    bad = frame.iloc[[0]].copy()
    bad["bbox_x_br"] = "1"
    # A third image can fail without removing the required retained train/val.
    original_path = Path(str(bad["image_path"].iloc[0]))
    extra = original_path.parent / "bad.png"
    Image.new("RGB", (32, 32), "green").save(extra)
    bad["image_name"] = extra.name
    bad["image_path"] = str(extra)
    pd.concat([frame, bad], ignore_index=True).to_csv(transformed, index=False)
    result = prepare_managed(
        config,
        "demo",
        transformed,
        source,
        tmp_path / "diagnostics",
        metadata,
        registry_hash="registry",
        files=LocalManagedPreparationFiles(),
        media=LocalMediaInspector(),
    )
    assert not result.ready
    assert not (result.directory / "dataset.csv").exists()
    loaded = LocalManagedPreparationFiles().load_prepared(result.directory)
    assert loaded.record.findings[0].task_id == 11
    assert loaded.record.findings[0].frame_id == 0
    assert loaded.record.findings[0].marker.startswith("cveta2:")
    assert loaded.record.payload_hashes == {}


@pytest.mark.parametrize(
    "name",
    ["transformed.csv", "source-snapshot.yaml", "dataset.csv", "preparation.json"],
)
def test_load_rejects_modified_bound_bytes(tmp_path: Path, name: str) -> None:
    """No changed reviewed bytes can enter publication unnoticed."""
    summary, *_ = _prepare(tmp_path)
    path = summary.directory / name
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ManagedError):
        LocalManagedPreparationFiles().load_prepared(summary.directory)


def test_source_definition_and_registry_must_match_fetch(tmp_path: Path) -> None:
    """A transformed output cannot be prepared against a different source policy."""
    config, transformed, source, metadata = _fixture(tmp_path)
    with pytest.raises(ManagedError, match="registry"):
        prepare_managed(
            config,
            "demo",
            transformed,
            source,
            tmp_path / "prepared",
            metadata,
            registry_hash="changed",
            files=LocalManagedPreparationFiles(),
            media=LocalMediaInspector(),
        )


def test_symlink_and_existing_destination_are_rejected(tmp_path: Path) -> None:
    """Review artifacts are regular files and never replace an existing result."""
    summary, config, transformed, source, metadata = _prepare(tmp_path)
    with pytest.raises(ManagedError):
        prepare_managed(
            config,
            "demo",
            transformed,
            source,
            summary.directory,
            metadata,
            registry_hash="registry",
            files=LocalManagedPreparationFiles(),
            media=LocalMediaInspector(),
        )
    payload = summary.directory / "dataset.csv"
    target = tmp_path / "replacement.csv"
    target.write_bytes(payload.read_bytes())
    payload.unlink()
    payload.symlink_to(target)
    with pytest.raises(ManagedError):
        LocalManagedPreparationFiles().load_prepared(summary.directory)
