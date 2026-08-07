"""Tests for pure helper functions of the upload service."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from cveta2.exceptions import Cveta2Error
from cveta2.models import ProjectAnnotations
from cveta2.services.output import enrich_dataframe_paths, populate_record_paths
from cveta2.services.upload import (
    _warn_missing_images,
    build_search_dirs,
    build_upload_plan,
    filter_frames_by_labels,
    read_exclude_names,
    split_deleted_rows,
)
from tests.helpers import make_bbox, make_cs_info

# ---------------------------------------------------------------------------
# _read_exclude_names
# ---------------------------------------------------------------------------


def test_read_exclude_names_none_returns_empty() -> None:
    assert read_exclude_names(None) == set()


def test_read_exclude_names_empty_string_returns_empty() -> None:
    assert read_exclude_names("") == set()


def test_read_exclude_names_valid_csv(tmp_path: Path) -> None:
    csv = tmp_path / "ip.csv"
    csv.write_text("image_name,other\nfoo.jpg,1\nbar.jpg,2\n", encoding="utf-8")
    assert read_exclude_names(str(csv)) == {"foo.jpg", "bar.jpg"}


def test_read_exclude_names_missing_file(tmp_path: Path) -> None:
    """The error must name the file; ``Cveta2Error(None)`` stringifies to "None"."""
    with pytest.raises(Cveta2Error, match=r"nope\.csv"):
        read_exclude_names(str(tmp_path / "nope.csv"))


def test_read_exclude_names_csv_without_image_name(tmp_path: Path) -> None:
    csv = tmp_path / "no_col.csv"
    csv.write_text("col_a,col_b\n1,2\n", encoding="utf-8")
    assert read_exclude_names(str(csv)) == set()


# ---------------------------------------------------------------------------
# split_deleted_rows
# ---------------------------------------------------------------------------


def test_split_deleted_rows_no_column() -> None:
    df = pd.DataFrame({"image_name": ["a.jpg", "b.jpg"]})
    df_normal, names = split_deleted_rows(df)
    assert names == []
    assert df_normal.equals(df)


def test_split_deleted_rows_mixed_shapes_keeps_csv_order() -> None:
    df = pd.DataFrame(
        {
            "image_name": ["a.jpg", "c.jpg", "b.jpg", "c.jpg"],
            "instance_shape": ["box", "deleted", "deleted", "deleted"],
        }
    )
    df_normal, names = split_deleted_rows(df)
    assert names == ["c.jpg", "b.jpg"]
    assert df_normal["image_name"].tolist() == ["a.jpg"]


def test_split_deleted_rows_none_deleted() -> None:
    df = pd.DataFrame(
        {
            "image_name": ["a.jpg"],
            "instance_shape": ["box"],
        }
    )
    df_normal, names = split_deleted_rows(df)
    assert names == []
    assert len(df_normal) == 1


# ---------------------------------------------------------------------------
# build_upload_plan
# ---------------------------------------------------------------------------


def test_build_upload_plan_preserves_csv_order() -> None:
    df = pd.DataFrame(
        {
            "image_name": ["b.jpg", "a.jpg", "b.jpg", "c.jpg"],
            "instance_label": ["Edge", "Edge", "Edge", "Edge"],
        }
    )
    plan = build_upload_plan(df, [], labels=["Edge"])
    assert plan.image_names == ["b.jpg", "a.jpg", "c.jpg"]


def test_build_upload_plan_raises_when_empty() -> None:
    df = pd.DataFrame({"image_name": [], "instance_label": []})
    with pytest.raises(Cveta2Error, match="после фильтрации"):
        build_upload_plan(df, [], labels=["Edge"])


def _plan_input_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "image_name": ["a.jpg", "b.jpg", "c.jpg"],
            "instance_label": ["Edge", None, "Edge"],
        }
    )


def test_build_upload_plan_skips_unannotated_frames_by_default() -> None:
    """The default must exclude NaN-label frames.

    Every earlier call either passed ``include_unannotated`` explicitly or
    used a frame set without NaN labels, so flipping the default was
    invisible.
    """
    plan = build_upload_plan(_plan_input_df(), [], labels=["Edge"])

    assert plan.image_names == ["a.jpg", "c.jpg"]


def test_build_upload_plan_forwards_include_unannotated() -> None:
    """``include_unannotated=True`` must reach ``filter_frames_by_labels``.

    Dropping the keyword, or passing ``None`` for it, both fall back to
    the falsy default — indistinguishable unless a NaN-label frame is
    present and the flag is on.
    """
    plan = build_upload_plan(
        _plan_input_df(), [], labels=["Edge"], include_unannotated=True
    )

    assert plan.image_names == ["a.jpg", "b.jpg", "c.jpg"]


def test_build_upload_plan_forwards_exclude_names() -> None:
    """``exclude_names`` must reach the filter, not be dropped on the way."""
    plan = build_upload_plan(
        _plan_input_df(), [], labels=["Edge"], exclude_names={"a.jpg"}
    )

    assert plan.image_names == ["c.jpg"]


def test_build_upload_plan_keeps_deleted_names_without_images() -> None:
    """Deleted-only input is a valid plan and carries the names through.

    Nothing asserted ``UploadPlan.deleted_names``, and no test reached the
    branch where the image list is empty but deletions remain.
    """
    empty = pd.DataFrame({"image_name": [], "instance_label": []})

    plan = build_upload_plan(empty, ["gone.jpg"], labels=["Edge"])

    assert plan.image_names == []
    assert plan.deleted_names == ["gone.jpg"]


# ---------------------------------------------------------------------------
# filter_frames_by_labels
# ---------------------------------------------------------------------------


def _frames_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "image_name": ["a.jpg", "a.jpg", "b.jpg", "c.jpg"],
            "instance_label": ["Edge", "Other", "Other", None],
        }
    )


def test_filter_frames_keeps_all_rows_of_selected_frame() -> None:
    result = filter_frames_by_labels(_frames_df(), ["Edge"])
    assert result["image_name"].tolist() == ["a.jpg", "a.jpg"]
    assert set(result["instance_label"]) == {"Edge", "Other"}


def test_filter_frames_excludes_frame_with_only_unselected_labels() -> None:
    result = filter_frames_by_labels(_frames_df(), ["Edge"])
    assert "b.jpg" not in set(result["image_name"])


def test_filter_frames_include_unannotated_selects_nan_label_frames() -> None:
    result = filter_frames_by_labels(_frames_df(), [], include_unannotated=True)
    assert result["image_name"].tolist() == ["c.jpg"]
    assert result["instance_label"].isna().all()


def test_filter_frames_exclude_names_removes_frames() -> None:
    result = filter_frames_by_labels(
        _frames_df(), ["Edge", "Other"], exclude_names={"a.jpg"}
    )
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
# enrich_dataframe_paths
# ---------------------------------------------------------------------------


def test_enrich_paths_adds_columns() -> None:
    df = pd.DataFrame({"image_name": ["a.jpg", "b.jpg"], "label": ["x", "y"]})
    found = {"a.jpg": Path("/data/a.jpg")}
    result = enrich_dataframe_paths(df, make_cs_info(), found)
    assert "s3_image_path" in result.columns
    assert "image_path" in result.columns
    assert result.iloc[0]["s3_image_path"] == "images/a.jpg"
    assert result.iloc[0]["image_path"] == str(Path("/data/a.jpg").resolve())
    assert pd.isna(result.iloc[1]["image_path"])


def test_enrich_paths_with_server_file_mapping() -> None:
    df = pd.DataFrame({"image_name": ["a.jpg"]})
    mapping = {"a.jpg": "2026-01/a.jpg"}
    result = enrich_dataframe_paths(df, make_cs_info(), {}, mapping)
    assert result.iloc[0]["s3_image_path"] == "images/2026-01/a.jpg"


# ---------------------------------------------------------------------------
# build_search_dirs
# ---------------------------------------------------------------------------


def test_build_search_dirs_with_arg(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    img_dir = tmp_path / "imgs"
    img_dir.mkdir()
    monkeypatch.setenv("CVETA2_CONFIG", str(tmp_path / "nonexistent.yaml"))
    dirs = build_search_dirs([str(img_dir)], "proj")
    assert img_dir.resolve() in dirs


def test_build_search_dirs_wraps_a_bare_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A single ``str``/``Path`` is wrapped, not discarded.

    Every earlier call passed a list, so the ``isinstance`` branch that
    wraps a scalar never ran and dropping its assignment changed nothing.
    """
    img_dir = tmp_path / "imgs"
    img_dir.mkdir()
    monkeypatch.setenv("CVETA2_CONFIG", str(tmp_path / "nonexistent.yaml"))

    assert build_search_dirs(str(img_dir), "proj") == [img_dir.resolve()]


def test_build_search_dirs_none_warns(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capture_logs: list[str],
) -> None:
    monkeypatch.setenv("CVETA2_CONFIG", str(tmp_path / "nonexistent.yaml"))
    dirs = build_search_dirs(None, "proj")
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
    dirs = build_search_dirs(None, "my-project")
    assert cache_dir in dirs


# ---------------------------------------------------------------------------
# populate_record_paths
# ---------------------------------------------------------------------------


def test_populate_paths_nested_frame_builds_full_s3_key() -> None:
    ann = make_bbox(image_name="sub1/sub2/img.jpg")
    result = ProjectAnnotations(annotations=[ann], deleted_images=[])

    populate_record_paths(result, make_cs_info(prefix="images"), None)

    assert ann.image_name == "img.jpg"
    assert ann.s3_image_path == "images/sub1/sub2/img.jpg"


def test_populate_paths_flat_frame_unchanged() -> None:
    ann = make_bbox(image_name="img.jpg")
    result = ProjectAnnotations(annotations=[ann], deleted_images=[])

    populate_record_paths(result, make_cs_info(prefix="images"), None)

    assert ann.s3_image_path == "images/img.jpg"


def test_populate_paths_local_mirrors_s3_by_default(tmp_path: Path) -> None:
    nested = tmp_path / "sub" / "img.jpg"
    nested.parent.mkdir(parents=True)
    nested.write_bytes(b"x")
    ann = make_bbox(image_name="sub/img.jpg")
    result = ProjectAnnotations(annotations=[ann], deleted_images=[])

    populate_record_paths(result, make_cs_info(prefix="images"), tmp_path)

    assert ann.image_path == str(nested.resolve())


def test_populate_paths_local_nested_with_ignored_prefix(tmp_path: Path) -> None:
    nested = tmp_path / "projA" / "2026-01" / "img.jpg"
    nested.parent.mkdir(parents=True)
    nested.write_bytes(b"x")
    ann = make_bbox(image_name="2026-01/img.jpg")
    result = ProjectAnnotations(annotations=[ann], deleted_images=[])

    populate_record_paths(
        result,
        make_cs_info(prefix="data/projA"),
        tmp_path,
        ignored_prefix="data",
    )

    assert ann.s3_image_path == "data/projA/2026-01/img.jpg"
    assert ann.image_path == str(nested.resolve())
