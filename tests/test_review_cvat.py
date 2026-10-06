"""Safety regressions for the simulated 2026-10-03 CVAT findings."""

from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

from cveta2._client.dtos import RawAnnotations, RawShape
from cveta2._client.ports import CvatApiPort
from cveta2._client.sdk_adapter import _should_retry_write
from cveta2._client_ops.session import TaskWriteSession
from cveta2.client import CvatClient
from cveta2.config import CvatConfig
from cveta2.exceptions import CvatApiError, Cveta2Error
from cveta2.models import LabelInfo, ProjectInfo, TaskInfo
from cveta2.services.upload import (
    UploadOptions,
    UploadPlan,
    UploadRequest,
    _ensure_annotations,
    _StagedUpload,
    upload_dataset,
)
from cveta2.upload_manifest import compute_fingerprint, delete_manifest
from tests.helpers import make_cs_info


def rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "image_name": "a.jpg",
                "instance_label": "car",
                "instance_shape": "box",
                "bbox_x_tl": 1.0,
                "bbox_y_tl": 2.0,
                "bbox_x_br": 3.0,
                "bbox_y_br": 4.0,
            }
        ]
    )


def test_duplicate_project_names_reject_all_matching_ids() -> None:
    client = CvatClient(CvatConfig())
    projects = [ProjectInfo(id=101, name="same"), ProjectInfo(id=202, name="SAME")]
    for candidates in (projects, list(reversed(projects))):
        with pytest.raises(Cveta2Error, match=r"101.*202|202.*101"):
            client.find_project_by_name("same", cached=candidates)
    assert client.resolve_project_id("202", cached=projects) == 202


def test_duplicate_task_names_reject_all_matching_ids() -> None:
    tasks = [
        TaskInfo(id=101, name="same", status="annotation", subset="", updated_date=""),
        TaskInfo(id=202, name="SAME", status="annotation", subset="", updated_date=""),
    ]
    with pytest.raises(Cveta2Error, match=r"101.*202"):
        CvatClient.resolve_task_selectors(tasks, ["same"])
    assert CvatClient.resolve_task_selectors(tasks, [202]) == [tasks[1]]


@pytest.mark.parametrize("column", ["bbox_x_tl", "bbox_y_tl", "bbox_x_br", "bbox_y_br"])
def test_incomplete_boxes_stop_direct_and_service_writes(column: str) -> None:
    df = rows()
    df.loc[0, column] = None
    api = MagicMock(spec=CvatApiPort)
    client = CvatClient(CvatConfig(), api=api)
    session = TaskWriteSession(
        api, 99, _name_to_frame={"a.jpg": 0}, _labels=[LabelInfo(id=7, name="car")]
    )
    with pytest.raises(Cveta2Error, match=r"a\.jpg"):
        client.upload_task_annotations(99, df, session=session)
    api.put_task_shapes.assert_not_called()
    request = UploadRequest(
        1, "project", "task", UploadPlan(df, ["a.jpg"], []), UploadOptions()
    )
    service_client = MagicMock()
    with pytest.raises(Cveta2Error, match=r"a\.jpg"):
        upload_dataset(service_client, request)
    assert service_client.mock_calls == []


def test_fingerprint_includes_annotation_content() -> None:
    original = rows()
    edited = rows()
    edited.loc[0, "bbox_x_tl"] = 100
    assert compute_fingerprint(
        ["a.jpg"], [], ["car"], annotations=original
    ) != compute_fingerprint(["a.jpg"], [], ["car"], annotations=edited)


def test_cleanup_permission_failure_is_a_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def denied(self: Path, *, missing_ok: bool = False) -> None:
        assert self.name == "identity.json"
        assert missing_ok
        raise PermissionError("simulated")

    monkeypatch.setattr(Path, "unlink", denied)
    delete_manifest(1, "identity", host="http://cvat.invalid", task_id=99)


def test_503_retry_after_does_not_authorize_write_replay() -> None:
    assert not _should_retry_write(
        CvatApiError("already applied", status_code=503, retry_after=0)
    )


def test_conflicting_shape_readback_never_appends() -> None:
    client = MagicMock()
    api = MagicMock(spec=CvatApiPort)
    api.get_task_annotations.return_value = RawAnnotations(
        shapes=[
            RawShape(
                id=1,
                type="rectangle",
                frame=0,
                label_id=7,
                points=[100, 2, 130, 4],
                occluded=False,
                z_order=0,
                rotation=0,
                source="manual",
                attributes=[],
                created_by="",
            )
        ]
    )
    session = TaskWriteSession(
        api, 99, _name_to_frame={"a.jpg": 0}, _labels=[LabelInfo(id=7, name="car")]
    )
    staged = _StagedUpload(MagicMock(), rows(), ["a.jpg"], {"a.jpg": "a.jpg"})
    with pytest.raises(Cveta2Error):
        _ensure_annotations(client, 99, staged, session, resuming=True)
    client.upload_task_annotations.assert_not_called()


@pytest.mark.parametrize("shape", [None, "deleted"])
def test_empty_and_deleted_records_are_valid(shape: str | None) -> None:
    api = MagicMock(spec=CvatApiPort)
    client = CvatClient(CvatConfig(), api=api)
    df = pd.DataFrame(
        [{"image_name": "a.jpg", "instance_label": None, "instance_shape": shape}]
    )
    assert client.upload_task_annotations(99, df) == 0
    assert api.mock_calls == []


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("instance_label", "person"),
        ("bbox_y_tl", 20),
        ("instance_attributes", '{"color":"red"}'),
        ("issue_text", "changed comment"),
        ("issue_state", "new"),
    ],
)
def test_complete_identity_detects_semantic_row_changes(
    column: str, value: str | int
) -> None:
    original = rows()
    edited = rows()
    edited[column] = value
    assert compute_fingerprint(
        ["a.jpg"], [], ["car"], annotations=original
    ) != compute_fingerprint(["a.jpg"], [], ["car"], annotations=edited)


def test_identity_preserves_frame_order_but_normalizes_bbox_numbers() -> None:
    original = rows()
    integer_boxes = original.copy()
    for column in ("bbox_x_tl", "bbox_y_tl", "bbox_x_br", "bbox_y_br"):
        integer_boxes[column] = integer_boxes[column].astype(int)
    first = compute_fingerprint(["a.jpg", "b.jpg"], [], [], annotations=original)
    assert first == compute_fingerprint(
        ["a.jpg", "b.jpg"], [], [], annotations=integer_boxes
    )
    assert first != compute_fingerprint(
        ["b.jpg", "a.jpg"], [], [], annotations=original
    )


@pytest.mark.parametrize(
    ("option", "value"),
    [
        ("segment_size", 10),
        ("image_quality", 70),
        ("mark_all_deleted", True),
        ("complete", True),
    ],
)
def test_changed_options_reject_resume_before_external_calls(
    option: str, value: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.test_upload_service import (
        make_client,
        make_request,
        make_s3,
        seeded_bucket,
    )

    client = make_client(
        cloud_storage=make_cs_info(bucket="test-bucket", prefix="images")
    )
    make_s3(monkeypatch, seeded_bucket(["a.jpg"]))
    request = make_request(image_names=["a.jpg"])
    with monkeypatch.context() as boundary:
        boundary.setattr(
            client.api,
            "put_task_shapes",
            MagicMock(side_effect=CvatApiError("interrupted")),
        )
        with pytest.raises(CvatApiError):
            upload_dataset(client, request)
    stage = MagicMock()
    monkeypatch.setattr("cveta2.services.upload._stage_images", stage)
    changed = replace(
        request,
        resume=True,
        options=UploadOptions(
            segment_size=value if option == "segment_size" else 100,
            image_quality=value if option == "image_quality" else 100,
            mark_all_deleted=option == "mark_all_deleted",
            complete=option == "complete",
        ),
    )
    with pytest.raises(Cveta2Error):
        upload_dataset(client, changed)
    stage.assert_not_called()


def test_cleanup_failure_preserves_success_and_prevents_future_writes(
    monkeypatch: pytest.MonkeyPatch, capture_logs: list[str]
) -> None:
    from cveta2.upload_manifest import list_manifests
    from tests.test_upload_service import (
        make_client,
        make_request,
        make_s3,
        seeded_bucket,
    )

    client = make_client(
        cloud_storage=make_cs_info(bucket="test-bucket", prefix="images")
    )
    make_s3(monkeypatch, seeded_bucket(["a.jpg"]))
    original = Path.unlink

    def denied(self: Path, *, missing_ok: bool = False) -> None:
        if "uploads" in self.parts and self.suffix == ".json":
            raise PermissionError("simulated cleanup denial")
        original(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", denied)
    first = upload_dataset(client, make_request(image_names=["a.jpg"]))
    manifest = list_manifests(7, host=client.host)[0]
    assert manifest.completed_counts is not None
    assert any(
        f"задачу {first.task_id} " in message and "устаревшее" in message
        for message in capture_logs
    )
    stage = MagicMock()
    monkeypatch.setattr("cveta2.services.upload._stage_images", stage)
    assert (
        upload_dataset(client, make_request(image_names=["a.jpg"], resume=True))
        == first
    )
    assert upload_dataset(client, make_request(image_names=["a.jpg"])) == first
    stage.assert_not_called()


def test_applied_then_503_has_exactly_one_effect() -> None:
    from cveta2._retry import network_retry

    effects: list[int] = []

    @network_retry(_should_retry_write, label="simulated ambiguous write")
    def applied() -> None:
        effects.append(1)
        raise CvatApiError("applied before error", status_code=503, retry_after=0)

    with pytest.raises(CvatApiError):
        applied()
    assert effects == [1]


@pytest.mark.parametrize("with_columns", [False, True])
def test_empty_shape_recovery_accepts_no_annotations(*, with_columns: bool) -> None:
    from cveta2.models import CSV_COLUMNS
    from cveta2.services.upload import _verify_existing_shapes

    api = MagicMock(spec=CvatApiPort)
    api.get_task_annotations.return_value = RawAnnotations()
    session = TaskWriteSession(api, 99)
    empty = pd.DataFrame(columns=list(CSV_COLUMNS)) if with_columns else pd.DataFrame()
    assert _verify_existing_shapes(99, empty, session) == 0


def test_changed_remote_directory_with_same_basename_rejects_before_staging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cveta2._client.dtos import RawDataMeta, RawFrame
    from tests.test_upload_service import (
        _seed_manifest_for,
        make_client,
        make_request,
        make_s3,
        seeded_bucket,
    )

    client = make_client(
        cloud_storage=make_cs_info(bucket="test-bucket", prefix="images")
    )
    make_s3(monkeypatch, seeded_bucket(["a.jpg"]))
    request = make_request(image_names=["a.jpg"])
    outcome = upload_dataset(client, request)
    _seed_manifest_for(client, request, outcome.task_id)
    remote = RawDataMeta(frames=[RawFrame("different/a.jpg", 640, 480)])
    monkeypatch.setattr(client.api, "get_task_data_meta", lambda _task_id: remote)
    stage = MagicMock()
    monkeypatch.setattr("cveta2.services.upload._stage_images", stage)
    with pytest.raises(Cveta2Error, match="кадры"):
        upload_dataset(client, replace(request, resume=True))
    stage.assert_not_called()


def test_deletion_only_request_resumes_without_shape_columns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.test_upload_service import (
        _seed_manifest_for,
        make_client,
        make_request,
        make_s3,
        seeded_bucket,
    )

    client = make_client(
        cloud_storage=make_cs_info(bucket="test-bucket", prefix="images")
    )
    make_s3(monkeypatch, seeded_bucket(["d.jpg"]))
    request = make_request(image_names=[], deleted_names=["d.jpg"])
    first = upload_dataset(client, request)
    _seed_manifest_for(client, request, first.task_id)
    assert upload_dataset(client, replace(request, resume=True)) == first
    assert first.annotations == 0


@pytest.mark.parametrize(
    ("actual", "expected", "matches"),
    [
        (["images/old/a.jpg"], ["images/old/a.jpg"], True),
        (["old/a.jpg"], ["images/old/a.jpg"], True),
        (["new/a.jpg"], ["images/old/a.jpg"], False),
        (["images/new/a.jpg"], ["images/old/a.jpg"], False),
        (["a.jpg"], ["images/old/a.jpg"], True),
        (["a.jpg", "a.jpg"], ["images/old/a.jpg", "images/new/a.jpg"], False),
        (["b.jpg", "a.jpg"], ["images/a.jpg", "images/b.jpg"], False),
    ],
)
def test_frame_paths_preserve_available_directory_identity(
    actual: list[str],
    expected: list[str],
    *,
    matches: bool,
) -> None:
    from cveta2.services.upload import _frames_match

    assert _frames_match(actual, expected, "/images/") == matches


def test_active_project_name_query_does_not_trust_stale_single_match() -> None:
    api = MagicMock(spec=CvatApiPort)
    api.list_projects.return_value = [
        ProjectInfo(id=101, name="same"),
        ProjectInfo(id=202, name="SAME"),
    ]
    client = CvatClient(CvatConfig(), api=api)
    with pytest.raises(Cveta2Error, match=r"101.*202"):
        client.find_project_by_name("same", cached=[ProjectInfo(id=101, name="same")])
    api.list_projects.assert_called_once_with()


def test_active_project_name_query_returns_current_unique_identity() -> None:
    api = MagicMock(spec=CvatApiPort)
    current = ProjectInfo(id=202, name="SAME")
    api.list_projects.return_value = [current]
    client = CvatClient(CvatConfig(), api=api)
    assert (
        client.find_project_by_name("same", cached=[ProjectInfo(id=101, name="same")])
        == current
    )


@pytest.mark.parametrize("checkpoint", ["initial", "pending", "created"])
def test_required_manifest_checkpoints_fail_closed(
    checkpoint: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json

    from cveta2 import upload_manifest
    from cveta2.upload_manifest import list_manifests
    from tests.fixtures.fake_cvat_api import FakeCvatApi
    from tests.test_upload_service import (
        make_client,
        make_request,
        make_s3,
        seeded_bucket,
    )

    client = make_client(
        cloud_storage=make_cs_info(bucket="test-bucket", prefix="images")
    )
    make_s3(monkeypatch, seeded_bucket(["a.jpg"]))
    from cveta2.fs_utils import replace_shared_bytes

    original = replace_shared_bytes

    def denied(path: Path, data: bytes) -> None:
        state = json.loads(data)
        stage = (
            "created"
            if state["task_id"] is not None
            else "pending"
            if state["creation_pending"]
            else "initial"
        )
        if stage == checkpoint:
            raise PermissionError("simulated required checkpoint denial")
        original(path, data)

    monkeypatch.setattr(upload_manifest, "replace_shared_bytes", denied)
    with pytest.raises(Cveta2Error, match="сохранить"):
        upload_dataset(client, make_request(image_names=["a.jpg"]))
    assert isinstance(client.api, FakeCvatApi)
    assert len(client.api.writes.created_tasks) == (1 if checkpoint == "created" else 0)
    if checkpoint == "created":
        manifest = list_manifests(7, host=client.host)[0]
        assert manifest.creation_pending
        assert manifest.task_id is None
        monkeypatch.setattr(upload_manifest, "replace_shared_bytes", original)
        with pytest.raises(Cveta2Error, match="неизвестен"):
            upload_dataset(client, make_request(image_names=["a.jpg"], resume=True))
        assert len(client.api.writes.created_tasks) == 1
        assert client.get_task_size(1) == 0


def _stored_box() -> RawShape:
    return RawShape(
        id=1,
        type="rectangle",
        frame=0,
        label_id=7,
        points=[1, 2, 3, 4],
        occluded=False,
        z_order=0,
        rotation=0,
        source="manual",
        attributes=[],
        created_by="",
    )


@pytest.mark.parametrize("label", [None, "", "   "])
def test_empty_labels_without_box_columns_are_valid(label: str | None) -> None:
    from cveta2.services.upload import _verify_existing_shapes
    from cveta2.upload_manifest import validate_upload_boxes

    empty = pd.DataFrame([{"image_name": "a.jpg", "instance_label": label}])
    validate_upload_boxes(empty)
    api = MagicMock(spec=CvatApiPort)
    api.get_task_annotations.return_value = RawAnnotations()
    client = CvatClient(CvatConfig(), api=api)
    assert client.upload_task_annotations(99, empty) == 0
    assert _verify_existing_shapes(99, empty, TaskWriteSession(api, 99)) == 0
    api.put_task_shapes.assert_not_called()


@pytest.mark.parametrize("complete_box", [False, True])
def test_deleted_labelled_rows_never_create_shapes(*, complete_box: bool) -> None:
    from cveta2.services.upload import _verify_existing_shapes
    from cveta2.upload_manifest import validate_upload_boxes

    deleted = rows()
    deleted["instance_shape"] = "deleted"
    if not complete_box:
        deleted = deleted.drop(columns=["bbox_y_br"])
    validate_upload_boxes(deleted)
    api = MagicMock(spec=CvatApiPort)
    api.get_task_annotations.return_value = RawAnnotations()
    client = CvatClient(CvatConfig(), api=api)
    session = TaskWriteSession(
        api, 99, _name_to_frame={"a.jpg": 0}, _labels=[LabelInfo(id=7, name="car")]
    )
    assert client.upload_task_annotations(99, deleted, session=session) == 0
    assert _verify_existing_shapes(99, deleted, session) == 0
    api.put_task_shapes.assert_not_called()


@pytest.mark.parametrize("value", ["not-a-number", float("inf"), float("-inf")])
def test_bad_box_values_produce_a_domain_diagnostic_before_calls(
    value: str | float,
) -> None:
    bad = rows().astype(object)
    bad.loc[0, "bbox_y_br"] = value
    api = MagicMock(spec=CvatApiPort)
    client = CvatClient(CvatConfig(), api=api)
    with pytest.raises(Cveta2Error, match=r"a\.jpg"):
        client.upload_task_annotations(99, bad)
    assert api.mock_calls == []


@pytest.mark.parametrize(
    "shape",
    [
        replace(_stored_box(), occluded=True),
        replace(_stored_box(), z_order=1),
        replace(_stored_box(), rotation=15),
        replace(_stored_box(), type="ellipse"),
        replace(_stored_box(), frame=1),
        replace(_stored_box(), label_id=8),
        replace(_stored_box(), points=[1, 2, 3, 5]),
    ],
)
def test_shape_recovery_rejects_each_conflicting_property(shape: RawShape) -> None:
    from cveta2.services.upload import _verify_existing_shapes

    api = MagicMock(spec=CvatApiPort)
    api.get_task_annotations.return_value = RawAnnotations(shapes=[shape])
    session = TaskWriteSession(
        api, 99, _name_to_frame={"a.jpg": 0}, _labels=[LabelInfo(id=7, name="car")]
    )
    with pytest.raises(Cveta2Error, match=r"99.*аннотации"):
        _verify_existing_shapes(99, rows(), session)
    api.put_task_shapes.assert_not_called()


def test_shape_attributes_conflict_with_default_upload_intent() -> None:
    from cveta2._client.dtos import RawAttribute
    from cveta2.services.upload import _verify_existing_shapes

    api = MagicMock(spec=CvatApiPort)
    api.get_task_annotations.return_value = RawAnnotations(
        shapes=[replace(_stored_box(), attributes=[RawAttribute(5, "changed")])]
    )
    session = TaskWriteSession(
        api, 99, _name_to_frame={"a.jpg": 0}, _labels=[LabelInfo(id=7, name="car")]
    )
    with pytest.raises(Cveta2Error, match="99"):
        _verify_existing_shapes(99, rows(), session)


@pytest.mark.parametrize(
    ("input_count", "remote_count"), [(2, 1), (1, 2), (0, 1), (2, 2)]
)
def test_shape_recovery_preserves_duplicate_multiplicity(
    input_count: int, remote_count: int
) -> None:
    from cveta2.services.upload import _verify_existing_shapes

    api = MagicMock(spec=CvatApiPort)
    api.get_task_annotations.return_value = RawAnnotations(
        shapes=[_stored_box()] * remote_count
    )
    session = TaskWriteSession(
        api, 99, _name_to_frame={"a.jpg": 0}, _labels=[LabelInfo(id=7, name="car")]
    )
    annotations = (
        pd.concat([rows()] * input_count, ignore_index=True)
        if input_count
        else pd.DataFrame()
    )
    if input_count == remote_count:
        assert _verify_existing_shapes(99, annotations, session) == remote_count
    else:
        with pytest.raises(Cveta2Error, match="99"):
            _verify_existing_shapes(99, annotations, session)


@pytest.mark.parametrize("unknown", ["image", "label"])
def test_shape_recovery_rejects_a_single_unknown_mapping(unknown: str) -> None:
    from cveta2.services.upload import _verify_existing_shapes

    api = MagicMock(spec=CvatApiPort)
    api.get_task_annotations.return_value = RawAnnotations()
    session = TaskWriteSession(
        api,
        99,
        _name_to_frame={} if unknown == "image" else {"a.jpg": 0},
        _labels=[] if unknown == "label" else [LabelInfo(id=7, name="car")],
    )
    with pytest.raises(Cveta2Error, match=r"99.*метки"):
        _verify_existing_shapes(99, rows(), session)
    api.put_task_shapes.assert_not_called()


@pytest.mark.parametrize("change", ["box", "task", "image_order", "deletion", "labels"])
def test_request_identity_binds_every_input_component(change: str) -> None:
    from cveta2.services.upload import request_fingerprint
    from tests.test_upload_service import make_request

    first = make_request(image_names=["a.jpg", "b.jpg"])
    edited_rows = first.plan.annotations.copy()
    edited_rows.loc[0, "bbox_y_br"] = 50
    modified = {
        "box": replace(first, plan=replace(first.plan, annotations=edited_rows)),
        "task": replace(first, task_name="different"),
        "image_order": replace(
            first, plan=replace(first.plan, image_names=["b.jpg", "a.jpg"])
        ),
        "deletion": replace(first, plan=replace(first.plan, deleted_names=["d.jpg"])),
        "labels": replace(first, labels=("person",)),
    }
    assert request_fingerprint(first) != request_fingerprint(modified[change])


@pytest.mark.parametrize("column", ["image_path", "s3_uri", "s3_path", "image_url"])
def test_local_lookup_properties_do_not_change_annotation_intent(column: str) -> None:
    original = rows()
    edited = rows()
    original[column] = "old-path"
    edited[column] = "new-path"
    assert compute_fingerprint(
        ["a.jpg"], [], [], annotations=original
    ) == compute_fingerprint(["a.jpg"], [], [], annotations=edited)


def test_fingerprint_normalizes_missing_columns_and_ordered_mappings() -> None:
    original = rows()
    edited = rows().iloc[:, ::-1].copy()
    edited["unused"] = None
    assert compute_fingerprint(
        ["a.jpg"], [], [], annotations=original, options={"complete": True, "size": 20}
    ) == compute_fingerprint(
        ["a.jpg"], [], [], annotations=edited, options={"size": 20, "complete": True}
    )
    assert compute_fingerprint([], [], []) == compute_fingerprint(
        [], [], [], task_name=""
    )


def test_fingerprint_accepts_semantic_timestamp_scalars() -> None:
    annotations = rows()
    annotations["task_updated_date"] = pd.Timestamp("2026-10-04")
    identity = compute_fingerprint(["a.jpg"], [], [], annotations=annotations)
    annotations["task_updated_date"] = pd.Timestamp("2026-10-05")
    assert compute_fingerprint(["a.jpg"], [], [], annotations=annotations) != identity


def test_mapping_identity_is_complete_and_order_independent() -> None:
    from cveta2.upload_manifest import compute_mapping_identity
    from tests.test_upload_manifest import _manifest

    manifest = _manifest()
    manifest.name_to_server_file = {"a.jpg": "old/a.jpg", "b.jpg": "old/b.jpg"}
    manifest.task_image_names = ["images/old/a.jpg", "images/old/b.jpg"]
    identity = compute_mapping_identity(manifest)
    reordered = manifest.model_copy(deep=True)
    reordered.name_to_server_file = {"b.jpg": "old/b.jpg", "a.jpg": "old/a.jpg"}
    assert compute_mapping_identity(reordered) == identity
    for field, value in [
        ("id", 9),
        ("bucket", "different"),
        ("prefix", "different"),
        ("endpoint_url", "http://different"),
    ]:
        altered = manifest.model_copy(deep=True)
        altered.cs_info = altered.cs_info.model_copy(update={field: value})
        assert compute_mapping_identity(altered) != identity
    altered = manifest.model_copy(deep=True)
    altered.name_to_server_file["a.jpg"] = "different/a.jpg"
    assert compute_mapping_identity(altered) != identity
    altered = manifest.model_copy(deep=True)
    altered.task_image_names.reverse()
    assert compute_mapping_identity(altered) != identity


@pytest.mark.parametrize("tamper", ["insufficient", "mapping"])
def test_insufficient_or_tampered_recovery_rejects_before_client_calls(
    tamper: str,
) -> None:
    from cveta2.services.upload import request_fingerprint
    from cveta2.upload_manifest import save_manifest
    from tests.test_upload_manifest import HOST, _manifest
    from tests.test_upload_service import make_request

    request = make_request(image_names=["a.jpg"], resume=True)
    manifest = _manifest(fingerprint=request_fingerprint(request), task_id=99)
    assert not manifest.intent_complete
    if tamper == "mapping":
        manifest.intent_complete = True
        manifest.name_to_server_file["a.jpg"] = "different/a.jpg"
    save_manifest(manifest)
    client = MagicMock()
    client.host = HOST
    with pytest.raises(Cveta2Error, match="намерения"):
        upload_dataset(client, request)
    assert client.mock_calls == []


@pytest.mark.parametrize("missing", ["task_id", "completed_counts"])
def test_incomplete_completed_outcome_is_a_domain_error(missing: str) -> None:
    from cveta2.services.upload import _completed_outcome
    from tests.test_upload_manifest import _manifest
    from tests.test_upload_service import make_request

    manifest = _manifest(task_id=None if missing == "task_id" else 99)
    manifest.completed_counts = None if missing == "completed_counts" else (1, 2, 3)
    with pytest.raises(Cveta2Error, match="повреждено"):
        _completed_outcome(make_request(image_names=["a.jpg"]), manifest)


def test_basename_fallback_reports_its_verification_limit(
    capture_logs: list[str],
) -> None:
    from cveta2.services.upload import _frames_match

    assert _frames_match(["a.jpg"], ["images/old/a.jpg"], "images")
    assert any("подтвердить невозможно" in message for message in capture_logs)


@pytest.mark.parametrize("prefix", ["", "/", "/imagesX/"])
def test_frame_prefix_normalization_and_empty_prefix(prefix: str) -> None:
    from cveta2.services.upload import _frames_match

    expected = ["imagesX/old/a.jpg"] if prefix == "/imagesX/" else ["old/a.jpg"]
    assert _frames_match(["old/a.jpg"], expected, prefix)
    assert not _frames_match(["different/a.jpg"], expected, prefix)
    assert not _frames_match([], expected, prefix)


def test_ambiguous_replacement_create_cannot_reuse_the_old_missing_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cveta2.upload_manifest import list_manifests
    from tests.fixtures.fake_cvat_api import FakeCvatApi
    from tests.test_upload_service import (
        _dies_attaching_frames,
        _InterruptedRunError,
        make_client,
        make_request,
        make_s3,
        seeded_bucket,
    )

    client = make_client(
        cloud_storage=make_cs_info(bucket="test-bucket", prefix="images")
    )
    make_s3(monkeypatch, seeded_bucket(["a.jpg"]))
    request = make_request(image_names=["a.jpg"])
    with _dies_attaching_frames(client), pytest.raises(_InterruptedRunError):
        upload_dataset(client, request)
    previous = list_manifests(7, host=client.host)[0]
    assert previous.task_id is not None
    client.delete_task(previous.task_id)
    original = client.api.create_task

    def applied_then_unavailable(spec: object) -> int:
        from cveta2._client.dtos import UploadTaskSpec

        assert isinstance(spec, UploadTaskSpec)
        original(spec)
        raise CvatApiError(
            "503 after replacement was created", status_code=503, retry_after=0
        )

    monkeypatch.setattr(client.api, "create_task", applied_then_unavailable)
    with pytest.raises(CvatApiError, match="503"):
        upload_dataset(client, replace(request, resume=True))
    assert isinstance(client.api, FakeCvatApi)
    created = len(client.api.writes.created_tasks)
    durable = list_manifests(7, host=client.host)[0]
    assert durable.task_id is None
    assert durable.creation_pending
    with pytest.raises(Cveta2Error, match="неизвестен"):
        upload_dataset(client, replace(request, resume=True))
    assert len(client.api.writes.created_tasks) == created


@pytest.mark.parametrize("state", ["pending", "project", "frames", "empty", "partial"])
def test_ensure_task_guard_reports_known_identity_and_never_replays(state: str) -> None:
    from cveta2._client.dtos import RawDataMeta, RawFrame
    from cveta2.services.upload import _ensure_task
    from tests.test_upload_manifest import _manifest
    from tests.test_upload_service import make_request

    client = MagicMock(spec=CvatClient)
    api = MagicMock(spec=CvatApiPort)
    client.get_task.return_value.project_id = 999 if state == "project" else 7
    client.get_task_size.return_value = (
        0 if state == "empty" else 1 if state == "partial" else 2
    )
    client.open_task_session.return_value = TaskWriteSession(
        api,
        77,
        _data_meta=RawDataMeta(
            [RawFrame("different/a.jpg", 640, 480), RawFrame("images/b.jpg", 640, 480)]
        ),
    )
    manifest = _manifest(task_id=None if state == "pending" else 77)
    manifest.creation_pending = state == "pending"
    staged = _StagedUpload(
        make_cs_info(prefix="images"),
        rows(),
        ["images/a.jpg", "images/b.jpg"],
        {"a.jpg": "a.jpg", "b.jpg": "b.jpg"},
    )
    pattern = {
        "pending": "неизвестен",
        "project": r"77.*999.*7",
        "frames": "77",
        "empty": r"77.*неизвестен",
        "partial": r"77.*1.*2",
    }[state]
    with pytest.raises(Cveta2Error, match=pattern):
        _ensure_task(
            client, make_request(image_names=["a.jpg", "b.jpg"]), staged, manifest
        )
    client.create_upload_task.assert_not_called()
    client.delete_task.assert_not_called()


@pytest.mark.parametrize("resuming", [False, True])
def test_completed_recovery_cleans_the_exact_stale_manifest(
    monkeypatch: pytest.MonkeyPatch,
    *,
    resuming: bool,
) -> None:
    from cveta2.upload_manifest import list_manifests
    from tests.test_upload_service import (
        make_client,
        make_request,
        make_s3,
        seeded_bucket,
    )

    client = make_client(
        cloud_storage=make_cs_info(bucket="test-bucket", prefix="images")
    )
    make_s3(monkeypatch, seeded_bucket(["a.jpg"]))
    original = Path.unlink

    def denied(self: Path, *, missing_ok: bool = False) -> None:
        if "uploads" in self.parts and self.suffix == ".json":
            raise PermissionError("simulated")
        original(self, missing_ok=missing_ok)

    with monkeypatch.context() as boundary:
        boundary.setattr(Path, "unlink", denied)
        first = upload_dataset(client, make_request(image_names=["a.jpg"]))
    assert len(list_manifests(7, host=client.host)) == 1
    stage = MagicMock()
    monkeypatch.setattr("cveta2.services.upload._stage_images", stage)
    assert (
        upload_dataset(client, make_request(image_names=["a.jpg"], resume=resuming))
        == first
    )
    assert list_manifests(7, host=client.host) == []
    stage.assert_not_called()


@pytest.mark.parametrize("resuming", [False, True])
def test_stale_cleanup_warning_identifies_task_on_each_recovery(
    monkeypatch: pytest.MonkeyPatch,
    capture_logs: list[str],
    *,
    resuming: bool,
) -> None:
    from tests.test_upload_service import (
        make_client,
        make_request,
        make_s3,
        seeded_bucket,
    )

    client = make_client(
        cloud_storage=make_cs_info(bucket="test-bucket", prefix="images")
    )
    make_s3(monkeypatch, seeded_bucket(["a.jpg"]))
    original = Path.unlink

    def denied(self: Path, *, missing_ok: bool = False) -> None:
        if "uploads" in self.parts and self.suffix == ".json":
            raise PermissionError("simulated")
        original(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", denied)
    first = upload_dataset(client, make_request(image_names=["a.jpg"]))
    capture_logs.clear()
    assert (
        upload_dataset(client, make_request(image_names=["a.jpg"], resume=resuming))
        == first
    )
    assert any(
        f"задачу {first.task_id} " in message and "устаревшее" in message
        for message in capture_logs
    )


def test_changed_cloud_storage_rejects_before_staging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.test_upload_service import (
        _seed_manifest_for,
        make_client,
        make_request,
        make_s3,
        seeded_bucket,
    )

    client = make_client(
        cloud_storage=make_cs_info(bucket="test-bucket", prefix="images")
    )
    make_s3(monkeypatch, seeded_bucket(["a.jpg"]))
    request = make_request(image_names=["a.jpg"])
    first = upload_dataset(client, request)
    _seed_manifest_for(client, request, first.task_id)
    monkeypatch.setattr(
        client,
        "detect_project_cloud_storage",
        lambda _project: make_cs_info(bucket="different"),
    )
    stage = MagicMock()
    monkeypatch.setattr("cveta2.services.upload._stage_images", stage)
    with pytest.raises(Cveta2Error, match="Cloud storage"):
        upload_dataset(client, replace(request, resume=True))
    stage.assert_not_called()


@pytest.mark.parametrize("known_task", [False, True])
def test_fresh_manifest_preserves_pending_false_identity_state(
    monkeypatch: pytest.MonkeyPatch,
    *,
    known_task: bool,
) -> None:
    from cveta2.services.upload import request_fingerprint
    from cveta2.upload_manifest import save_manifest
    from tests.fixtures.fake_cvat_api import FakeCvatApi
    from tests.test_upload_manifest import _manifest
    from tests.test_upload_service import (
        make_client,
        make_request,
        make_s3,
        seeded_bucket,
    )

    client = make_client(
        cloud_storage=make_cs_info(bucket="test-bucket", prefix="images")
    )
    make_s3(monkeypatch, seeded_bucket(["a.jpg"]))
    request = make_request(image_names=["a.jpg"])
    manifest = _manifest(
        fingerprint=request_fingerprint(request), task_id=77 if known_task else None
    )
    manifest.host = client.host
    manifest.creation_pending = False
    save_manifest(manifest)
    assert isinstance(client.api, FakeCvatApi)
    if known_task:
        with pytest.raises(Cveta2Error, match=r"77.*--resume"):
            upload_dataset(client, request)
        assert client.api.writes.created_tasks == []
    else:
        assert upload_dataset(client, request).task_id == 1
        assert len(client.api.writes.created_tasks) == 1


def test_nonfinite_semantic_property_is_not_serialized_as_upload_intent() -> None:
    annotations = rows()
    annotations["custom_numeric_property"] = float("inf")
    with pytest.raises(ValueError, match="JSON"):
        compute_fingerprint(["a.jpg"], [], [], annotations=annotations)


def test_disconnected_name_resolution_retains_cached_identity() -> None:
    client = CvatClient(CvatConfig())
    cached = [ProjectInfo(id=71, name="Canonical")]
    assert client.resolve_project_id(" canonical ", cached=cached) == 71


def test_disconnected_cache_miss_uses_filtered_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = CvatClient(CvatConfig())
    fallback = MagicMock(
        return_value=[
            ProjectInfo(id=71, name="CANONICAL"),
            ProjectInfo(id=72, name="other"),
        ]
    )
    monkeypatch.setattr(client, "list_projects", fallback)
    assert client.find_project_by_name("canonical", cached=[]).id == 71
    fallback.assert_called_once_with()


def test_missing_label_column_means_no_annotation_writes() -> None:
    from cveta2.services.upload import _verify_existing_shapes
    from cveta2.upload_manifest import validate_upload_boxes

    frame_only = pd.DataFrame([{"image_name": "a.jpg"}])
    validate_upload_boxes(pd.DataFrame())
    validate_upload_boxes(frame_only)
    api = MagicMock(spec=CvatApiPort)
    api.get_task_annotations.return_value = RawAnnotations(shapes=[])
    session = TaskWriteSession(
        api, 99, _name_to_frame={"a.jpg": 0}, _labels=[LabelInfo(id=7, name="car")]
    )
    client = CvatClient(CvatConfig(), api=api)
    assert client.upload_task_annotations(99, frame_only, session=session) == 0
    assert _verify_existing_shapes(99, frame_only, session) == 0
    api.put_task_shapes.assert_not_called()


def test_blank_labels_are_ignored_during_image_staging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cveta2.services.upload import _stage_images
    from tests.test_upload_service import make_client, make_s3, seeded_bucket

    client = make_client(
        cloud_storage=make_cs_info(bucket="test-bucket", prefix="images")
    )
    make_s3(monkeypatch, seeded_bucket(["a.jpg"]))
    request = UploadRequest(
        7,
        "project",
        "task",
        UploadPlan(
            pd.DataFrame([{"image_name": "a.jpg", "instance_label": "  "}]),
            ["a.jpg"],
            [],
        ),
        UploadOptions(),
    )
    staged = _stage_images(client, request)
    assert staged.task_image_names == ["images/a.jpg"]


def test_completion_save_failure_warns_without_reclassifying_success(
    monkeypatch: pytest.MonkeyPatch, capture_logs: list[str]
) -> None:
    from cveta2 import upload_manifest
    from cveta2.upload_manifest import new_manifest, save_manifest

    manifest = new_manifest(
        "", "identity", 7, "task", make_cs_info(), {}, [], host="http://cvat.invalid"
    )

    def denied(_path: Path, _data: bytes) -> None:
        raise PermissionError("completion bookkeeping denied")

    monkeypatch.setattr(upload_manifest, "replace_shared_bytes", denied)
    save_manifest(manifest)
    assert any("completion bookkeeping denied" in message for message in capture_logs)


@pytest.mark.parametrize("prefix", [" ", "XXX"])
def test_cloud_prefix_characters_are_not_strip_sets(prefix: str) -> None:
    from cveta2.services.upload import _frames_match

    assert _frames_match(["dir/a.jpg"], [f"{prefix}/dir/a.jpg"], prefix)
    assert not _frames_match(["dir/a.jpg"], ["XXXX/dir/a.jpg"], "")


def test_full_frame_paths_do_not_report_basename_uncertainty(
    capture_logs: list[str],
) -> None:
    from cveta2.services.upload import _frames_match

    assert _frames_match(["images/dir/a.jpg"], ["images/dir/a.jpg"], "images")
    assert not any("подтвердить невозможно" in message for message in capture_logs)


def test_preflight_unknown_task_identity_is_actionable_before_reads() -> None:
    from cveta2.services.upload import _preflight_resume_target
    from cveta2.upload_manifest import new_manifest
    from tests.test_upload_service import make_request

    client = MagicMock()
    manifest = new_manifest(
        "", "identity", 7, "task", make_cs_info(), {}, [], host="http://cvat.invalid"
    )
    with pytest.raises(Cveta2Error, match=r"(?i)id.*неизвестен"):
        _preflight_resume_target(client, make_request(image_names=[]), manifest)
    assert client.mock_calls == []
