"""Unit tests for the convert command (CSV <-> YOLO)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
import pytest
import yaml

from cveta2.commands.convert import (
    _link_or_copy,
    _parse_label_file,
    _pixel_to_yolo,
    _SizeCache,
    _yolo_to_pixel,
    run_convert,
)
from cveta2.models import CSV_COLUMNS, BBoxAnnotation

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

COCO8_ROOT = Path(__file__).parent / "fixtures" / "data" / "coco8"
COCO8_YAML = Path(__file__).parent / "fixtures" / "data" / "coco8.yaml"


def _make_dataset_csv(tmp_path: Path, rows: list[dict[str, object]]) -> Path:
    csv_path = tmp_path / "dataset.csv"
    df = pd.DataFrame(rows, columns=list(CSV_COLUMNS))
    df.to_csv(csv_path, index=False, encoding="utf-8")
    return csv_path


def _box_row(  # noqa: PLR0913
    image_name: str,
    label: str,
    split: str,
    *,
    x_tl: float = 10.0,
    y_tl: float = 20.0,
    x_br: float = 100.0,
    y_br: float = 200.0,
    img_w: int = 640,
    img_h: int = 480,
) -> dict[str, object]:
    row: dict[str, object] = dict.fromkeys(CSV_COLUMNS, None)
    row["image_name"] = image_name
    row["image_width"] = img_w
    row["image_height"] = img_h
    row["instance_shape"] = "box"
    row["instance_label"] = label
    row["bbox_x_tl"] = x_tl
    row["bbox_y_tl"] = y_tl
    row["bbox_x_br"] = x_br
    row["bbox_y_br"] = y_br
    row["task_id"] = 1
    row["task_name"] = "test"
    row["task_status"] = "completed"
    row["task_updated_date"] = "2026-01-01T00:00:00Z"
    row["created_by_username"] = "admin"
    row["frame_id"] = 0
    row["split"] = split
    row["subset"] = ""
    row["occluded"] = False
    row["z_order"] = 0
    row["rotation"] = 0.0
    row["source"] = "manual"
    row["annotation_id"] = 1
    row["confidence"] = None
    row["attributes"] = json.dumps({})
    return row


def _none_row(
    image_name: str,
    split: str,
    *,
    img_w: int = 640,
    img_h: int = 480,
) -> dict[str, object]:
    row: dict[str, object] = dict.fromkeys(CSV_COLUMNS, None)
    row["image_name"] = image_name
    row["image_width"] = img_w
    row["image_height"] = img_h
    row["instance_shape"] = "none"
    row["task_id"] = 1
    row["task_name"] = "test"
    row["task_status"] = "completed"
    row["task_updated_date"] = "2026-01-01T00:00:00Z"
    row["frame_id"] = 1
    row["split"] = split
    row["subset"] = ""
    row["source"] = "manual"
    row["attributes"] = json.dumps({})
    return row


def _make_args(**kwargs: object) -> argparse.Namespace:
    ns = argparse.Namespace()
    for k, v in kwargs.items():
        setattr(ns, k, v)
    return ns


# ---------------------------------------------------------------------------
# Coordinate conversion tests
# ---------------------------------------------------------------------------


class TestCoordinateConversion:
    """Tests for pixel <-> YOLO coordinate conversion."""

    def test_pixel_to_yolo_basic(self) -> None:
        xc, yc, w, h = _pixel_to_yolo(100, 50, 200, 150, 400, 300)
        assert xc == pytest.approx(0.375)
        assert yc == pytest.approx(1.0 / 3.0)
        assert w == pytest.approx(0.25)
        assert h == pytest.approx(1.0 / 3.0)

    def test_yolo_to_pixel_basic(self) -> None:
        x_tl, y_tl, x_br, y_br = _yolo_to_pixel(0.5, 0.5, 0.5, 0.5, 640, 480)
        assert x_tl == pytest.approx(160.0)
        assert y_tl == pytest.approx(120.0)
        assert x_br == pytest.approx(480.0)
        assert y_br == pytest.approx(360.0)

    def test_roundtrip(self) -> None:
        """Pixel -> yolo -> pixel should recover original coords."""
        x_tl, y_tl, x_br, y_br = 50.0, 30.0, 200.0, 180.0
        img_w, img_h = 640, 480
        xc, yc, w, h = _pixel_to_yolo(x_tl, y_tl, x_br, y_br, img_w, img_h)
        x_tl2, y_tl2, x_br2, y_br2 = _yolo_to_pixel(xc, yc, w, h, img_w, img_h)
        assert x_tl2 == pytest.approx(x_tl, abs=0.01)
        assert y_tl2 == pytest.approx(y_tl, abs=0.01)
        assert x_br2 == pytest.approx(x_br, abs=0.01)
        assert y_br2 == pytest.approx(y_br, abs=0.01)


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

    def test_copy_mode(self, tmp_path: Path) -> None:
        src = tmp_path / "src.txt"
        src.write_text("hello")
        dst = tmp_path / "out" / "dst.txt"
        _link_or_copy(src, dst, "copy")
        assert dst.read_text() == "hello"

    def test_symlink_mode(self, tmp_path: Path) -> None:
        src = tmp_path / "src.txt"
        src.write_text("hello")
        dst = tmp_path / "out" / "dst.txt"
        _link_or_copy(src, dst, "symlink")
        assert dst.is_symlink()
        assert dst.read_text() == "hello"

    def test_hardlink_mode(self, tmp_path: Path) -> None:
        src = tmp_path / "src.txt"
        src.write_text("hello")
        dst = tmp_path / "out" / "dst.txt"
        _link_or_copy(src, dst, "hardlink")
        assert dst.read_text() == "hello"
        assert src.stat().st_ino == dst.stat().st_ino

    def test_skip_existing(self, tmp_path: Path) -> None:
        src = tmp_path / "src.txt"
        src.write_text("new")
        dst = tmp_path / "dst.txt"
        dst.write_text("old")
        _link_or_copy(src, dst, "copy")
        assert dst.read_text() == "old"  # not overwritten


# ---------------------------------------------------------------------------
# confidence field tests
# ---------------------------------------------------------------------------


class TestConfidenceField:
    """Tests for the confidence field on BBoxAnnotation."""

    def test_confidence_in_csv_columns(self) -> None:
        assert "confidence" in CSV_COLUMNS

    def test_bbox_annotation_with_confidence(self) -> None:
        ann = BBoxAnnotation(
            image_name="test.jpg",
            image_width=640,
            image_height=480,
            instance_label="cat",
            bbox_x_tl=10,
            bbox_y_tl=20,
            bbox_x_br=100,
            bbox_y_br=200,
            task_id=1,
            task_name="test",
            frame_id=0,
            subset="",
            occluded=False,
            z_order=0,
            rotation=0.0,
            source="manual",
            annotation_id=1,
            confidence=0.95,
            attributes={},
        )
        assert ann.confidence == 0.95
        row = ann.to_csv_row()
        assert row["confidence"] == 0.95

    def test_bbox_annotation_without_confidence(self) -> None:
        ann = BBoxAnnotation(
            image_name="test.jpg",
            image_width=640,
            image_height=480,
            instance_label="cat",
            bbox_x_tl=10,
            bbox_y_tl=20,
            bbox_x_br=100,
            bbox_y_br=200,
            task_id=1,
            task_name="test",
            frame_id=0,
            subset="",
            occluded=False,
            z_order=0,
            rotation=0.0,
            source="manual",
            annotation_id=1,
            attributes={},
        )
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
        img_dir.mkdir()
        from PIL import Image

        Image.new("RGB", (640, 480)).save(img_dir / "test.jpg")

        rows = [
            _box_row("test.jpg", "cat", "train"),
            _box_row(
                "test.jpg",
                "dog",
                "train",
                x_tl=200,
                y_tl=100,
                x_br=300,
                y_br=250,
            ),
        ]
        csv_path = _make_dataset_csv(tmp_path, rows)

        out_dir = tmp_path / "yolo_out"
        args = _make_args(
            to_yolo=True,
            from_yolo=False,
            dataset=str(csv_path),
            output=str(out_dir),
            link_mode="copy",
            image_dir=[str(img_dir)],
            names_file=None,
        )
        run_convert(args)

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
        img_dir.mkdir()
        from PIL import Image

        Image.new("RGB", (640, 480)).save(img_dir / "empty.jpg")

        rows = [_none_row("empty.jpg", "val")]
        csv_path = _make_dataset_csv(tmp_path, rows)

        out_dir = tmp_path / "yolo_out"
        args = _make_args(
            to_yolo=True,
            from_yolo=False,
            dataset=str(csv_path),
            output=str(out_dir),
            link_mode="copy",
            image_dir=[str(img_dir)],
            names_file=None,
        )
        run_convert(args)

        label_path = out_dir / "labels" / "val" / "empty.txt"
        assert label_path.is_file()
        assert label_path.read_text() == ""

    def test_missing_split_error(self, tmp_path: Path) -> None:
        """Should error if any image has no split."""
        rows = [_box_row("test.jpg", "cat", "train")]
        rows[0]["split"] = None
        csv_path = _make_dataset_csv(tmp_path, rows)

        out_dir = tmp_path / "yolo_out"
        args = _make_args(
            to_yolo=True,
            from_yolo=False,
            dataset=str(csv_path),
            output=str(out_dir),
            link_mode="copy",
            image_dir=[],
            names_file=None,
        )
        with pytest.raises(SystemExit):
            run_convert(args)

    def test_only_existing_splits_in_yaml(self, tmp_path: Path) -> None:
        """dataset.yaml should only include splits that exist in data."""
        img_dir = tmp_path / "images"
        img_dir.mkdir()
        from PIL import Image

        Image.new("RGB", (640, 480)).save(img_dir / "test.jpg")

        rows = [_box_row("test.jpg", "cat", "val")]
        csv_path = _make_dataset_csv(tmp_path, rows)

        out_dir = tmp_path / "yolo_out"
        args = _make_args(
            to_yolo=True,
            from_yolo=False,
            dataset=str(csv_path),
            output=str(out_dir),
            link_mode="copy",
            image_dir=[str(img_dir)],
            names_file=None,
        )
        run_convert(args)

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
        args = _make_args(
            to_yolo=False,
            from_yolo=True,
            input=str(ds_copy),
            output=str(output_csv),
            image_dir=None,
            names_file=None,
            dataset=None,
            link_mode="auto",
            read_all_sizes=False,
        )
        run_convert(args)

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

        from PIL import Image

        img_dir = tmp_path / "imgs"
        img_dir.mkdir()
        Image.new("RGB", (640, 480)).save(img_dir / "img1.jpg")

        names_path = tmp_path / "names.yaml"
        with names_path.open("w") as f:
            yaml.dump({"names": {0: "cat", 1: "dog"}}, f)

        output_csv = tmp_path / "output.csv"
        args = _make_args(
            to_yolo=False,
            from_yolo=True,
            input=str(pred_dir),
            output=str(output_csv),
            image_dir=[str(img_dir)],
            names_file=str(names_path),
            dataset=None,
            link_mode="auto",
            read_all_sizes=False,
        )
        run_convert(args)

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
        from PIL import Image

        img_dir = tmp_path / "images"
        img_dir.mkdir()
        Image.new("RGB", (640, 480)).save(img_dir / "test.jpg")

        original_rows = [
            _box_row(
                "test.jpg",
                "cat",
                "train",
                x_tl=50.0,
                y_tl=30.0,
                x_br=200.0,
                y_br=180.0,
            ),
            _box_row(
                "test.jpg",
                "dog",
                "train",
                x_tl=300.0,
                y_tl=100.0,
                x_br=500.0,
                y_br=400.0,
            ),
        ]
        original_rows[1]["annotation_id"] = 2
        csv_path = _make_dataset_csv(tmp_path, original_rows)

        # CSV -> YOLO
        yolo_dir = tmp_path / "yolo"
        run_convert(
            _make_args(
                to_yolo=True,
                from_yolo=False,
                dataset=str(csv_path),
                output=str(yolo_dir),
                link_mode="copy",
                image_dir=[str(img_dir)],
                names_file=None,
            )
        )

        # YOLO -> CSV
        roundtrip_csv = tmp_path / "roundtrip.csv"
        run_convert(
            _make_args(
                to_yolo=False,
                from_yolo=True,
                input=str(yolo_dir),
                output=str(roundtrip_csv),
                image_dir=None,
                names_file=None,
                dataset=None,
                link_mode="auto",
                read_all_sizes=False,
            )
        )

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

    def _make_image(self, path: Path, width: int, height: int) -> None:
        from PIL import Image

        img = Image.new("RGB", (width, height))
        img.save(path)

    def test_read_all_false_returns_first_size(self, tmp_path: Path) -> None:
        """When read_all=False, all calls return the first image's size."""
        img1 = tmp_path / "a.jpg"
        img2 = tmp_path / "b.jpg"
        self._make_image(img1, 640, 480)
        self._make_image(img2, 320, 240)

        cache = _SizeCache(read_all=False)
        assert cache.get(img1) == (640, 480)
        assert cache.get(img2) == (640, 480)

    def test_read_all_true_reads_each_image(self, tmp_path: Path) -> None:
        """When read_all=True, each image is read individually."""
        img1 = tmp_path / "a.jpg"
        img2 = tmp_path / "b.jpg"
        self._make_image(img1, 640, 480)
        self._make_image(img2, 320, 240)

        cache = _SizeCache(read_all=True)
        assert cache.get(img1) == (640, 480)
        assert cache.get(img2) == (320, 240)
