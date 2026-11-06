"""Tests for pure helper functions of the upload service."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from cveta2.adapters.config.settings import cache_dir_for_project
from cveta2.adapters.files.dataset import enrich_dataframe_paths, populate_record_paths
from cveta2.application.use_cases.upload import (
    _warn_missing_images,
    build_upload_plan,
    filter_frames_by_labels,
    split_deleted_rows,
)
from cveta2.composition.workflows import build_search_dirs, read_exclude_names
from cveta2.domain.errors import Cveta2Error
from cveta2.domain.models import ProjectAnnotations
from tests.helpers import make_bbox, make_cs_info

# ---------------------------------------------------------------------------
# read_exclude_names
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", [None, ""], ids=["none", "empty_string"])
def test_read_exclude_names_without_a_path_is_empty(value: str | None) -> None:
    assert read_exclude_names(value) == set()


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("image_name,other\nfoo.jpg,1\nbar.jpg,2\n", {"foo.jpg", "bar.jpg"}),
        # Image identifiers are kept literally, not parsed as numbers or NaN.
        ("image_name,task_id\n001,1\n", {"001"}),
        ("image_name,task_id\nNA,1\n", {"NA"}),
        ("col_a,col_b\n1,2\n", set()),
    ],
    ids=["valid", "leading_zeros", "na_literal", "no_image_name_column"],
)
def test_read_exclude_names_reads_the_image_name_column(
    tmp_path: Path, content: str, expected: set[str]
) -> None:
    csv = tmp_path / "in_progress.csv"
    csv.write_text(content, encoding="utf-8")
    assert read_exclude_names(str(csv)) == expected


def test_read_exclude_names_missing_file(tmp_path: Path) -> None:
    """The error must name the file; ``Cveta2Error(None)`` stringifies to "None"."""
    with pytest.raises(Cveta2Error, match=r"nope\.csv"):
        read_exclude_names(str(tmp_path / "nope.csv"))


# ---------------------------------------------------------------------------
# split_deleted_rows
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("columns", "expected_normal", "expected_deleted"),
    [
        ({"image_name": ["a.jpg", "b.jpg"]}, ["a.jpg", "b.jpg"], []),
        ({"image_name": ["a.jpg"], "instance_shape": ["box"]}, ["a.jpg"], []),
        (
            {
                "image_name": ["a.jpg", "c.jpg", "b.jpg", "c.jpg"],
                "instance_shape": ["box", "deleted", "deleted", "deleted"],
            },
            ["a.jpg"],
            ["c.jpg", "b.jpg"],
        ),
    ],
    ids=["no_shape_column", "none_deleted", "mixed_keeps_csv_order"],
)
def test_split_deleted_rows(
    columns: dict[str, list[str]],
    expected_normal: list[str],
    expected_deleted: list[str],
) -> None:
    df = pd.DataFrame(columns)
    df_normal, names = split_deleted_rows(df)
    assert names == expected_deleted
    assert df_normal["image_name"].tolist() == expected_normal


# ---------------------------------------------------------------------------
# build_upload_plan
# ---------------------------------------------------------------------------


def _plan_input_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "image_name": ["a.jpg", "b.jpg", "c.jpg"],
            "instance_label": ["Edge", None, "Edge"],
        }
    )


def _empty_df() -> pd.DataFrame:
    return pd.DataFrame({"image_name": [], "instance_label": []})


@pytest.mark.parametrize(
    ("df", "deleted", "unannotated", "exclude", "expected_images", "expected_deleted"),
    [
        (
            pd.DataFrame(
                {
                    "image_name": ["b.jpg", "a.jpg", "b.jpg", "c.jpg"],
                    "instance_label": ["Edge"] * 4,
                }
            ),
            [],
            False,
            None,
            ["b.jpg", "a.jpg", "c.jpg"],
            [],
        ),
        # The default must exclude NaN-label frames.
        (_plan_input_df(), [], False, None, ["a.jpg", "c.jpg"], []),
        # ``include_unannotated=True`` must reach ``filter_frames_by_labels``.
        (
            _plan_input_df(),
            [],
            True,
            None,
            ["a.jpg", "b.jpg", "c.jpg"],
            [],
        ),
        (_plan_input_df(), [], False, {"a.jpg"}, ["c.jpg"], []),
        # Deleted-only input is a valid plan and carries the names through.
        (_empty_df(), ["gone.jpg"], False, None, [], ["gone.jpg"]),
        (
            _plan_input_df(),
            ["busy.jpg", "gone.jpg"],
            False,
            {"a.jpg", "busy.jpg"},
            ["c.jpg"],
            ["gone.jpg"],
        ),
    ],
    ids=[
        "preserves_csv_order",
        "skips_unannotated_by_default",
        "forwards_include_unannotated",
        "forwards_exclude_names",
        "deleted_only",
        "exclusions_also_remove_deleted",
    ],
)
def test_build_upload_plan(  # noqa: PLR0913, PLR0917
    df: pd.DataFrame,
    deleted: list[str],
    unannotated: bool,  # noqa: FBT001
    exclude: set[str] | None,
    expected_images: list[str],
    expected_deleted: list[str],
) -> None:
    plan = build_upload_plan(
        df,
        deleted,
        labels=["Edge"],
        include_unannotated=unannotated,
        exclude_names=exclude,
    )
    assert plan.image_names == expected_images
    assert plan.deleted_names == expected_deleted


def test_build_upload_plan_raises_when_empty() -> None:
    with pytest.raises(Cveta2Error, match="после фильтрации"):
        build_upload_plan(_empty_df(), [], labels=["Edge"])


def test_excluding_every_deleted_frame_leaves_nothing_to_upload() -> None:
    with pytest.raises(Cveta2Error):
        build_upload_plan(
            _empty_df(), ["busy.jpg"], labels=[], exclude_names={"busy.jpg"}
        )


# ---------------------------------------------------------------------------
# filter_frames_by_labels
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("labels", "unannotated", "exclude", "expected"),
    [
        # Every row of a selected frame is kept; frames with only other labels go.
        (["Edge"], False, None, [("a.jpg", "Edge"), ("a.jpg", "Other")]),
        ([], True, None, [("c.jpg", None)]),
        (["Edge", "Other"], False, {"a.jpg"}, [("b.jpg", "Other")]),
    ],
    ids=["keeps_all_rows_of_selected_frame", "unannotated", "exclude_names"],
)
def test_filter_frames_by_labels(
    labels: list[str],
    unannotated: bool,  # noqa: FBT001
    exclude: set[str] | None,
    expected: list[tuple[str, str | None]],
) -> None:
    frames = pd.DataFrame(
        {
            "image_name": ["a.jpg", "a.jpg", "b.jpg", "c.jpg"],
            "instance_label": ["Edge", "Other", "Other", None],
        }
    )
    result = filter_frames_by_labels(
        frames, labels, include_unannotated=unannotated, exclude_names=exclude
    )
    rows = [
        (name, None if pd.isna(label) else label)
        for name, label in zip(
            result["image_name"], result["instance_label"], strict=True
        )
    ]
    assert rows == expected


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


@pytest.mark.parametrize(
    ("image_dir", "config", "explicit_config_path", "expected", "warns"),
    [
        ("list", None, False, "imgs", False),
        # A single ``str`` is wrapped, not discarded.
        ("bare", None, False, "imgs", False),
        (None, None, False, None, True),
        ("none", "image_cache:\n  proj: {explicit}\n", False, "explicit", False),
        # A project configured only through ``cache.images_root`` still resolves
        # (upload used to read ``image_cache`` alone).
        ("none", "cache:\n  images_root: {root}\n", False, "root", False),
        # ``image_cache`` wins; the root is only a fallback.
        (
            "none",
            "image_cache:\n  proj: {explicit}\ncache:\n  images_root: {root}\n",
            False,
            "explicit",
            False,
        ),
        # ``config_path=`` beats the ambient ``CVETA2_CONFIG`` file.
        ("none", "image_cache:\n  proj: {explicit}\n", True, "explicit", False),
    ],
    ids=[
        "list_arg",
        "bare_path_arg",
        "nothing_warns",
        "image_cache_entry",
        "images_root_fallback",
        "explicit_entry_beats_root",
        "explicit_config_path",
    ],
)
def test_build_search_dirs(  # noqa: PLR0913, PLR0917
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capture_logs: list[str],
    image_dir: str | None,
    config: str | None,
    explicit_config_path: bool,  # noqa: FBT001
    expected: str | None,
    warns: bool,  # noqa: FBT001
) -> None:
    dirs = {"imgs": tmp_path / "imgs", "explicit": tmp_path / "explicit"}
    root = tmp_path / "datasets"
    for path in (*dirs.values(), root):
        path.mkdir()
    dirs["root"] = cache_dir_for_project(root, "proj")
    cfg_path = tmp_path / "config.yaml"
    if config is not None:
        cfg_path.write_text(
            config.format(explicit=dirs["explicit"], root=root), encoding="utf-8"
        )
    ambient = tmp_path / "nonexistent.yaml" if explicit_config_path else cfg_path
    monkeypatch.setenv("CVETA2_CONFIG", str(ambient))
    choices: dict[str, list[str] | str] = {
        "list": [str(dirs["imgs"])],
        "bare": str(dirs["imgs"]),
    }
    arg = choices.get(image_dir or "")

    result = build_search_dirs(
        arg, "proj", config_path=cfg_path if explicit_config_path else None
    )

    assert result == ([] if expected is None else [dirs[expected].resolve()])
    assert any("Не указан --image-dir" in m for m in capture_logs) is warns


# ---------------------------------------------------------------------------
# populate_record_paths
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("frame_name", "expected_key"),
    [
        ("sub1/sub2/img.jpg", "images/sub1/sub2/img.jpg"),
        ("img.jpg", "images/img.jpg"),
    ],
    ids=["nested", "flat"],
)
def test_populate_paths_builds_full_s3_key(frame_name: str, expected_key: str) -> None:
    ann = make_bbox(image_name=frame_name)

    populate_record_paths(
        ProjectAnnotations(annotations=[ann], deleted_images=[]),
        make_cs_info(prefix="images"),
        None,
    )

    assert ann.image_name == "img.jpg"
    assert ann.s3_image_path == expected_key


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


def test_local_frame_path_without_cloud_storage_is_relative_to_cache(
    tmp_path: Path,
) -> None:
    cached = tmp_path / "nested" / "a.jpg"
    cached.parent.mkdir()
    cached.write_bytes(b"image")
    record = make_bbox(image_name="a.jpg", frame_path="/nested/a.jpg")

    populate_record_paths(
        ProjectAnnotations(annotations=[record], deleted_images=[]), None, tmp_path
    )

    assert record.image_path == str(cached)
    assert record.s3_image_path is None


@pytest.mark.parametrize("escape", ["dotdot_key", "cache_symlink"])
def test_invalid_resolved_path_reports_the_original_frame_name(
    tmp_path: Path, escape: str
) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    if escape == "dotdot_key":
        record = make_bbox(image_name="bad.jpg", s3_image_path="images/../bad.jpg")
    else:
        (cache / "nested").symlink_to(tmp_path, target_is_directory=True)
        record = make_bbox(image_name="bad.jpg", frame_path="nested/bad.jpg")
    with pytest.raises(Cveta2Error, match=r"bad\.jpg"):
        populate_record_paths(
            ProjectAnnotations(annotations=[record], deleted_images=[]),
            make_cs_info(prefix="images"),
            cache,
        )
