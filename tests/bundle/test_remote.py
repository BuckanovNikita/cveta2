"""Remote adapters tested without requiring the optional ClearML SDK."""

import json
import sys
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from cveta2.adapters.class_api.http import HttpClassApi
from cveta2.adapters.clearml.bundle import ClearMLStore, S3Roots
from cveta2.domain.bundle.models import UploadCancelled, UploadError


@pytest.fixture
def http_api() -> Iterator[str]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            assert self.headers.get("Authorization") is None
            if self.path == "/error":
                self.send_error(503)
                return
            self.send_response(200)
            self.end_headers()
            payload = {
                "/classes": json.dumps(
                    [
                        {
                            "id": 999,
                            "number": 7,
                            "name": "cat",
                            "techClass": False,
                            "isPeriodical": False,
                            "isCritical": False,
                            "threshold": 0.5,
                        }
                    ]
                ),
                "/bad-json": "not json",
                "/bad-schema": '[{"id": 7}]',
                "/wrong-shape": "{}",
            }[self.path]
            self.wfile.write(payload.encode())

        def log_message(self, *_args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        worker.join()
        server.server_close()


def test_http_fetch_uses_number_and_unauthenticated_real_get(http_api: str) -> None:
    records = HttpClassApi(timeout=2).fetch(http_api + "/classes")
    assert [(record.id, record.number, record.name) for record in records] == [
        (999, 7, "cat")
    ]


@pytest.mark.parametrize(
    "route", ["/error", "/bad-json", "/bad-schema", "/wrong-shape"]
)
def test_http_errors_are_explicit(http_api: str, route: str) -> None:
    with pytest.raises(UploadError):
        HttpClassApi().fetch(http_api + route)


@pytest.mark.parametrize(
    "url", ["file:///etc/passwd", "https://user:secret@example.com/api"]
)
def test_http_rejects_credentials_and_non_http(url: str) -> None:
    with pytest.raises(UploadError):
        HttpClassApi().fetch(url)


@pytest.fixture
def sdk(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> SimpleNamespace:
    parent = Mock()
    parent.id, parent.project, parent.name, parent.version = (
        "parent",
        "project",
        "dataset",
        "1.0.0",
    )
    parent.is_final.return_value = True
    parent.list_files.return_value = ["dataset.yaml", "old.csv", "external.jpg"]
    parent.get_local_copy.return_value = str(tmp_path)
    (tmp_path / "dataset.yaml").write_text("classes: {}")
    factory = Mock()
    factory.list_datasets.return_value = [
        {"id": "parent", "project": "project", "name": "dataset"}
    ]
    factory.get.return_value = parent
    child = Mock()
    child.id, child.version = "child", "1.0.1"
    child.list_files.side_effect = [
        ["old.csv", "external.jpg"],
        [],
        ["dataset.csv", "dataset.yaml", "tasks.yaml"],
        ["dataset.csv", "dataset.yaml", "tasks.yaml"],
        ["dataset.csv", "dataset.yaml", "tasks.yaml"],
    ]
    child.upload.return_value = True
    child.is_dirty.return_value = False
    child.finalize.return_value = True
    child.is_final.return_value = True
    factory.create.return_value = child
    storage = Mock()
    storage.list.return_value = ["s3://bucket/images/a.jpg"]
    monkeypatch.setitem(
        sys.modules, "clearml", SimpleNamespace(Dataset=factory, StorageManager=storage)
    )
    return SimpleNamespace(factory=factory, parent=parent, child=child, storage=storage)


def test_names_are_exact_project_finalized_and_not_archived(
    sdk: SimpleNamespace,
) -> None:
    sdk.factory.list_datasets.return_value += [
        {"project": "project/child", "name": "wrong"},
        {"project": "project", "name": "dataset"},
        {"project": "project", "name": "other"},
    ]
    assert ClearMLStore().names("project") == ["dataset", "other"]
    sdk.factory.list_datasets.assert_called_once_with(
        dataset_project="project",
        only_completed=True,
        recursive_project_search=False,
        include_archived=False,
    )
    sdk.factory.create.assert_not_called()


def test_latest_downloads_only_metadata_without_links(
    sdk: SimpleNamespace, tmp_path: Path
) -> None:
    result = ClearMLStore().latest("project", "dataset")
    assert result is not None
    assert result.dataset_id == "parent"
    assert result.metadata_path == tmp_path / "dataset.yaml"
    sdk.factory.get.assert_called_once_with(
        dataset_project="project",
        dataset_name="dataset",
        only_completed=True,
        auto_create=False,
        include_archived=False,
    )
    sdk.parent.get_local_copy.assert_called_once_with(
        files=["dataset.yaml"], use_soft_links=False, raise_on_error=True
    )
    sdk.parent.remove_files.assert_not_called()


def test_latest_absence_is_determined_by_successful_listing(
    sdk: SimpleNamespace,
) -> None:
    sdk.factory.list_datasets.return_value = []
    assert ClearMLStore().latest("project", "dataset") is None
    sdk.factory.get.assert_not_called()


@pytest.mark.parametrize("operation", ["list_datasets", "get"])
def test_latest_never_treats_sdk_failure_as_absence(
    sdk: SimpleNamespace, operation: str
) -> None:
    getattr(sdk.factory, operation).side_effect = RuntimeError("authentication failed")
    with pytest.raises(UploadError, match="ClearML"):
        ClearMLStore().latest("project", "dataset")


@pytest.mark.parametrize(
    ("attribute", "value"), [("project", "other"), ("name", "other")]
)
def test_latest_rejects_wrong_identity(
    sdk: SimpleNamespace, attribute: str, value: Any
) -> None:
    setattr(sdk.parent, attribute, value)
    with pytest.raises(UploadError):
        ClearMLStore().latest("project", "dataset")


def test_latest_rejects_unfinalized(sdk: SimpleNamespace) -> None:
    sdk.parent.is_final.return_value = False
    with pytest.raises(UploadError):
        ClearMLStore().latest("project", "dataset")


def test_latest_does_not_download_when_metadata_absent(sdk: SimpleNamespace) -> None:
    sdk.parent.list_files.return_value = ["dataset.csv"]
    result = ClearMLStore().latest("project", "dataset")
    assert result is not None
    assert result.metadata_path is None
    sdk.parent.get_local_copy.assert_not_called()


@pytest.fixture
def bundle(tmp_path: Path) -> Path:
    for filename in ("dataset.csv", "dataset.yaml", "tasks.yaml", "report.json"):
        (tmp_path / filename).write_text(filename)
    return tmp_path


def test_publication_replaces_child_manifest_preserves_parent(
    sdk: SimpleNamespace, bundle: Path
) -> None:
    result = ClearMLStore().publish("project", "dataset", "parent", bundle)
    assert result.dataset_id == "child"
    assert result.version == "1.0.1"
    sdk.factory.create.assert_called_once_with(
        dataset_project="project", dataset_name="dataset", parent_datasets=["parent"]
    )
    sdk.child.remove_files.assert_called_once_with(dataset_path="*", recursive=True)
    assert [call.kwargs["path"] for call in sdk.child.add_files.call_args_list] == [
        str(bundle / name) for name in ("dataset.csv", "dataset.yaml", "tasks.yaml")
    ]
    sdk.child.upload.assert_called_once_with(retries=0)
    sdk.child.finalize.assert_called_once_with(raise_on_error=True, auto_upload=False)
    sdk.parent.remove_files.assert_not_called()
    sdk.parent.add_files.assert_not_called()
    sdk.parent.upload.assert_not_called()


@pytest.mark.parametrize("stage", ["upload", "finalize"])
@pytest.mark.parametrize("failure", [False, RuntimeError("network broke")])
def test_publication_failure_reports_created_id_without_retry(
    sdk: SimpleNamespace, bundle: Path, stage: str, failure: Any
) -> None:
    operation = getattr(sdk.child, stage)
    if isinstance(failure, Exception):
        operation.side_effect = failure
    else:
        operation.return_value = failure
    with pytest.raises(UploadError, match="child"):
        ClearMLStore().publish("project", "dataset", "parent", bundle)
    sdk.factory.create.assert_called_once()
    operation.assert_called_once()
    if stage == "upload":
        sdk.child.finalize.assert_not_called()


@pytest.mark.parametrize("stage", ["upload", "finalize"])
def test_interrupted_publication_retains_created_id_and_does_not_retry(
    sdk: SimpleNamespace, bundle: Path, stage: str
) -> None:
    operation = getattr(sdk.child, stage)
    operation.side_effect = KeyboardInterrupt
    with pytest.raises(UploadCancelled, match="child") as caught:
        ClearMLStore().publish("project", "dataset", "parent", bundle)
    assert "inspect" in str(caught.value).lower()
    operation.assert_called_once()
    sdk.factory.create.assert_called_once()
    if stage == "upload":
        sdk.child.finalize.assert_not_called()


def test_publication_rejects_manifest_survivors(
    sdk: SimpleNamespace, bundle: Path
) -> None:
    sdk.child.list_files.side_effect = [["external.jpg"], ["external.jpg"]]
    with pytest.raises(UploadError, match="child"):
        ClearMLStore().publish("project", "dataset", "parent", bundle)
    sdk.child.upload.assert_not_called()


def test_missing_bundle_file_blocks_before_creation(
    sdk: SimpleNamespace, bundle: Path
) -> None:
    (bundle / "tasks.yaml").unlink()
    with pytest.raises(UploadError):
        ClearMLStore().publish("project", "dataset", None, bundle)
    sdk.factory.create.assert_not_called()


def test_s3_checks_prefix_listing_without_object_probes(sdk: SimpleNamespace) -> None:
    S3Roots().check_root("s3://bucket/images")
    sdk.storage.list.assert_called_once_with(
        remote_url="s3://bucket/images/", return_full_path=True
    )
    sdk.storage.exists_file.assert_not_called()
    sdk.storage.get_file_size_bytes.assert_not_called()


@pytest.mark.parametrize(
    "objects",
    [
        None,
        [],
        ["s3://bucket/images-other/a.jpg"],
        ["s3://other/images/a.jpg"],
        ["s3://bucket/images"],
    ],
)
def test_s3_missing_or_sibling_prefix_fails(sdk: SimpleNamespace, objects: Any) -> None:
    sdk.storage.list.return_value = objects
    with pytest.raises(UploadError):
        S3Roots().check_root("s3://bucket/images")


def test_s3_bucket_listing_may_be_empty(sdk: SimpleNamespace) -> None:
    sdk.storage.list.return_value = []
    S3Roots().check_root("s3://bucket")


def test_s3_sdk_error_is_actionable(sdk: SimpleNamespace) -> None:
    sdk.storage.list.side_effect = RuntimeError("access denied")
    with pytest.raises(UploadError, match="S3"):
        S3Roots().check_root("s3://bucket/images")


def test_missing_sdk_is_actionable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "clearml", None)
    with pytest.raises(UploadError, match="clearml"):
        ClearMLStore().names("project")


def test_sdk_upload_none_success_requires_no_pending_files(
    sdk: SimpleNamespace, bundle: Path
) -> None:
    # ClearML's normal successful upload returns None, despite its bool annotation.
    sdk.child.upload.return_value = None
    assert (
        ClearMLStore().publish("project", "dataset", None, bundle).dataset_id == "child"
    )
    assert sdk.factory.create.call_args.kwargs["parent_datasets"] == []


def test_dirty_upload_blocks_finalization(sdk: SimpleNamespace, bundle: Path) -> None:
    sdk.child.is_dirty.return_value = True
    with pytest.raises(UploadError, match="child"):
        ClearMLStore().publish("project", "dataset", "parent", bundle)
    sdk.child.finalize.assert_not_called()


def test_upload_losing_a_file_blocks_finalization(
    sdk: SimpleNamespace, bundle: Path
) -> None:
    sdk.child.list_files.side_effect = [
        [],
        [],
        ["dataset.csv", "dataset.yaml", "tasks.yaml"],
        ["dataset.csv", "dataset.yaml"],
    ]
    with pytest.raises(UploadError, match="child"):
        ClearMLStore().publish("project", "dataset", None, bundle)
    sdk.child.finalize.assert_not_called()


def test_false_final_state_is_failure(sdk: SimpleNamespace, bundle: Path) -> None:
    sdk.child.is_final.return_value = False
    with pytest.raises(UploadError, match="child"):
        ClearMLStore().publish("project", "dataset", None, bundle)


def test_parent_id_returned_as_child_is_never_mutated(
    sdk: SimpleNamespace, bundle: Path
) -> None:
    sdk.child.id = "parent"
    with pytest.raises(UploadError, match="refusing mutation"):
        ClearMLStore().publish("project", "dataset", "parent", bundle)
    sdk.child.list_files.assert_not_called()
    sdk.child.remove_files.assert_not_called()
    sdk.child.add_files.assert_not_called()


@pytest.mark.parametrize(
    "url", ["https://user:secret@example.com/", "file:///etc/passwd"]
)
def test_redirect_rejects_credential_or_non_http_target(url: str) -> None:
    from http.client import HTTPMessage
    from io import BytesIO
    from urllib.request import Request

    from cveta2.adapters.class_api.http import _PublicRedirect

    with pytest.raises(UploadError):
        _PublicRedirect().redirect_request(
            Request("https://example.com"), BytesIO(), 302, "Found", HTTPMessage(), url
        )


def test_http_timeout_and_truncated_response_are_upload_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from http.client import IncompleteRead

    opener = Mock()
    monkeypatch.setattr(
        "cveta2.adapters.class_api.http.build_opener", lambda *_args: opener
    )
    for failure in (TimeoutError("too slow"), IncompleteRead(b"partial")):
        opener.open.side_effect = failure
        with pytest.raises(UploadError, match="request failed"):
            HttpClassApi(timeout=0.1).fetch("http://example.test/classes")
        assert opener.open.call_args.kwargs["timeout"] == 0.1


@pytest.mark.parametrize(
    "root",
    [
        "s3://bucket/a/../b",
        "s3://bucket/a//b",
        "s3://bucket:9000/a",
        "s3://user@bucket/a",
    ],
)
def test_invalid_s3_roots_fail_before_sdk_call(sdk: SimpleNamespace, root: str) -> None:
    with pytest.raises(UploadError):
        S3Roots().check_root(root)
    sdk.storage.list.assert_not_called()
