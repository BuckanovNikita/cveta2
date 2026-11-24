"""Bundle policy regression contracts."""

from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from PIL import Image

from cveta2.adapters.files.media import inspect_images
from cveta2.domain.bundle.models import (
    BundleValidation,
    ClassInfo,
    DatasetMetadata,
    UploadError,
)
from cveta2.domain.bundle.validation import (
    excluded_class_rows,
    images_without_split,
    missing_active_classes,
    trainability_gaps,
)
from cveta2.domain.bundle.validation import validate_bundle as _validate_bundle
from cveta2.domain.verification.models import ValidationOptions
from cveta2.domain.verification.validation import validate_dataframe


def validate_bundle(frame: Any, metadata: Any, base_dir: Any, *, allow_empty_split: bool = False) -> BundleValidation:
    return _validate_bundle(
        frame,
        metadata,
        inspection=inspect_images(
            frame,
            profile="clearml-yolo",
            options=ValidationOptions(check_images=True, emit_warnings=False, base_dir=base_dir),
        ),
        allow_empty_split=allow_empty_split,
    )


def metadata() -> DatasetMetadata:
    return DatasetMetadata(
        api_url="https://example.com/classes",
        classes={
            "cat": ClassInfo(prod_id=1, alt_names=["kitten"]),
            "dog": ClassInfo(prod_id=2),
            "ignored": ClassInfo(prod_id=3, empty=True, alt_names=["old-ignored"]),
        },
    )


def row(tmp_path: Path, name: str, split: str = "train", label: str = "cat") -> dict[str, object]:
    path = tmp_path / name
    Image.new("RGB", (32, 32)).save(path, format="PNG")
    return {
        "image_name": name,
        "image_path": str(path),
        "split": split,
        "instance_label": label,
        "bbox_x_tl": "1",
        "bbox_y_tl": "1",
        "bbox_x_br": "20",
        "bbox_y_br": "20",
        "extra": "untouched",
    }


def test_aliases_deduplicate_and_preserve_original_broken_cells(tmp_path: Path) -> None:
    first = row(tmp_path, "train.png", label="kitten")
    second = {**first, "instance_label": "cat", "extra": "second"}
    frame = pd.DataFrame([first, second, row(tmp_path, "val.png", "val")], index=[9, 9, -1])
    original = frame.copy(deep=True)
    bundle = validate_bundle(frame, metadata(), tmp_path)
    assert not bundle.blockers
    assert bundle.result.clean_row_positions == (0, 2)
    assert bundle.result.clean.iloc[0]["instance_label"] == "cat"
    pd.testing.assert_frame_equal(bundle.result.broken, original.iloc[[1]])
    pd.testing.assert_frame_equal(bundle.broken_images, original.iloc[[0, 1]])
    pd.testing.assert_frame_equal(frame, original)
    assert bundle.result.clean.index.tolist() == [9, -1]


@pytest.mark.parametrize("label", ["unknown", "ignored", "old-ignored"])
def test_excluded_classes_quarantine_whole_image(tmp_path: Path, label: str) -> None:
    good = row(tmp_path, "bad.png")
    bad = {**good, "instance_label": label, "bbox_x_tl": "21", "bbox_x_br": "31"}
    frame = pd.DataFrame([good, bad, row(tmp_path, "train.png"), row(tmp_path, "val.png", "val")])
    result = validate_bundle(frame, metadata(), tmp_path)
    assert result.result.broken_row_positions == (0, 1)
    assert len(result.broken_images) == 2
    assert not result.blockers


def test_aliases_canonicalized_before_cross_class_conflicts(tmp_path: Path) -> None:
    first = row(tmp_path, "conflict.png", label="kitten")
    frame = pd.DataFrame([first, {**first, "instance_label": "dog"}, row(tmp_path, "val.png", "val")])
    result = validate_bundle(frame, metadata(), tmp_path)
    assert result.result.broken_row_positions == (0, 1)
    assert result.blockers


def test_background_is_preserved_but_training_boxes_required(tmp_path: Path) -> None:
    background = row(tmp_path, "train.png", label="")
    for column in ("bbox_x_tl", "bbox_y_tl", "bbox_x_br", "bbox_y_br"):
        background[column] = ""
    bundle = validate_bundle(
        pd.DataFrame([background, row(tmp_path, "val.png", "val")]),
        metadata(),
        tmp_path,
    )
    assert bundle.result.broken.empty
    assert any("training box" in reason for reason in bundle.blockers)


def test_validation_split_may_contain_only_background_images(tmp_path: Path) -> None:
    background = row(tmp_path, "val.png", "val", label="")
    for column in ("bbox_x_tl", "bbox_y_tl", "bbox_x_br", "bbox_y_br"):
        background[column] = ""
    bundle = validate_bundle(
        pd.DataFrame([row(tmp_path, "train.png"), background]),
        metadata(),
        tmp_path,
    )
    assert not bundle.blockers
    assert not bundle.result.requires_cleanup
    assert bundle.result.clean_row_positions == (0, 1)


def test_invalid_split_blocks_even_with_trainable_remainder(tmp_path: Path) -> None:
    frame = pd.DataFrame(
        [
            row(tmp_path, "a.png", ""),
            row(tmp_path, "b.png"),
            row(tmp_path, "c.png", "val"),
        ]
    )
    assert any("split" in reason for reason in validate_bundle(frame, metadata(), tmp_path).blockers)


@pytest.mark.parametrize(
    ("kind", "code"),
    [
        ("missing", "media_missing"),
        ("small", "training_image_size"),
        ("gif", "training_image_format"),
    ],
)
def test_training_media_quarantine(tmp_path: Path, kind: str, code: str) -> None:
    bad = row(tmp_path, "bad.png")
    path = Path(str(bad["image_path"]))
    if kind == "missing":
        path.unlink()
    elif kind == "small":
        Image.new("RGB", (9, 32)).save(path)
    else:
        Image.new("RGB", (32, 32)).save(path, format="GIF")
    frame = pd.DataFrame([bad, row(tmp_path, "train.png"), row(tmp_path, "val.png", "val")])
    bundle = validate_bundle(frame, metadata(), tmp_path)
    assert bundle.result.broken_row_positions == (0,)
    assert code in {issue.code for issue in bundle.result.issues}


def test_avif_training_image_is_accepted(tmp_path: Path) -> None:
    good = row(tmp_path, "train.avif")
    Image.new("RGB", (32, 32)).save(Path(str(good["image_path"])), format="AVIF")
    frame = pd.DataFrame([good, row(tmp_path, "val.png", "val")])
    bundle = validate_bundle(frame, metadata(), tmp_path)
    assert bundle.result.broken_row_positions == ()
    assert not bundle.blockers


@pytest.mark.parametrize("extension", ["heic", "heif", "dng", "HEIC"])
def test_extensions_without_a_decoder_are_quarantined(tmp_path: Path, extension: str) -> None:
    bad = row(tmp_path, f"bad.{extension}")
    frame = pd.DataFrame([bad, row(tmp_path, "train.png"), row(tmp_path, "val.png", "val")])
    bundle = validate_bundle(frame, metadata(), tmp_path)
    assert bundle.result.broken_row_positions == (0,)
    assert "training_image_format" in {issue.code for issue in bundle.result.issues}


def test_relative_paths_block_upload(tmp_path: Path) -> None:
    value = row(tmp_path, "train.png")
    value["image_path"] = "train.png"
    with pytest.raises(UploadError):
        validate_bundle(pd.DataFrame([value]), metadata(), tmp_path)


def test_clipping_is_only_in_clean_and_broken_evidence_is_original(
    tmp_path: Path,
) -> None:
    first = row(tmp_path, "train.png", label="kitten")
    first["bbox_x_tl"] = "-1"
    repeated = {**first, "extra": "different"}
    frame = pd.DataFrame([first, repeated, row(tmp_path, "val.png", "val")], index=[4, 4, 4])
    bundle = validate_bundle(frame, metadata(), tmp_path)
    assert bundle.result.clean.iloc[0]["bbox_x_tl"] == "0"
    assert bundle.result.clean.iloc[0]["instance_label"] == "cat"
    pd.testing.assert_frame_equal(bundle.broken_images, frame.iloc[[0, 1]])
    pd.testing.assert_frame_equal(bundle.result.broken, frame.iloc[[1]])


def test_minimum_side_and_extension_quarantine_all_duplicate_rows(
    tmp_path: Path,
) -> None:
    bad = row(tmp_path, "bad.gif")
    background = {**bad, "instance_label": ""}
    for column in ("bbox_x_tl", "bbox_y_tl", "bbox_x_br", "bbox_y_br"):
        background[column] = ""
    frame = pd.DataFrame(
        [
            background,
            background,
            row(tmp_path, "train.png"),
            row(tmp_path, "val.png", "val"),
        ]
    )
    bundle = validate_bundle(frame, metadata(), tmp_path)
    assert bundle.result.broken_row_positions == (0, 1)
    assert not bundle.blockers
    assert "training_image_format" in {issue.code for issue in bundle.result.issues}


def test_empty_input_and_missing_val_block(tmp_path: Path) -> None:
    frame = pd.DataFrame([row(tmp_path, "train.png")])
    assert any("val" in blocker for blocker in validate_bundle(frame, metadata(), tmp_path).blockers)
    assert validate_bundle(frame.iloc[:0], metadata(), tmp_path).blockers


def test_explicit_negative_does_not_require_an_empty_class(tmp_path: Path) -> None:
    background = row(tmp_path, "val.png", "val", "")
    for column in ("bbox_x_tl", "bbox_y_tl", "bbox_x_br", "bbox_y_br"):
        background[column] = ""
    bundle = validate_bundle(pd.DataFrame([row(tmp_path, "train.png"), background]), metadata(), tmp_path)
    assert not bundle.blockers
    assert bundle.result.broken.empty


SPLIT_BLOCKER = "Every input row must have a valid train, val or test split assignment."


def coverage_metadata() -> DatasetMetadata:
    return DatasetMetadata(
        api_url="https://example.com/classes",
        classes={
            "bowl": ClassInfo(prod_id=1),
            "cup": ClassInfo(prod_id=2, alt_names=["mug"]),
            "plate": ClassInfo(prod_id=3, empty=True),
        },
    )


def labelled(*rows: tuple[object, object]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["instance_label", "instance_shape"], dtype=object)


def test_missing_active_classes_lists_sorted_unexcluded_classes_without_bbox() -> None:
    assert missing_active_classes(labelled(("bowl", "box"), ("", "none")), coverage_metadata()) == ("cup",)
    assert missing_active_classes(labelled(), coverage_metadata()) == ("bowl", "cup")
    assert missing_active_classes(pd.DataFrame(), coverage_metadata()) == ("bowl", "cup")


def test_missing_active_classes_counts_aliases() -> None:
    assert "cup" not in missing_active_classes(labelled(("mug", "box")), coverage_metadata())


def test_missing_active_classes_counts_rows_without_a_shape_as_boxes() -> None:
    frame = labelled(("bowl", ""), ("cup", "none"), ("cup", "deleted"))
    assert missing_active_classes(frame, coverage_metadata()) == ("cup",)
    without_column = pd.DataFrame({"instance_label": ["bowl", "mug", float("nan")]}, dtype=object)
    assert missing_active_classes(without_column, coverage_metadata()) == ()


def test_excluded_class_rows_counts_rows_of_excluded_classes() -> None:
    frame = labelled(("plate", "box"), ("plate", "box"), ("bowl", "box"))
    assert excluded_class_rows(frame, coverage_metadata()) == 2
    assert excluded_class_rows(pd.DataFrame(), coverage_metadata()) == 0


def coverage_row(tmp_path: Path, name: str, split: str = "train", label: str = "bowl") -> dict[str, object]:
    return {key: value for key, value in row(tmp_path, name, split, label).items() if key != "extra"}


@pytest.mark.parametrize("empty", ["", float("nan")])
def test_preparation_mode_accepts_empty_split(tmp_path: Path, empty: object) -> None:
    frame = pd.DataFrame([coverage_row(tmp_path, "a.png"), coverage_row(tmp_path, "b.png", label="cup")])
    frame["split"] = pd.Series([empty, empty], dtype=object)
    bundle = validate_bundle(frame, coverage_metadata(), tmp_path, allow_empty_split=True)
    assert bundle.result.broken_row_positions == ()
    assert bundle.blockers == ()
    assert images_without_split(bundle.result.clean) == 2
    strict = validate_bundle(frame, coverage_metadata(), tmp_path)
    assert strict.result.broken_row_positions == (0, 1)
    assert {issue.row_position for issue in strict.result.issues if issue.code == "invalid_split"} == {0, 1}
    assert SPLIT_BLOCKER in strict.blockers


@pytest.mark.parametrize("allow_empty_split", [False, True])
def test_preparation_mode_still_rejects_invalid_split_value(tmp_path: Path, *, allow_empty_split: bool) -> None:
    frame = pd.DataFrame(
        [
            coverage_row(tmp_path, "a.png", "holdout"),
            coverage_row(tmp_path, "b.png"),
            coverage_row(tmp_path, "c.png", "val"),
        ]
    )
    bundle = validate_bundle(frame, coverage_metadata(), tmp_path, allow_empty_split=allow_empty_split)
    assert bundle.result.broken_row_positions == (0,)
    assert "invalid_split" in {issue.code for issue in bundle.result.issues if issue.row_position == 0}


def test_preparation_mode_keeps_structural_and_empty_blockers(tmp_path: Path) -> None:
    frame = pd.DataFrame([coverage_row(tmp_path, "a.png")]).drop(columns=["split"])
    blockers = validate_bundle(frame, coverage_metadata(), tmp_path, allow_empty_split=True).blockers
    assert "Input CSV has structural validation errors." in blockers
    assert "No valid images remain for upload." in blockers
    assert SPLIT_BLOCKER not in blockers


def test_preparation_mode_leaves_trainability_to_the_caller(tmp_path: Path) -> None:
    frame = pd.DataFrame([coverage_row(tmp_path, "a.png"), coverage_row(tmp_path, "b.png", label="cup")])
    prepared = validate_bundle(frame, coverage_metadata(), tmp_path, allow_empty_split=True)
    assert "Required val split has no valid images." not in prepared.blockers
    assert prepared.blockers == ()
    assert trainability_gaps(prepared.result.clean) == ("val_images",)
    assert validate_bundle(frame, coverage_metadata(), tmp_path).blockers == (
        "Required val split has no valid images.",
    )


def test_trainability_gaps_ignore_rows_without_a_split() -> None:
    clean = pd.DataFrame(
        {"split": ["", "val", "train"], "instance_label": ["bowl", "bowl", ""]},
        dtype=object,
    )
    assert trainability_gaps(clean) == ("train_box",)
    assert trainability_gaps(clean.iloc[[0]]) == ("train_images", "val_images", "train_box")
    assert trainability_gaps(pd.DataFrame()) == ("train_images", "val_images", "train_box")


def test_default_mode_lists_every_trainability_blocker_in_order(tmp_path: Path) -> None:
    background = coverage_row(tmp_path, "a.png", "test", "")
    for column in ("bbox_x_tl", "bbox_y_tl", "bbox_x_br", "bbox_y_br"):
        background[column] = ""
    assert validate_bundle(pd.DataFrame([background]), coverage_metadata(), tmp_path).blockers == (
        "Required train split has no valid images.",
        "Required val split has no valid images.",
        "At least one valid training box is required.",
    )


def test_images_without_split_counts_distinct_names() -> None:
    frame = pd.DataFrame(
        {"image_name": ["a.png", "a.png", "b.png", "c.png"], "split": ["", float("nan"), "train", ""]},
        dtype=object,
    )
    assert images_without_split(frame) == 2
    assert images_without_split(frame.drop(columns=["split"])) == 3
    assert images_without_split(pd.DataFrame()) == 0


def test_clearml_yolo_profile_still_requires_split(tmp_path: Path) -> None:
    frame = pd.DataFrame([coverage_row(tmp_path, "a.png", "")])
    result = validate_dataframe(frame, profile="clearml-yolo")
    assert "invalid_split" in {issue.code for issue in result.issues}


@pytest.mark.parametrize("allow_empty_split", [False, True])
def test_validate_bundle_does_not_check_class_coverage(tmp_path: Path, *, allow_empty_split: bool) -> None:
    frame = pd.DataFrame([coverage_row(tmp_path, "a.png"), coverage_row(tmp_path, "b.png", "val")])
    assert missing_active_classes(frame, coverage_metadata()) == ("cup",)
    bundle = validate_bundle(frame, coverage_metadata(), tmp_path, allow_empty_split=allow_empty_split)
    assert bundle.blockers == ()
