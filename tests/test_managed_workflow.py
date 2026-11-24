"""Public managed workflow integrates real policy/files with fake external services."""

import hashlib
import json
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Self, TypedDict

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
from cveta2.application.ports.managed_sources import S3Object, S3ObjectIdentity
from cveta2.composition import managed
from cveta2.domain.bundle.models import (
    ApiClass,
    ClassInfo,
    DatasetMetadata,
    DatasetParent,
    ImageRoots,
    Publication,
)
from cveta2.domain.errors import CvatApiError, Cveta2Error
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
        self.fail_frames: set[int] = set()
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
        if task_id not in self.tasks:
            raise CvatApiError(f"Task {task_id} not found", status_code=404)
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
        """Capture an object whose bytes and version tests can replace."""
        self.content = content
        self.version = "v1"

    def object_identity(self, uri: str) -> S3ObjectIdentity:
        assert uri == "s3://annotations/imported.csv"
        return S3ObjectIdentity(f'"{hashlib.sha256(self.content).hexdigest()[:32]}"', self.version)

    def read_object(self, uri: str) -> S3Object:
        identity = self.object_identity(uri)
        return S3Object(self.content, hashlib.sha256(self.content).hexdigest(), identity.etag, identity.version_id)


class FakeClearML:
    """Retain exact publication files and parent metadata between API operations."""

    def __init__(self, root: Path) -> None:
        """Store immutable versions under an isolated temporary root."""
        self.root = root
        self.latest_id: str | None = None
        self.publications: list[str] = []
        self.parents: list[str | None] = []
        # Per publication, in order: the file list and output_uri the caller passed.
        self.published_calls: list[tuple[tuple[str, ...], str | None]] = []

    def latest(self, project: str, name: str) -> DatasetParent | None:
        if self.latest_id is None or (project, name) != ("CV/combined", "annotations"):
            return None
        metadata = self.root / self.latest_id / "dataset.yaml"
        return DatasetParent(
            self.latest_id,
            project,
            name,
            str(len(self.publications)),
            metadata if metadata.is_file() else None,
        )

    def publish(  # noqa: PLR0913
        self,
        project: str,
        name: str,
        parent_id: str | None,
        directory: Path,
        *,
        files: tuple[str, ...],
        output_uri: str | None = None,
    ) -> Publication:
        self.published_calls.append((files, output_uri))
        assert project == "CV/combined"
        assert name == "annotations"
        self.parents.append(parent_id)
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

    def parent_file(self, _parent: DatasetParent, _filename: str) -> Path | None:
        return None

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
                "global_config": str(shared),
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


def _edit_shared(workflow: Workflow, edit: Callable[[dict[str, Any]], object]) -> None:
    shared = yaml.safe_load(workflow.shared.read_text())
    edit(shared)
    workflow.shared.write_text(yaml.safe_dump(shared))


def _non_managed_latest(workflow: Workflow, *, metadata: bool = True) -> Path:
    """Install a version without a ``managed`` block (made outside the managed workflow) as the latest one.

    Its class differs from the registry's, so reading it for classes would fail the preparation.
    """
    parent = workflow.clearml.root / "external"
    parent.mkdir(parents=True)
    if metadata:
        plain = DatasetMetadata(
            api_url="https://classes.example/api",
            classes={"dog": ClassInfo(prod_id=8)},
            images=ImageRoots(local_root=[str(workflow.images)]),
        )
        (parent / "dataset.yaml").write_text(yaml.safe_dump(plain.model_dump(mode="json")))
    pd.DataFrame({"image_name": ["old.png"], "image_path": ["/old.png"], "split": ["val"]}).to_csv(
        parent / "dataset.csv", index=False
    )
    workflow.clearml.latest_id = "external"
    return parent


def _hand_splits(frame: pd.DataFrame) -> pd.DataFrame:
    """Give every row of an image the split a user would set by hand, by name order."""
    names = sorted(set(frame["image_name"]))
    chosen = {name: ("train", "train", "train", "val", "test")[index % 5] for index, name in enumerate(names)}
    return frame.assign(split=frame["image_name"].map(chosen))


def _transform(
    workflow: Workflow,
    tmp_path: Path,
    *,
    bad: bool = False,
    bad_frames: tuple[str, ...] = ("0",),
) -> tuple[Path, Path]:
    """Fetch, then write the transformed CSV a user would hand to prepare."""
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
    _hand_splits(transformed).to_csv(output, index=False)
    return fetched, output


def _prepare(
    workflow: Workflow,
    tmp_path: Path,
    *,
    bad: bool = False,
    bad_frames: tuple[str, ...] = ("0",),
    first: bool = False,
) -> Path:
    fetched, output = _transform(workflow, tmp_path, bad=bad, bad_frames=bad_frames)
    prepared = tmp_path / "prepared"
    summary = api.prepare_managed_dataset(
        "combined",
        output,
        source=fetched,
        output_dir=prepared,
        clean=bad,
        first=first,
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
            "--global-config",
            str(workflow.shared),
        ]
    )
    main(["dataset", "list", "--config", str(workflow.personal), "--json"])
    definitions = json.loads(capsys.readouterr().out)
    assert definitions[0]["name"] == "combined"
    assert len(definitions[0]["sources"]) == 3
    assert workflow.shared.read_bytes() == original
    assert workflow.cvat.annotation_reads == []


def test_managed_publish_passes_three_files_without_output_uri(workflow: Workflow, tmp_path: Path) -> None:
    api.publish_dataset(_prepare(workflow, tmp_path), **workflow.options)
    assert workflow.clearml.published_calls == [(("dataset.csv", "dataset.yaml", "tasks.yaml"), None)]


def test_public_pipeline_publishes_three_files_and_reuses_unchanged_tasks(workflow: Workflow, tmp_path: Path) -> None:
    assert workflow.clearml.latest_id is None
    prepared = _prepare(workflow, tmp_path)
    assert workflow.clearml.publications == []
    assert LocalSourceFiles().read_snapshot(tmp_path / "fetched").parent_id is None
    record = json.loads((prepared / "preparation.json").read_bytes())
    assert (record["parent_id"], record["first"]) == (None, False)
    result = api.publish_dataset(prepared, **workflow.options)
    assert result.dataset_id == "version-1"
    assert workflow.clearml.parents == [None]
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
    assert (reused["directory"], reused["parent_id"]) == (str(tmp_path / "again"), "version-1")
    forced = api.fetch_dataset("combined", output_dir=tmp_path / "forced", refresh=True, **workflow.options)
    assert sorted(workflow.cvat.annotation_reads) == [101, 102]
    assert {source["name"]: source["fetched"] for source in forced["sources"]} == {
        "main": [101],
        "other": [102],
        "imported": [],
    }
    assert forced["sources"][2]["content_hash"] == hashlib.sha256(workflow.s3.content).hexdigest()
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


@pytest.mark.parametrize("change", ["parent", "image"])
def test_stale_prerequisites_prevent_publication(workflow: Workflow, tmp_path: Path, change: str) -> None:
    prepared = _prepare(workflow, tmp_path)
    message = "fetch again|prepare again|validation"
    if change == "parent":
        workflow.clearml.root.mkdir()
        target = workflow.clearml.root / "competing"
        target.mkdir()
        shutil.copy(prepared / "dataset.yaml", target / "dataset.yaml")
        workflow.clearml.latest_id = "competing"
    else:
        Image.new("RGB", (32, 32), "white").save(workflow.images / "task101-0.png")
    with pytest.raises(ManagedError, match=message):
        api.publish_dataset(prepared, **workflow.options)
    assert workflow.clearml.publications == []


_SOURCE_WARNINGS = {
    "cvat": "main: задача 101 изменена после fetch",
    "label-attribute": "main: изменились метки проекта",
    "s3": "imported: в S3 лежит другой объект (ETag или версия)",
    "s3-version": "imported: в S3 лежит другой объект (ETag или версия)",
}


@pytest.mark.parametrize("change", _SOURCE_WARNINGS)
def test_source_changes_after_fetch_warn_and_publish(
    workflow: Workflow, tmp_path: Path, capture_logs: list[str], change: str
) -> None:
    prepared = _prepare(workflow, tmp_path)
    if change == "cvat":
        workflow.cvat.tasks[101] = workflow.cvat.tasks[101].model_copy(update={"updated_date": "edited"})
    elif change == "label-attribute":
        label = workflow.cvat.labels[12][0]
        workflow.cvat.labels[12] = [
            label.model_copy(update={"attributes": [label.attributes[0].model_copy(update={"default_value": "poor"})]})
        ]
    elif change == "s3":
        workflow.s3.content += b"\n"
    else:
        workflow.s3.version = "v2"

    assert api.publish_dataset(prepared, **workflow.options).dataset_id == "version-1"
    assert f"{_SOURCE_WARNINGS[change]}. Датасет собирается из выгруженных данных." in capture_logs


def test_task_completed_after_fetch_stops_publication(workflow: Workflow, tmp_path: Path) -> None:
    prepared = _prepare(workflow, tmp_path)
    workflow.cvat.tasks[103] = workflow.cvat.tasks[101].model_copy(update={"id": 103, "updated_date": "new"})
    workflow.cvat.issues[103] = []
    with pytest.raises(
        ManagedError, match="CVAT tasks completed after fetch: main/103; fetch the managed dataset again"
    ):
        api.publish_dataset(prepared, **workflow.options)
    assert workflow.clearml.publications == []


def test_findings_of_an_edited_task_are_skipped(workflow: Workflow, tmp_path: Path, capture_logs: list[str]) -> None:
    prepared = _prepare(workflow, tmp_path, bad=True)
    workflow.cvat.tasks[101] = workflow.cvat.tasks[101].model_copy(update={"updated_date": "edited"})
    outcome = api.report_dataset_errors(prepared, **workflow.options)
    assert (outcome.created, outcome.skipped) == (0, 1)
    assert workflow.cvat.issues[101] == []
    assert any("Замечаний не отправлено: 1" in line for line in capture_logs)


@pytest.mark.parametrize("metadata", [True, False], ids=["plain-metadata", "no-metadata"])
def test_latest_version_without_managed_metadata_is_refused_naming_first(
    workflow: Workflow, tmp_path: Path, *, metadata: bool
) -> None:
    _non_managed_latest(workflow, metadata=metadata)
    with pytest.raises(ManagedError, match=r"Parent external is not a managed dataset version; .*--first"):
        _prepare(workflow, tmp_path)
    assert not (tmp_path / "prepared").exists()


def _invalidate_metadata(parent: Path) -> None:
    """Leave a dataset.yaml that parses as YAML but not as dataset metadata (an unknown key)."""
    metadata = yaml.safe_load((parent / "dataset.yaml").read_text())
    metadata["unknown_key"] = 1
    (parent / "dataset.yaml").write_text(yaml.safe_dump(metadata))


@pytest.mark.parametrize("latest", ["plain-metadata", "no-metadata", "invalid-metadata", "empty"])
def test_first_starts_a_lineage_over_a_non_managed_latest_version(
    workflow: Workflow, tmp_path: Path, capture_logs: list[str], latest: str
) -> None:
    """Over a version without managed metadata, without or with an unreadable dataset.yaml, or in an empty dataset."""
    if latest != "empty":
        parent = _non_managed_latest(workflow, metadata=latest != "no-metadata")
        if latest == "invalid-metadata":
            _invalidate_metadata(parent)
    seen = None if latest == "empty" else "external"
    fetched, output = _transform(workflow, tmp_path)
    prepared = tmp_path / "prepared"
    main(
        [
            "dataset",
            "prepare",
            "combined",
            str(output),
            "--source",
            str(fetched),
            "--output-dir",
            str(prepared),
            "--first",
            "--config",
            str(workflow.personal),
            "--global-config",
            str(workflow.shared),
        ]
    )
    record = json.loads((prepared / "preparation.json").read_bytes())
    # The latest version seen by fetch stays bound for freshness; it is never linked as a parent.
    assert (record["first"], record["parent_id"]) == (True, seen)
    first_warnings = [message for message in capture_logs if "--first" in message]
    if latest in {"no-metadata", "invalid-metadata"}:
        assert len(first_warnings) == 1
        assert "external" in first_warnings[0]
    else:
        assert first_warnings == []

    published = api.publish_dataset(prepared, **workflow.options)

    assert workflow.clearml.parents == [None]
    remote = workflow.clearml.root / published.dataset_id
    tasks = yaml.safe_load((remote / "tasks.yaml").read_text())
    assert tasks["managed"]["parent_id"] is None
    assert set(yaml.safe_load((remote / "dataset.yaml").read_text())["classes"]) == {"cat"}
    rows = pd.read_csv(remote / "dataset.csv", keep_default_na=False)
    transformed = pd.read_csv(output, keep_default_na=False)
    by_name = dict(zip(transformed["image_name"], transformed["split"], strict=True))
    assert all(by_name[name] == split for name, split in zip(rows["image_name"], rows["split"], strict=True))
    child = _prepare(workflow, tmp_path / "child")
    assert json.loads((child / "preparation.json").read_bytes())["parent_id"] == published.dataset_id


def test_unreadable_latest_version_still_stops_prepare_without_first(
    workflow: Workflow, tmp_path: Path, capture_logs: list[str]
) -> None:
    """Fetch warns and fetches every source again; only --first may start over such a version."""
    _invalidate_metadata(_non_managed_latest(workflow))
    with pytest.raises(Cveta2Error, match=r"Invalid dataset metadata .*unknown_key"):
        _prepare(workflow, tmp_path)
    assert any("external" in message and "dataset.yaml" in message for message in capture_logs)
    assert sorted(workflow.cvat.annotation_reads) == [101, 102]
    assert not (tmp_path / "prepared").exists()


def test_first_takes_no_split_from_a_latest_version_that_lost_its_managed_metadata(
    workflow: Workflow, tmp_path: Path
) -> None:
    """Its tasks.yaml still carries a managed snapshot with assignments; none of them may come back."""
    published = api.publish_dataset(_prepare(workflow, tmp_path / "one"), **workflow.options)
    remote = workflow.clearml.root / published.dataset_id
    old = pd.read_csv(remote / "dataset.csv", keep_default_na=False)
    old_split = dict(zip(old["image_name"], old["split"], strict=False))
    metadata = yaml.safe_load((remote / "dataset.yaml").read_text())
    metadata.pop("managed")
    (remote / "dataset.yaml").write_text(yaml.safe_dump(metadata))
    assert yaml.safe_load((remote / "tasks.yaml").read_text())["managed"]["assignments"]
    workflow.cvat.annotation_reads.clear()

    fetched = tmp_path / "two" / "fetched"
    api.fetch_dataset("combined", output_dir=fetched, **workflow.options)
    assert LocalSourceFiles().read_snapshot(fetched).assignments == {}
    assert sorted(workflow.cvat.annotation_reads) == [101, 102]
    frame = pd.read_csv(fetched / "dataset.csv", keep_default_na=False)
    frame["image_path"] = frame["image_name"].map(lambda name: str(workflow.images / name))
    rotate = {"train": "val", "val": "test", "test": "train"}
    frame = frame.assign(split=frame["image_name"].map(lambda name: rotate[old_split[name]]))
    output = tmp_path / "two" / "transformed.csv"
    frame.to_csv(output, index=False)

    summary = api.prepare_managed_dataset(
        "combined", output, source=fetched, output_dir=tmp_path / "two" / "prepared", first=True, **workflow.options
    )

    assert summary.ready, summary.report
    assert summary.report["split_replacements"] == 0
    result = pd.read_csv(summary.directory / "dataset.csv", keep_default_na=False)
    assert all(
        split == rotate[old_split[name]] for name, split in zip(result["image_name"], result["split"], strict=True)
    )


def test_first_reads_no_tasks_yaml_from_a_non_managed_latest_version(workflow: Workflow, tmp_path: Path) -> None:
    """Fetch must not parse anything of a version it may not reuse, so a broken tasks.yaml cannot block --first."""
    parent = _non_managed_latest(workflow)
    (parent / "tasks.yaml").write_text("managed: {format_version: 1, unexpected: [}\n")

    prepared = _prepare(workflow, tmp_path, first=True)

    record = json.loads((prepared / "preparation.json").read_bytes())
    assert (record["first"], record["parent_id"]) == (True, "external")
    assert sorted(workflow.cvat.annotation_reads) == [101, 102]


def test_first_is_refused_once_a_managed_lineage_exists(workflow: Workflow, tmp_path: Path) -> None:
    api.publish_dataset(_prepare(workflow, tmp_path / "first"), **workflow.options)
    with pytest.raises(
        ManagedError, match="Managed lineage already exists at parent version-1; prepare without --first"
    ):
        _prepare(workflow, tmp_path / "again", first=True)
    assert not (tmp_path / "again" / "prepared").exists()


def test_managed_version_published_after_a_first_preparation_blocks_it(workflow: Workflow, tmp_path: Path) -> None:
    _non_managed_latest(workflow)
    one = _prepare(workflow, tmp_path / "one", first=True)
    two = _prepare(workflow, tmp_path / "two", first=True)
    assert api.publish_dataset(one, **workflow.options).dataset_id == "version-1"
    with pytest.raises(ManagedError, match="Latest ClearML parent changed; fetch and prepare again"):
        api.publish_dataset(two, **workflow.options)
    assert workflow.clearml.publications == ["version-1"]


def test_show_reports_a_non_managed_latest_version_without_reading_it(workflow: Workflow) -> None:
    parent = _non_managed_latest(workflow)
    (parent / "dataset.yaml").write_text("not: [valid metadata")
    shown = api.show_dataset("combined", **workflow.options)
    assert (shown["parent_id"], shown["parent_version"]) == ("external", "0")


def test_parent_that_lost_its_metadata_blocks_publication(workflow: Workflow, tmp_path: Path) -> None:
    first = api.publish_dataset(_prepare(workflow, tmp_path / "first"), **workflow.options)
    prepared = _prepare(workflow, tmp_path / "child")
    (workflow.clearml.root / first.dataset_id / "dataset.yaml").unlink()
    with pytest.raises(ManagedError, match=r"dataset\.yaml"):
        api.publish_dataset(prepared, **workflow.options)
    assert workflow.clearml.publications == ["version-1"]


def test_parent_api_url_with_a_slash_in_its_password_stops_prepare(workflow: Workflow, tmp_path: Path) -> None:
    first = api.publish_dataset(_prepare(workflow, tmp_path / "first"), **workflow.options)
    metadata_path = workflow.clearml.root / first.dataset_id / "dataset.yaml"
    metadata = yaml.safe_load(metadata_path.read_text())
    metadata["api_url"] = "https://key:se/cret@classes.example/api"
    metadata_path.write_text(yaml.safe_dump(metadata))
    with pytest.raises(Cveta2Error, match=r"Invalid dataset metadata .*api_url must not contain credentials") as caught:
        _prepare(workflow, tmp_path / "child")
    assert "se/cret" not in str(caught.value)
    assert workflow.clearml.publications == ["version-1"]


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


def test_unexplained_task_change_skips_a_pending_delivery(workflow: Workflow, tmp_path: Path) -> None:
    prepared = _prepare(workflow, tmp_path, bad=True, bad_frames=("0", "1"))
    workflow.cvat.advance_issue_timestamp = True
    workflow.cvat.fail_frames = {0}
    api.report_dataset_errors(prepared, **workflow.options)
    workflow.cvat.fail_frames.clear()
    workflow.cvat.tasks[101] = workflow.cvat.tasks[101].model_copy(update={"updated_date": "edited"})
    outcome = api.report_dataset_errors(prepared, **workflow.options)
    # Both findings are on task 101, so both are skipped, the delivered one too.
    assert (outcome.created, outcome.skipped, outcome.failed) == (0, 2, [])
    assert sorted(issue.frame for issue in workflow.cvat.issues[101]) == [1]
    assert api.publish_dataset(prepared, **workflow.options).dataset_id == "version-1"
    assert sorted(issue.frame for issue in workflow.cvat.issues[101]) == [1]


def test_pending_receipt_of_a_deleted_task_does_not_stop_the_command(
    workflow: Workflow, tmp_path: Path, capture_logs: list[str]
) -> None:
    prepared = _prepare(workflow, tmp_path, bad=True)
    workflow.cvat.fail_issues = True
    assert len(api.report_dataset_errors(prepared, **workflow.options).failed) == 1
    del workflow.cvat.tasks[101]

    outcome = api.report_dataset_errors(prepared, **workflow.options)

    assert (outcome.created, outcome.skipped, outcome.failed) == (0, 1, [])
    assert any(line.startswith("main: задача 101 недоступна в CVAT (") for line in capture_logs)
    assert "main: задача 101 удалена. Датасет собирается из выгруженных данных." in capture_logs
    (ledger,) = (workflow.personal.parent / "managed-feedback").iterdir()
    receipts = json.loads(ledger.read_text())["receipts"]
    assert [receipt["delivered"] for receipt in receipts.values()] == [False]
    assert api.publish_dataset(prepared, **workflow.options).dataset_id == "version-1"


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
    _hand_splits(transformed).to_csv(output, index=False)
    return fetched, output


@pytest.mark.parametrize("change_labels", [False, True])
def test_feedback_from_an_inspection_does_not_stale_a_sibling_preparation(
    workflow: Workflow, tmp_path: Path, *, change_labels: bool
) -> None:
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
    if change_labels:
        label = workflow.cvat.labels[12][0]
        attribute = label.attributes[0].model_copy(update={"default_value": "poor"})
        workflow.cvat.labels[12][0] = label.model_copy(update={"attributes": [attribute]})
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


@pytest.mark.parametrize("damage", ["missing-registry", "missing-labels"])
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
        else:
            snapshot["sources"][0].pop("labels")
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


def test_overlap_decision_added_after_a_failed_prepare_uses_the_same_fetch(workflow: Workflow, tmp_path: Path) -> None:
    fetched = tmp_path / "fetched"
    api.fetch_dataset("combined", output_dir=fetched, **workflow.options)
    transformed = pd.read_csv(fetched / "dataset.csv", keep_default_na=False)
    transformed["image_path"] = transformed["image_name"].map(lambda name: str(workflow.images / name))
    # The imported CSV repeats an image that the main CVAT source also annotates.
    duplicate = transformed["source_id"].eq("imported") & transformed["image_name"].eq("external-0.png")
    transformed.loc[duplicate, ["image_name", "image_path"]] = ["task101-0.png", str(workflow.images / "task101-0.png")]
    output = tmp_path / "transformed.csv"
    _hand_splits(transformed).to_csv(output, index=False)
    with pytest.raises(ManagedError, match="Image overlap requires source selection"):
        api.prepare_managed_dataset("combined", output, source=fetched, output_dir=tmp_path / "x", **workflow.options)
    digest = hashlib.sha256((workflow.images / "task101-0.png").read_bytes()).hexdigest()
    _edit_shared(
        workflow,
        lambda shared: shared["datasets"]["combined"].update(
            overlaps={digest: {"source": "main", "members": ["imported", "main"]}}
        ),
    )
    workflow.cvat.annotation_reads.clear()

    prepared = api.prepare_managed_dataset(
        "combined", output, source=fetched, output_dir=tmp_path / "prepared", **workflow.options
    )

    assert prepared.ready, prepared.report
    assert workflow.cvat.annotation_reads == []
    assert api.publish_dataset(prepared.directory, **workflow.options).dataset_id == "version-1"


@pytest.mark.parametrize("split", ["absent", "empty"])
def test_missing_splits_make_preparation_not_ready_and_create_no_cvat_issues(
    workflow: Workflow, tmp_path: Path, split: str
) -> None:
    fetched = tmp_path / "fetched"
    api.fetch_dataset("combined", output_dir=fetched, **workflow.options)
    transformed = pd.read_csv(fetched / "dataset.csv", keep_default_na=False)
    transformed["image_path"] = transformed["image_name"].map(lambda name: str(workflow.images / name))
    transformed = transformed.drop(columns="split") if split == "absent" else transformed.assign(split="")
    output = tmp_path / "transformed.csv"
    transformed.to_csv(output, index=False)
    prepared = api.prepare_managed_dataset(
        "combined", output, source=fetched, output_dir=tmp_path / "prepared", clean=True, **workflow.options
    )
    assert not prepared.ready
    assert api.report_dataset_errors(prepared.directory, **workflow.options).created == 0
    assert workflow.cvat.issues == {101: [], 102: []}


def _ignore_bookkeeping(shared: dict[str, Any]) -> None:
    shared["projects"]["main"]["ignore"][0].update(name="renamed", description="edited", silent=True)


def _reorder_sources(shared: dict[str, Any]) -> None:
    shared["datasets"]["combined"]["sources"].reverse()


@pytest.mark.parametrize("edit", [_ignore_bookkeeping, _reorder_sources], ids=["ignored-description", "source-order"])
def test_edits_that_change_no_data_keep_fetch_preparation_and_reuse(
    workflow: Workflow, tmp_path: Path, edit: Callable[[dict[str, Any]], None]
) -> None:
    _edit_shared(workflow, lambda shared: shared["projects"]["main"].update(ignore=[{"id": 999, "description": "x"}]))
    prepared = _prepare(workflow, tmp_path)
    _edit_shared(workflow, edit)

    again = api.prepare_managed_dataset(
        "combined",
        tmp_path / "transformed.csv",
        source=tmp_path / "fetched",
        output_dir=tmp_path / "again",
        **workflow.options,
    )
    published = api.publish_dataset(prepared, **workflow.options)
    workflow.cvat.annotation_reads.clear()
    refetched = api.fetch_dataset("combined", output_dir=tmp_path / "refetched", **workflow.options)

    assert again.ready
    assert published.dataset_id == "version-1"
    assert workflow.cvat.annotation_reads == []
    assert sorted(task for source in refetched["sources"] for task in source["reused"]) == [101, 102]


def _move_source(shared: dict[str, Any]) -> None:
    shared["datasets"]["combined"]["sources"][2]["uri"] = "s3://annotations/moved.csv"


def _ignore_task(shared: dict[str, Any]) -> None:
    shared["projects"]["other"]["ignore"] = [{"id": 999}]


@pytest.mark.parametrize("edit", [_move_source, _ignore_task], ids=["source-uri", "ignored-id"])
def test_source_edits_after_preparation_warn_and_publish(
    workflow: Workflow, tmp_path: Path, capture_logs: list[str], edit: Callable[[dict[str, Any]], None]
) -> None:
    prepared = _prepare(workflow, tmp_path)
    _edit_shared(workflow, edit)
    assert api.publish_dataset(prepared, **workflow.options).dataset_id == "version-1"
    if edit is _move_source:
        assert (
            "Источник отличается от выгруженного: imported: uri s3://annotations/imported.csv → "
            "s3://annotations/moved.csv. Датасет собирается из выгруженных данных."
        ) in capture_logs


def _repoint_main(shared: dict[str, Any]) -> None:
    shared["projects"]["third"] = {"id": 40}
    shared["datasets"]["combined"]["sources"][0]["project"] = "third"


def _drop_main(shared: dict[str, Any]) -> None:
    shared["datasets"]["combined"]["sources"].pop(0)


def _renumber_main(shared: dict[str, Any]) -> None:
    shared["projects"]["main"]["id"] = 13


@pytest.mark.parametrize(
    ("edit", "warnings"),
    [
        (_repoint_main, ["Источник отличается от выгруженного: main: project_id 12 → 40"]),
        (_drop_main, ["Источник отличается от выгруженного: main: только в снимке"]),
        (
            _renumber_main,
            [
                "Источник отличается от выгруженного: main: project_id 12 → 13",
                "main: проект 12 больше не описан в конфигурации, задачи не проверены",
            ],
        ),
    ],
    ids=["another-project", "dropped-source", "unconfigured-project"],
)
def test_findings_of_a_source_that_differs_from_the_definition_are_skipped(
    workflow: Workflow,
    tmp_path: Path,
    capture_logs: list[str],
    edit: Callable[[dict[str, Any]], None],
    warnings: list[str],
) -> None:
    """The command goes on from the fetched sources and sends no finding of the changed source."""
    prepared = _prepare(workflow, tmp_path, bad=True)
    _edit_shared(workflow, edit)

    outcome = api.report_dataset_errors(prepared, **workflow.options)

    assert (outcome.created, outcome.skipped, outcome.failed) == (0, 1, [])
    assert workflow.cvat.issues[101] == []
    for line in warnings:
        assert f"{line}. Датасет собирается из выгруженных данных." in capture_logs
    assert api.publish_dataset(prepared, **workflow.options).dataset_id == "version-1"
    assert workflow.cvat.issues[101] == []


def test_task_ignored_after_fetch_is_reported_as_ignored_and_its_findings_skipped(
    workflow: Workflow, tmp_path: Path, capture_logs: list[str]
) -> None:
    prepared = _prepare(workflow, tmp_path, bad=True)
    _edit_shared(workflow, lambda shared: shared["projects"]["main"].update(ignore=[{"id": 101}]))

    outcome = api.report_dataset_errors(prepared, **workflow.options)

    assert (outcome.created, outcome.skipped) == (0, 1)
    assert "main: задача 101 теперь игнорируется. Датасет собирается из выгруженных данных." in capture_logs
    assert not any("удалена" in line for line in capture_logs)
    assert workflow.cvat.issues[101] == []


def test_server_wide_access_error_still_stops_the_command(
    workflow: Workflow, tmp_path: Path, capture_logs: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pending receipt's task is unavailable, but so is the whole project: freshness cannot be judged."""
    prepared = _prepare(workflow, tmp_path, bad=True)
    workflow.cvat.fail_issues = True
    assert len(api.report_dataset_errors(prepared, **workflow.options).failed) == 1
    workflow.cvat.fail_issues = False

    def forbidden(*_args: object) -> None:
        raise CvatApiError("Forbidden", status_code=403)

    for method in ("get_task", "get_project_tasks", "get_project_labels"):
        monkeypatch.setattr(workflow.cvat, method, forbidden)

    with pytest.raises(CvatApiError, match="Forbidden"):
        api.report_dataset_errors(prepared, **workflow.options)
    # The pending receipt's task was judged unavailable first; the project listing then stopped the command.
    assert any(line.startswith("main: задача 101 недоступна в CVAT (") for line in capture_logs)
    with pytest.raises(CvatApiError, match="Forbidden"):
        api.publish_dataset(prepared, **workflow.options)
    assert workflow.cvat.issues[101] == []
    assert workflow.clearml.publications == []


def _prepare_s3_only(workflow: Workflow, tmp_path: Path) -> Path:
    """Fetch and prepare a dataset whose only source is the S3 CSV: no CVAT task IDs."""
    _edit_shared(
        workflow,
        lambda shared: shared["datasets"]["combined"].update(sources=[shared["datasets"]["combined"]["sources"][2]]),
    )
    fetched = tmp_path / "fetched"
    assert api.fetch_dataset("combined", output_dir=fetched, **workflow.options)["rows"] == 6
    transformed = pd.read_csv(fetched / "dataset.csv", keep_default_na=False)
    transformed["image_path"] = transformed["image_name"].map(lambda name: str(workflow.images / name))
    _hand_splits(transformed).to_csv(tmp_path / "transformed.csv", index=False)
    summary = api.prepare_managed_dataset(
        "combined", tmp_path / "transformed.csv", source=fetched, output_dir=tmp_path / "prepared", **workflow.options
    )
    assert summary.ready, summary.report
    return summary.directory


@pytest.mark.parametrize(
    ("cvat", "s3_only", "message"),
    [
        (
            {"host": "https://cvat.moved.example"},
            False,
            (
                "CVAT server differs from the one fetched: fetched https://cvat.example (organization none), "
                "configured https://cvat.moved.example (organization none); fetch the managed dataset again"
            ),
        ),
        (
            {"host": "https://cvat.example", "organization": "team"},
            False,
            (
                "CVAT server differs from the one fetched: fetched https://cvat.example (organization none), "
                "configured https://cvat.example (organization team); fetch the managed dataset again"
            ),
        ),
        ({"host": "https://cvat.moved.example"}, True, None),
    ],
    ids=["host", "organization", "s3-only"],
)
def test_another_cvat_server_after_fetch_stops_feedback_and_publication(
    workflow: Workflow, tmp_path: Path, cvat: dict[str, str], *, s3_only: bool, message: str | None
) -> None:
    """Only recorded CVAT task IDs tie a preparation to a server; an S3-only dataset has none."""
    prepared = _prepare_s3_only(workflow, tmp_path) if s3_only else _prepare(workflow, tmp_path, bad=True)
    _edit_shared(workflow, lambda shared: shared.update(cvat=cvat))

    if message is None:
        assert api.report_dataset_errors(prepared, **workflow.options).failed == []
        assert api.publish_dataset(prepared, **workflow.options).dataset_id == "version-1"
        return
    with pytest.raises(ManagedError, match=re.escape(message)):
        api.report_dataset_errors(prepared, **workflow.options)
    with pytest.raises(ManagedError, match=re.escape(message)):
        api.publish_dataset(prepared, **workflow.options)
    assert workflow.cvat.issues == {101: [], 102: []}
    assert workflow.clearml.publications == []


def test_same_cvat_server_written_differently_still_publishes(workflow: Workflow, tmp_path: Path) -> None:
    """The comparison uses the normalised identity: a trailing slash and an empty organization change nothing."""
    prepared = _prepare(workflow, tmp_path, bad=True)
    _edit_shared(workflow, lambda shared: shared.update(cvat={"host": "https://cvat.example/", "organization": ""}))

    assert api.report_dataset_errors(prepared, **workflow.options).created == 1
    assert api.publish_dataset(prepared, **workflow.options).dataset_id == "version-1"


def test_snapshot_without_a_cvat_server_cannot_be_prepared(workflow: Workflow, tmp_path: Path) -> None:
    fetched, transformed = _transform(workflow, tmp_path)
    snapshot_path = fetched / "source-snapshot.yaml"
    snapshot = yaml.safe_load(snapshot_path.read_text())
    assert snapshot.pop("cvat") == {"host": "https://cvat.example", "organization": None}
    snapshot_path.write_text(yaml.safe_dump(snapshot, allow_unicode=True))

    with pytest.raises(ManagedError, match="Source snapshot lacks the CVAT server identity; fetch and prepare again"):
        api.prepare_managed_dataset(
            "combined", transformed, source=fetched, output_dir=tmp_path / "prepared", **workflow.options
        )
    assert not (tmp_path / "prepared").exists()


def _change_registry(monkeypatch: pytest.MonkeyPatch, *, name: str = "cat", threshold: float = 0.5) -> None:
    """Serve the fixture's single class (number 7) with another name or threshold."""
    changed = [
        ApiClass(
            id=90,
            number=7,
            name=name,
            techClass=False,
            isPeriodical=False,
            isCritical=False,
            threshold=threshold,
        )
    ]
    monkeypatch.setattr(HttpClassApi, "fetch", lambda _self, _url: changed)


def test_registry_rename_after_preparation_stops_publication(
    workflow: Workflow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = _prepare(workflow, tmp_path)
    _change_registry(monkeypatch, name="kitty")
    assert api.report_dataset_errors(prepared, **workflow.options).failed == []
    with pytest.raises(ManagedError, match="differ from the class registry: cat, kitty; prepare again"):
        api.publish_dataset(prepared, **workflow.options)
    assert workflow.clearml.publications == []


def test_registry_threshold_change_after_preparation_publishes(
    workflow: Workflow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = _prepare(workflow, tmp_path)
    _change_registry(monkeypatch, threshold=0.9)
    assert api.publish_dataset(prepared, **workflow.options).dataset_id == "version-1"


def _other_definition_hash(_shared: dict[str, Any], parent: Path) -> None:
    tasks = yaml.safe_load((parent / "tasks.yaml").read_text())
    tasks["managed"]["definition_hash"] = hashlib.sha256(b"whole definition").hexdigest()
    (parent / "tasks.yaml").write_text(yaml.safe_dump(tasks))


def _unknown_identity(shared: dict[str, Any], parent: Path) -> None:
    _other_definition_hash(shared, parent)
    metadata = yaml.safe_load((parent / "dataset.yaml").read_text())
    metadata.pop("managed")
    (parent / "dataset.yaml").write_text(yaml.safe_dump(metadata))


def _moved_server(shared: dict[str, Any], _parent: Path) -> None:
    shared["cvat"]["host"] = "https://cvat.moved.example"


@pytest.mark.parametrize(
    ("edit", "reads"),
    [
        (_other_definition_hash, []),
        (lambda shared, _parent: _ignore_task(shared), []),
        (_moved_server, [101, 102]),
    ],
    ids=["hash-mismatch", "ignored-id", "host"],
)
def test_published_server_identity_decides_whether_fetch_resets_every_source(
    workflow: Workflow, tmp_path: Path, edit: Callable[[dict[str, Any], Path], None], reads: list[int]
) -> None:
    published = api.publish_dataset(_prepare(workflow, tmp_path / "first"), **workflow.options)
    _edit_shared(workflow, lambda shared: edit(shared, workflow.clearml.root / published.dataset_id))
    workflow.cvat.annotation_reads.clear()

    second = _prepare(workflow, tmp_path / "second")

    assert sorted(workflow.cvat.annotation_reads) == reads
    assert api.publish_dataset(second, **workflow.options).dataset_id == "version-2"
    assert workflow.clearml.parents == [None, "version-1"]
    workflow.cvat.annotation_reads.clear()
    api.fetch_dataset("combined", output_dir=tmp_path / "third", **workflow.options)
    assert workflow.cvat.annotation_reads == []


def test_parent_without_managed_identity_resets_every_source_and_is_refused_by_prepare(
    workflow: Workflow, tmp_path: Path
) -> None:
    """Without the parent's CVAT identity fetch trusts none of its tasks; prepare needs a managed parent."""
    published = api.publish_dataset(_prepare(workflow, tmp_path / "first"), **workflow.options)
    _edit_shared(workflow, lambda shared: _unknown_identity(shared, workflow.clearml.root / published.dataset_id))
    workflow.cvat.annotation_reads.clear()

    with pytest.raises(ManagedError, match="Parent version-1 is not a managed dataset version"):
        _prepare(workflow, tmp_path / "second")

    assert sorted(workflow.cvat.annotation_reads) == [101, 102]


def test_show_dataset_reports_the_definition_and_rejects_unknown_names(workflow: Workflow) -> None:
    shown = api.show_dataset("combined", **workflow.options)
    assert shown["definition"]["clearml"] == {"project": "CV/combined", "dataset": "annotations"}
    assert (shown["parent_id"], shown["parent_version"]) == (None, None)
    with pytest.raises(ManagedError, match="Unknown managed dataset: missing"):
        api.show_dataset("missing", **workflow.options)


def _publish_then_prepare_child(workflow: Workflow, tmp_path: Path) -> Path:
    """Publish version-1, then prepare its child from a fetch that names it as parent."""
    api.publish_dataset(_prepare(workflow, tmp_path / "first"), **workflow.options)
    return _prepare(workflow, tmp_path / "child")


def test_child_takes_the_published_split_of_an_image_its_managed_parent_published(
    workflow: Workflow, tmp_path: Path
) -> None:
    first = api.publish_dataset(_prepare(workflow, tmp_path / "first"), **workflow.options)
    metadata_path = workflow.clearml.root / first.dataset_id / "dataset.yaml"
    metadata = yaml.safe_load(metadata_path.read_text())
    # Move one published image to another split, so it differs from the child's hand split.
    moved = next(iter(metadata["managed"]["assignments"]))
    target = "val" if metadata["managed"]["assignments"][moved] == "test" else "test"
    metadata["managed"]["assignments"][moved] = target
    metadata_path.write_text(yaml.safe_dump(metadata))
    child = _prepare(workflow, tmp_path / "child")
    transformed = pd.read_csv(tmp_path / "child" / "transformed.csv", keep_default_na=False)
    rows = pd.read_csv(child / "dataset.csv", keep_default_na=False)
    hashes = rows["image_path"].map(lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest())
    names = set(rows.loc[hashes.eq(moved), "image_name"])
    assert names
    # The child's CSV carried another split, so the published value is what propagated.
    assert target not in set(transformed.loc[transformed["image_name"].isin(names), "split"])
    assert set(rows.loc[hashes.eq(moved), "split"]) == {target}


def test_destination_with_another_parent_needs_a_new_fetch(workflow: Workflow, tmp_path: Path) -> None:
    prepared = _publish_then_prepare_child(workflow, tmp_path)
    _edit_shared(
        workflow,
        lambda shared: shared["datasets"]["combined"].update(clearml={"project": "CV/moved", "dataset": "annotations"}),
    )

    with pytest.raises(ManagedError, match="Latest ClearML parent changed"):
        api.publish_dataset(prepared, **workflow.options)
    with pytest.raises(ManagedError, match="Source parent changed; fetch the managed dataset again"):
        api.prepare_managed_dataset(
            "combined",
            tmp_path / "child" / "transformed.csv",
            source=tmp_path / "child" / "fetched",
            output_dir=tmp_path / "again",
            **workflow.options,
        )
    assert workflow.clearml.publications == ["version-1"]
