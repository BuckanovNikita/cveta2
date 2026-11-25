"""Managed source snapshots reconstruct complete candidates without stale rows."""

import hashlib
import io
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pandas as pd
import pytest
import yaml
from botocore.exceptions import ClientError

from cveta2.adapters.clearml.managed_sources import ClearMLSources
from cveta2.adapters.cvat.managed_sources import CvatSources
from cveta2.adapters.files.managed_sources import LocalSourceFiles
from cveta2.adapters.files.verification import read_csv_bytes
from cveta2.adapters.s3.managed_sources import S3CsvSources
from cveta2.application.client.assembly import task_to_records
from cveta2.application.ports.dtos import RawAnnotations, RawDataMeta, RawFrame, RawJob
from cveta2.application.ports.managed_sources import ProjectState, S3Object, S3ObjectIdentity
from cveta2.application.use_cases.managed_publication import (
    ManagedPublicationServices,
    _assess_sources,
)
from cveta2.application.use_cases.managed_sources import (
    fetch_sources,
)
from cveta2.domain.bundle.models import ApiClass
from cveta2.domain.class_registry import registry_fingerprint
from cveta2.domain.errors import Cveta2Error
from cveta2.domain.managed.evidence import SourceAssessment, labels_fingerprint
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
    source_fingerprint,
)
from cveta2.domain.models import CSV_COLUMNS, LabelAttributeInfo, LabelInfo, TaskInfo


def _registry() -> list[ApiClass]:
    return [ApiClass(id=90, number=7, name="cat", techClass=False, isPeriodical=False, isCritical=False, threshold=0.5)]


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
    tables = dict.fromkeys(("dataset.csv", "obsolete.csv", "in_progress.csv", "deleted.csv"), blank)
    if not empty:
        tables["deleted.csv" if deleted else "dataset.csv"] = pd.DataFrame([record], columns=list(CSV_COLUMNS)).to_csv(
            index=False
        )
    return TaskSnapshot(id=task_id, updated_date=date, completed=completed, tables=tables)


class _Cvat:
    def __init__(self, projects: dict[int, list[TaskSnapshot]]) -> None:
        self.projects = projects
        self.labels = {project: [LabelInfo(id=1, name="cat")] for project in projects}
        self.downloads: list[tuple[int, int]] = []

    def inspect_project(self, project_id: int) -> ProjectState:
        return ProjectState(
            [task.model_copy(update={"tables": {}}) for task in self.projects[project_id]],
            labels_fingerprint(self.labels[project_id]),
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
        return S3Object(self.content, hashlib.sha256(self.content).hexdigest(), "opaque-etag", "v1")

    def object_identity(self, _uri: str) -> S3ObjectIdentity:
        return S3ObjectIdentity("opaque-etag", "v1")


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
    previous_cvat: CvatIdentity | None = None,
    s3: _S3 | None = None,
    registry: list[ApiClass] | None = None,
    refresh: bool = False,
) -> tuple[ManagedSnapshot, pd.DataFrame]:
    return fetch_sources(
        config,
        definition,
        cvat=reader,
        s3=s3 or _S3(),
        files=LocalSourceFiles(),
        registry=_registry() if registry is None else registry,
        previous=previous,
        previous_cvat=previous_cvat,
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
    assert first.definition_hash == source_fingerprint(config, definition)
    assert (first.sources[2].etag, first.sources[2].version_id) == ("opaque-etag", "v1")
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
        reader.labels[12] = [LabelInfo(id=1, name="cat", color="#ff0000")]
    _fetch(
        config,
        definition,
        reader,
        previous=first,
        previous_cvat=config.cvat,
        registry=[_registry()[0].model_copy(update={"threshold": 0.75})] if reason == "registry" else _registry(),
        refresh=reason == "force",
    )
    assert reader.downloads == [(12, 1)]


def _add_source(raw: dict[str, Any]) -> None:
    raw["projects"]["r"] = {"id": 31}
    raw["datasets"]["combined"]["sources"].append({"name": "third", "type": "cvat", "project": "r"})


_EDITS: dict[str, Callable[[dict[str, Any]], object]] = {
    "ignored-description": lambda raw: raw["projects"]["p"]["ignore"][0].update(
        name="renamed", description="edited", silent=True
    ),
    "source-order": lambda raw: raw["datasets"]["combined"]["sources"].reverse(),
    "overlap-decision": lambda raw: raw["datasets"]["combined"].update(
        overlaps={"digest": {"source": "main", "members": ["main", "extra"]}}
    ),
    "source-uri": lambda raw: raw["datasets"]["combined"]["sources"][2].update(uri="s3://bucket/moved.csv"),
    "ignored-id": lambda raw: raw["projects"]["p"]["ignore"].append({"id": 3}),
    "added-source": _add_source,
    "renamed-source": lambda raw: raw["datasets"]["combined"]["sources"][1].update(name="renamed"),
    "project-id": lambda raw: raw["projects"]["q"].update(id=31),
    "swapped-projects": lambda raw: [
        source.update(project={"p": "q", "q": "p"}[source["project"]])
        for source in raw["datasets"]["combined"]["sources"][:2]
    ],
    "removed-source": lambda raw: raw["datasets"]["combined"]["sources"].pop(1),
    "organization": lambda raw: raw["cvat"].update(organization="team"),
    "host": lambda raw: raw["cvat"].update(host="https://cvat.moved.example"),
}


def _edited(config: ProjectConfig, edit: str) -> tuple[ProjectConfig, DatasetDefinition]:
    raw = config.model_dump(mode="json")
    _EDITS[edit](raw)
    edited = ProjectConfig.model_validate(raw)
    return edited, edited.datasets["combined"]


def _supplemental_with_ignored_task() -> tuple[ProjectConfig, DatasetDefinition]:
    config, _ = _config(supplemental=True)
    raw = config.model_dump(mode="json")
    raw["projects"]["p"]["ignore"] = [{"id": 50, "description": "broken"}]
    edited = ProjectConfig.model_validate(raw)
    return edited, edited.datasets["combined"]


@pytest.mark.parametrize("edit", ["ignored-description", "source-order", "overlap-decision"])
def test_edits_fetch_does_not_read_keep_task_reuse(edit: str) -> None:
    config, definition = _supplemental_with_ignored_task()
    reader = _Cvat({12: [_task(1)], 27: [_task(2)]})
    first, frame = _fetch(config, definition, reader)
    reader.downloads.clear()
    edited, edited_definition = _edited(config, edit)

    second, repeated = _fetch(edited, edited_definition, reader, previous=first)

    assert reader.downloads == []
    assert second.definition_hash == first.definition_hash
    assert sorted(repeated["source_id"]) == sorted(frame["source_id"])


def _three_projects() -> _Cvat:
    return _Cvat(
        {
            12: [_task(1, "one.jpg"), _task(3, "three.jpg")],
            27: [_task(2, "two.jpg")],
            31: [_task(4, "four.jpg")],
        }
    )


@pytest.mark.parametrize(
    ("edit", "downloads"),
    [
        ("ignored-id", []),
        ("source-uri", []),
        ("added-source", [(31, 4)]),
        ("renamed-source", [(27, 2)]),
        ("project-id", [(31, 4)]),
        ("swapped-projects", [(12, 1), (12, 3), (27, 2)]),
        ("removed-source", []),
        ("host", [(12, 1), (12, 3), (27, 2)]),
        ("organization", [(12, 1), (12, 3), (27, 2)]),
    ],
)
def test_source_edit_refetches_only_that_source_unless_the_server_changed(
    edit: str, downloads: list[tuple[int, int]]
) -> None:
    config, definition = _supplemental_with_ignored_task()
    reader = _three_projects()
    s3 = _S3()
    first, _ = _fetch(config, definition, reader, s3=s3)
    reader.downloads.clear()
    edited, edited_definition = _edited(config, edit)

    second, _ = _fetch(edited, edited_definition, reader, previous=first, previous_cvat=config.cvat, s3=s3)

    assert sorted(reader.downloads) == downloads
    assert s3.reads == 2
    assert second.definition_hash == source_fingerprint(edited, edited_definition) != first.definition_hash


def test_ignoring_a_live_task_drops_it_and_unignoring_fetches_only_it() -> None:
    config, definition = _supplemental_with_ignored_task()
    reader = _three_projects()
    first, _ = _fetch(config, definition, reader)
    reader.downloads.clear()
    edited, edited_definition = _edited(config, "ignored-id")

    ignored, frame = _fetch(edited, edited_definition, reader, previous=first, previous_cvat=config.cvat)

    assert reader.downloads == []
    assert set(ignored.sources[0].tasks) == {"1"}
    assert "three.jpg" not in set(frame["image_name"])
    restored, frame = _fetch(config, definition, reader, previous=ignored, previous_cvat=config.cvat)
    assert reader.downloads == [(12, 3)]
    assert set(restored.sources[0].tasks) == {"1", "3"}
    assert "three.jpg" in set(frame["image_name"])


@pytest.mark.parametrize(("identity", "downloads"), [("known", []), ("unknown", [(12, 1)])])
def test_definition_hash_mismatch_resets_every_source_only_when_the_server_is_unknown(
    identity: str, downloads: list[tuple[int, int]]
) -> None:
    """A snapshot whose hash differs never fails; without a published server identity it resets every source."""
    config, definition = _config()
    reader = _Cvat({12: [_task(1)]})
    first, _ = _fetch(config, definition, reader)
    carried = {"assignments": {"image-sha256": "train"}, "image_hashes": {"/images/image.jpg": "image-sha256"}}
    published = first.model_copy(update={"definition_hash": "0" * 64, **carried})
    previous_cvat = config.cvat if identity == "known" else None
    reader.downloads.clear()

    refetched, _ = _fetch(config, definition, reader, previous=published, previous_cvat=previous_cvat)

    assert reader.downloads == downloads
    assert (refetched.assignments, refetched.image_hashes) == (carried["assignments"], carried["image_hashes"])
    assert refetched.definition_hash == source_fingerprint(config, definition)
    reader.downloads.clear()
    _fetch(config, definition, reader, previous=refetched, previous_cvat=previous_cvat)
    assert reader.downloads == []


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
    assert len(read_csv_bytes(second.sources[0].tables["in_progress.csv"].encode())) == 1


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
    s3.content = b"source_id," + _S3().content.replace(b"\nextra.jpg,", b"\nforged,extra.jpg,")
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


def test_export_reports_uncreatable_output_parent(tmp_path: Path) -> None:
    config, definition = _config()
    snapshot, frame = _fetch(config, definition, _Cvat({12: [_task(1)]}))
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("x")
    output = blocker / "nested" / "fetched"
    with pytest.raises(ManagedError, match="nested") as raised:
        LocalSourceFiles().export(output, snapshot, frame)
    assert isinstance(raised.value.__cause__, OSError)


@pytest.mark.parametrize("missing", ["registry", "labels"])
def test_legacy_snapshot_reads_but_refetches_all_tasks_and_keeps_assignments(tmp_path: Path, missing: str) -> None:
    config, definition = _config()
    reader = _Cvat({12: [_task(1)]})
    first, _ = _fetch(config, definition, reader)
    stored = first.model_dump(mode="json")
    stored["assignments"] = {"image-sha256": "train"}
    if missing == "registry":
        stored.pop("registry")
    else:
        stored["sources"][0].pop("labels")
    path = tmp_path / "legacy.yaml"
    path.write_text(yaml.safe_dump(stored))
    legacy = LocalSourceFiles().read_snapshot(path)
    assert (legacy.registry if missing == "registry" else legacy.sources[0].labels) is None
    container = legacy if missing == "registry" else legacy.sources[0]
    assert missing not in container.model_dump()
    reader.downloads.clear()

    refreshed, _ = _fetch(config, definition, reader, previous=legacy, previous_cvat=config.cvat)

    assert reader.downloads == [(12, 1)]
    assert refreshed.assignments == {"image-sha256": "train"}
    assert refreshed.registry == _registry()
    assert refreshed.sources[0].labels == reader.labels[12]


def test_empty_records_are_present_evidence_and_can_be_reused() -> None:
    config, definition = _config()
    reader = _Cvat({12: [_task(1, empty=True)]})
    reader.labels[12] = []
    first, _ = _fetch(config, definition, reader, registry=[])
    reader.downloads.clear()

    second, _ = _fetch(config, definition, reader, registry=[], previous=first)

    assert second.registry == []
    assert second.sources[0].labels == []
    assert reader.downloads == []
    assert second.sources[0].reused == [1]


@pytest.mark.parametrize("damage", ["registry", "labels"])
def test_corrupt_parent_records_refetch_every_task(damage: str) -> None:
    config, definition = _config()
    reader = _Cvat({12: [_task(1)]})
    first, _ = _fetch(config, definition, reader)
    stored = first.model_dump(mode="json")
    if damage == "registry":
        stored["registry"][0]["threshold"] = 0.75
    else:
        stored["sources"][0]["labels"][0]["color"] = "#ffffff"
    corrupted = ManagedSnapshot.model_validate(stored)
    reader.downloads.clear()

    _fetch(config, definition, reader, previous=corrupted)

    assert reader.downloads == [(12, 1)]


def test_record_order_does_not_change_fingerprints_or_reuse() -> None:
    config, definition = _config()
    reader = _Cvat({12: [_task(1)]})
    reader.labels[12].append(LabelInfo(id=2, name="dog"))
    registry = [*_registry(), _registry()[0].model_copy(update={"id": 91, "number": 8, "name": "dog"})]
    first, _ = _fetch(config, definition, reader, registry=registry)
    reader.downloads.clear()
    reader.labels[12].reverse()

    second, _ = _fetch(config, definition, reader, previous=first, registry=list(reversed(registry)))

    assert first.registry_hash == second.registry_hash == registry_fingerprint(registry)
    assert first.sources[0].labels_fingerprint == second.sources[0].labels_fingerprint
    assert reader.downloads == []


@pytest.mark.parametrize(
    ("field", "value"),
    [("mutable", False), ("input_type", "text"), ("default_value", "poor"), ("values", ["good", "poor"])],
)
def test_label_attribute_change_invalidates_unchanged_task(field: str, value: object) -> None:
    config, definition = _config()
    reader = _Cvat({12: [_task(1)]})
    attribute = LabelAttributeInfo(
        id=4, name="quality", mutable=True, input_type="select", default_value="good", values=["good"]
    )
    reader.labels[12] = [LabelInfo(id=1, name="cat", attributes=[attribute])]
    first, _ = _fetch(config, definition, reader)
    reader.downloads.clear()
    reader.labels[12] = [LabelInfo(id=1, name="cat", attributes=[attribute.model_copy(update={field: value})])]

    second, _ = _fetch(config, definition, reader, previous=first)

    assert reader.downloads == [(12, 1)]
    assert second.sources[0].labels_fingerprint != first.sources[0].labels_fingerprint


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
    assert client.method_calls == client.get_object.call_args_list or len(client.method_calls) == 1


def _assess(config: ProjectConfig, snapshot: ManagedSnapshot, reader: _Cvat, s3: _S3) -> SourceAssessment:
    services = ManagedPublicationServices(
        files=Mock(),
        media=Mock(),
        remote=Mock(),
        registry=Mock(),
        cvat=reader,
        s3=s3,
        roots=Mock(),
        s3_roots=Mock(),
        feedback=Mock(),
        ledger=Mock(),
    )
    return _assess_sources(config, snapshot, services)


def test_assess_sources_warns_about_an_unconfigured_project_and_stops_on_a_completed_task() -> None:
    config, definition = _config(supplemental=True)
    reader = _Cvat({12: [_task(1)], 27: [_task(2)]})
    s3 = _S3()
    snapshot, _ = _fetch(config, definition, reader, s3=s3)
    unconfigured = config.model_copy(update={"projects": {"p": config.projects["p"]}})

    assessment = _assess(unconfigured, snapshot, reader, s3)

    assert assessment.warnings == ("other: проект 27 больше не описан в конфигурации, задачи не проверены",)
    assert assessment.stale_tasks == {("other", 2)}
    reader.projects[12].append(_task(3))
    reader.projects[27].append(_task(4))
    with pytest.raises(ManagedError, match=r"CVAT tasks completed after fetch: main/3, other/4; fetch the managed"):
        _assess(config, snapshot, reader, s3)


def test_s3_adapter_reads_identity_without_the_body() -> None:
    client = Mock()
    client.head_object.return_value = {"ETag": '"e1"', "VersionId": "v2"}

    identity = S3CsvSources(client).object_identity("s3://bucket/data.csv")

    assert identity == S3ObjectIdentity('"e1"', "v2")
    client.head_object.assert_called_once_with(Bucket="bucket", Key="data.csv")
    client.get_object.assert_not_called()


def test_s3_adapter_identity_failure_names_the_source() -> None:
    client = Mock()
    client.head_object.side_effect = ClientError({"Error": {"Code": "404"}}, "HeadObject")

    with pytest.raises(ManagedError, match=r"Cannot read required S3 CSV source: s3://bucket/data\.csv"):
        S3CsvSources(client).object_identity("s3://bucket/data.csv")


@pytest.mark.parametrize("operation", ["read_object", "object_identity"])
def test_s3_adapter_never_echoes_an_invalid_source_uri(operation: str) -> None:
    client = Mock()
    with pytest.raises(ManagedError, match=r"^Invalid S3 CSV source uri: expected s3://bucket/key\.csv$") as caught:
        getattr(S3CsvSources(client), operation)("s3://AKIAKEY:TOPSECRET@bucket/key.csv")
    assert "TOPSECRET" not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__
    client.get_object.assert_not_called()
    client.head_object.assert_not_called()


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
    assert LocalSourceFiles().project_tables([captured])["dataset.csv"].count("image.jpg") == 0
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
    factory.get.assert_called_with(dataset_id="pinned", only_completed=True, auto_create=False)
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
