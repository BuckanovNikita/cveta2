"""Tests for sync-root override in resolve_project_and_cloud_storage."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest
import yaml

from cveta2.commands._helpers import resolve_project_and_cloud_storage
from cveta2.exceptions import Cveta2Error
from cveta2.image_downloader import CloudStorageInfo

if TYPE_CHECKING:
    from pathlib import Path


def _cvat_cs_info() -> CloudStorageInfo:
    return CloudStorageInfo(
        id=7,
        bucket="cvat-bucket",
        prefix="cvat/prefix",
        endpoint_url="http://minio:9000",
    )


def _make_client(cs_info: CloudStorageInfo | None) -> MagicMock:
    client = MagicMock()
    client.resolve_project_id.return_value = 1
    client.detect_project_cloud_storage.return_value = cs_info
    return client


def _write_config(
    path: Path,
    monkeypatch: pytest.MonkeyPatch,
    sync_roots: dict[str, str] | None = None,
) -> None:
    data: dict[str, object] = {"cvat": {"host": "http://localhost:8080"}}
    if sync_roots:
        data["sync_roots"] = sync_roots
    cfg_path = path / "config.yaml"
    cfg_path.write_text(yaml.safe_dump(data), encoding="utf-8")
    monkeypatch.setenv("CVETA2_CONFIG", str(cfg_path))


def _resolve(
    client: MagicMock,
    sync_root: str | None = None,
) -> CloudStorageInfo | None:
    with patch("cveta2.commands._helpers.load_projects_cache", return_value=[]):
        _pid, _name, cs_info = resolve_project_and_cloud_storage(
            client, "my-project", sync_root=sync_root
        )
    return cs_info


def test_config_root_with_bucket_and_prefix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_config(
        tmp_path,
        monkeypatch,
        sync_roots={"my-project": "s3://custom-bucket/images/my_favourite"},
    )
    cs_info = _resolve(_make_client(_cvat_cs_info()))

    assert cs_info is not None
    assert cs_info.bucket == "custom-bucket"
    assert cs_info.prefix == "images/my_favourite"
    assert cs_info.id == 7
    assert cs_info.endpoint_url == "http://minio:9000"


def test_config_root_prefix_only_keeps_cvat_bucket(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_config(
        tmp_path,
        monkeypatch,
        sync_roots={"my-project": "images/my_favourite"},
    )
    cs_info = _resolve(_make_client(_cvat_cs_info()))

    assert cs_info is not None
    assert cs_info.bucket == "cvat-bucket"
    assert cs_info.prefix == "images/my_favourite"


def test_explicit_root_beats_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_config(
        tmp_path,
        monkeypatch,
        sync_roots={"my-project": "s3://config-bucket/config-prefix"},
    )
    cs_info = _resolve(
        _make_client(_cvat_cs_info()),
        sync_root="s3://cli-bucket/cli-prefix",
    )

    assert cs_info is not None
    assert cs_info.bucket == "cli-bucket"
    assert cs_info.prefix == "cli-prefix"


def test_no_root_passthrough(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_config(tmp_path, monkeypatch)
    original = _cvat_cs_info()
    cs_info = _resolve(_make_client(original))

    assert cs_info == original


def test_root_for_other_project_not_applied(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_config(
        tmp_path,
        monkeypatch,
        sync_roots={"other-project": "s3://custom-bucket/other"},
    )
    original = _cvat_cs_info()
    cs_info = _resolve(_make_client(original))

    assert cs_info == original


def test_invalid_root_raises_cveta2_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_config(tmp_path, monkeypatch)
    client = _make_client(_cvat_cs_info())

    with (
        patch("cveta2.commands._helpers.load_projects_cache", return_value=[]),
        pytest.raises(Cveta2Error, match="sync root"),
    ):
        resolve_project_and_cloud_storage(client, "my-project", sync_root="s3://")


def test_root_without_cloud_storage_returns_none(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_config(
        tmp_path,
        monkeypatch,
        sync_roots={"my-project": "s3://custom-bucket/images"},
    )
    cs_info = _resolve(_make_client(None))

    assert cs_info is None
