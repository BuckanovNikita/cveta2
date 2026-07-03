"""Tests for pure helper functions in cveta2/commands/upload.py."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from cveta2.commands.upload import (
    _NO_ANNOTATION_LABEL,
    _build_search_dirs,
    _enrich_paths,
    _extract_deleted_names,
    _filter_frames_by_labels,
    _read_exclude_names,
    _warn_missing_images,
)
from cveta2.image_downloader import CloudStorageInfo

# ---------------------------------------------------------------------------
# _read_exclude_names
# ---------------------------------------------------------------------------


def test_read_exclude_names_none_returns_empty() -> None:
    assert _read_exclude_names(None) == set()


def test_read_exclude_names_empty_string_returns_empty() -> None:
    assert _read_exclude_names("") == set()


def test_read_exclude_names_valid_csv(tmp_path: Path) -> None:
    csv = tmp_path / "ip.csv"
    csv.write_text("image_name,other\nfoo.jpg,1\nbar.jpg,2\n", encoding="utf-8")
    assert _read_exclude_names(str(csv)) == {"foo.jpg", "bar.jpg"}


def test_read_exclude_names_missing_file(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        _read_exclude_names(str(tmp_path / "nope.csv"))


def test_read_exclude_names_csv_without_image_name(tmp_path: Path) -> None:
    csv = tmp_path / "no_col.csv"
    csv.write_text("col_a,col_b\n1,2\n", encoding="utf-8")
    assert _read_exclude_names(str(csv)) == set()


# ---------------------------------------------------------------------------
# _extract_deleted_names
# ---------------------------------------------------------------------------


def test_extract_deleted_names_no_column() -> None:
    df = pd.DataFrame({"image_name": ["a.jpg", "b.jpg"]})
    assert _extract_deleted_names(df) == set()


def test_extract_deleted_names_mixed_shapes() -> None:
    df = pd.DataFrame(
        {
            "image_name": ["a.jpg", "b.jpg", "c.jpg"],
            "instance_shape": ["box", "deleted", "deleted"],
        }
    )
    assert _extract_deleted_names(df) == {"b.jpg", "c.jpg"}


def test_extract_deleted_names_none_deleted() -> None:
    df = pd.DataFrame(
        {
            "image_name": ["a.jpg"],
            "instance_shape": ["box"],
        }
    )
    assert _extract_deleted_names(df) == set()


# ---------------------------------------------------------------------------
# _filter_frames_by_labels
# ---------------------------------------------------------------------------


def _frames_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "image_name": ["a.jpg", "a.jpg", "b.jpg", "c.jpg"],
            "instance_label": ["Edge", "Other", "Other", None],
        }
    )


def test_filter_frames_keeps_all_rows_of_selected_frame() -> None:
    result = _filter_frames_by_labels(_frames_df(), ["Edge"], set())
    assert result["image_name"].tolist() == ["a.jpg", "a.jpg"]
    assert set(result["instance_label"]) == {"Edge", "Other"}


def test_filter_frames_excludes_frame_with_only_unselected_labels() -> None:
    result = _filter_frames_by_labels(_frames_df(), ["Edge"], set())
    assert "b.jpg" not in set(result["image_name"])


def test_filter_frames_sentinel_includes_nan_label_frames() -> None:
    result = _filter_frames_by_labels(_frames_df(), [_NO_ANNOTATION_LABEL], set())
    assert result["image_name"].tolist() == ["c.jpg"]
    assert result["instance_label"].isna().all()


def test_filter_frames_exclude_names_removes_frames() -> None:
    result = _filter_frames_by_labels(_frames_df(), ["Edge", "Other"], {"a.jpg"})
    assert set(result["image_name"]) == {"b.jpg"}


# ---------------------------------------------------------------------------
# _warn_missing_images
# ---------------------------------------------------------------------------


def test_warn_missing_empty_no_log(capture_logs: list[str]) -> None:
    _warn_missing_images([])
    assert not capture_logs


def test_warn_missing_few_items_all_shown(capture_logs: list[str]) -> None:
    _warn_missing_images(["a.jpg", "b.jpg"])
    assert len(capture_logs) == 1
    assert "a.jpg" in capture_logs[0]
    assert "b.jpg" in capture_logs[0]
    assert "и ещё" not in capture_logs[0]


def test_warn_missing_many_items_truncated(capture_logs: list[str]) -> None:
    names = [f"img{i}.jpg" for i in range(15)]
    _warn_missing_images(names)
    assert len(capture_logs) == 1
    assert "и ещё 5" in capture_logs[0]


# ---------------------------------------------------------------------------
# _enrich_paths
# ---------------------------------------------------------------------------


def _make_cs_info() -> CloudStorageInfo:
    return CloudStorageInfo(
        id=1, bucket="test-bucket", prefix="images", endpoint_url="http://s3"
    )


def test_enrich_paths_adds_columns() -> None:
    df = pd.DataFrame({"image_name": ["a.jpg", "b.jpg"], "label": ["x", "y"]})
    found = {"a.jpg": Path("/data/a.jpg")}
    result = _enrich_paths(df, _make_cs_info(), found)
    assert "s3_path" in result.columns
    assert "image_path" in result.columns
    assert result.iloc[0]["s3_path"] == "images/a.jpg"
    assert result.iloc[0]["image_path"] == str(Path("/data/a.jpg").resolve())
    assert pd.isna(result.iloc[1]["image_path"])


def test_enrich_paths_with_server_file_mapping() -> None:
    df = pd.DataFrame({"image_name": ["a.jpg"]})
    mapping = {"a.jpg": "2026-01/a.jpg"}
    result = _enrich_paths(df, _make_cs_info(), {}, mapping)
    assert result.iloc[0]["s3_path"] == "images/2026-01/a.jpg"


# ---------------------------------------------------------------------------
# _build_search_dirs
# ---------------------------------------------------------------------------


def test_build_search_dirs_with_arg(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    img_dir = tmp_path / "imgs"
    img_dir.mkdir()
    monkeypatch.setenv("CVETA2_CONFIG", str(tmp_path / "nonexistent.yaml"))
    dirs = _build_search_dirs(str(img_dir), "proj")
    assert img_dir.resolve() in dirs


def test_build_search_dirs_none_warns(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capture_logs: list[str],
) -> None:
    monkeypatch.setenv("CVETA2_CONFIG", str(tmp_path / "nonexistent.yaml"))
    dirs = _build_search_dirs(None, "proj")
    assert dirs == []
    assert any("Не указан --image-dir" in m for m in capture_logs)


def test_build_search_dirs_includes_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(f"image_cache:\n  my-project: {cache_dir}\n", encoding="utf-8")
    monkeypatch.setenv("CVETA2_CONFIG", str(cfg_path))
    dirs = _build_search_dirs(None, "my-project")
    assert cache_dir in dirs
