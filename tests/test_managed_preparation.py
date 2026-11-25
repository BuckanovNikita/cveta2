"""Managed preparation keeps the transformed CSV, original source evidence and plain state."""

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest
import yaml
from PIL import Image

from cveta2.adapters.files.managed_preparation import LocalManagedPreparationFiles
from cveta2.adapters.files.media import LocalMediaInspector
from cveta2.application.use_cases.managed_preparation import prepare_managed, published_assignments
from cveta2.domain.bundle.models import ApiClass, ClassInfo, DatasetMetadata, ImageRoots, UploadError
from cveta2.domain.class_registry import registry_fingerprint
from cveta2.domain.managed.evidence import labels_fingerprint
from cveta2.domain.managed.models import (
    ClearMLDestination,
    CvatIdentity,
    DatasetDefinition,
    ManagedError,
    ManagedMetadata,
    ManagedSnapshot,
    ProjectConfig,
    ProjectDefinition,
    SourceDefinition,
    SourceSnapshot,
    TaskSnapshot,
    definition_fingerprint,
    source_fingerprint,
)
from cveta2.domain.managed.preparation import FeedbackFinding, PreparationSummary
from cveta2.domain.models import LabelInfo


def _registry() -> list[ApiClass]:
    return [
        ApiClass(id=90, number=1, name="helmet", techClass=False, isPeriodical=False, isCritical=False, threshold=0.5)
    ]


class FakeS3Roots:
    """Record S3 root access checks; a listed root can be made inaccessible."""

    def __init__(self, denied: frozenset[str] = frozenset()) -> None:
        """Deny access to the given roots only."""
        self.denied = denied
        self.checked: list[str] = []

    def check_root(self, root: str) -> None:
        self.checked.append(root)
        if root in self.denied:
            raise UploadError(f"Cannot access S3 root {root}")


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
                "split": ("train", "val")[index],
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
        definition_hash=source_fingerprint(config, config.datasets["demo"]),
        registry_hash=registry_fingerprint(_registry()),
        registry=_registry(),
        cvat=config.cvat,
        sources=[
            SourceSnapshot(
                name="main",
                type="cvat",
                project_id=7,
                labels=[LabelInfo(id=1, name="helmet")],
                labels_fingerprint=labels_fingerprint([LabelInfo(id=1, name="helmet")]),
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
        files=LocalManagedPreparationFiles(),
        media=LocalMediaInspector(),
        s3_roots=FakeS3Roots(),
        clean=clean,
    )
    return result, config, transformed, source, metadata


def test_prepare_writes_format_three_record(tmp_path: Path) -> None:
    """The record is plain state; the payload and inputs are read as they are now."""
    summary, _config, _transformed, source, _metadata = _prepare(tmp_path)
    assert summary.ready
    record = json.loads((summary.directory / "preparation.json").read_bytes())
    assert record["format_version"] == 3
    assert set(record) == {
        "format_version",
        "name",
        "parent_id",
        "parent_version",
        "findings",
        "ready",
        "clean",
        "first",
    }
    assert not (summary.directory / "preparation.sha256").exists()
    files = LocalManagedPreparationFiles()
    loaded = files.load_prepared(summary.directory)
    assert loaded.ledger_key == hashlib.sha256((source / "source-snapshot.yaml").read_bytes()).hexdigest()
    assert loaded.captured.snapshot.sources[0].tasks["11"].tables
    assert loaded.metadata is not None
    assert loaded.metadata.managed is not None
    assert loaded.frame is not None
    assert loaded.frame["split"].tolist() == ["train", "val"]
    tasks = yaml.safe_load((summary.directory / "tasks.yaml").read_text())
    assert tasks["included"] == [11]
    with files.stage_payload(summary.directory) as staged:
        assert sorted(path.name for path in staged.iterdir()) == ["dataset.csv", "dataset.yaml", "tasks.yaml"]
        assert (staged / "dataset.csv").read_bytes() == (summary.directory / "dataset.csv").read_bytes()


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
        files=LocalManagedPreparationFiles(),
        media=LocalMediaInspector(),
        s3_roots=FakeS3Roots(),
        clean=True,
    )
    assert result.ready
    assert result.report["unmapped_errors"] == 1
    issues = result.report["issues"]
    assert isinstance(issues, list)
    assert any(isinstance(issue, dict) and issue.get("code") == "media_missing" for issue in issues)
    image_hashes = yaml.safe_load((result.directory / "tasks.yaml").read_text())["managed"]["image_hashes"]
    assert len(image_hashes) == 2
    assert str(tmp_path / "images" / "missing.png") not in image_hashes


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
        files=LocalManagedPreparationFiles(),
        media=LocalMediaInspector(),
        s3_roots=FakeS3Roots(),
    )
    assert not result.ready
    assert not (result.directory / "dataset.csv").exists()
    loaded = LocalManagedPreparationFiles().load_prepared(result.directory)
    assert loaded.record.findings[0].task_id == 11
    assert loaded.record.findings[0].frame_id == 0
    assert loaded.record.findings[0].marker.startswith("cveta2:")
    assert loaded.frame is None


def _edit_bytes(path: Path) -> None:
    """Change a file's bytes but not its content: CSV lines end in CRLF, YAML gains a blank line."""
    content = path.read_bytes()
    path.write_bytes(content.replace(b"\n", b"\r\n") if path.suffix == ".csv" else content + b"\n")


@pytest.mark.parametrize(
    "name",
    ["transformed.csv", "source-snapshot.yaml", "dataset.csv", "dataset.yaml", "tasks.yaml"],
)
def test_load_accepts_edited_files(tmp_path: Path, name: str) -> None:
    """No checksum binds the files: each command reads them as they are now."""
    summary, *_ = _prepare(tmp_path)
    path = summary.directory / name
    before = path.read_bytes()
    _edit_bytes(path)
    assert path.read_bytes() != before
    loaded = LocalManagedPreparationFiles().load_prepared(summary.directory)
    assert loaded.frame is not None
    assert loaded.record.ready


@pytest.mark.parametrize("version", [2, 4])
def test_load_refuses_another_format_version(tmp_path: Path, version: int) -> None:
    summary, *_ = _prepare(tmp_path)
    record_path = summary.directory / "preparation.json"
    record = json.loads(record_path.read_bytes())
    record["format_version"] = version
    record_path.write_text(json.dumps(record))
    with pytest.raises(ManagedError, match=r"Cannot load managed preparation: .*format_version"):
        LocalManagedPreparationFiles().load_prepared(summary.directory)


@pytest.mark.parametrize("content", [b"{not json", b"\xff\xfe"], ids=["json", "utf-8"])
def test_load_refuses_an_unreadable_record(tmp_path: Path, content: bytes) -> None:
    summary, *_ = _prepare(tmp_path)
    (summary.directory / "preparation.json").write_bytes(content)
    with pytest.raises(ManagedError, match="Cannot load managed preparation"):
        LocalManagedPreparationFiles().load_prepared(summary.directory)


@pytest.mark.parametrize("damage", ["invalid-value", "syntax-error"])
def test_load_names_invalid_fields_without_printing_their_values(tmp_path: Path, damage: str) -> None:
    """Hand edits are allowed, so a refusal must not echo what was typed, credentials included."""
    summary, *_ = _prepare(tmp_path)
    metadata_path = summary.directory / "dataset.yaml"
    secret = "https://user:s3cr3t-token@classes.example/api"
    if damage == "invalid-value":
        metadata = yaml.safe_load(metadata_path.read_text())
        metadata["api_url"] = secret
        metadata_path.write_text(yaml.safe_dump(metadata))
        expected = r"Cannot load managed preparation: .*api_url"
    else:
        lines = metadata_path.read_text().splitlines()
        lines = [f"api_url: {secret}: y" if line.startswith("api_url:") else line for line in lines]
        metadata_path.write_text("\n".join(lines) + "\n")
        expected = r"Cannot load managed preparation: .*dataset\.yaml: .*\(line \d+, column \d+\)$"
    with pytest.raises(ManagedError, match=expected) as raised:
        LocalManagedPreparationFiles().load_prepared(summary.directory)
    assert "s3cr3t-token" not in str(raised.value)


def test_load_refuses_a_partial_payload(tmp_path: Path) -> None:
    summary, *_ = _prepare(tmp_path)
    (summary.directory / "tasks.yaml").unlink()
    with pytest.raises(ManagedError, match=r"tasks\.yaml"):
        LocalManagedPreparationFiles().load_prepared(summary.directory)


@pytest.mark.parametrize("damage", ["missing-registry", "missing-labels"])
def test_incomplete_source_records_cannot_be_prepared(tmp_path: Path, damage: str) -> None:
    config, transformed, source, metadata = _fixture(tmp_path)
    source_path = source / "source-snapshot.yaml"
    stored = yaml.safe_load(source_path.read_text())
    if damage == "missing-registry":
        stored.pop("registry")
    else:
        stored["sources"][0].pop("labels")
    source_path.write_text(yaml.safe_dump(stored))
    output = tmp_path / "refused"

    with pytest.raises(
        ManagedError,
        match=(
            r"^Source snapshot lacks class-registry records; fetch and prepare again$"
            if damage == "missing-registry"
            else r"^Source snapshot lacks CVAT label definitions: main; fetch and prepare again$"
        ),
    ):
        prepare_managed(
            config,
            "demo",
            transformed,
            source,
            output,
            metadata,
            files=LocalManagedPreparationFiles(),
            media=LocalMediaInspector(),
            s3_roots=FakeS3Roots(),
        )
    assert not output.exists()


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
            files=LocalManagedPreparationFiles(),
            media=LocalMediaInspector(),
            s3_roots=FakeS3Roots(),
        )
    payload = summary.directory / "dataset.csv"
    target = tmp_path / "replacement.csv"
    target.write_bytes(payload.read_bytes())
    payload.unlink()
    payload.symlink_to(target)
    with pytest.raises(ManagedError):
        LocalManagedPreparationFiles().load_prepared(summary.directory)


def test_preparation_inside_the_fetch_source_is_refused(tmp_path: Path) -> None:
    """Review output never mixes with the source evidence it was derived from."""
    config, transformed, source, metadata = _fixture(tmp_path)
    with pytest.raises(ManagedError, match="outside the fetch source directory"):
        prepare_managed(
            config,
            "demo",
            transformed,
            source / "source-snapshot.yaml",
            source / "prepared",
            metadata,
            files=LocalManagedPreparationFiles(),
            media=LocalMediaInspector(),
            s3_roots=FakeS3Roots(),
        )
    assert sorted(path.name for path in source.iterdir()) == ["source-snapshot.yaml"]


def test_inaccessible_s3_root_blocks_preparation(tmp_path: Path) -> None:
    """S3 roots are proven accessible at prepare time, not first at publication."""
    config, transformed, source, metadata = _fixture(tmp_path)
    roots = metadata.images.model_copy(update={"s3_root": ["s3://bucket/ok", "s3://bucket/denied"]})
    s3_roots = FakeS3Roots(frozenset({"s3://bucket/denied"}))
    with pytest.raises(UploadError):
        prepare_managed(
            config,
            "demo",
            transformed,
            source,
            tmp_path / "prepared",
            metadata.model_copy(update={"images": roots}),
            files=LocalManagedPreparationFiles(),
            media=LocalMediaInspector(),
            s3_roots=s3_roots,
        )
    assert s3_roots.checked == ["s3://bucket/ok", "s3://bucket/denied"]
    assert not (tmp_path / "prepared").exists()


def _prepare_with(
    config: ProjectConfig, tmp_path: Path, transformed: Path, source: Path, metadata: DatasetMetadata
) -> PreparationSummary:
    return prepare_managed(
        config,
        "demo",
        transformed,
        source,
        tmp_path / "prepared",
        metadata,
        files=LocalManagedPreparationFiles(),
        media=LocalMediaInspector(),
        s3_roots=FakeS3Roots(),
    )


def _edit(config: ProjectConfig, edit: str) -> ProjectConfig:
    raw = config.model_dump(mode="json")
    dataset = raw["datasets"]["demo"]
    if edit == "overlap-decision":
        dataset["overlaps"] = {"digest": {"source": "main", "members": ["main", "other"]}}
    elif edit == "project-bookkeeping":
        raw["projects"]["p"].update(name="Renamed", sync_root="s3://images/p")
    elif edit == "project-id":
        raw["projects"]["p"]["id"] = 8
    elif edit == "ignored-id":
        raw["projects"]["p"]["ignore"] = [{"id": 99}]
    else:
        raw["cvat"]["organization"] = "moved"
    return ProjectConfig.model_validate(raw)


@pytest.mark.parametrize("edit", ["overlap-decision", "project-bookkeeping"])
def test_policy_and_bookkeeping_edits_prepare_on_the_same_fetch(tmp_path: Path, edit: str) -> None:
    config, transformed, source, metadata = _fixture(tmp_path)
    summary = _prepare_with(_edit(config, edit), tmp_path, transformed, source, metadata)
    assert summary.ready


def test_published_image_gets_its_published_split_and_a_new_image_keeps_its_own(tmp_path: Path) -> None:
    config, transformed, source, metadata = _fixture(tmp_path)
    digest = hashlib.sha256((tmp_path / "images" / "1.png").read_bytes()).hexdigest()
    snapshot = yaml.safe_load((source / "source-snapshot.yaml").read_text())
    snapshot["assignments"] = {digest: "train"}
    (source / "source-snapshot.yaml").write_text(yaml.safe_dump(snapshot))
    frame = pd.read_csv(transformed, keep_default_na=False)
    frame.loc[frame["image_name"].eq("0.png"), "split"] = "val"
    frame.to_csv(transformed, index=False)
    summary = _prepare_with(config, tmp_path, transformed, source, metadata)
    rows = pd.read_csv(summary.directory / "dataset.csv", keep_default_na=False)
    assert dict(zip(rows["image_name"], rows["split"], strict=True)) == {"0.png": "val", "1.png": "train"}
    assert summary.report["split_replacements"] == 1


def _forget_assignments(source: Path) -> None:
    """Make both fixture images new: the fetch snapshot records no published split."""
    snapshot = yaml.safe_load((source / "source-snapshot.yaml").read_text())
    snapshot["assignments"] = {}
    (source / "source-snapshot.yaml").write_text(yaml.safe_dump(snapshot))


def test_empty_split_of_a_new_image_is_pending(tmp_path: Path) -> None:
    config, transformed, source, metadata = _fixture(tmp_path)
    _forget_assignments(source)
    rows = pd.read_csv(transformed, keep_default_na=False)
    rows.loc[rows["image_name"].eq("1.png"), "split"] = ""
    rows.to_csv(transformed, index=False)
    directory = tmp_path / "prepared"
    summary = _prepare_with(config, tmp_path, transformed, source, metadata)
    assert summary.ready
    assert (directory / "dataset.csv").exists()
    assert summary.report["pending"] == [f"заполните split у 1 изображений в {directory / 'dataset.csv'}"]


def test_trainability_gaps_are_pending_when_every_split_is_set(tmp_path: Path) -> None:
    config, transformed, source, metadata = _fixture(tmp_path)
    _forget_assignments(source)
    rows = pd.read_csv(transformed, keep_default_na=False)
    rows["split"] = "train"
    rows.to_csv(transformed, index=False)
    summary = _prepare_with(config, tmp_path, transformed, source, metadata)
    assert summary.ready
    assert summary.report["pending"] == ["в val нет изображений"]


def test_active_class_without_bbox_blocks(tmp_path: Path) -> None:
    config, transformed, source, metadata = _fixture(tmp_path)
    classes = {**metadata.classes, "dog": ClassInfo(prod_id=8)}
    blocked = _prepare_with(config, tmp_path, transformed, source, metadata.model_copy(update={"classes": classes}))
    assert not blocked.ready
    blockers = blocked.report["blockers"]
    assert isinstance(blockers, list)
    assert "Active classes have no bbox: dog" in blockers
    assert blocked.report["missing_classes"] == ["dog"]
    assert not (blocked.directory / "dataset.csv").exists()
    classes["dog"] = ClassInfo(prod_id=8, empty=True)
    summary = prepare_managed(
        config,
        "demo",
        transformed,
        source,
        tmp_path / "again",
        metadata.model_copy(update={"classes": classes}),
        files=LocalManagedPreparationFiles(),
        media=LocalMediaInspector(),
        s3_roots=FakeS3Roots(),
    )
    assert summary.ready


def test_same_content_in_two_splits_blocks(tmp_path: Path) -> None:
    config, transformed, source, metadata = _fixture(tmp_path)
    _forget_assignments(source)
    images = tmp_path / "images"
    copy = images / "copy.png"
    copy.write_bytes((images / "0.png").read_bytes())
    rows = pd.read_csv(transformed, keep_default_na=False, dtype=str)
    extra = rows[rows["image_name"].eq("0.png")].assign(image_name=copy.name, image_path=str(copy), split="val")
    pd.concat([rows, extra], ignore_index=True).to_csv(transformed, index=False)
    summary = _prepare_with(config, tmp_path, transformed, source, metadata)
    assert not summary.ready
    blockers = summary.report["blockers"]
    assert isinstance(blockers, list)
    assert "Image content has rows in several splits: 0.png, copy.png" in blockers
    assert summary.report["split_collisions"] == ["0.png", "copy.png"]
    assert not (summary.directory / "dataset.csv").exists()


def test_one_image_name_in_two_splits_blocks_even_with_cleanup(tmp_path: Path) -> None:
    """Cleanup would drop the conflicting rows; the collision is named instead."""
    config, transformed, source, metadata = _fixture(tmp_path)
    _forget_assignments(source)
    rows = pd.read_csv(transformed, keep_default_na=False, dtype=str)
    extra = rows[rows["image_name"].eq("0.png")].assign(split="val", bbox_x_tl="2")
    pd.concat([rows, extra], ignore_index=True).to_csv(transformed, index=False)
    summary = prepare_managed(
        config,
        "demo",
        transformed,
        source,
        tmp_path / "prepared",
        metadata,
        files=LocalManagedPreparationFiles(),
        media=LocalMediaInspector(),
        s3_roots=FakeS3Roots(),
        clean=True,
    )
    assert not summary.ready
    blockers = summary.report["blockers"]
    assert isinstance(blockers, list)
    assert "Image content has rows in several splits: 0.png" in blockers
    assert not (summary.directory / "dataset.csv").exists()


def test_cleanup_is_accepted_by_default_and_no_clean_blocks(tmp_path: Path) -> None:
    config, transformed, source, metadata = _fixture(tmp_path)
    frame = pd.read_csv(transformed, keep_default_na=False)
    bad = frame.iloc[[0]].copy()
    bad["bbox_x_br"] = "1"
    extra = Path(str(bad["image_path"].iloc[0])).parent / "bad.png"
    Image.new("RGB", (32, 32), "green").save(extra)
    bad["image_name"] = extra.name
    bad["image_path"] = str(extra)
    pd.concat([frame, bad], ignore_index=True).to_csv(transformed, index=False)
    summaries = {
        clean: prepare_managed(
            config,
            "demo",
            transformed,
            source,
            tmp_path / f"prepared-{clean}",
            metadata,
            files=LocalManagedPreparationFiles(),
            media=LocalMediaInspector(),
            s3_roots=FakeS3Roots(),
            clean=clean,
        )
        for clean in (True, False)
    }
    assert summaries[True].ready
    assert not summaries[False].ready
    blockers = summaries[False].report["blockers"]
    assert isinstance(blockers, list)
    assert "Cleanup is needed and --no-clean was given." in blockers


def test_split_mistakes_stay_out_of_cvat_feedback(tmp_path: Path) -> None:
    """A wrong split is the CSV author's to fix; only annotation errors reach CVAT frames."""
    config, transformed, source, metadata = _fixture(tmp_path)
    snapshot = yaml.safe_load((source / "source-snapshot.yaml").read_text())
    snapshot["assignments"] = {}
    (source / "source-snapshot.yaml").write_text(yaml.safe_dump(snapshot))
    rows = pd.read_csv(transformed, keep_default_na=False, dtype=str)
    rows["split"] = "holdout"
    rows.loc[rows["image_name"].eq("0.png"), "bbox_x_br"] = "1"
    rows.to_csv(transformed, index=False)
    summary = _prepare_with(config, tmp_path, transformed, source, metadata)
    assert not summary.ready
    findings = LocalManagedPreparationFiles().load_prepared(summary.directory).record.findings
    assert [(finding.task_id, finding.frame_id) for finding in findings] == [(11, 0)]
    assert findings[0].codes
    assert not {"invalid_split", "split_conflict"} & set(findings[0].codes)
    assert not any("train, val or test" in message for message in findings[0].messages)
    assert summary.report["unmapped_errors"] == 0


def _three_rows_of_one_image(
    tmp_path: Path, splits: tuple[str, str, str], *, bad_box: int | None = None
) -> list[FeedbackFinding]:
    """Prepare with three rows of ``0.png`` (distinct boxes) and return the recorded findings."""
    config, transformed, source, metadata = _fixture(tmp_path)
    _forget_assignments(source)
    rows = pd.read_csv(transformed, keep_default_na=False, dtype=str)
    image = rows[rows["image_name"].eq("0.png")]
    extra = [image.assign(split=split, bbox_x_tl=str(1 + index)) for index, split in enumerate(splits)]
    if bad_box is not None:
        extra[bad_box] = extra[bad_box].assign(bbox_x_br="1")
    pd.concat([rows[rows["image_name"].ne("0.png")], *extra], ignore_index=True).to_csv(transformed, index=False)
    summary = prepare_managed(
        config,
        "demo",
        transformed,
        source,
        tmp_path / "prepared",
        metadata,
        files=LocalManagedPreparationFiles(),
        media=LocalMediaInspector(),
        s3_roots=FakeS3Roots(),
        clean=True,
    )
    assert not summary.ready
    return LocalManagedPreparationFiles().load_prepared(summary.directory).record.findings


@pytest.mark.parametrize("splits", [("train", "train", "val"), ("train", "train", "holdout")])
def test_rows_quarantined_by_a_split_mistake_stay_out_of_cvat_feedback(
    tmp_path: Path, splits: tuple[str, str, str]
) -> None:
    """The other rows of an image that only a split mistake rejects are not an annotator's error."""
    assert _three_rows_of_one_image(tmp_path, splits) == []


def test_rows_quarantined_by_an_annotation_error_still_reach_cvat_feedback(tmp_path: Path) -> None:
    findings = _three_rows_of_one_image(tmp_path, ("train", "val", "val"), bad_box=1)
    assert [(finding.task_id, finding.frame_id) for finding in findings] == [(11, 0)]
    assert {"invalid_box_area", "image_quarantined"} <= set(findings[0].codes)
    assert not {"invalid_split", "split_conflict"} & set(findings[0].codes)


def test_published_assignments_come_only_from_a_managed_parent(tmp_path: Path) -> None:
    config, _transformed, _source, metadata = _fixture(tmp_path)
    assert published_assignments(None) == {}
    managed = metadata.model_copy(
        update={
            "managed": ManagedMetadata(
                name="demo",
                definition_hash="0" * 64,
                definition=config.datasets["demo"],
                cvat=config.cvat,
                assignments={"digest": "test"},
            )
        }
    )
    assert published_assignments(managed) == {"digest": "test"}
    with pytest.raises(ManagedError, match="Parent is not a managed dataset version"):
        published_assignments(metadata)


@pytest.mark.parametrize("edit", ["project-id", "ignored-id", "organization"])
def test_source_edits_warn_and_prepare_from_the_fetched_sources(
    tmp_path: Path, capture_logs: list[str], edit: str
) -> None:
    config, transformed, source, metadata = _fixture(tmp_path)
    summary = _prepare_with(_edit(config, edit), tmp_path, transformed, source, metadata)
    assert summary.ready
    if edit == "project-id":
        assert (
            "Источник отличается от выгруженного: main: project_id 7 → 8. Датасет собирается из выгруженных данных."
            in capture_logs
        )


def test_payload_carries_recomputed_informational_hashes(tmp_path: Path) -> None:
    summary, config, *_ = _prepare(tmp_path)
    loaded = LocalManagedPreparationFiles().load_prepared(summary.directory)
    definition = config.datasets["demo"]
    assert loaded.metadata is not None
    assert loaded.metadata.managed is not None
    assert loaded.metadata.managed.definition_hash == definition_fingerprint(config, definition)
