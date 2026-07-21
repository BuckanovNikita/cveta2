"""Tests for cvat_sdk request builders."""

from __future__ import annotations

from cveta2._client.dtos import UploadTaskSpec
from cveta2._client.sdk_requests import build_data_request


def test_build_data_request_uses_predefined_sorting() -> None:
    spec = UploadTaskSpec(
        project_id=1,
        name="t",
        server_files=["p/b.jpg", "p/a.jpg"],
        cloud_storage_id=7,
    )
    request = build_data_request(spec)
    assert request.sorting_method.value == "predefined"
    assert request.server_files == ["p/b.jpg", "p/a.jpg"]
