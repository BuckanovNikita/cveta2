"""Unit tests for cveta2/services/convert/yolo.py (CSV <-> YOLO)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd
import pytest
import yaml

from cveta2.exceptions import Cveta2Error
from cveta2.services.convert import common as convert
from cveta2.services.convert import (
    convert_from_yolo,
    convert_to_yolo,
)
from cveta2.services.convert.yolo import _load_class_names_yaml, _parse_label_file
from tests.helpers import (
    csv_row,
    make_image,
    write_convert_csv,
)

COCO8_ROOT = Path(__file__).parent / "fixtures" / "data" / "coco8"
COCO8_YAML = Path(__file__).parent / "fixtures" / "data" / "coco8.yaml"

_TWO_BOXES = "0 0.5 0.5 0.2 0.2\n1 0.25 0.25 0.1 0.1\n"


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

    def test_non_numeric_line_is_skipped_not_terminal(self, tmp_path: Path) -> None:
        """A line of the right length but the wrong type skips only itself.

        ``float(part)`` used to escape uncaught, so one header row or one
        stray token anywhere in a label tree aborted the whole conversion
        with a bare ``ValueError``.
        """
        p = tmp_path / "label.txt"
        p.write_text("class xc yc w h\n1 0.1 0.2 0.3 0.4\n")
        assert _parse_label_file(p) == [[1.0, 0.1, 0.2, 0.3, 0.4]]

    @pytest.mark.parametrize(
        "bad_lines",
        [
            pytest.param(["0 0.5 0.5 0.3", "2 0.1 0.2"], id="too-short"),
            pytest.param(["class xc yc w h", "x y z w h"], id="non-numeric"),
        ],
    )
    def test_skipped_lines_are_counted_in_a_warning(
        self, tmp_path: Path, capture_logs: list[str], bad_lines: list[str]
    ) -> None:
        """How many lines were dropped is reported, not just *that* some were.

        The count is the whole point of the summary: a caller reading
        "1 skipped" when 2 were dropped is told the result is more complete
        than it is.  Asserted per skip reason so neither branch's counter can
        stand in for the other's.
        """
        p = tmp_path / "label.txt"
        p.write_text("\n".join([*bad_lines, "1 0.1 0.2 0.3 0.4"]) + "\n")

        assert _parse_label_file(p) == [[1.0, 0.1, 0.2, 0.3, 0.4]]
        assert [message.rsplit(": ", 1)[-1] for message in capture_logs] == ["2"]

    def test_well_formed_file_warns_nothing(
        self, tmp_path: Path, capture_logs: list[str]
    ) -> None:
        """Neither a 5-field box nor a 6-field prediction line is reported.

        The 6-field line pins the ``>`` in the extra-fields guard: with only
        5-field lines here, ``>=`` would warn about every prediction file
        and still pass.
        """
        p = tmp_path / "label.txt"
        p.write_text("0 0.5 0.5 0.3 0.4\n1 0.5 0.5 0.3 0.4 0.95\n")
        assert len(_parse_label_file(p)) == 2
        assert capture_logs == []

    def test_extra_fields_are_kept_but_counted_in_a_warning(
        self, tmp_path: Path, capture_logs: list[str]
    ) -> None:
        """A segmentation/OBB line is still returned whole, and reported.

        Such lines used to be read silently as boxes made of the first two
        polygon vertices. They are still accepted — ultralytics track output
        (``cls xc yc w h conf id``) and pose labels start with a valid
        detection line — but the caller now learns how many there were.
        Two such lines separate ``+= 1`` from ``= 1``.
        """
        p = tmp_path / "label.txt"
        obb = "0 0.1 0.1 0.9 0.1 0.9 0.9 0.1 0.9"
        p.write_text(f"{obb}\n1 0.5 0.5 0.3 0.4\n{obb}\n")

        rows = _parse_label_file(p)

        assert [len(row) for row in rows] == [9, 5, 9]
        assert rows[0] == [0.0, 0.1, 0.1, 0.9, 0.1, 0.9, 0.9, 0.1, 0.9]
        assert len(capture_logs) == 1
        assert "Строк с полями сверх 6" in capture_logs[0]
        assert str(p) in capture_logs[0]
        assert capture_logs[0].endswith(": 2; учтены только class xc yc w h [conf]")

    def test_extra_fields_and_skipped_lines_are_counted_apart(
        self, tmp_path: Path, capture_logs: list[str]
    ) -> None:
        """Each warning carries its own count; a bad long line counts once.

        A non-numeric 9-field line is a skipped line, not an extra-fields
        line, so it must not inflate the second counter.
        """
        p = tmp_path / "label.txt"
        p.write_text(
            "0 0.5 0.5 0.3\n"
            "x y z w h a b c d\n"
            "0 0.1 0.1 0.9 0.1 0.9 0.9 0.1 0.9\n"
            "1 0.5 0.5 0.3 0.4\n"
        )

        assert len(_parse_label_file(p)) == 2
        assert [m.split(": ", 1)[0] for m in capture_logs] == [
            "Пропущено нечитаемых строк в " + str(p),
            f"Строк с полями сверх 6 (сегментация/OBB/keypoints?) в {p}",
        ]
        assert capture_logs[0].endswith(": 2")
        assert capture_logs[1].endswith(": 1; учтены только class xc yc w h [conf]")


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
        csv_path = write_convert_csv(tmp_path, rows)

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
        csv_path = write_convert_csv(tmp_path, rows)

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
        csv_path = write_convert_csv(tmp_path, rows)

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
        csv_path = write_convert_csv(tmp_path, rows)

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
        csv_path = write_convert_csv(tmp_path, rows)

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
        csv_path = write_convert_csv(tmp_path, rows)

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
        csv_path = write_convert_csv(tmp_path, rows)

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
        csv_path = write_convert_csv(tmp_path, rows)

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
        csv_path = write_convert_csv(tmp_path, rows)

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
        csv_path = write_convert_csv(tmp_path, rows)

        out_dir = tmp_path / "yolo_out"
        convert_to_yolo(csv_path, out_dir, image_dirs=[str(img_dir)], link_mode="copy")

        assert (out_dir / "labels" / "val" / "ghost.txt").read_text() == ""

    def test_empty_labels_for_none_shape(self, tmp_path: Path) -> None:
        """Images with instance_shape=none should get empty label files."""
        img_dir = tmp_path / "images"
        make_image(img_dir / "empty.jpg")

        rows = [csv_row("empty.jpg", shape="none", split="val")]
        csv_path = write_convert_csv(tmp_path, rows)

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
        csv_path = write_convert_csv(tmp_path, rows)

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


class TestFromYoloDataset:
    """Tests for --from-yolo YOLO to CSV conversion."""

    def test_coco8_dataset(self, tmp_path: Path) -> None:
        """Convert coco8 fixture to CSV and check basic properties."""
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
        csv_path = write_convert_csv(tmp_path, original_rows)

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


def _write_yolo_label(root: Path, split: str, stem: str, text: str) -> None:
    """Write one YOLO label file under ``<root>/labels/<split>``."""
    path = root / "labels" / split / f"{stem}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_yolo_yaml(
    root: Path,
    names: dict[int, str] | list[str],
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

    def test_list_form_names_are_indexed_by_position(self, tmp_path: Path) -> None:
        """``names: [cat, dog]`` — the YOLOv5-era form — maps ids by position.

        Ultralytics accepts the list form and normalises it itself; here it
        raised a bare ``AttributeError`` on ``.items()``.
        """
        root = tmp_path / "ds"
        make_image(root / "images" / "train" / "a.jpg")
        _write_yolo_label(root, "train", "a", _TWO_BOXES)
        _write_yolo_yaml(root, ["cat", "dog"], ["train"])

        out = tmp_path / "out.csv"
        convert_from_yolo(root, out, read_all_sizes=False)

        assert pd.read_csv(out)["instance_label"].tolist() == ["cat", "dog"]

    @pytest.mark.parametrize("names_value", ["names: 3\n", "names: null\n"])
    def test_scalar_names_are_rejected(self, tmp_path: Path, names_value: str) -> None:
        """A ``names`` that is neither list nor mapping aborts with an explanation.

        A missing key keeps its own message (see the test above); only an
        explicit wrong-typed value reaches this one.
        """
        root = tmp_path / "ds"
        self._labelled(root, "train", "a")
        (root / "dataset.yaml").write_text(
            f"train: images/train\n{names_value}", encoding="utf-8"
        )

        with pytest.raises(
            Cveta2Error,
            match=r"names в .*dataset\.yaml должен быть списком или словарём",
        ):
            convert_from_yolo(root, tmp_path / "out.csv", read_all_sizes=False)

    def test_empty_yaml_is_rejected(self, tmp_path: Path) -> None:
        """An empty dataset.yaml aborts with an explanation, not AttributeError.

        ``yaml.safe_load`` returns ``None`` for an empty document, and the
        ``.get("names")`` that followed raised a bare ``AttributeError``.
        """
        root = tmp_path / "ds"
        self._labelled(root, "train", "a")
        (root / "dataset.yaml").write_text("", encoding="utf-8")

        with pytest.raises(Cveta2Error, match="не содержит YAML-словарь"):
            convert_from_yolo(root, tmp_path / "out.csv", read_all_sizes=False)

    def test_scalar_yaml_is_rejected(self, tmp_path: Path) -> None:
        """A dataset.yaml holding a bare scalar is rejected the same way."""
        root = tmp_path / "ds"
        self._labelled(root, "train", "a")
        (root / "dataset.yaml").write_text("just-a-string", encoding="utf-8")

        with pytest.raises(Cveta2Error, match="не содержит YAML-словарь"):
            convert_from_yolo(root, tmp_path / "out.csv", read_all_sizes=False)


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

    def test_list_form_names_file_maps_ids_by_position(self, tmp_path: Path) -> None:
        """A ``--names-file`` holding ``names: [cat, dog]`` labels boxes by index."""
        pred_dir = tmp_path / "preds"
        make_image(pred_dir / "images" / "a.jpg")
        (pred_dir / "a.txt").write_text(_TWO_BOXES, encoding="utf-8")
        names_path = tmp_path / "names.yaml"
        names_path.write_text("names: [cat, dog]\n", encoding="utf-8")

        out = tmp_path / "out.csv"
        convert_from_yolo(pred_dir, out, names_file=names_path, read_all_sizes=False)

        assert pd.read_csv(out)["instance_label"].tolist() == ["cat", "dog"]

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

    def test_list_form_names_are_indexed_and_stringified(self, tmp_path: Path) -> None:
        """``names: [cat, 7]`` yields ``{0: "cat", 1: "7"}``.

        Asserted on the function, not through the CSV: ``pd.read_csv`` would
        coerce ``"7"`` back to an int and hide a missing ``str()``.
        """
        path = tmp_path / "names.yaml"
        path.write_text("names: [cat, 7]\n", encoding="utf-8")
        assert _load_class_names_yaml(path) == {0: "cat", 1: "7"}

    @pytest.mark.parametrize("document", ["names: 3\n", "names: null\n"])
    def test_scalar_names_value_is_rejected(
        self, tmp_path: Path, document: str
    ) -> None:
        """A mapping whose ``names`` is a scalar aborts, naming the file.

        A bare scalar document still yields ``{}`` (see the test above); the
        raise is reserved for an explicit ``names`` of the wrong type.
        """
        path = tmp_path / "names.yaml"
        path.write_text(document, encoding="utf-8")
        with pytest.raises(
            Cveta2Error, match=r"names в .*names\.yaml должен быть списком или словарём"
        ):
            _load_class_names_yaml(path)
