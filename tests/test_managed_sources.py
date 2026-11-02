"""Managed source snapshots reconstruct complete candidates without stale rows."""

import hashlib
import io
from pathlib import Path
from unittest.mock import Mock

import pandas as pd
import pytest
import yaml

from cveta2.adapters.clearml.managed_sources import ClearMLSources
from cveta2.adapters.cvat.managed_sources import CvatSources
from cveta2.adapters.files.managed_sources import LocalSourceFiles
from cveta2.adapters.files.verification import read_csv_bytes
from cveta2.adapters.s3.managed_sources import S3CsvSources
from cveta2.application.client.assembly import task_to_records
from cveta2.application.ports.dtos import RawAnnotations, RawDataMeta, RawFrame, RawJob
from cveta2.application.ports.managed_sources import ProjectState, S3Object
from cveta2.application.use_cases.managed_sources import (
    fetch_sources,
)
from cveta2.domain.errors import Cveta2Error
from cveta2.domain.managed.models import (
    ClearMLDestination,
    CvatIdentity,
    DatasetDefinition,
    ManagedError,
    ManagedSnapshot,
    ProjectConfig,
    ProjectDefinition,
    SourceDefinition,
    TaskSnapshot,
    definition_fingerprint,
)
from cveta2.domain.models import CSV_COLUMNS, LabelInfo, TaskInfo


def _task(  # noqa: PLR0913
    task_id: int,
    image: str = "image.jpg",
    *,
    date: str = "2026-11-02",
    completed: bool = True,
    empty: bool = False,
    deleted: bool = False,
) -> TaskSnapshot:
    record: dict[str, str | int | bool] = {
        "task_id": task_id,
        "task_name": f"Task {task_id}",
        "image_name": image,
        "image_path": f"/images/{image}",
        "image_width": 100,
        "image_height": 100,
        "instance_shape": "deleted" if deleted else "box",
        "instance_label": "cat",
        "bbox_x_tl": 10,
        "bbox_y_tl": 10,
        "bbox_x_br": 40,
        "bbox_y_br": 40,
        "frame_id": 0,
        "task_completed": completed,
        "task_updated_date": date,
        "job_stage": "acceptance" if completed else "annotation",
        "job_state": "completed" if completed else "in progress",
    }
    blank = pd.DataFrame(columns=list(CSV_COLUMNS)).to_csv(index=False)
    tables = dict.fromkeys(
        ("dataset.csv", "obsolete.csv", "in_progress.csv", "deleted.csv"), blank
    )
    if not empty:
        tables["deleted.csv" if deleted else "dataset.csv"] = pd.DataFrame(
            [record], columns=list(CSV_COLUMNS)
        ).to_csv(index=False)
    return TaskSnapshot(
        id=task_id, updated_date=date, completed=completed, tables=tables
    )


class _Cvat:
    def __init__(self, projects: dict[int, list[TaskSnapshot]]) -> None:
        self.projects = projects
        self.labels = dict.fromkeys(projects, "labels-v1")
        self.downloads: list[tuple[int, int]] = []

    def inspect_project(self, project_id: int) -> ProjectState:
        return ProjectState(
            [
                task.model_copy(update={"tables": {}})
                for task in self.projects[project_id]
            ],
            self.labels[project_id],
        )

    def read_task(self, project_id: int, task: TaskSnapshot) -> TaskSnapshot:
        self.downloads.append((project_id, task.id))
        return next(item for item in self.projects[project_id] if item.id == task.id)


class _S3:
    def __init__(self, content: bytes | None = None) -> None:
        self.content = content or (
            b"image_name,image_path,instance_label,bbox_x_tl,bbox_y_tl,bbox_x_br,bbox_y_br\n"
            b"extra.jpg,/images/extra.jpg,cat,10,10,40,40\n"
        )
        self.reads = 0

    def read_object(self, _uri: str) -> S3Object:
        self.reads += 1
        return S3Object(
            self.content, hashlib.sha256(self.content).hexdigest(), "opaque-etag", "v1"
        )


def _config(*, supplemental: bool = False) -> tuple[ProjectConfig, DatasetDefinition]:
    sources = [SourceDefinition(name="main", type="cvat", project="p")]
    projects = {"p": ProjectDefinition(id=12)}
    if supplemental:
        sources += [
            SourceDefinition(name="other", type="cvat", project="q"),
            SourceDefinition(name="extra", type="s3-csv", uri="s3://bucket/extra.csv"),
        ]
        projects["q"] = ProjectDefinition(id=27)
    definition = DatasetDefinition(
        sources=sources,
        clearml=ClearMLDestination(project="CV/datasets", dataset="combined"),
        api_url="https://classes.example.test/classes",
    )
    return ProjectConfig(
        cvat=CvatIdentity(host="https://cvat.example.test"),
        projects=projects,
        datasets={"combined": definition},
    ), definition


def _fetch(  # noqa: PLR0913
    config: ProjectConfig,
    definition: DatasetDefinition,
    reader: _Cvat,
    *,
    previous: ManagedSnapshot | None = None,
    s3: _S3 | None = None,
    registry_hash: str = "registry-v1",
    refresh: bool = False,
) -> tuple[ManagedSnapshot, pd.DataFrame]:
    return fetch_sources(
        config,
        definition,
        cvat=reader,
        s3=s3 or _S3(),
        files=LocalSourceFiles(),
        registry_hash=registry_hash,
        previous=previous,
        refresh=refresh,
    )


def test_reuse_per_task_and_complete_mixed_source_provenance() -> None:
    config, definition = _config(supplemental=True)
    reader = _Cvat({12: [_task(1)], 27: [_task(2)]})
    s3 = _S3()
    first, frame = _fetch(config, definition, reader, s3=s3)
    assert set(frame["source_id"]) == {"main", "other", "extra"}
    assert len(frame) == 3  # same basename in different projects does not supersede
    assert frame.loc[frame.source_id.eq("extra"), "source_task_id"].tolist() == [""]
    assert frame.loc[frame.source_id.eq("main"), "source_project_id"].tolist() == ["12"]
    assert first.definition_hash == definition_fingerprint(config, "combined")
    reader.downloads.clear()
    second, repeated = _fetch(config, definition, reader, previous=first, s3=s3)
    assert reader.downloads == []
    assert second.sources[0].reused == [1]
    pd.testing.assert_frame_equal(frame, repeated)
    assert s3.reads == 2


@pytest.mark.parametrize("reason", ["metadata", "labels", "registry", "force"])
def test_changes_invalidate_reuse(reason: str) -> None:
    config, definition = _config()
    reader = _Cvat({12: [_task(1)]})
    first, _ = _fetch(config, definition, reader)
    reader.downloads.clear()
    if reason == "metadata":
        reader.projects[12] = [_task(1, date="later")]
    if reason == "labels":
        reader.labels[12] = "labels-v2"
    _fetch(
        config,
        definition,
        reader,
        previous=first,
        registry_hash="registry-v2" if reason == "registry" else "registry-v1",
        refresh=reason == "force",
    )
    assert reader.downloads == [(12, 1)]


def test_original_superseded_rows_survive_and_deleted_tasks_are_removed() -> None:
    config, definition = _config()
    reader = _Cvat({12: [_task(1), _task(2)]})
    first, frame = _fetch(config, definition, reader)
    assert frame["source_task_id"].tolist() == ["2"]
    assert "1" in first.sources[0].tasks
    reader.projects[12] = [_task(1)]
    reader.downloads.clear()
    second, resurrected = _fetch(config, definition, reader, previous=first)
    assert reader.downloads == []
    assert set(second.sources[0].tasks) == {"1"}
    assert resurrected["source_task_id"].tolist() == ["1"]


def test_reopened_tasks_leave_training_and_empty_task_evidence_is_reusable() -> None:
    config, definition = _config()
    reader = _Cvat({12: [_task(1), _task(2, empty=True)]})
    first, _ = _fetch(config, definition, reader)
    reader.projects[12] = [
        _task(1, completed=False, date="reopened"),
        _task(2, empty=True),
    ]
    reader.downloads.clear()
    second, frame = _fetch(config, definition, reader, previous=first)
    assert frame.empty
    assert reader.downloads == [(12, 1)]
    assert second.sources[0].reused == [2]
    assert not second.sources[0].tasks["1"].completed
    assert (
        len(read_csv_bytes(second.sources[0].tables["in_progress.csv"].encode())) == 1
    )


def test_deletion_wins_same_task_ties_and_is_source_local() -> None:
    config, definition = _config()
    annotation = _task(1)
    deletion = _task(1, deleted=True)
    tied = annotation.model_copy(
        update={
            "tables": {
                **annotation.tables,
                "deleted.csv": deletion.tables["deleted.csv"],
            }
        }
    )
    snapshot, frame = _fetch(config, definition, _Cvat({12: [tied]}))
    assert frame.empty
    assert "image.jpg" in snapshot.sources[0].tables["obsolete.csv"]
    assert "image.jpg" in snapshot.sources[0].tables["deleted.csv"]


def test_s3_changes_replace_source_and_reject_malformed_or_reserved_csv() -> None:
    config, definition = _config(supplemental=True)
    reader = _Cvat({12: [], 27: []})
    s3 = _S3()
    first, _ = _fetch(config, definition, reader, s3=s3)
    s3.content = s3.content.replace(b"extra.jpg", b"replacement.jpg")
    second, frame = _fetch(config, definition, reader, previous=first, s3=s3)
    assert frame["image_name"].tolist() == ["replacement.jpg"]
    assert second.sources[-1].content_hash != first.sources[-1].content_hash
    s3.content = b"image_name\ninvalid.jpg\n"
    with pytest.raises(ManagedError, match="required columns"):
        _fetch(config, definition, reader, s3=s3)
    s3.content = b"source_id," + _S3().content.replace(
        b"\nextra.jpg,", b"\nforged,extra.jpg,"
    )
    with pytest.raises(ManagedError, match="reserved"):
        _fetch(config, definition, reader, s3=s3)


def test_source_failure_does_not_export_partial_success(tmp_path: Path) -> None:
    config, definition = _config(supplemental=True)
    reader = _Cvat({12: [_task(1)]})
    with pytest.raises(KeyError):  # missing required second project is not absence
        _fetch(config, definition, reader)
    assert list(tmp_path.iterdir()) == []


def test_fresh_export_and_snapshot_roundtrip(tmp_path: Path) -> None:
    config, definition = _config()
    snapshot, frame = _fetch(config, definition, _Cvat({12: [_task(1)]}))
    files = LocalSourceFiles()
    output = tmp_path / "fetched"
    files.export(output, snapshot, frame)
    assert files.read_snapshot(output) == snapshot
    assert (output / "sources" / "main" / "obsolete.csv").is_file()
    assert {path.name for path in output.iterdir()} == {
        "dataset.csv",
        "source-snapshot.yaml",
        "sources",
    }
    with pytest.raises(ManagedError, match="already exists"):
        files.export(output, snapshot, frame)


def test_s3_adapter_captures_opaque_etag_and_content_without_images() -> None:
    content = _S3().content
    client = Mock()
    client.get_object.return_value = {
        "Body": io.BytesIO(content),
        "ETag": '"multipart-2"',
        "VersionId": "version",
    }
    captured = S3CsvSources(client).read_object("s3://bucket/data.csv")
    assert captured.content_hash == hashlib.sha256(content).hexdigest()
    assert captured.etag == '"multipart-2"'
    client.get_object.assert_called_once_with(Bucket="bucket", Key="data.csv")
    assert (
        client.method_calls == client.get_object.call_args_list
        or len(client.method_calls) == 1
    )


def test_cvat_adapter_metadata_inspection_does_not_download_annotations() -> None:
    api = Mock()
    api.get_project_tasks.return_value = [
        TaskInfo(
            id=1,
            name="task",
            project_id=12,
            status="completed",
            subset="",
            updated_date="now",
        )
    ]
    api.get_project_labels.return_value = [LabelInfo(id=3, name="cat")]
    api.get_task_jobs.return_value = [
        RawJob(
            id=1,
            start_frame=0,
            stop_frame=0,
            stage="acceptance",
            state="completed",
        )
    ]
    state = CvatSources(api, task_to_records).inspect_project(12)
    assert state.tasks[0].completed
    api.get_task_annotations.assert_not_called()
    api.get_task_data_meta.assert_not_called()


def test_cvat_adapter_jobs_and_capture_completion_use_the_same_rule() -> None:
    api = Mock()
    task = TaskInfo(
        id=1,
        name="task",
        project_id=12,
        status="completed",
        subset="",
        updated_date="now",
    )
    api.get_project_tasks.return_value = [task]
    api.get_task.return_value = task
    api.get_project_labels.return_value = [LabelInfo(id=3, name="cat")]
    unfinished = RawJob(
        id=1,
        start_frame=0,
        stop_frame=0,
        stage="annotation",
        state="completed",
    )
    api.get_task_jobs.return_value = [unfinished]
    api.get_task_annotations.return_value = RawAnnotations()
    api.get_task_data_meta.return_value = RawDataMeta([RawFrame("image.jpg", 100, 100)])
    api.get_task_issues.return_value = []
    adapter = CvatSources(api, task_to_records)
    inspected = adapter.inspect_project(12).tasks[0]
    assert not inspected.completed
    captured = adapter.read_task(12, inspected)
    assert not captured.completed
    assert (
        LocalSourceFiles().project_tables([captured])["dataset.csv"].count("image.jpg")
        == 0
    )
    api.get_task_jobs.return_value = [
        RawJob(
            id=1,
            start_frame=0,
            stop_frame=0,
            stage="acceptance",
            state="completed",
        )
    ]
    with pytest.raises(ManagedError, match="completion changed"):
        adapter.read_task(12, inspected)


def test_published_snapshot_reads_exact_id_and_rejects_missing_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cveta2.adapters.clearml import managed_sources

    config, definition = _config()
    snapshot, _ = _fetch(config, definition, _Cvat({12: [_task(1)]}))
    (tmp_path / "tasks.yaml").write_text(
        yaml.safe_dump(
            {
                "included": [1],
                "obsolete": [],
                "managed": snapshot.model_dump(mode="json"),
            }
        )
    )
    dataset = Mock()
    dataset.id = "pinned"
    dataset.is_final.return_value = True
    dataset.list_files.return_value = ["tasks.yaml"]
    dataset.get_local_copy.return_value = str(tmp_path)
    factory = Mock()
    factory.get.return_value = dataset
    monkeypatch.setattr(managed_sources, "_factory", lambda: factory)
    assert ClearMLSources().read_snapshot("pinned") == snapshot
    factory.get.assert_called_with(
        dataset_id="pinned", only_completed=True, auto_create=False
    )
    with pytest.raises(Cveta2Error, match="required payload"):
        ClearMLSources().read_files("pinned", ("dataset.csv",))
    dataset.id = "wrong"
    with pytest.raises(Cveta2Error, match="different or unfinished"):
        ClearMLSources().read_snapshot("pinned")


def test_published_legacy_absence_and_corrupt_yaml_are_distinct(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cveta2.adapters.clearml import managed_sources

    dataset = Mock()
    dataset.id = "legacy"
    dataset.is_final.return_value = True
    dataset.list_files.return_value = ["dataset.csv"]
    dataset.get_local_copy.return_value = str(tmp_path)
    factory = Mock()
    factory.get.return_value = dataset
    monkeypatch.setattr(managed_sources, "_factory", lambda: factory)
    assert ClearMLSources().read_snapshot("legacy") is None
    dataset.get_local_copy.assert_not_called()
    factory.get.side_effect = ConnectionError("network unavailable")
    with pytest.raises(Cveta2Error, match="network unavailable"):
        ClearMLSources().read_snapshot("legacy")
    factory.get.side_effect = None
    dataset.list_files.return_value = ["tasks.yaml"]
    (tmp_path / "tasks.yaml").write_text("included: []\nincluded: []\n")
    with pytest.raises(ManagedError, match="Duplicate"):
        ClearMLSources().read_snapshot("legacy")
    (tmp_path / "tasks.yaml").write_text("managed: &cycle\n  sources: [*cycle]\n")
    with pytest.raises(ManagedError, match="Recursive"):
        ClearMLSources().read_snapshot("legacy")
