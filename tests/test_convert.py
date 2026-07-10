"""Unit tests for the convert command (CSV <-> YOLO)."""

from __future__ import annotations

import errno
import json
import shutil
from pathlib import Path

import pandas as pd
import pytest
import yaml

from cveta2.commands.convert import run_convert
from cveta2.exceptions import Cveta2Error
from cveta2.models import CSV_COLUMNS
from cveta2.services.convert import common as convert
from cveta2.services.convert import (
    convert_from_yolo,
    convert_to_coco,
    convert_to_yolo,
)
from cveta2.services.convert.common import (
    CocoBox,
    PixelBox,
    YoloBox,
    _link_or_copy,
    _pixel_to_coco,
    _pixel_to_yolo,
    _require_positive_dimensions,
    _SizeCache,
    _yolo_to_pixel,
)
from cveta2.services.convert.yolo import _parse_label_file
from tests.helpers import csv_row, make_args, make_bbox, make_image, write_dataset_csv


def _make_dataset_csv(tmp_path: Path, rows: list[dict[str, object]]) -> Path:
    return write_dataset_csv(tmp_path / "dataset.csv", rows, columns=CSV_COLUMNS)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

COCO8_ROOT = Path(__file__).parent / "fixtures" / "data" / "coco8"
COCO8_YAML = Path(__file__).parent / "fixtures" / "data" / "coco8.yaml"


# ---------------------------------------------------------------------------
# Coordinate conversion tests
# ---------------------------------------------------------------------------


class TestCoordinateConversion:
    """Tests for pixel <-> YOLO coordinate conversion."""

    @pytest.mark.parametrize(
        ("result", "expected"),
        [
            (
                _pixel_to_yolo(PixelBox(100, 50, 200, 150), 400, 300),
                YoloBox(0.375, 1.0 / 3.0, 0.25, 1.0 / 3.0),
            ),
            (
                _yolo_to_pixel(YoloBox(0.5, 0.5, 0.5, 0.5), 640, 480),
                PixelBox(160.0, 120.0, 480.0, 360.0),
            ),
            (
                _pixel_to_coco(PixelBox(100, 50, 300, 250)),
                CocoBox(x=100, y=50, w=200, h=200),
            ),
        ],
    )
    def test_conversion_directions(
        self,
        result: tuple[float, ...],
        expected: tuple[float, ...],
    ) -> None:
        assert result == pytest.approx(expected)

    def test_roundtrip(self) -> None:
        """Pixel -> yolo -> pixel should recover original coords."""
        original = PixelBox(50.0, 30.0, 200.0, 180.0)
        img_w, img_h = 640, 480
        yolo = _pixel_to_yolo(original, img_w, img_h)
        recovered = _yolo_to_pixel(yolo, img_w, img_h)
        assert recovered.x_tl == pytest.approx(original.x_tl, abs=0.01)
        assert recovered.y_tl == pytest.approx(original.y_tl, abs=0.01)
        assert recovered.x_br == pytest.approx(original.x_br, abs=0.01)
        assert recovered.y_br == pytest.approx(original.y_br, abs=0.01)

    @pytest.mark.parametrize(("width", "height"), [(0, 100), (100, 0), (0, 0), (-1, 5)])
    def test_non_positive_dimensions_raise(self, width: int, height: int) -> None:
        with pytest.raises(Cveta2Error, match="некорректный размер"):
            _require_positive_dimensions(width, height, "bad.jpg")

    def test_positive_dimensions_pass(self) -> None:
        _require_positive_dimensions(640, 480, "ok.jpg")


# ---------------------------------------------------------------------------
# parse_label_file tests
# ---------------------------------------------------------------------------


class TestParseLabelFile:
    """Tests for YOLO label file parsing."""

    def test_standard_5_fields(self, tmp_path: Path) -> None:
        p = tmp_path / "label.txt"
        p.write_text("0 0.5 0.5 0.3 0.4\n1 0.1 0.2 0.3 0.4\n")
        result = _parse_label_file(p)
        assert len(result) == 2
        assert result[0] == [0.0, 0.5, 0.5, 0.3, 0.4]

    def test_6_fields_with_conf(self, tmp_path: Path) -> None:
        p = tmp_path / "label.txt"
        p.write_text("0 0.5 0.5 0.3 0.4 0.95\n")
        result = _parse_label_file(p)
        assert len(result) == 1
        assert len(result[0]) == 6
        assert result[0][5] == pytest.approx(0.95)

    def test_missing_file(self, tmp_path: Path) -> None:
        result = _parse_label_file(tmp_path / "nonexistent.txt")
        assert result == []

    def test_empty_file(self, tmp_path: Path) -> None:
        p = tmp_path / "label.txt"
        p.write_text("")
        result = _parse_label_file(p)
        assert result == []


# ---------------------------------------------------------------------------
# link_or_copy tests
# ---------------------------------------------------------------------------


class TestLinkOrCopy:
    """Tests for _link_or_copy file placement."""

    @pytest.mark.parametrize("mode", ["copy", "symlink", "hardlink"])
    def test_link_mode_places_file(self, tmp_path: Path, mode: str) -> None:
        src = tmp_path / "src.txt"
        src.write_text("hello")
        dst = tmp_path / "out" / "dst.txt"
        _link_or_copy(src, dst, mode)
        assert dst.read_text() == "hello"
        if mode == "symlink":
            assert dst.is_symlink()
        if mode == "hardlink":
            assert src.stat().st_ino == dst.stat().st_ino

    def test_skip_existing(self, tmp_path: Path) -> None:
        src = tmp_path / "src.txt"
        src.write_text("new")
        dst = tmp_path / "dst.txt"
        dst.write_text("old")
        _link_or_copy(src, dst, "copy")
        assert dst.read_text() == "old"  # not overwritten


class TestReflinkFallback:
    """Tests for fallback to plain copy when reflink fails."""

    @pytest.fixture(autouse=True)
    def _reset_warned_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(convert, "_reflink_warner", convert._OnceWarner())

    @staticmethod
    def _make_src(tmp_path: Path, name: str = "src.txt") -> Path:
        src = tmp_path / name
        src.write_text("hello")
        return src

    @pytest.mark.parametrize(
        ("mode", "patch_target"),
        [
            ("reflink", "reflink_copy.reflink"),
            ("auto", "reflink_copy.reflink_or_copy"),
        ],
    )
    def test_falls_back_to_copy_on_oserror(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capture_logs: list[str],
        mode: str,
        patch_target: str,
    ) -> None:
        def failing(_src: str, _dst: str) -> None:
            raise OSError(errno.EXDEV, "Invalid cross-device link")

        monkeypatch.setattr(patch_target, failing)
        src = self._make_src(tmp_path)
        dst = tmp_path / "out" / "dst.txt"
        _link_or_copy(src, dst, mode)
        assert dst.read_text() == "hello"
        assert any("reflink недоступен" in m for m in capture_logs)

    def test_half_created_dst_removed_before_copy(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def failing_reflink(_src: str, dst: str) -> None:
            Path(dst).write_text("partial")
            raise OSError(errno.EXDEV, "Invalid cross-device link")

        monkeypatch.setattr("reflink_copy.reflink", failing_reflink)
        src = self._make_src(tmp_path)
        dst = tmp_path / "out" / "dst.txt"
        _link_or_copy(src, dst, "reflink")
        assert dst.read_text() == "hello"

    def test_warning_emitted_once_for_multiple_files(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capture_logs: list[str],
    ) -> None:
        def failing_reflink(_src: str, _dst: str) -> None:
            raise OSError(errno.EXDEV, "Invalid cross-device link")

        monkeypatch.setattr("reflink_copy.reflink", failing_reflink)
        for i in range(3):
            src = self._make_src(tmp_path, f"src{i}.txt")
            _link_or_copy(src, tmp_path / "out" / f"dst{i}.txt", "reflink")
        warnings = [m for m in capture_logs if "reflink недоступен" in m]
        assert len(warnings) == 1

    def test_reflink_success_no_warning(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capture_logs: list[str],
    ) -> None:
        def succeeding_reflink(src: str, dst: str) -> None:
            shutil.copy2(src, dst)

        monkeypatch.setattr("reflink_copy.reflink", succeeding_reflink)
        src = self._make_src(tmp_path)
        dst = tmp_path / "out" / "dst.txt"
        _link_or_copy(src, dst, "reflink")
        assert dst.read_text() == "hello"
        assert not capture_logs

    def test_auto_mode_real_library_no_warning(
        self,
        tmp_path: Path,
        capture_logs: list[str],
    ) -> None:
        src = self._make_src(tmp_path)
        dst = tmp_path / "out" / "dst.txt"
        _link_or_copy(src, dst, "auto")
        assert dst.read_text() == "hello"
        assert not capture_logs


# ---------------------------------------------------------------------------
# confidence field tests
# ---------------------------------------------------------------------------


class TestConfidenceField:
    """Tests for the confidence field on BBoxAnnotation."""

    def test_confidence_in_csv_columns(self) -> None:
        assert "confidence" in CSV_COLUMNS

    def test_bbox_annotation_with_confidence(self) -> None:
        ann = make_bbox(confidence=0.95)
        assert ann.confidence == 0.95
        row = ann.to_csv_row()
        assert row["confidence"] == 0.95

    def test_bbox_annotation_without_confidence(self) -> None:
        ann = make_bbox()
        assert ann.confidence is None
        row = ann.to_csv_row()
        assert row["confidence"] is None


# ---------------------------------------------------------------------------
# --to-yolo tests
# ---------------------------------------------------------------------------


class TestToYolo:
    """Tests for --to-yolo CSV to YOLO conversion."""

    def test_basic_structure(self, tmp_path: Path) -> None:
        """Check that --to-yolo creates proper directory structure."""
        img_dir = tmp_path / "images"
        make_image(img_dir / "test.jpg")

        rows = [
            csv_row("test.jpg", label="cat", split="train"),
            csv_row(
                "test.jpg",
                label="dog",
                split="train",
                bbox_x_tl=200,
                bbox_y_tl=100,
                bbox_x_br=300,
                bbox_y_br=250,
            ),
        ]
        csv_path = _make_dataset_csv(tmp_path, rows)

        out_dir = tmp_path / "yolo_out"
        convert_to_yolo(
            csv_path,
            out_dir,
            image_dirs=[str(img_dir)],
            link_mode="copy",
        )

        assert (out_dir / "images" / "train" / "test.jpg").is_file()
        assert (out_dir / "labels" / "train" / "test.txt").is_file()
        assert (out_dir / "dataset.yaml").is_file()

        label_content = (out_dir / "labels" / "train" / "test.txt").read_text()
        lines = label_content.strip().splitlines()
        assert len(lines) == 2

        with (out_dir / "dataset.yaml").open() as f:
            ds = yaml.safe_load(f)
        assert "names" in ds
        assert "train" in ds
        assert set(ds["names"].values()) == {"cat", "dog"}

    def test_empty_labels_for_none_shape(self, tmp_path: Path) -> None:
        """Images with instance_shape=none should get empty label files."""
        img_dir = tmp_path / "images"
        make_image(img_dir / "empty.jpg")

        rows = [csv_row("empty.jpg", shape="none", split="val")]
        csv_path = _make_dataset_csv(tmp_path, rows)

        out_dir = tmp_path / "yolo_out"
        convert_to_yolo(
            csv_path,
            out_dir,
            image_dirs=[str(img_dir)],
            link_mode="copy",
        )

        label_path = out_dir / "labels" / "val" / "empty.txt"
        assert label_path.is_file()
        assert label_path.read_text() == ""

    def test_only_existing_splits_in_yaml(self, tmp_path: Path) -> None:
        """dataset.yaml should only include splits that exist in data."""
        img_dir = tmp_path / "images"
        make_image(img_dir / "test.jpg")

        rows = [csv_row("test.jpg", label="cat", split="val")]
        csv_path = _make_dataset_csv(tmp_path, rows)

        out_dir = tmp_path / "yolo_out"
        convert_to_yolo(
            csv_path,
            out_dir,
            image_dirs=[str(img_dir)],
            link_mode="copy",
        )

        with (out_dir / "dataset.yaml").open() as f:
            ds = yaml.safe_load(f)
        assert "val" in ds
        assert "train" not in ds
        assert "test" not in ds


# ---------------------------------------------------------------------------
# --from-yolo tests
# ---------------------------------------------------------------------------


class TestFromYoloDataset:
    """Tests for --from-yolo YOLO to CSV conversion."""

    def test_coco8_dataset(self, tmp_path: Path) -> None:
        """Convert coco8 fixture to CSV and check basic properties."""
        import shutil

        ds_copy = tmp_path / "coco8"
        shutil.copytree(COCO8_ROOT, ds_copy)

        with COCO8_YAML.open() as f:
            coco_cfg = yaml.safe_load(f)
        coco_cfg["path"] = str(ds_copy)
        ds_yaml = ds_copy / "dataset.yaml"
        with ds_yaml.open("w") as f:
            yaml.dump(coco_cfg, f)

        output_csv = tmp_path / "output.csv"
        convert_from_yolo(ds_copy, output_csv, read_all_sizes=False)

        assert output_csv.is_file()
        df = pd.read_csv(output_csv)
        assert len(df) > 0
        assert "image_name" in df.columns
        assert "confidence" in df.columns
        assert set(df["instance_shape"].unique()) == {"box"}
        assert set(df["split"].unique()) <= {"train", "val"}

    def test_prediction_mode_with_confidence(self, tmp_path: Path) -> None:
        """Prediction mode: bare .txt files with confidence field."""
        pred_dir = tmp_path / "preds"
        pred_dir.mkdir()
        (pred_dir / "img1.txt").write_text(
            "0 0.5 0.5 0.3 0.4 0.95\n1 0.2 0.3 0.1 0.2 0.87\n"
        )

        img_dir = tmp_path / "imgs"
        make_image(img_dir / "img1.jpg")

        names_path = tmp_path / "names.yaml"
        with names_path.open("w") as f:
            yaml.dump({"names": {0: "cat", 1: "dog"}}, f)

        output_csv = tmp_path / "output.csv"
        convert_from_yolo(
            pred_dir,
            output_csv,
            names_file=names_path,
            image_dirs=[str(img_dir)],
            read_all_sizes=False,
        )

        df = pd.read_csv(output_csv)
        assert len(df) == 2
        assert df.iloc[0]["confidence"] == pytest.approx(0.95)
        assert df.iloc[1]["confidence"] == pytest.approx(0.87)
        assert df.iloc[0]["instance_label"] == "cat"
        assert df.iloc[1]["instance_label"] == "dog"


# ---------------------------------------------------------------------------
# Roundtrip test
# ---------------------------------------------------------------------------


class TestRoundtrip:
    """Tests for CSV -> YOLO -> CSV roundtrip fidelity."""

    def test_csv_to_yolo_to_csv(self, tmp_path: Path) -> None:
        """CSV -> YOLO -> CSV should preserve bbox coordinates."""
        img_dir = tmp_path / "images"
        make_image(img_dir / "test.jpg")

        original_rows = [
            csv_row(
                "test.jpg",
                label="cat",
                split="train",
                bbox_x_tl=50.0,
                bbox_y_tl=30.0,
                bbox_x_br=200.0,
                bbox_y_br=180.0,
            ),
            csv_row(
                "test.jpg",
                label="dog",
                split="train",
                bbox_x_tl=300.0,
                bbox_y_tl=100.0,
                bbox_x_br=500.0,
                bbox_y_br=400.0,
            ),
        ]
        original_rows[1]["annotation_id"] = 2
        csv_path = _make_dataset_csv(tmp_path, original_rows)

        # CSV -> YOLO
        yolo_dir = tmp_path / "yolo"
        convert_to_yolo(
            csv_path,
            yolo_dir,
            image_dirs=[str(img_dir)],
            link_mode="copy",
        )

        # YOLO -> CSV
        roundtrip_csv = tmp_path / "roundtrip.csv"
        convert_from_yolo(yolo_dir, roundtrip_csv, read_all_sizes=False)

        df_orig = pd.read_csv(csv_path)
        df_rt = pd.read_csv(roundtrip_csv)

        df_orig_box = (
            df_orig[df_orig["instance_shape"] == "box"]
            .sort_values(["image_name", "instance_label"])
            .reset_index(drop=True)
        )
        df_rt_box = (
            df_rt[df_rt["instance_shape"] == "box"]
            .sort_values(["image_name", "instance_label"])
            .reset_index(drop=True)
        )
        assert len(df_orig_box) == len(df_rt_box)

        for i in range(len(df_orig_box)):
            for col in ("bbox_x_tl", "bbox_y_tl", "bbox_x_br", "bbox_y_br"):
                orig = df_orig_box.iloc[i][col]
                rt = df_rt_box.iloc[i][col]
                assert orig == pytest.approx(rt, abs=1.0), (
                    f"Row {i}, {col}: {orig} vs {rt}"
                )


class TestSizeCache:
    """Tests for _SizeCache image dimension caching."""

    def test_read_all_false_returns_first_size(self, tmp_path: Path) -> None:
        """When read_all=False, all calls return the first image's size."""
        img1 = make_image(tmp_path / "a.jpg", 640, 480)
        img2 = make_image(tmp_path / "b.jpg", 320, 240)

        cache = _SizeCache(read_all=False)
        assert cache.get(img1) == (640, 480)
        assert cache.get(img2) == (640, 480)

    def test_read_all_true_reads_each_image(self, tmp_path: Path) -> None:
        """When read_all=True, each image is read individually."""
        img1 = make_image(tmp_path / "a.jpg", 640, 480)
        img2 = make_image(tmp_path / "b.jpg", 320, 240)

        cache = _SizeCache(read_all=True)
        assert cache.get(img1) == (640, 480)
        assert cache.get(img2) == (320, 240)


# ---------------------------------------------------------------------------
# --to-coco tests
# ---------------------------------------------------------------------------


def _run_to_coco(tmp_path: Path, csv_path: Path, img_dir: Path) -> Path:
    out_dir = tmp_path / "coco_out"
    convert_to_coco(csv_path, out_dir, image_dirs=[str(img_dir)], link_mode="copy")
    return out_dir


@pytest.mark.parametrize("export_format", ["yolo", "coco"])
def test_missing_split_error(tmp_path: Path, export_format: str) -> None:
    """--to-yolo and --to-coco both error when any image has no split."""
    rows = [csv_row("test.jpg", label="cat", split="train")]
    rows[0]["split"] = None
    csv_path = _make_dataset_csv(tmp_path, rows)

    export = convert_to_yolo if export_format == "yolo" else convert_to_coco
    with pytest.raises(Cveta2Error):
        export(csv_path, tmp_path / "out", image_dirs=[str(tmp_path)], link_mode="copy")


def test_run_convert_missing_split_exits(tmp_path: Path) -> None:
    """The adapter maps a conversion-logic error onto ``SystemExit``."""
    rows = [csv_row("test.jpg", label="cat", split="train")]
    rows[0]["split"] = None
    csv_path = _make_dataset_csv(tmp_path, rows)

    args = make_args(
        to_yolo=True,
        from_yolo=False,
        dataset=str(csv_path),
        output=str(tmp_path / "yolo_out"),
        link_mode="copy",
        image_dir=[],
        names_file=None,
    )

    with pytest.raises(SystemExit):
        run_convert(args)


class TestToCoco:
    """Tests for --to-coco CSV to COCO conversion."""

    def test_basic_structure(self, tmp_path: Path) -> None:
        """Check directory layout, JSON schema, bbox/area/category values."""
        img_dir = tmp_path / "images"
        make_image(img_dir / "test.jpg")

        rows = [
            csv_row(
                "test.jpg",
                label="cat",
                split="train",
                bbox_x_tl=10,
                bbox_y_tl=20,
                bbox_x_br=110,
                bbox_y_br=120,
            ),
        ]
        csv_path = _make_dataset_csv(tmp_path, rows)
        out_dir = _run_to_coco(tmp_path, csv_path, img_dir)

        assert (out_dir / "train" / "test.jpg").is_file()
        json_path = out_dir / "train" / "_annotations.coco.json"
        assert json_path.is_file()

        with json_path.open() as f:
            coco = json.load(f)

        assert "images" in coco
        assert "annotations" in coco
        assert "categories" in coco

        assert len(coco["images"]) == 1
        assert coco["images"][0]["file_name"] == "test.jpg"
        assert coco["images"][0]["width"] == 640
        assert coco["images"][0]["height"] == 480

        assert len(coco["annotations"]) == 1
        ann = coco["annotations"][0]
        assert ann["bbox"] == [10.0, 20.0, 100.0, 100.0]
        assert ann["area"] == pytest.approx(10000.0)
        assert ann["iscrowd"] == 0
        assert ann["category_id"] == 1  # 1-based

        assert len(coco["categories"]) == 1
        assert coco["categories"][0]["id"] == 1
        assert coco["categories"][0]["name"] == "cat"

    def test_val_renamed_to_valid(self, tmp_path: Path) -> None:
        """Val split directory should be renamed to valid/."""
        img_dir = tmp_path / "images"
        make_image(img_dir / "test.jpg")

        rows = [csv_row("test.jpg", label="cat", split="val")]
        csv_path = _make_dataset_csv(tmp_path, rows)
        out_dir = _run_to_coco(tmp_path, csv_path, img_dir)

        assert (out_dir / "valid" / "_annotations.coco.json").is_file()
        assert not (out_dir / "val").exists()

    def test_none_shape_in_images_not_annotations(self, tmp_path: Path) -> None:
        """Images with shape=none appear in images but not annotations."""
        img_dir = tmp_path / "images"
        make_image(img_dir / "empty.jpg")

        rows = [csv_row("empty.jpg", shape="none", split="train")]
        csv_path = _make_dataset_csv(tmp_path, rows)
        out_dir = _run_to_coco(tmp_path, csv_path, img_dir)

        json_path = out_dir / "train" / "_annotations.coco.json"
        with json_path.open() as f:
            coco = json.load(f)

        assert len(coco["images"]) == 1
        assert coco["images"][0]["file_name"] == "empty.jpg"
        assert len(coco["annotations"]) == 0

    def test_multiple_labels_1based_ids(self, tmp_path: Path) -> None:
        """Sorted labels should get 1-based category IDs."""
        img_dir = tmp_path / "images"
        make_image(img_dir / "a.jpg")
        make_image(img_dir / "b.jpg")
        make_image(img_dir / "c.jpg")

        rows = [
            csv_row("a.jpg", label="zebra", split="train"),
            csv_row("b.jpg", label="apple", split="train"),
            csv_row("c.jpg", label="mango", split="train"),
        ]
        csv_path = _make_dataset_csv(tmp_path, rows)
        out_dir = _run_to_coco(tmp_path, csv_path, img_dir)

        json_path = out_dir / "train" / "_annotations.coco.json"
        with json_path.open() as f:
            coco = json.load(f)

        cats = {c["name"]: c["id"] for c in coco["categories"]}
        # Sorted: apple=1, mango=2, zebra=3
        assert cats == {"apple": 1, "mango": 2, "zebra": 3}
