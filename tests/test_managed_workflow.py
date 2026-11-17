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
from cveta2.domain.bundle.models import ApiClass, DatasetParent, Publication
from cveta2.domain.errors import Cveta2Error
from cveta2.domain.managed.models import ManagedError, ManagedSnapshot
from cveta2.domain.models import LabelAttributeInfo, LabelInfo, TaskInfo
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
        self.advance_issue_timestamp = False
        self.labels = {
            project: [
                LabelInfo(
                    id=1,
                    name="cat",
                    color="#123456",
                    type="rectangle",
                    project_id=project,
                    attributes=[
                        LabelAttributeInfo(
                            id=4,
                            name="quality",
                            mutable=True,
                            input_type="select",
                            default_value="good",
                            values=["good", "poor"],
                        )
                    ],
                ),
                LabelInfo(
                    id=2,
                    name="pose",
                    type="skeleton",
                    project_id=project,
                    svg='<svg><circle data-node-id="3" /></svg>',
                    sublabels=[LabelInfo(id=3, name="head", type="points", parent_id=2, has_parent=True)],
                ),
            ]
            for project in (12, 27)
        }

    def get_project_tasks(self, project_id: int) -> list[TaskInfo]:
        return [task for task in self.tasks.values() if task.project_id == project_id]

    def get_project_labels(self, project_id: int) -> list[LabelInfo]:
        return self.labels[project_id]

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
        if self.fail_issues:
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
        return DatasetParent(
            self.latest_id,
            project,
            name,
            str(len(self.publications)),
            self.root / self.latest_id / "dataset.yaml",
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

    def read_snapshot(self, dataset_id: str) -> ManagedSnapshot:
        return LocalSourceFiles().read_snapshot(self.root / dataset_id / "tasks.yaml")

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


def _prepare(workflow: Workflow, tmp_path: Path, *, bad: bool = False) -> Path:
    fetched = tmp_path / "fetched"
    result = api.fetch_dataset("combined", output_dir=fetched, **workflow.options)
    assert result["rows"] == 30
    transformed = pd.read_csv(fetched / "dataset.csv", keep_default_na=False)
    transformed["image_path"] = transformed["image_name"].map(lambda name: str(workflow.images / name))
    if bad:
        transformed.loc[
            transformed["source_id"].eq("main") & transformed["source_frame_id"].astype(str).eq("0"),
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


def test_full_registry_and_labels_survive_fetch_prepare_and_publication(workflow: Workflow, tmp_path: Path) -> None:
    prepared = _prepare(workflow, tmp_path)
    result = api.publish_dataset(prepared, **workflow.options)
    expected_registry = [
        {
            "id": 90,
            "number": 7,
            "name": "cat",
            "techClass": False,
            "isPeriodical": False,
            "isCritical": False,
            "threshold": 0.5,
        }
    ]
    fetched = yaml.safe_load((tmp_path / "fetched" / "source-snapshot.yaml").read_text())
    local = yaml.safe_load((prepared / "tasks.yaml").read_text())["managed"]
    published = yaml.safe_load((workflow.clearml.root / result.dataset_id / "tasks.yaml").read_text())["managed"]
    for snapshot in (fetched, local, published):
        assert snapshot.get("registry") == expected_registry
        for source in snapshot["sources"]:
            if source["type"] == "cvat":
                assert source.get("labels") == [
                    label.model_dump(mode="json") for label in workflow.cvat.get_project_labels(source["project_id"])
                ]


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


@pytest.mark.parametrize("change", ["definition", "parent", "cvat", "label-attribute", "s3", "image"])
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
    elif change == "label-attribute":
        label = workflow.cvat.labels[12][0]
        workflow.cvat.labels[12] = [
            label.model_copy(update={"attributes": [label.attributes[0].model_copy(update={"default_value": "poor"})]})
        ]
    elif change == "s3":
        workflow.s3.content += b"\n"
    else:
        Image.new("RGB", (32, 32), "white").save(workflow.images / "task101-0.png")
    with pytest.raises(ManagedError):
        api.publish_dataset(prepared, **workflow.options)
    assert workflow.clearml.publications == []


@pytest.mark.parametrize("damage", ["missing-registry", "missing-labels", "changed-registry", "changed-labels"])
def test_incomplete_or_corrupt_prepared_records_block_publication(
    workflow: Workflow, tmp_path: Path, damage: str
) -> None:
    prepared = _prepare(workflow, tmp_path)
    source_path = prepared / "source-snapshot.yaml"
    tasks_path = prepared / "tasks.yaml"
    record_path = prepared / "preparation.json"
    source = yaml.safe_load(source_path.read_text())
    tasks = yaml.safe_load(tasks_path.read_text())
    record = json.loads(record_path.read_text())
    # Keep byte bindings consistent, as in an old or corrupted exporter, so the
    # publication check must inspect the records themselves rather than checksums.
    for snapshot in (source, tasks["managed"], record["snapshot"]):
        if damage == "missing-registry":
            snapshot.pop("registry")
        elif damage == "missing-labels":
            snapshot["sources"][0].pop("labels")
        elif damage == "changed-registry":
            snapshot["registry"][0]["threshold"] = 0.75
        else:
            snapshot["sources"][0]["labels"][0]["attributes"][0]["default_value"] = "poor"
    source_path.write_text(yaml.safe_dump(source))
    tasks_path.write_text(yaml.safe_dump(tasks))
    record["source_hash"] = hashlib.sha256(source_path.read_bytes()).hexdigest()
    record["payload_hashes"]["tasks.yaml"] = hashlib.sha256(tasks_path.read_bytes()).hexdigest()
    record_path.write_text(json.dumps(record))
    (prepared / "preparation.sha256").write_text(hashlib.sha256(record_path.read_bytes()).hexdigest())

    with pytest.raises(ManagedError, match=r"fetch|fingerprint|records|definitions"):
        api.publish_dataset(prepared, **workflow.options)

    assert workflow.clearml.publications == []
    assert all(not issues for issues in workflow.cvat.issues.values())


@pytest.mark.parametrize("missing", ["registry", "labels"])
def test_legacy_published_parent_refetches_all_tasks_and_preserves_splits(
    workflow: Workflow, tmp_path: Path, missing: str
) -> None:
    prepared = _prepare(workflow, tmp_path)
    published = api.publish_dataset(prepared, **workflow.options)
    tasks_path = workflow.clearml.root / published.dataset_id / "tasks.yaml"
    tasks = yaml.safe_load(tasks_path.read_text())
    assignments = tasks["managed"]["assignments"]
    assert assignments
    if missing == "registry":
        tasks["managed"].pop("registry")
    else:
        tasks["managed"]["sources"][0].pop("labels")
    tasks_path.write_text(yaml.safe_dump(tasks))
    workflow.cvat.annotation_reads.clear()

    api.fetch_dataset("combined", output_dir=tmp_path / "refetched", **workflow.options)

    refreshed = LocalSourceFiles().read_snapshot(tmp_path / "refetched")
    assert sorted(workflow.cvat.annotation_reads) == [101, 102]
    assert refreshed.assignments == assignments
    assert refreshed.registry is not None
    assert all(source.labels is not None for source in refreshed.sources if source.type == "cvat")
