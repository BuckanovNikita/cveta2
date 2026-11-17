"""Public managed workflow integrates real policy/files with fake external services."""

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Self, TypedDict

import pandas as pd
import pytest
import yaml
from PIL import Image

from cveta2.adapters.class_api.http import HttpClassApi
from cveta2.adapters.files.managed_sources import LocalSourceFiles
from cveta2.application.ports.dtos import (
    NewIssue,
    RawAnnotations,
    RawDataMeta,
    RawFrame,
    RawIssue,
    RawJob,
    RawShape,
)
from cveta2.application.ports.managed_sources import S3Object
from cveta2.composition import managed
from cveta2.domain.bundle.models import (
    ApiClass,
    ClassInfo,
    DatasetMetadata,
    DatasetParent,
    ImageRoots,
    Publication,
)
from cveta2.domain.errors import Cveta2Error
from cveta2.domain.managed.models import ManagedError, ManagedSnapshot, SplitPolicy
from cveta2.domain.managed.policies import assign_splits
from cveta2.domain.models import LabelInfo, TaskInfo
from cveta2.interfaces import managed_datasets as api
from cveta2.interfaces.cli import main


class FakeCvat:
    """Stand-in raw CVAT boundary, retaining real source and feedback adapters."""

    def __init__(self) -> None:
        """Initialize two independent completed task inventories."""
        self.tasks = {
            task_id: TaskInfo(
                id=task_id,
                project_id=project,
                name=f"task-{task_id}",
                status="completed",
                subset="",
                updated_date="original",
            )
            for task_id, project in ((101, 12), (102, 27))
        }
        self.annotation_reads: list[int] = []
        self.issues: dict[int, list[RawIssue]] = {101: [], 102: []}
        self.fail_issues = False
        self.fail_frames: set[int] = set()
        self.advance_issue_timestamp = False

    def get_project_tasks(self, project_id: int) -> list[TaskInfo]:
        return [task for task in self.tasks.values() if task.project_id == project_id]

    def get_project_labels(self, _project_id: int) -> list[LabelInfo]:
        return [LabelInfo(id=1, name="cat")]

    def get_task(self, task_id: int) -> TaskInfo:
        return self.tasks[task_id]

    def get_task_jobs(self, task_id: int) -> list[RawJob]:
        return [
            RawJob(
                id=task_id * 10,
                start_frame=0,
                stop_frame=11,
                stage="acceptance",
                state="completed",
            )
        ]

    def get_task_data_meta(self, task_id: int) -> RawDataMeta:
        return RawDataMeta([RawFrame(name=f"task{task_id}-{frame}.png", width=32, height=32) for frame in range(12)])

    def get_task_annotations(self, task_id: int) -> RawAnnotations:
        self.annotation_reads.append(task_id)
        return RawAnnotations(
            [
                RawShape(
                    id=task_id * 100 + frame,
                    type="rectangle",
                    frame=frame,
                    label_id=1,
                    points=[1.0, 1.0, 20.0, 20.0],
                    occluded=False,
                    z_order=0,
                    rotation=0.0,
                    source="manual",
                    attributes=[],
                    created_by="annotator",
                )
                for frame in range(12)
            ]
        )

    def get_task_issues(self, task_id: int) -> list[RawIssue]:
        return self.issues[task_id]

    def create_issue(self, issue: NewIssue) -> None:
        if self.fail_issues or issue.frame in self.fail_frames:
            raise Cveta2Error("Simulated feedback failure")
        task_id = issue.job_id // 10
        self.issues[task_id].append(
            RawIssue(
                id=len(self.issues[task_id]) + 1,
                frame=issue.frame,
                resolved=False,
                comments=[issue.message],
                position=issue.position,
            )
        )
        if self.advance_issue_timestamp:
            self.tasks[task_id] = self.tasks[task_id].model_copy(
                update={"updated_date": f"issue-{len(self.issues[task_id])}"}
            )


class FakeConnection:
    """Context lifetime is fake; all managed orchestration stays real."""

    def __init__(self, raw: FakeCvat) -> None:
        """Bind only the raw external API boundary."""
        self.api = raw

    def __enter__(self) -> Self:
        """Enter the fake external connection lifetime."""
        return self

    def __exit__(self, *_args: object) -> None:
        """Close without touching any service."""


class FakeS3:
    def __init__(self, content: bytes) -> None:
        """Capture an object whose bytes tests can replace."""
        self.content = content

    def read_object(self, uri: str) -> S3Object:
        assert uri == "s3://annotations/imported.csv"
        return S3Object(self.content, hashlib.sha256(self.content).hexdigest(), "opaque", "v1")


class FakeClearML:
    """Retain exact publication files and parent metadata between API operations."""

    def __init__(self, root: Path) -> None:
        """Store immutable versions under an isolated temporary root."""
        self.root = root
        self.latest_id: str | None = None
        self.publications: list[str] = []

    def latest(self, project: str, name: str) -> DatasetParent | None:
        if self.latest_id is None:
            return None
        metadata = self.root / self.latest_id / "dataset.yaml"
        return DatasetParent(
            self.latest_id,
            project,
            name,
            str(len(self.publications)),
            metadata if metadata.is_file() else None,
        )

    def publish(self, project: str, name: str, parent_id: str | None, directory: Path) -> Publication:
        assert project == "CV/combined"
        assert name == "annotations"
        assert parent_id == self.latest_id
        assert {path.name for path in directory.iterdir()} == {
            "dataset.csv",
            "dataset.yaml",
            "tasks.yaml",
        }
        dataset_id = f"version-{len(self.publications) + 1}"
        shutil.copytree(directory, self.root / dataset_id)
        self.publications.append(dataset_id)
        self.latest_id = dataset_id
        return Publication(dataset_id, str(len(self.publications)))

    def read_snapshot(self, dataset_id: str) -> ManagedSnapshot | None:
        path = self.root / dataset_id / "tasks.yaml"
        return LocalSourceFiles().read_snapshot(path) if path.is_file() else None

    def read_files(self, dataset_id: str, names: tuple[str, ...]) -> dict[str, bytes]:
        return {name: (self.root / dataset_id / name).read_bytes() for name in names}

    def versions(self, _project: str, _name: str) -> list[dict[str, str | None]]:
        return [
            {"id": dataset_id, "version": str(index)} for index, dataset_id in enumerate(self.publications, start=1)
        ]


class ConfigPaths(TypedDict):
    config_path: Path
    project_config: Path


@dataclass
class Workflow:
    personal: Path
    shared: Path
    images: Path
    cvat: FakeCvat
    s3: FakeS3
    clearml: FakeClearML

    @property
    def options(self) -> ConfigPaths:
        return {"config_path": self.personal, "project_config": self.shared}


@pytest.fixture
def workflow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Workflow:
    """Only outgoing service adapters are replaced; source/config/files are real."""
    images = tmp_path / "images"
    images.mkdir()
    cvat = FakeCvat()
    names = [frame.name for task in cvat.tasks for frame in cvat.get_task_data_meta(task).frames]
    names += [f"external-{index}.png" for index in range(6)]
    for name in names:
        color = tuple(hashlib.sha256(name.encode()).digest()[:3])
        Image.new("RGB", (32, 32), color).save(images / name)
    imported = pd.DataFrame(
        [
            {
                "image_name": name,
                "image_path": str(images / name),
                "instance_label": "cat",
                "bbox_x_tl": 1,
                "bbox_y_tl": 1,
                "bbox_x_br": 20,
                "bbox_y_br": 20,
            }
            for name in names
            if name.startswith("external")
        ]
    )
    s3 = FakeS3(imported.to_csv(index=False).encode())
    shared = tmp_path / "project-config.yaml"
    shared.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "cvat": {"host": "https://cvat.example"},
                "projects": {"main": {"id": 12}, "other": {"id": 27}},
                "datasets": {
                    "combined": {
                        "sources": [
                            {"name": "main", "type": "cvat", "project": "main"},
                            {"name": "other", "type": "cvat", "project": "other"},
                            {
                                "name": "imported",
                                "type": "s3-csv",
                                "uri": "s3://annotations/imported.csv",
                            },
                        ],
                        "clearml": {"project": "CV/combined", "dataset": "annotations"},
                        "api_url": "https://classes.example/api",
                    }
                },
            }
        )
    )
    personal = tmp_path / "config.yaml"
    personal.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "project_config": str(shared),
                "cvat": {"username": "user", "password": "secret"},
                "cache": {"images_root": str(images)},
            }
        )
    )
    clearml = FakeClearML(tmp_path / "remote")
    monkeypatch.setattr(managed, "CvatClient", lambda _cfg: FakeConnection(cvat))
    monkeypatch.setattr(managed, "ClearMLStore", lambda: clearml)
    monkeypatch.setattr(managed, "ClearMLSources", lambda: clearml)
    monkeypatch.setattr(managed, "S3CsvSources", lambda: s3)
    records = [
        ApiClass(
            id=90,
            number=7,
            name="cat",
            techClass=False,
            isPeriodical=False,
            isCritical=False,
            threshold=0.5,
        )
    ]
    monkeypatch.setattr(HttpClassApi, "fetch", lambda _self, _url: records)
    return Workflow(personal, shared, images, cvat, s3, clearml)


def _legacy_parent(workflow: Workflow, dataset: pd.DataFrame | None = None) -> Path:
    """Install a standalone parent without managed extensions as the latest version."""
    parent = workflow.clearml.root / "legacy"
    parent.mkdir(parents=True)
    metadata = DatasetMetadata(
        api_url="https://classes.example/api",
        classes={"cat": ClassInfo(prod_id=7)},
        images=ImageRoots(local_root=[str(workflow.images)]),
    )
    (parent / "dataset.yaml").write_text(yaml.safe_dump(metadata.model_dump(mode="json")))
    published = pd.DataFrame(columns=["image_name", "image_path", "split"]) if dataset is None else dataset
    published.to_csv(parent / "dataset.csv", index=False)
    workflow.clearml.latest_id = "legacy"
    return parent


def _prepare(
    workflow: Workflow,
    tmp_path: Path,
    *,
    bad: bool = False,
    bad_frames: tuple[str, ...] = ("0",),
) -> Path:
    fetched = tmp_path / "fetched"
    result = api.fetch_dataset("combined", output_dir=fetched, **workflow.options)
    assert result["rows"] == 30
    transformed = pd.read_csv(fetched / "dataset.csv", keep_default_na=False)
    transformed["image_path"] = transformed["image_name"].map(lambda name: str(workflow.images / name))
    if bad:
        transformed.loc[
            transformed["source_id"].eq("main") & transformed["source_frame_id"].astype(str).isin(bad_frames),
            "bbox_x_br",
        ] = 1
    output = tmp_path / "transformed.csv"
    transformed.to_csv(output, index=False)
    prepared = tmp_path / "prepared"
    summary = api.prepare_managed_dataset(
        "combined",
        output,
        source=fetched,
        output_dir=prepared,
        clean=bad,
        **workflow.options,
    )
    assert summary.ready, summary.report
    return prepared


def test_setup_attach_and_cli_list_never_modify_shared_config(
    workflow: Workflow, capsys: pytest.CaptureFixture[str]
) -> None:
    original = workflow.shared.read_bytes()
    main(
        [
            "setup",
            "--config",
            str(workflow.personal),
            "--project-config",
            str(workflow.shared),
        ]
    )
    main(["dataset", "list", "--config", str(workflow.personal), "--json"])
    definitions = json.loads(capsys.readouterr().out)
    assert definitions[0]["name"] == "combined"
    assert len(definitions[0]["sources"]) == 3
    assert workflow.shared.read_bytes() == original
    assert workflow.cvat.annotation_reads == []


def test_public_pipeline_publishes_three_files_and_reuses_unchanged_tasks(workflow: Workflow, tmp_path: Path) -> None:
    assert workflow.clearml.latest_id is None
    prepared = _prepare(workflow, tmp_path)
    assert workflow.clearml.publications == []
    assert LocalSourceFiles().read_snapshot(tmp_path / "fetched").parent_id is None
    assert json.loads((prepared / "preparation.json").read_bytes())["parent_id"] is None
    result = api.publish_dataset(prepared, **workflow.options)
    assert result.dataset_id == "version-1"
    assert {path.name for path in (workflow.clearml.root / result.dataset_id).iterdir()} == {
        "dataset.csv",
        "dataset.yaml",
        "tasks.yaml",
    }
    source = workflow.clearml.read_snapshot(result.dataset_id)
    assert source is not None
    assert {item.type for item in source.sources} == {"cvat", "s3-csv"}
    workflow.cvat.annotation_reads.clear()
    reused = api.fetch_dataset("combined", output_dir=tmp_path / "again", **workflow.options)
    assert workflow.cvat.annotation_reads == []
    assert reused["sources"][0]["reused"] == [101]
    assert reused["sources"][1]["reused"] == [102]
    assert len(api.dataset_versions("combined", **workflow.options)) == 1
    compared = api.compare_datasets(str(prepared), result.dataset_id, **workflow.options)
    assert compared["rows"]["added"] == 0
    assert compared["rows"]["removed"] == 0


def test_feedback_retry_and_own_timestamp_change_allow_clean_publication(workflow: Workflow, tmp_path: Path) -> None:
    prepared = _prepare(workflow, tmp_path, bad=True)
    workflow.cvat.advance_issue_timestamp = True
    first = api.report_dataset_errors(prepared, **workflow.options)
    assert first.created == 1
    assert first.failed == []
    second = api.report_dataset_errors(prepared, **workflow.options)
    assert second.created == 0
    assert second.existing == 1
    assert len(workflow.cvat.issues[101]) == 1
    published = api.publish_dataset(prepared, **workflow.options)
    assert published.dataset_id == "version-1"
    final = pd.read_csv(workflow.clearml.root / published.dataset_id / "dataset.csv")
    assert len(final) == 29


def test_feedback_failure_blocks_remote_publication(workflow: Workflow, tmp_path: Path) -> None:
    prepared = _prepare(workflow, tmp_path, bad=True)
    workflow.cvat.fail_issues = True
    with pytest.raises(ManagedError, match=r"feedback|Feedback"):
        api.publish_dataset(prepared, **workflow.options)
    assert workflow.clearml.publications == []
    workflow.cvat.fail_issues = False
    assert api.publish_dataset(prepared, **workflow.options).dataset_id == "version-1"


@pytest.mark.parametrize("change", ["definition", "parent", "cvat", "s3", "image"])
def test_stale_prerequisites_prevent_publication(workflow: Workflow, tmp_path: Path, change: str) -> None:
    prepared = _prepare(workflow, tmp_path)
    if change == "definition":
        definition = yaml.safe_load(workflow.shared.read_text())
        definition["datasets"]["combined"]["empty_classes"] = [7]
        workflow.shared.write_text(yaml.safe_dump(definition))
    elif change == "parent":
        workflow.clearml.root.mkdir()
        target = workflow.clearml.root / "competing"
        target.mkdir()
        shutil.copy(prepared / "dataset.yaml", target / "dataset.yaml")
        workflow.clearml.latest_id = "competing"
    elif change == "cvat":
        workflow.cvat.tasks[101] = workflow.cvat.tasks[101].model_copy(update={"updated_date": "edited"})
    elif change == "s3":
        workflow.s3.content += b"\n"
    else:
        Image.new("RGB", (32, 32), "white").save(workflow.images / "task101-0.png")
    with pytest.raises(ManagedError):
        api.publish_dataset(prepared, **workflow.options)
    assert workflow.clearml.publications == []


def test_csv_only_parent_cannot_become_a_ready_preparation(workflow: Workflow, tmp_path: Path) -> None:
    parent = _legacy_parent(workflow)
    (parent / "dataset.yaml").unlink()
    with pytest.raises(ManagedError, match=r"dataset\.yaml"):
        _prepare(workflow, tmp_path)
    assert not (tmp_path / "prepared").exists()


def test_parent_that_lost_its_metadata_blocks_publication(workflow: Workflow, tmp_path: Path) -> None:
    parent = _legacy_parent(workflow)
    prepared = _prepare(workflow, tmp_path)
    (parent / "dataset.yaml").unlink()
    with pytest.raises(ManagedError, match=r"dataset\.yaml"):
        api.publish_dataset(prepared, **workflow.options)
    assert workflow.clearml.publications == []


def test_legacy_parent_adoption_keeps_published_splits_of_unambiguous_images(
    workflow: Workflow, tmp_path: Path
) -> None:
    paths = sorted(str(path) for path in workflow.images.iterdir())
    hashes = {path: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in paths}
    seeded, _ = assign_splits(pd.DataFrame({"image_path": paths}), SplitPolicy(), hashes)
    # Published splits deliberately differ from what seeded hashing would choose.
    published = dict(zip(paths, seeded["split"].map({"train": "val", "val": "train", "test": "train"}), strict=True))
    ambiguous = paths[0]
    rows = [{"image_name": Path(path).name, "image_path": path, "split": split} for path, split in published.items()]
    rows.append({"image_name": Path(ambiguous).name, "image_path": ambiguous, "split": "test"})
    _legacy_parent(workflow, pd.DataFrame(rows))
    prepared = _prepare(workflow, tmp_path)
    result = pd.read_csv(prepared / "dataset.csv", keep_default_na=False)
    splits = result.groupby("image_path")["split"].agg(set).to_dict()
    assert {path: splits[path] for path in paths if path != ambiguous} == {
        path: {published[path]} for path in paths if path != ambiguous
    }
    assert splits[ambiguous] == set(seeded.loc[seeded["image_path"].eq(ambiguous), "split"])
    report = json.loads((prepared / "report.json").read_text())
    assert report["parent_split_conflicts"] == 1


def test_failed_feedback_is_delivered_after_a_sibling_issue_moved_the_task(workflow: Workflow, tmp_path: Path) -> None:
    prepared = _prepare(workflow, tmp_path, bad=True, bad_frames=("0", "1"))
    workflow.cvat.advance_issue_timestamp = True
    workflow.cvat.fail_frames = {0}
    first = api.report_dataset_errors(prepared, **workflow.options)
    assert (first.created, len(first.failed)) == (1, 1)
    workflow.cvat.fail_frames.clear()
    retried = api.report_dataset_errors(prepared, **workflow.options)
    assert (retried.created, retried.existing, retried.failed) == (1, 1, [])
    assert sorted(issue.frame for issue in workflow.cvat.issues[101]) == [0, 1]
    assert api.publish_dataset(prepared, **workflow.options).dataset_id == "version-1"


def test_unexplained_task_change_still_blocks_a_pending_delivery(workflow: Workflow, tmp_path: Path) -> None:
    prepared = _prepare(workflow, tmp_path, bad=True, bad_frames=("0", "1"))
    workflow.cvat.advance_issue_timestamp = True
    workflow.cvat.fail_frames = {0}
    api.report_dataset_errors(prepared, **workflow.options)
    workflow.cvat.fail_frames.clear()
    workflow.cvat.tasks[101] = workflow.cvat.tasks[101].model_copy(update={"updated_date": "edited"})
    with pytest.raises(ManagedError):
        api.report_dataset_errors(prepared, **workflow.options)
    assert sorted(issue.frame for issue in workflow.cvat.issues[101]) == [1]
    with pytest.raises(ManagedError):
        api.publish_dataset(prepared, **workflow.options)
    assert workflow.clearml.publications == []


def _fetch_and_transform(workflow: Workflow, tmp_path: Path) -> tuple[Path, Path]:
    fetched = tmp_path / "fetched"
    api.fetch_dataset("combined", output_dir=fetched, **workflow.options)
    transformed = pd.read_csv(fetched / "dataset.csv", keep_default_na=False)
    transformed["image_path"] = transformed["image_name"].map(lambda name: str(workflow.images / name))
    transformed.loc[
        transformed["source_id"].eq("main") & transformed["source_frame_id"].astype(str).eq("0"),
        "bbox_x_br",
    ] = 1
    output = tmp_path / "transformed.csv"
    transformed.to_csv(output, index=False)
    return fetched, output


def test_feedback_from_an_inspection_does_not_stale_a_sibling_preparation(workflow: Workflow, tmp_path: Path) -> None:
    fetched, transformed = _fetch_and_transform(workflow, tmp_path)
    inspection = api.prepare_managed_dataset(
        "combined", transformed, source=fetched, output_dir=tmp_path / "inspection", **workflow.options
    )
    assert not inspection.ready
    workflow.cvat.advance_issue_timestamp = True
    assert api.report_dataset_errors(inspection.directory, **workflow.options).created == 1
    prepared = api.prepare_managed_dataset(
        "combined", transformed, source=fetched, output_dir=tmp_path / "prepared", clean=True, **workflow.options
    )
    assert prepared.ready
    assert api.publish_dataset(prepared.directory, **workflow.options).dataset_id == "version-1"
    assert len(workflow.cvat.issues[101]) == 1


@pytest.mark.parametrize("publish_sibling", [False, True])
def test_preparation_with_a_ledger_from_before_sharing_still_publishes(
    workflow: Workflow, tmp_path: Path, *, publish_sibling: bool
) -> None:
    prepared = _prepare(workflow, tmp_path, bad=True)
    workflow.cvat.advance_issue_timestamp = True
    assert api.report_dataset_errors(prepared, **workflow.options).created == 1
    (shared,) = (workflow.personal.parent / "managed-feedback").iterdir()
    # Earlier versions kept the only ledger inside the preparation directory.
    local = shared.rename(prepared / "feedback.json")
    original_ledger = local.read_bytes()
    repeated = api.report_dataset_errors(prepared, **workflow.options)
    assert (repeated.created, repeated.existing, repeated.failed) == (0, 1, [])
    target = prepared
    if publish_sibling:
        sibling = api.prepare_managed_dataset(
            "combined",
            tmp_path / "transformed.csv",
            source=tmp_path / "fetched",
            output_dir=tmp_path / "sibling",
            clean=True,
            **workflow.options,
        )
        assert sibling.ready
        target = sibling.directory
    assert api.publish_dataset(target, **workflow.options).dataset_id == "version-1"
    assert len(workflow.cvat.issues[101]) == 1
    assert local.read_bytes() == original_ledger
