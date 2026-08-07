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
    _build_search_dirs,
    _find_image_by_stem,
    _link_or_copy,
    _make_csv_row_base,
    _make_csv_row_box,
    _pixel_to_coco,
    _pixel_to_yolo,
    _read_text_utf8,
    _require_positive_dimensions,
    _SizeCache,
    _validate_splits,
    _write_csv,
    _write_text_utf8,
    _yolo_to_pixel,
)
from cveta2.services.convert.yolo import _load_class_names_yaml, _parse_label_file
from tests.helpers import (
    csv_row,
    make_bbox,
    make_image,
    parse_cli_args,
    write_dataset_csv,
)


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

    @pytest.mark.parametrize(
        ("width", "height"), [(1, 1), (1, 480), (640, 1), (640, 480)]
    )
    def test_positive_dimensions_pass(self, width: int, height: int) -> None:
        """A single-pixel dimension is valid.

        The old test only passed 640x480, so widening either bound to
        ``<= 1`` (rejecting 1-pixel images) changed nothing observable.
        """
        _require_positive_dimensions(width, height, "ok.jpg")


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

    def test_short_line_is_skipped_not_terminal(self, tmp_path: Path) -> None:
        """A malformed 4-field line skips only itself.

        Every fixture file was uniformly well-formed, so replacing the
        ``continue`` with a ``break`` discarded nothing.
        """
        p = tmp_path / "label.txt"
        p.write_text("0 0.5 0.5 0.3\n1 0.1 0.2 0.3 0.4\n")
        assert _parse_label_file(p) == [[1.0, 0.1, 0.2, 0.3, 0.4]]

    def test_blank_lines_and_trailing_whitespace(self, tmp_path: Path) -> None:
        """Blank lines and padding around a line are tolerated."""
        p = tmp_path / "label.txt"
        p.write_text("\n  0 0.5 0.5 0.3 0.4   \n\n")
        assert _parse_label_file(p) == [[0.0, 0.5, 0.5, 0.3, 0.4]]


# ---------------------------------------------------------------------------
# link_or_copy tests
# ---------------------------------------------------------------------------


class TestLinkOrCopy:
    """Tests for _link_or_copy file placement."""

    @pytest.mark.parametrize("mode", ["copy", "symlink", "hardlink"])
    def test_link_mode_places_file(self, tmp_path: Path, mode: str) -> None:
        """Destination sits two levels deep, so ``parents=True`` is load-bearing.

        The old destination was ``tmp_path/out/dst.txt`` — one missing
        level, which ``mkdir(parents=False)`` still creates.
        """
        src = tmp_path / "src.txt"
        src.write_text("hello")
        dst = tmp_path / "out" / "deep" / "dst.txt"
        _link_or_copy(src, dst, mode)
        assert dst.read_text() == "hello"
        if mode == "symlink":
            assert dst.is_symlink()
        if mode == "hardlink":
            assert src.stat().st_ino == dst.stat().st_ino

    def test_unknown_mode_rejected(self, tmp_path: Path) -> None:
        """An unrecognised link mode names itself in the error.

        Nothing exercised the ``else`` branch, so replacing its whole
        message with ``None`` was invisible.
        """
        src = tmp_path / "src.txt"
        src.write_text("hello")
        with pytest.raises(Cveta2Error, match="Неизвестный link-mode: 'teleport'"):
            _link_or_copy(src, tmp_path / "dst.txt", "teleport")

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

    def test_class_ids_are_zero_based(self, tmp_path: Path) -> None:
        """YOLO class ids must start at 0, in both dataset.yaml and label lines.

        The structure test above asserts ``set(ds["names"].values())`` — the
        names, not the keys — and the CSV->YOLO->CSV roundtrip shifts ids and
        names together, so ``label_start=1`` was invisible to both while
        emitting 1-based class ids, i.e. silently invalid training data.
        """
        img_dir = tmp_path / "images"
        make_image(img_dir / "test.jpg")

        rows = [
            csv_row("test.jpg", label="dog", split="train"),
            csv_row(
                "test.jpg",
                label="cat",
                split="train",
                bbox_x_tl=200,
                bbox_x_br=300,
            ),
        ]
        csv_path = _make_dataset_csv(tmp_path, rows)

        out_dir = tmp_path / "yolo_out"
        convert_to_yolo(csv_path, out_dir, image_dirs=[str(img_dir)], link_mode="copy")

        with (out_dir / "dataset.yaml").open() as f:
            ds = yaml.safe_load(f)
        assert ds["names"] == {0: "cat", 1: "dog"}
        assert ds["path"] == str(out_dir.resolve())

        lines = (out_dir / "labels" / "train" / "test.txt").read_text().splitlines()
        assert sorted(int(line.split()[0]) for line in lines) == [0, 1]

    def test_all_three_splits_listed_in_yaml(self, tmp_path: Path) -> None:
        """train/val/test each get an ``images/<split>`` entry.

        Only train and val were ever exercised, so corrupting the "test"
        literal in the split tuple dropped the key unnoticed.
        """
        img_dir = tmp_path / "images"
        rows = []
        for split in ("train", "val", "test"):
            make_image(img_dir / f"{split}.jpg")
            rows.append(csv_row(f"{split}.jpg", label="cat", split=split))
        csv_path = _make_dataset_csv(tmp_path, rows)

        out_dir = tmp_path / "yolo_out"
        convert_to_yolo(csv_path, out_dir, image_dirs=[str(img_dir)], link_mode="copy")

        with (out_dir / "dataset.yaml").open() as f:
            ds = yaml.safe_load(f)
        assert ds["train"] == "images/train"
        assert ds["val"] == "images/val"
        assert ds["test"] == "images/test"

    def test_nested_output_dir_and_rerun(self, tmp_path: Path) -> None:
        """The output tree is created from scratch and a second run is a no-op.

        Every export test used a single missing level and ran once, so
        ``parents=False`` and ``exist_ok=False`` on the output, images and
        labels directories all survived. The ``iterdir`` assertion also pins
        the directory names themselves.
        """
        img_dir = tmp_path / "images"
        make_image(img_dir / "test.jpg")
        rows = [csv_row("test.jpg", label="cat", split="train")]
        csv_path = _make_dataset_csv(tmp_path, rows)

        out_dir = tmp_path / "deep" / "nested" / "yolo_out"
        for _ in range(2):
            convert_to_yolo(
                csv_path, out_dir, image_dirs=[str(img_dir)], link_mode="copy"
            )

        assert sorted(p.name for p in out_dir.iterdir()) == [
            "dataset.yaml",
            "images",
            "labels",
        ]

    def test_default_link_mode_places_the_image(self, tmp_path: Path) -> None:
        """Omitting ``link_mode`` must select a mode ``_link_or_copy`` knows.

        Every test passed ``link_mode="copy"``, so corrupting the "auto"
        default into an unknown mode was never executed.
        """
        img_dir = tmp_path / "images"
        make_image(img_dir / "test.jpg")
        rows = [csv_row("test.jpg", label="cat", split="train")]
        csv_path = _make_dataset_csv(tmp_path, rows)

        out_dir = tmp_path / "yolo_out"
        convert_to_yolo(csv_path, out_dir, image_dirs=[str(img_dir)])

        assert (out_dir / "images" / "train" / "test.jpg").is_file()

    def test_non_positive_csv_dimension_names_the_image(self, tmp_path: Path) -> None:
        """A zero image_width in the CSV aborts, naming the offending image.

        The image name reaches only the error message, so passing ``None``
        for it survived while no export test triggered the guard at all.
        """
        img_dir = tmp_path / "images"
        make_image(img_dir / "zero.jpg")
        rows = [csv_row("zero.jpg", label="cat", split="train", image_width=0)]
        csv_path = _make_dataset_csv(tmp_path, rows)

        with pytest.raises(Cveta2Error, match=r"'zero\.jpg' \(0x480\)"):
            convert_to_yolo(
                csv_path,
                tmp_path / "out",
                image_dirs=[str(img_dir)],
                link_mode="copy",
            )

    def test_missing_image_still_writes_labels(self, tmp_path: Path) -> None:
        """A CSV row whose image is absent from disk is labelled but not copied.

        Every export test had all images on disk, so relaxing the
        ``in found and not in images_processed`` guard to ``or`` never
        reached the ``found[name]`` lookup with a missing key.
        """
        img_dir = tmp_path / "images"
        img_dir.mkdir()
        rows = [csv_row("ghost.jpg", label="cat", split="train")]
        csv_path = _make_dataset_csv(tmp_path, rows)

        out_dir = tmp_path / "yolo_out"
        convert_to_yolo(csv_path, out_dir, image_dirs=[str(img_dir)], link_mode="copy")

        assert (out_dir / "labels" / "train" / "ghost.txt").is_file()
        assert not (out_dir / "images" / "train" / "ghost.jpg").exists()

    def test_image_in_two_splits_is_placed_only_once(self, tmp_path: Path) -> None:
        """An image listed under two splits lands in the first split's dir only.

        This pins current behaviour, and it is the only observable effect of
        the ``images_processed`` bookkeeping: without it the image would be
        copied into every split it appears in. Note the asymmetry - the second
        split still gets a label file, so it ends up with a label and no image.
        """
        img_dir = tmp_path / "images"
        make_image(img_dir / "both.jpg")
        make_image(img_dir / "empty.jpg")

        rows = [
            csv_row("both.jpg", label="cat", split="train"),
            csv_row("both.jpg", shape="none", split="val"),
            csv_row("empty.jpg", shape="none", split="train"),
            csv_row("empty.jpg", shape="none", split="val"),
        ]
        csv_path = _make_dataset_csv(tmp_path, rows)

        out_dir = tmp_path / "yolo_out"
        convert_to_yolo(csv_path, out_dir, image_dirs=[str(img_dir)], link_mode="copy")

        assert (out_dir / "images" / "train" / "both.jpg").is_file()
        assert not (out_dir / "images" / "val" / "both.jpg").exists()
        assert (out_dir / "images" / "train" / "empty.jpg").is_file()
        assert not (out_dir / "images" / "val" / "empty.jpg").exists()
        assert (out_dir / "labels" / "val" / "both.txt").is_file()

    def test_none_shape_places_image_and_keeps_tree_names(self, tmp_path: Path) -> None:
        """A none-shape row copies its image into ``images/<split>``.

        The empty-label test only checked the label file, so inverting either
        half of the copy guard - and corrupting the "images" directory name -
        left no trace.
        """
        img_dir = tmp_path / "images"
        make_image(img_dir / "empty.jpg")
        rows = [csv_row("empty.jpg", shape="none", split="val")]
        csv_path = _make_dataset_csv(tmp_path, rows)

        out_dir = tmp_path / "yolo_out"
        convert_to_yolo(csv_path, out_dir, image_dirs=[str(img_dir)], link_mode="copy")

        assert (out_dir / "images" / "val" / "empty.jpg").is_file()
        assert sorted(p.name for p in out_dir.iterdir()) == [
            "dataset.yaml",
            "images",
            "labels",
        ]

    def test_none_shape_missing_image_still_writes_label(self, tmp_path: Path) -> None:
        """A none-shape row whose image is absent is labelled but not copied.

        Mirrors the box case: relaxing the copy guard to ``or`` would look up
        a key that is not in ``found``.
        """
        img_dir = tmp_path / "images"
        img_dir.mkdir()
        rows = [csv_row("ghost.jpg", shape="none", split="val")]
        csv_path = _make_dataset_csv(tmp_path, rows)

        out_dir = tmp_path / "yolo_out"
        convert_to_yolo(csv_path, out_dir, image_dirs=[str(img_dir)], link_mode="copy")

        assert (out_dir / "labels" / "val" / "ghost.txt").read_text() == ""

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

    def test_default_reuses_the_first_size(self, tmp_path: Path) -> None:
        """Constructed with no arguments, the cache measures only once.

        Both existing tests pass ``read_all`` explicitly, so flipping the
        default was never observed.
        """
        img1 = make_image(tmp_path / "a.jpg", 640, 480)
        img2 = make_image(tmp_path / "b.jpg", 320, 240)

        cache = _SizeCache()
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
    with pytest.raises(Cveta2Error, match="не задан split"):
        export(csv_path, tmp_path / "out", image_dirs=[str(tmp_path)], link_mode="copy")


def test_run_convert_missing_split_exits(tmp_path: Path) -> None:
    """A conversion-logic error propagates to the CLI boundary."""
    rows = [csv_row("test.jpg", label="cat", split="train")]
    rows[0]["split"] = None
    csv_path = _make_dataset_csv(tmp_path, rows)

    args = parse_cli_args(
        "convert",
        "--to-yolo",
        "-d",
        str(csv_path),
        "-o",
        str(tmp_path / "yolo_out"),
        "--link-mode",
        "copy",
    )

    with pytest.raises(Cveta2Error, match="не задан split"):
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

    def test_ids_link_annotations_to_images_and_categories(
        self, tmp_path: Path
    ) -> None:
        """Every annotation points at a real image id and a real category id.

        The existing tests assert absolute starting values on a single-image,
        single-annotation export, which cannot see the id *wiring*: dropping
        the ``image_id`` key, blanking ``image_id_map`` or reusing one
        ``ann_id`` for every annotation all survived.
        """
        img_dir = tmp_path / "images"
        make_image(img_dir / "a.jpg")
        make_image(img_dir / "b.jpg")

        rows = [
            csv_row("a.jpg", label="cat", split="train"),
            csv_row("b.jpg", label="dog", split="train"),
            csv_row(
                "b.jpg",
                label="dog",
                split="train",
                bbox_x_tl=200,
                bbox_x_br=300,
                annotation_id=2,
            ),
        ]
        csv_path = _make_dataset_csv(tmp_path, rows)
        out_dir = _run_to_coco(tmp_path, csv_path, img_dir)

        with (out_dir / "train" / "_annotations.coco.json").open() as f:
            coco = json.load(f)

        image_ids = {im["file_name"]: im["id"] for im in coco["images"]}
        assert sorted(image_ids) == ["a.jpg", "b.jpg"]
        assert len(set(image_ids.values())) == 2

        cat_ids = {c["name"]: c["id"] for c in coco["categories"]}
        assert sorted(cat_ids) == ["cat", "dog"]
        assert [c["supercategory"] for c in coco["categories"]] == ["none", "none"]

        ann_ids = [a["id"] for a in coco["annotations"]]
        assert len(set(ann_ids)) == 3
        assert all(ann_id > 0 for ann_id in ann_ids)

        linked = sorted((a["image_id"], a["category_id"]) for a in coco["annotations"])
        assert linked == sorted(
            [
                (image_ids["a.jpg"], cat_ids["cat"]),
                (image_ids["b.jpg"], cat_ids["dog"]),
                (image_ids["b.jpg"], cat_ids["dog"]),
            ]
        )

    def test_bbox_and_area_rounded_to_two_decimals(self, tmp_path: Path) -> None:
        """Non-round coordinates pin the rounding precision.

        The structure test uses whole-pixel coordinates, where ``round(x, 2)``,
        ``round(x, 3)`` and ``round(x)`` are all equal.
        """
        img_dir = tmp_path / "images"
        make_image(img_dir / "test.jpg")

        rows = [
            csv_row(
                "test.jpg",
                label="cat",
                split="train",
                bbox_x_tl=10.129,
                bbox_y_tl=20.239,
                bbox_x_br=110.987,
                bbox_y_br=120.876,
            ),
        ]
        csv_path = _make_dataset_csv(tmp_path, rows)
        out_dir = _run_to_coco(tmp_path, csv_path, img_dir)

        with (out_dir / "train" / "_annotations.coco.json").open() as f:
            coco = json.load(f)

        ann = coco["annotations"][0]
        assert ann["bbox"] == [10.13, 20.24, 100.86, 100.64]
        assert ann["area"] == 10150.05

    def test_default_link_mode_places_the_image(self, tmp_path: Path) -> None:
        """Omitting ``link_mode`` must select a mode ``_link_or_copy`` knows."""
        img_dir = tmp_path / "images"
        make_image(img_dir / "test.jpg")
        rows = [csv_row("test.jpg", label="cat", split="train")]
        csv_path = _make_dataset_csv(tmp_path, rows)

        out_dir = tmp_path / "coco_out"
        convert_to_coco(csv_path, out_dir, image_dirs=[str(img_dir)])

        assert (out_dir / "train" / "test.jpg").is_file()

    def test_nested_output_dir_and_rerun(self, tmp_path: Path) -> None:
        """The split dirs survive a second run into the same output tree.

        Every COCO test ran once into a fresh directory, so ``exist_ok=False``
        on the split directory was never reached.
        """
        img_dir = tmp_path / "images"
        make_image(img_dir / "test.jpg")
        rows = [csv_row("test.jpg", label="cat", split="train")]
        csv_path = _make_dataset_csv(tmp_path, rows)

        out_dir = tmp_path / "deep" / "nested" / "coco_out"
        for _ in range(2):
            convert_to_coco(
                csv_path, out_dir, image_dirs=[str(img_dir)], link_mode="copy"
            )

        assert (out_dir / "train" / "_annotations.coco.json").is_file()


# ---------------------------------------------------------------------------
# UTF-8 file helpers
# ---------------------------------------------------------------------------


class TestUtf8FileHelpers:
    """Tests for the locale-independent text read/write helpers."""

    def test_roundtrip_writes_utf8_bytes_and_keeps_newlines(
        self, tmp_path: Path
    ) -> None:
        """Content is encoded as UTF-8 with untranslated line endings.

        Nothing ever read the raw bytes of a label file or dataset.yaml back,
        so the codec used to write them was unconstrained.
        """
        path = tmp_path / "t.txt"
        text = "кошка\nсобака\n"
        _write_text_utf8(path, text)
        assert path.read_bytes() == text.encode("utf-8")
        assert _read_text_utf8(path) == text


# ---------------------------------------------------------------------------
# Image search dirs
# ---------------------------------------------------------------------------


class TestBuildSearchDirs:
    """Tests for combining --image-dir args with the image-cache config."""

    @staticmethod
    def _write_image_cache(config_path: Path, projects: dict[str, Path]) -> None:
        config_path.write_text(
            yaml.dump({"image_cache": {k: str(v) for k, v in projects.items()}}),
            encoding="utf-8",
        )

    def test_cache_dirs_follow_the_explicit_ones(
        self, tmp_path: Path, isolated_config_path: Path
    ) -> None:
        """Configured cache dirs are appended after the --image-dir args.

        No test called this function at all, so both the dedup check and the
        appended value itself were free.
        """
        self._write_image_cache(
            isolated_config_path, {"p1": tmp_path / "c1", "p2": tmp_path / "c2"}
        )
        assert _build_search_dirs([tmp_path / "given"]) == [
            tmp_path / "given",
            tmp_path / "c1",
            tmp_path / "c2",
        ]

    def test_cache_dir_already_given_is_not_repeated(
        self, tmp_path: Path, isolated_config_path: Path
    ) -> None:
        """A cache dir passed as --image-dir appears once, not twice."""
        self._write_image_cache(isolated_config_path, {"p1": tmp_path / "shared"})
        assert _build_search_dirs([tmp_path / "shared"]) == [tmp_path / "shared"]

    def test_without_args_only_cache_dirs_remain(
        self, tmp_path: Path, isolated_config_path: Path
    ) -> None:
        """With no --image-dir args the cache dirs are the whole search path."""
        self._write_image_cache(isolated_config_path, {"p1": tmp_path / "c1"})
        assert _build_search_dirs(None) == [tmp_path / "c1"]


class TestFindImageByStem:
    """Tests for the search order of ``_find_image_by_stem``."""

    def test_flat_file_beats_subdir(self, tmp_path: Path) -> None:
        """A flat hit wins over the same stem inside a subdir."""
        make_image(tmp_path / "a.jpg")
        make_image(tmp_path / "images" / "a.jpg")
        found = _find_image_by_stem("a", [tmp_path], subdirs=["images"])
        assert found == tmp_path / "a.jpg"

    def test_earlier_extension_wins(self, tmp_path: Path) -> None:
        """``.jpg`` precedes ``.png`` in the extension order."""
        make_image(tmp_path / "a.png")
        make_image(tmp_path / "a.jpg")
        assert _find_image_by_stem("a", [tmp_path]) == tmp_path / "a.jpg"

    def test_earlier_dir_wins(self, tmp_path: Path) -> None:
        """The first search dir holding the stem wins."""
        make_image(tmp_path / "first" / "a.jpg")
        make_image(tmp_path / "second" / "a.jpg")
        found = _find_image_by_stem("a", [tmp_path / "first", tmp_path / "second"])
        assert found == tmp_path / "first" / "a.jpg"

    def test_missing_dir_does_not_stop_the_search(self, tmp_path: Path) -> None:
        """A nonexistent search dir is skipped, not treated as the end.

        Only ever called with existing dirs, so turning the ``continue``
        into a ``break`` was invisible.
        """
        make_image(tmp_path / "real" / "a.jpg")
        found = _find_image_by_stem("a", [tmp_path / "gone", tmp_path / "real"])
        assert found == tmp_path / "real" / "a.jpg"

    def test_found_inside_subdir(self, tmp_path: Path) -> None:
        """A stem only present under a subdir is still found.

        Every previous call resolved on the flat ``.jpg`` case, so the whole
        subdir loop was unexecuted.
        """
        make_image(tmp_path / "images" / "a.png")
        found = _find_image_by_stem("a", [tmp_path], subdirs=["images"])
        assert found == tmp_path / "images" / "a.png"

    def test_missing_subdir_does_not_stop_the_search(self, tmp_path: Path) -> None:
        """A nonexistent subdir is skipped, not treated as the end."""
        make_image(tmp_path / "images" / "a.jpg")
        found = _find_image_by_stem("a", [tmp_path], subdirs=["gone", "images"])
        assert found == tmp_path / "images" / "a.jpg"

    def test_returns_none_when_nothing_matches(self, tmp_path: Path) -> None:
        """An absent stem yields None rather than raising."""
        assert _find_image_by_stem("a", [tmp_path], subdirs=["images"]) is None


# ---------------------------------------------------------------------------
# CSV row builders and writer
# ---------------------------------------------------------------------------


class TestCsvRowBuilders:
    """Tests for the row dicts stamped on every YOLO-imported annotation."""

    def test_base_row_stamps_yolo_provenance(self) -> None:
        """The full row dict is pinned, constants included.

        Nothing asserted the provenance columns this function fills in, so
        every literal in it - ``task_name``, ``source``, the empty strings,
        even the ``img_size`` index - was free to change.
        """
        row = _make_csv_row_base(
            "none", "img.jpg", (640, 480), split="train", frame_id=7
        )
        expected: dict[str, object] = dict.fromkeys(CSV_COLUMNS, None)
        expected.update(
            image_name="img.jpg",
            image_width=640,
            image_height=480,
            instance_shape="none",
            task_id=0,
            task_name="yolo",
            task_status="",
            task_updated_date="",
            created_by_username="",
            frame_id=7,
            split="train",
            subset="",
            source="yolo",
            attributes="{}",
        )
        assert row == expected

    def test_box_row_rounds_coordinates_to_two_decimals(self) -> None:
        """Box columns are pinned with coordinates that survive rounding.

        Coordinates with more than two decimals are what makes ``round(x, 3)``
        and a dropped precision argument distinguishable.
        """
        row = _make_csv_row_box(
            image_name="img.jpg",
            img_w=640,
            img_h=480,
            label="cat",
            x_tl=12.3456,
            y_tl=34.5678,
            x_br=56.7891,
            y_br=78.9123,
            split="val",
            frame_id=3,
            annotation_id=9,
            confidence=0.5,
        )
        expected: dict[str, object] = dict.fromkeys(CSV_COLUMNS, None)
        expected.update(
            image_name="img.jpg",
            image_width=640,
            image_height=480,
            instance_shape="box",
            instance_label="cat",
            bbox_x_tl=12.35,
            bbox_y_tl=34.57,
            bbox_x_br=56.79,
            bbox_y_br=78.91,
            occluded=False,
            z_order=0,
            rotation=0.0,
            annotation_id=9,
            confidence=0.5,
            task_id=0,
            task_name="yolo",
            task_status="",
            task_updated_date="",
            created_by_username="",
            frame_id=3,
            split="val",
            subset="",
            source="yolo",
            attributes="{}",
        )
        assert row == expected


class TestWriteCsv:
    """Tests for the CSV writer shared by both from-YOLO modes."""

    def test_empty_rows_still_write_the_header(self, tmp_path: Path) -> None:
        """A run that produced no rows writes a headers-only CSV.

        Without the explicit ``columns`` the frame would have no columns at
        all and the file would be unreadable; nothing covered that path, nor
        an output path whose parent chain does not exist yet.
        """
        out = tmp_path / "a" / "b" / "out.csv"
        _write_csv([], out)
        df = pd.read_csv(out)
        assert list(df.columns) == list(CSV_COLUMNS)
        assert len(df) == 0

    def test_dataframe_index_is_not_written(self, tmp_path: Path) -> None:
        """No extra index column leaks into the CSV."""
        out = tmp_path / "out.csv"
        row = _make_csv_row_base("none", "a.jpg", (10, 20), split=None, frame_id=0)
        _write_csv([row], out)
        assert list(pd.read_csv(out).columns) == list(CSV_COLUMNS)


class TestValidateSplits:
    """Tests for the split-completeness guard."""

    def test_empty_string_split_is_rejected(self) -> None:
        """A literal empty split is as invalid as a missing one.

        ``pd.read_csv`` turns empty fields into NaN, so no CSV-driven test can
        reach the ``== ""`` half of the condition - only a direct call can.
        """
        df = pd.DataFrame(
            [
                {"image_name": "a.jpg", "split": ""},
                {"image_name": "b.jpg", "split": "train"},
            ]
        )
        with pytest.raises(
            Cveta2Error, match=r"у 1 изображений не задан split\. Примеры: a\.jpg"
        ):
            _validate_splits(df)


# ---------------------------------------------------------------------------
# from-YOLO: dataset mode
# ---------------------------------------------------------------------------

_TWO_BOXES = "0 0.5 0.5 0.2 0.2\n1 0.25 0.25 0.1 0.1\n"


def _write_yolo_label(root: Path, split: str, stem: str, text: str) -> None:
    """Write one YOLO label file under ``<root>/labels/<split>``."""
    path = root / "labels" / split / f"{stem}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_yolo_yaml(
    root: Path,
    names: dict[int, str],
    splits: list[str],
    *,
    include_names: bool = True,
) -> None:
    """Write a minimal ultralytics dataset.yaml listing *splits*."""
    data: dict[str, object] = {"names": names} if include_names else {}
    for split in splits:
        data[split] = f"images/{split}"
    (root / "dataset.yaml").write_text(yaml.dump(data), encoding="utf-8")


class TestFromYoloDatasetRows:
    """Tests for the CSV rows produced by dataset mode."""

    @staticmethod
    def _three_labelled_images(root: Path) -> None:
        for stem in ("a", "b", "c"):
            make_image(root / "images" / "train" / f"{stem}.jpg")
            _write_yolo_label(root, "train", stem, _TWO_BOXES)
        _write_yolo_yaml(root, {0: "cat", 1: "dog"}, ["train"])

    def test_frame_and_annotation_ids_are_sequential(self, tmp_path: Path) -> None:
        """frame_id counts images from 0; annotation_id counts boxes from 1.

        Nothing asserted either column, so every counter mutation - a wrong
        start, a decrement, a step of two, or assignment instead of increment
        - produced an identical-looking CSV. Three images are needed: with two,
        ``frame_id = 1`` and ``frame_id += 1`` agree.
        """
        root = tmp_path / "ds"
        self._three_labelled_images(root)

        out = tmp_path / "out.csv"
        convert_from_yolo(root, out, read_all_sizes=False)

        df = pd.read_csv(out)
        assert df["frame_id"].tolist() == [0, 0, 1, 1, 2, 2]
        assert df["annotation_id"].tolist() == [1, 2, 3, 4, 5, 6]
        assert (
            df["image_name"].tolist() == ["a.jpg"] * 2 + ["b.jpg"] * 2 + ["c.jpg"] * 2
        )
        assert df["instance_label"].tolist() == ["cat", "dog"] * 3
        assert df["split"].tolist() == ["train"] * 6

    def test_unlabelled_image_becomes_a_none_row(self, tmp_path: Path) -> None:
        """An image with no label file yields one ``instance_shape=none`` row.

        The coco8 fixture labels every image, so the whole none-row branch -
        its shape literal, its size tuple, its split and frame_id - was never
        executed.
        """
        root = tmp_path / "ds"
        make_image(root / "images" / "train" / "a.jpg")
        make_image(root / "images" / "train" / "b.jpg")
        _write_yolo_label(root, "train", "a", _TWO_BOXES)
        _write_yolo_yaml(root, {0: "cat", 1: "dog"}, ["train"])

        out = tmp_path / "out.csv"
        convert_from_yolo(root, out, read_all_sizes=False)

        df = pd.read_csv(out)
        none_rows = df[df["instance_shape"] == "none"]
        assert len(none_rows) == 1
        row = none_rows.iloc[0]
        assert row["image_name"] == "b.jpg"
        assert row["split"] == "train"
        assert row["frame_id"] == 1
        assert row["image_width"] == 640
        assert row["image_height"] == 480
        assert pd.isna(row["instance_label"])

    @staticmethod
    def _two_differently_sized_images(root: Path) -> None:
        make_image(root / "images" / "train" / "a.jpg", 640, 480)
        make_image(root / "images" / "train" / "b.jpg", 320, 240)
        for stem in ("a", "b"):
            _write_yolo_label(root, "train", stem, "0 0.5 0.5 0.2 0.2\n")
        _write_yolo_yaml(root, {0: "cat"}, ["train"])

    def test_first_image_size_is_reused_by_default(self, tmp_path: Path) -> None:
        """Without ``read_all_sizes`` every row carries the first image's size.

        No test asserted ``image_width``/``image_height`` at all, and every
        call passed ``read_all_sizes`` explicitly, so both the default and the
        size-caching itself were unobserved.
        """
        root = tmp_path / "ds"
        self._two_differently_sized_images(root)

        out = tmp_path / "out.csv"
        convert_from_yolo(root, out)

        df = pd.read_csv(out)
        assert df["image_width"].tolist() == [640, 640]
        assert df["image_height"].tolist() == [480, 480]

    def test_read_all_sizes_measures_every_image(self, tmp_path: Path) -> None:
        """``read_all_sizes=True`` stamps each image's own dimensions."""
        root = tmp_path / "ds"
        self._two_differently_sized_images(root)

        out = tmp_path / "out.csv"
        convert_from_yolo(root, out, read_all_sizes=True)

        df = pd.read_csv(out)
        assert df["image_width"].tolist() == [640, 320]
        assert df["image_height"].tolist() == [480, 240]

    def test_non_positive_image_size_names_the_image(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A degenerate image size aborts, naming the offending file.

        Real images always report positive dimensions, so the guard was never
        triggered from this path and the image name it reports was free.
        """
        root = tmp_path / "ds"
        make_image(root / "images" / "train" / "flat.jpg")
        _write_yolo_label(root, "train", "flat", "0 0.5 0.5 0.2 0.2\n")
        _write_yolo_yaml(root, {0: "cat"}, ["train"])
        monkeypatch.setattr(convert, "_get_image_size", lambda _path: (0, 10))

        with pytest.raises(Cveta2Error, match=r"'flat\.jpg' \(0x10\)"):
            convert_from_yolo(root, tmp_path / "out.csv", read_all_sizes=False)


class TestFromYoloDatasetSplits:
    """Tests for how dataset mode walks the train/val/test keys."""

    @staticmethod
    def _labelled(root: Path, split: str, stem: str) -> None:
        make_image(root / "images" / split / f"{stem}.jpg")
        _write_yolo_label(root, split, stem, "0 0.5 0.5 0.2 0.2\n")

    def test_split_absent_from_yaml_is_skipped(self, tmp_path: Path) -> None:
        """A missing ``train`` key does not stop val and test from loading.

        The fixture always defines train first, so replacing the ``continue``
        with a ``break`` never lost anything.
        """
        root = tmp_path / "ds"
        self._labelled(root, "val", "a")
        self._labelled(root, "test", "b")
        _write_yolo_yaml(root, {0: "cat"}, ["val", "test"])

        out = tmp_path / "out.csv"
        convert_from_yolo(root, out, read_all_sizes=False)

        assert sorted(pd.read_csv(out)["split"]) == ["test", "val"]

    def test_split_with_missing_images_dir_is_skipped(self, tmp_path: Path) -> None:
        """A yaml entry pointing at a nonexistent dir warns and moves on."""
        root = tmp_path / "ds"
        self._labelled(root, "test", "b")
        _write_yolo_yaml(root, {0: "cat"}, ["val", "test"])

        out = tmp_path / "out.csv"
        convert_from_yolo(root, out, read_all_sizes=False)

        assert pd.read_csv(out)["split"].tolist() == ["test"]

    def test_non_image_files_are_skipped(self, tmp_path: Path) -> None:
        """A stray file sorted before the images does not end the walk."""
        root = tmp_path / "ds"
        self._labelled(root, "train", "zz")
        (root / "images" / "train" / "aa.txt").write_text("note", encoding="utf-8")
        _write_yolo_yaml(root, {0: "cat"}, ["train"])

        out = tmp_path / "out.csv"
        convert_from_yolo(root, out, read_all_sizes=False)

        assert pd.read_csv(out)["image_name"].tolist() == ["zz.jpg"]

    def test_yaml_without_names_is_rejected(self, tmp_path: Path) -> None:
        """A dataset.yaml with no ``names`` mapping aborts with an explanation.

        Nothing exercised this guard, so both its message and the ``{}``
        fallback that feeds it were unconstrained.
        """
        root = tmp_path / "ds"
        self._labelled(root, "train", "a")
        _write_yolo_yaml(root, {}, ["train"], include_names=False)

        with pytest.raises(Cveta2Error, match="не найдены имена классов"):
            convert_from_yolo(root, tmp_path / "out.csv", read_all_sizes=False)


# ---------------------------------------------------------------------------
# from-YOLO: prediction mode
# ---------------------------------------------------------------------------


class TestFromYoloPredictions:
    """Tests for bare-.txt prediction mode."""

    @staticmethod
    def _names_file(tmp_path: Path, names: dict[int, str]) -> Path:
        path = tmp_path / "names.yaml"
        path.write_text(yaml.dump({"names": names}), encoding="utf-8")
        return path

    def test_ids_are_sequential_and_images_come_from_the_subdir(
        self, tmp_path: Path
    ) -> None:
        """Images live in ``<input>/images``; ids count frames and boxes.

        Prediction fixtures always put images in a separate --image-dir, so
        the ``subdirs=["images"]`` lookup was never used, and neither counter
        was ever asserted. Three frames are needed to separate ``frame_id = 1``
        from ``frame_id += 1``.
        """
        pred_dir = tmp_path / "preds"
        for stem in ("a", "b", "c"):
            make_image(pred_dir / "images" / f"{stem}.jpg")
            (pred_dir / f"{stem}.txt").write_text(_TWO_BOXES, encoding="utf-8")

        out = tmp_path / "out.csv"
        convert_from_yolo(
            pred_dir,
            out,
            names_file=self._names_file(tmp_path, {0: "cat", 1: "dog"}),
            read_all_sizes=False,
        )

        df = pd.read_csv(out)
        assert df["frame_id"].tolist() == [0, 0, 1, 1, 2, 2]
        assert df["annotation_id"].tolist() == [1, 2, 3, 4, 5, 6]
        assert (
            df["image_name"].tolist() == ["a.jpg"] * 2 + ["b.jpg"] * 2 + ["c.jpg"] * 2
        )
        assert df["image_width"].tolist() == [640] * 6
        assert df["split"].isna().all()

    def test_nested_label_files_are_found(self, tmp_path: Path) -> None:
        """The ``**/*.txt`` glob reaches label files in subdirectories.

        Every prediction fixture directory was flat.
        """
        pred_dir = tmp_path / "preds"
        make_image(pred_dir / "images" / "deep.jpg")
        nested = pred_dir / "run1" / "labels"
        nested.mkdir(parents=True)
        (nested / "deep.txt").write_text("0 0.5 0.5 0.2 0.2\n", encoding="utf-8")

        out = tmp_path / "out.csv"
        convert_from_yolo(
            pred_dir,
            out,
            names_file=self._names_file(tmp_path, {0: "cat"}),
            read_all_sizes=False,
        )

        assert pd.read_csv(out)["image_name"].tolist() == ["deep.jpg"]

    def test_empty_label_file_is_skipped(self, tmp_path: Path) -> None:
        """A detection-free .txt is skipped without ending the walk."""
        pred_dir = tmp_path / "preds"
        make_image(pred_dir / "images" / "b.jpg")
        (pred_dir / "a.txt").write_text("\n", encoding="utf-8")
        (pred_dir / "b.txt").write_text("0 0.5 0.5 0.2 0.2\n", encoding="utf-8")

        out = tmp_path / "out.csv"
        convert_from_yolo(
            pred_dir,
            out,
            names_file=self._names_file(tmp_path, {0: "cat"}),
            read_all_sizes=False,
        )

        df = pd.read_csv(out)
        assert df["image_name"].tolist() == ["b.jpg"]
        assert df["frame_id"].tolist() == [0]

    def test_missing_image_is_collected_and_the_walk_continues(
        self, tmp_path: Path, capture_logs: list[str]
    ) -> None:
        """A .txt with no matching image is reported, later files still load.

        Nothing produced a missing image here, so the ``missing_images`` list
        was never appended to and the skip never had to resume.
        """
        pred_dir = tmp_path / "preds"
        make_image(pred_dir / "images" / "b.jpg")
        (pred_dir / "a.txt").write_text("0 0.5 0.5 0.2 0.2\n", encoding="utf-8")
        (pred_dir / "b.txt").write_text("0 0.5 0.5 0.2 0.2\n", encoding="utf-8")

        out = tmp_path / "out.csv"
        convert_from_yolo(
            pred_dir,
            out,
            names_file=self._names_file(tmp_path, {0: "cat"}),
            read_all_sizes=False,
        )

        assert pd.read_csv(out)["image_name"].tolist() == ["b.jpg"]
        assert any("Не найдены изображения для 1" in m for m in capture_logs)

    def test_directory_without_txt_files_is_rejected(self, tmp_path: Path) -> None:
        """An input dir holding no .txt at all aborts with an explanation."""
        pred_dir = tmp_path / "preds"
        pred_dir.mkdir()

        with pytest.raises(Cveta2Error, match=r"не найдено \.txt файлов"):
            convert_from_yolo(pred_dir, tmp_path / "out.csv", read_all_sizes=False)

    def test_unknown_class_id_gets_a_placeholder_label(self, tmp_path: Path) -> None:
        """A class id absent from the names map becomes ``class_<id>``.

        Every fixture only used ids present in the map, so dropping the
        ``.get`` default left the label ``None`` unnoticed.
        """
        pred_dir = tmp_path / "preds"
        make_image(pred_dir / "images" / "a.jpg")
        (pred_dir / "a.txt").write_text("7 0.5 0.5 0.2 0.2\n", encoding="utf-8")

        out = tmp_path / "out.csv"
        convert_from_yolo(
            pred_dir,
            out,
            names_file=self._names_file(tmp_path, {0: "cat"}),
            read_all_sizes=False,
        )

        assert pd.read_csv(out)["instance_label"].tolist() == ["class_7"]

    def test_read_all_sizes_measures_every_image(self, tmp_path: Path) -> None:
        """``read_all_sizes=True`` reaches prediction mode too.

        The flag has a second, separate call site here that no test used.
        """
        pred_dir = tmp_path / "preds"
        make_image(pred_dir / "images" / "a.jpg", 640, 480)
        make_image(pred_dir / "images" / "b.jpg", 320, 240)
        for stem in ("a", "b"):
            (pred_dir / f"{stem}.txt").write_text(
                "0 0.5 0.5 0.2 0.2\n", encoding="utf-8"
            )

        out = tmp_path / "out.csv"
        convert_from_yolo(
            pred_dir,
            out,
            names_file=self._names_file(tmp_path, {0: "cat"}),
            read_all_sizes=True,
        )

        df = pd.read_csv(out)
        assert df["image_width"].tolist() == [640, 320]
        assert df["image_height"].tolist() == [480, 240]

    def test_non_positive_image_size_names_the_image(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A degenerate image size aborts, naming the offending file."""
        pred_dir = tmp_path / "preds"
        make_image(pred_dir / "images" / "flat.jpg")
        (pred_dir / "flat.txt").write_text("0 0.5 0.5 0.2 0.2\n", encoding="utf-8")
        monkeypatch.setattr(convert, "_get_image_size", lambda _path: (0, 10))

        with pytest.raises(Cveta2Error, match=r"'flat\.jpg' \(0x10\)"):
            convert_from_yolo(pred_dir, tmp_path / "out.csv", read_all_sizes=False)


# ---------------------------------------------------------------------------
# Class-name YAML loading
# ---------------------------------------------------------------------------


class TestLoadClassNamesYaml:
    """Tests for the ``--names`` file reader used by prediction mode."""

    def test_missing_file_is_rejected(self, tmp_path: Path) -> None:
        """The error names the path it could not find."""
        with pytest.raises(Cveta2Error, match="файл имён классов не найден"):
            _load_class_names_yaml(tmp_path / "nope.yaml")

    def test_names_key_mapping(self, tmp_path: Path) -> None:
        """A ``{names: {...}}`` document yields the inner mapping."""
        path = tmp_path / "names.yaml"
        path.write_text(yaml.dump({"names": {0: "cat", 1: "dog"}}), encoding="utf-8")
        assert _load_class_names_yaml(path) == {0: "cat", 1: "dog"}

    def test_flat_mapping(self, tmp_path: Path) -> None:
        """A bare ``{0: cat}`` document is accepted too.

        Only the ``names``-keyed form was ever loaded, so the flat branch's
        key and value conversions were unexecuted.
        """
        path = tmp_path / "names.yaml"
        path.write_text(yaml.dump({0: "cat", 1: "dog"}), encoding="utf-8")
        assert _load_class_names_yaml(path) == {0: "cat", 1: "dog"}

    def test_non_mapping_document_yields_no_names(self, tmp_path: Path) -> None:
        """A YAML file that is not a mapping degrades to an empty map.

        Both branches guard on ``isinstance(data, dict)``; with only mappings
        ever loaded, weakening the first guard to ``or`` was invisible.
        """
        path = tmp_path / "names.yaml"
        path.write_text("names\n", encoding="utf-8")
        assert _load_class_names_yaml(path) == {}
