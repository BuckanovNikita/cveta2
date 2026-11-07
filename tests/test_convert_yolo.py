"""Unit tests for cveta2/services/convert/yolo.py (CSV <-> YOLO)."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Literal

import pandas as pd
import pytest
import yaml
from hypothesis import example, given
from hypothesis import strategies as st

from cveta2.adapters.files.conversion import (
    LocalConversionFiles,
    _images_from_split_source,
    _load_class_names_yaml,
    _resolve_dataset_root,
    _resolve_listed_image,
)
from cveta2.application.use_cases.convert.yolo import _parse_label_file
from cveta2.composition.conversion import convert_from_yolo, convert_to_yolo
from cveta2.domain.conversion import _label_path_for_image
from cveta2.domain.errors import Cveta2Error
from tests.helpers import (
    csv_row,
    make_image,
    write_convert_csv,
)

COCO8_ROOT = Path(__file__).parent / "fixtures" / "data" / "coco8"
COCO8_YAML = Path(__file__).parent / "fixtures" / "data" / "coco8.yaml"

_TWO_BOXES = "0 0.5 0.5 0.2 0.2\n1 0.25 0.25 0.1 0.1\n"


class TestConversionRegressions:
    """Exercise filesystem and CSV contracts across complete conversions."""

    def test_reexport_reuses_current_image_when_source_is_unavailable(self, tmp_path: Path) -> None:
        images = tmp_path / "source"
        make_image(images / "a.jpg")
        csv_path = write_convert_csv(tmp_path, [csv_row("a.jpg", label="cat", split="train")])
        output = tmp_path / "yolo"
        convert_to_yolo(csv_path, output, image_dirs=[images], link_mode="copy")
        (images / "a.jpg").unlink()

        convert_to_yolo(csv_path, output, image_dirs=[images], link_mode="copy")

        assert (output / "images/train/a.jpg").is_file()

    def test_box_row_takes_precedence_over_negative_row(self, tmp_path: Path) -> None:
        images = tmp_path / "source"
        make_image(images / "a.jpg")
        csv_path = write_convert_csv(
            tmp_path,
            [
                csv_row("a.jpg", label="cat", split="train"),
                csv_row("a.jpg", shape="none", split="train"),
            ],
        )
        output = tmp_path / "yolo"

        convert_to_yolo(csv_path, output, image_dirs=[images], link_mode="copy")

        assert len(_parse_label_file(output / "labels/train/a.txt", files=LocalConversionFiles())) == 1

    @pytest.mark.parametrize("source", ["directory", "image", "list", "link-dir"])
    def test_symlink_images_keep_dataset_labels(self, tmp_path: Path, source: str) -> None:
        images = tmp_path / "source"
        make_image(images / "a.jpg")
        csv_path = write_convert_csv(tmp_path, [csv_row("a.jpg", label="cat", split="train")])
        output = tmp_path / "yolo"
        convert_to_yolo(csv_path, output, image_dirs=[images], link_mode="symlink")
        config_path = output / "dataset.yaml"
        config = yaml.safe_load(config_path.read_text())
        if source == "image":
            config["train"] = "images/train/a.jpg"
        elif source == "list":
            (output / "train.txt").write_text("./images/train/a.jpg\n")
            config["train"] = "train.txt"
        elif source == "link-dir":
            (output / "images/train/a.jpg").unlink()
            (output / "images/train").rmdir()
            (output / "images/train").symlink_to(images, target_is_directory=True)
        config_path.write_text(yaml.safe_dump(config))

        imported = tmp_path / "imported.csv"
        convert_from_yolo(output, imported)

        result = pd.read_csv(imported)
        assert result["image_name"].tolist() == ["a.jpg"]
        assert result["instance_shape"].tolist() == ["box"]
        assert result["instance_label"].tolist() == ["cat"]
        assert result.loc[0, "bbox_x_tl"] == pytest.approx(10.0)

    @pytest.mark.parametrize("link_mode", ["copy", "symlink"])
    def test_reexport_removes_old_labels_and_images(
        self, tmp_path: Path, link_mode: Literal["copy", "symlink"]
    ) -> None:
        images = tmp_path / "source"
        for name in ("negative.jpg", "removed.jpg", "moved.jpg", "new.jpg"):
            make_image(images / name)
        csv_path = write_convert_csv(
            tmp_path,
            [csv_row(name, label="cat", split="train") for name in ("negative.jpg", "removed.jpg", "moved.jpg")],
        )
        output = tmp_path / "yolo"
        convert_to_yolo(csv_path, output, image_dirs=[images], link_mode=link_mode)
        (images / "removed.jpg").unlink()
        note = output / "images/train/README.md"
        note.write_text("Keep this note")
        write_convert_csv(
            tmp_path,
            [
                csv_row("negative.jpg", shape="none", split="train"),
                csv_row("moved.jpg", label="dog", split="val"),
                csv_row("new.jpg", label="dog", split="train"),
            ],
        )

        convert_to_yolo(csv_path, output, image_dirs=[images], link_mode=link_mode)

        assert (output / "labels/train/negative.txt").read_text() == ""
        assert {p.relative_to(output).as_posix() for p in output.glob("images/*/*.jpg")} == {
            "images/train/negative.jpg",
            "images/val/moved.jpg",
            "images/train/new.jpg",
        }
        assert {p.relative_to(output).as_posix() for p in output.glob("labels/*/*.txt")} == {
            "labels/train/negative.txt",
            "labels/val/moved.txt",
            "labels/train/new.txt",
        }
        assert (images / "moved.jpg").is_file()
        assert note.read_text() == "Keep this note"
        imported = tmp_path / "imported.csv"
        convert_from_yolo(output, imported)
        result = pd.read_csv(imported).set_index("image_name")
        assert result.loc["negative.jpg", "instance_shape"] == "none"
        assert result.loc["moved.jpg", "split"] == "val"
        assert result.loc["new.jpg", "instance_label"] == "dog"

    @pytest.mark.parametrize("linked_directory", ["images", "images/train"])
    def test_reexport_never_prunes_source_directory_symlinks(self, tmp_path: Path, linked_directory: str) -> None:
        images = tmp_path / "source"
        nested = images / "train" if linked_directory == "images" else images
        make_image(nested / "a.jpg")
        make_image(nested / "unselected.jpg")
        csv_path = write_convert_csv(tmp_path, [csv_row("a.jpg", label="cat", split="train")])
        output = tmp_path / "yolo"
        link = output / linked_directory
        link.parent.mkdir(parents=True)
        link.symlink_to(images, target_is_directory=True)
        stale_label = output / "labels/train/unselected.txt"
        stale_label.parent.mkdir(parents=True)
        stale_label.write_text(_TWO_BOXES)

        convert_to_yolo(csv_path, output, image_dirs=[nested], link_mode="copy")

        assert (nested / "unselected.jpg").is_file()
        assert not stale_label.exists()


class TestParseLabelFile:
    """Tests for YOLO label file parsing."""

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            pytest.param(
                "0 0.5 0.5 0.3 0.4\n1 0.1 0.2 0.3 0.4\n",
                [[0.0, 0.5, 0.5, 0.3, 0.4], [1.0, 0.1, 0.2, 0.3, 0.4]],
                id="standard",
            ),
            pytest.param("0 0.5 0.5 0.3 0.4 0.95\n", [[0.0, 0.5, 0.5, 0.3, 0.4, 0.95]], id="conf"),
            pytest.param(None, [], id="missing"),
            pytest.param("", [], id="empty"),
            pytest.param(
                "\n  0 0.5 0.5 0.3 0.4   \n\n",
                [[0.0, 0.5, 0.5, 0.3, 0.4]],
                id="blank-and-padding",
            ),
        ],
    )
    def test_parses_well_formed_lines(self, tmp_path: Path, text: str | None, expected: list[list[float]]) -> None:
        p = tmp_path / "label.txt"
        if text is not None:
            p.write_text(text)
        assert _parse_label_file(p, files=LocalConversionFiles()) == expected

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

        assert _parse_label_file(p, files=LocalConversionFiles()) == [[1.0, 0.1, 0.2, 0.3, 0.4]]
        assert capture_logs[-1].endswith(": 2")
        assert f"{p}:1" in capture_logs[0]
        assert f"{p}:2" in capture_logs[1]

    def test_well_formed_file_warns_nothing(self, tmp_path: Path, capture_logs: list[str]) -> None:
        """Neither a 5-field box nor a 6-field prediction line is reported.

        The 6-field line pins the ``>`` in the extra-fields guard: with only
        5-field lines here, ``>=`` would warn about every prediction file
        and still pass.
        """
        p = tmp_path / "label.txt"
        p.write_text("0 0.5 0.5 0.3 0.4\n1 0.5 0.5 0.3 0.4 0.95\n")
        assert len(_parse_label_file(p, files=LocalConversionFiles())) == 2
        assert capture_logs == []

    def test_extra_fields_are_kept_but_counted_in_a_warning(self, tmp_path: Path, capture_logs: list[str]) -> None:
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

        rows = _parse_label_file(p, files=LocalConversionFiles())

        assert [len(row) for row in rows] == [9, 5, 9]
        assert rows[0] == [0.0, 0.1, 0.1, 0.9, 0.1, 0.9, 0.9, 0.1, 0.9]
        assert len(capture_logs) == 1
        assert "Строк с полями сверх 6" in capture_logs[0]
        assert str(p) in capture_logs[0]
        assert capture_logs[0].endswith(": 2; учтены только class xc yc w h [conf]")

    def test_extra_fields_and_skipped_lines_are_counted_apart(self, tmp_path: Path, capture_logs: list[str]) -> None:
        """Each warning carries its own count; a bad long line counts once.

        A non-numeric 9-field line is a skipped line, not an extra-fields
        line, so it must not inflate the second counter.
        """
        p = tmp_path / "label.txt"
        p.write_text("0 0.5 0.5 0.3\nx y z w h a b c d\n0 0.1 0.1 0.9 0.1 0.9 0.9 0.1 0.9\n1 0.5 0.5 0.3 0.4\n")

        assert len(_parse_label_file(p, files=LocalConversionFiles())) == 2
        assert [m.split(": ", 1)[0] for m in capture_logs[2:]] == [
            "Пропущено нечитаемых строк в " + str(p),
            f"Строк с полями сверх 6 (сегментация/OBB/keypoints?) в {p}",
        ]
        assert capture_logs[2].endswith(": 2")
        assert capture_logs[3].endswith(": 1; учтены только class xc yc w h [conf]")


class TestToYolo:
    """Tests for --to-yolo CSV to YOLO conversion."""

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
            convert_to_yolo(csv_path, out_dir, image_dirs=[str(img_dir)], link_mode="copy")

        assert sorted(p.name for p in out_dir.iterdir()) == [
            "dataset.yaml",
            "images",
            "labels",
        ]

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

    @pytest.mark.parametrize(("shape", "label_text"), [("box", None), ("none", "")])
    def test_missing_image_still_writes_labels(self, tmp_path: Path, shape: str, label_text: str | None) -> None:
        """A CSV row whose image is absent from disk is labelled but not copied."""
        img_dir = tmp_path / "images"
        img_dir.mkdir()
        rows = [csv_row("ghost.jpg", shape=shape, split="val")]
        csv_path = write_convert_csv(tmp_path, rows)

        out_dir = tmp_path / "yolo_out"
        convert_to_yolo(csv_path, out_dir, image_dirs=[str(img_dir)], link_mode="copy")

        label = out_dir / "labels" / "val" / "ghost.txt"
        assert label.is_file()
        if label_text is not None:
            assert label.read_text() == label_text
        assert not (out_dir / "images" / "val" / "ghost.jpg").exists()

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

    def test_none_shape_places_image_with_empty_label(self, tmp_path: Path) -> None:
        """A none-shape row copies its image and gets an empty label file."""
        img_dir = tmp_path / "images"
        make_image(img_dir / "empty.jpg")
        rows = [csv_row("empty.jpg", shape="none", split="val")]
        csv_path = write_convert_csv(tmp_path, rows)

        out_dir = tmp_path / "yolo_out"
        convert_to_yolo(csv_path, out_dir, image_dirs=[str(img_dir)], link_mode="copy")

        assert (out_dir / "images" / "val" / "empty.jpg").is_file()
        assert (out_dir / "labels" / "val" / "empty.txt").read_text() == ""


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
        (pred_dir / "img1.txt").write_text("0 0.5 0.5 0.3 0.4 0.95\n1 0.2 0.3 0.1 0.2 0.87\n")

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


_SPLITS = st.sampled_from(["train", "val", "test"])
# Text labels such as "001" and "NA" must survive pandas' type and NA guessing.
_LABELS = st.sampled_from(["cat", "dog", "001", "NA"])


@st.composite
def _labelled_box(draw: st.DrawFn) -> tuple[str, float, float, float, float]:
    """Draw a label and a quarter-pixel box inside a 640x480 image."""
    x_tl = draw(st.integers(0, 639 * 4)) / 4
    y_tl = draw(st.integers(0, 479 * 4)) / 4
    x_br = draw(st.integers(int(x_tl * 4) + 1, 640 * 4)) / 4
    y_br = draw(st.integers(int(y_tl * 4) + 1, 480 * 4)) / 4
    return draw(_LABELS), x_tl, y_tl, x_br, y_br


_EXPORTS = st.dictionaries(
    st.sampled_from(["a.jpg", "b.jpg", "c.jpg"]),
    st.tuples(_SPLITS, st.lists(_labelled_box(), min_size=1, max_size=3)),
    min_size=1,
)


@pytest.fixture(scope="module")
def source_images(tmp_path_factory: pytest.TempPathFactory) -> Path:
    images = tmp_path_factory.mktemp("source")
    for name in ("a.jpg", "b.jpg", "c.jpg"):
        make_image(images / name)
    return images


@given(export=_EXPORTS)
# Pinned: all three splits at once, the text labels pandas would mangle, and
# boxes touching the image corners.
@example(
    export={
        "a.jpg": ("train", [("001", 0.0, 0.0, 10.0, 10.0)]),
        "b.jpg": ("val", [("NA", 1.0, 1.0, 20.0, 20.0)]),
        "c.jpg": ("test", [("cat", 0.25, 0.5, 640.0, 480.0)]),
    }
)
def test_csv_to_yolo_to_csv_roundtrip(
    source_images: Path,
    export: dict[str, tuple[str, list[tuple[str, float, float, float, float]]]],
) -> None:
    """CSV -> YOLO -> CSV keeps boxes, text labels and splits; ids are 0-based.

    dataset.yaml lists exactly the splits present, maps sorted labels from
    class id 0, and records the resolved output root.
    """
    rows: list[dict[str, object]] = []
    expected: list[tuple[str, str, str, float, float, float, float]] = []
    for image, (split, boxes) in export.items():
        for label, *coords in boxes:
            x_tl, y_tl, x_br, y_br = coords
            rows.append(
                csv_row(
                    image,
                    label=label,
                    split=split,
                    bbox_x_tl=x_tl,
                    bbox_y_tl=y_tl,
                    bbox_x_br=x_br,
                    bbox_y_br=y_br,
                    annotation_id=len(rows) + 1,
                )
            )
            expected.append((image, split, label, x_tl, y_tl, x_br, y_br))
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        out = work / "yolo"
        convert_to_yolo(
            write_convert_csv(work, rows),
            out,
            image_dirs=[source_images],
            link_mode="copy",
        )
        config = yaml.safe_load((out / "dataset.yaml").read_text())
        for image, (split, _) in export.items():
            assert (out / "images" / split / image).is_file()
        roundtrip = work / "roundtrip.csv"
        convert_from_yolo(out, roundtrip)
        result = pd.read_csv(roundtrip, dtype={"instance_label": str}, keep_default_na=False)

    labels = sorted({row[2] for row in expected})
    assert config["names"] == dict(enumerate(labels))
    assert config["path"] == str(out.resolve())
    splits = {split for split, _ in export.values()}
    assert {key: config.get(key) for key in ("train", "val", "test")} == {
        key: f"images/{key}" if key in splits else None for key in ("train", "val", "test")
    }
    actual = sorted(
        result[
            [
                "image_name",
                "split",
                "instance_label",
                "bbox_x_tl",
                "bbox_y_tl",
                "bbox_x_br",
                "bbox_y_br",
            ]
        ].itertuples(index=False, name=None)
    )
    assert len(actual) == len(expected)
    for got, want in zip(actual, sorted(expected), strict=True):
        assert got[:3] == want[:3]
        assert got[3:] == pytest.approx(want[3:], abs=0.011)


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
        assert df["image_name"].tolist() == ["a.jpg"] * 2 + ["b.jpg"] * 2 + ["c.jpg"] * 2
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

    @pytest.mark.parametrize(
        ("read_all_sizes", "widths", "heights"),
        [(None, [640, 640], [480, 480]), (True, [640, 320], [480, 240])],
    )
    def test_read_all_sizes_controls_size_measurement(
        self,
        tmp_path: Path,
        read_all_sizes: bool | None,  # noqa: FBT001 - parametrized flag
        widths: list[int],
        heights: list[int],
    ) -> None:
        """By default every row reuses the first image's size; the flag measures all."""
        root = tmp_path / "ds"
        self._two_differently_sized_images(root)

        out = tmp_path / "out.csv"
        if read_all_sizes is None:
            convert_from_yolo(root, out)
        else:
            convert_from_yolo(root, out, read_all_sizes=read_all_sizes)

        df = pd.read_csv(out)
        assert df["image_width"].tolist() == widths
        assert df["image_height"].tolist() == heights

    def test_non_positive_image_size_names_the_image(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A degenerate image size aborts, naming the offending file.

        Real images always report positive dimensions, so the guard was never
        triggered from this path and the image name it reports was free.
        """
        root = tmp_path / "ds"
        make_image(root / "images" / "train" / "flat.jpg")
        _write_yolo_label(root, "train", "flat", "0 0.5 0.5 0.2 0.2\n")
        _write_yolo_yaml(root, {0: "cat"}, ["train"])
        monkeypatch.setattr(LocalConversionFiles, "image_size", staticmethod(lambda _path: (0, 10)))

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

    def test_relative_dataset_root_is_resolved_from_yaml(self, tmp_path: Path) -> None:
        data_root = tmp_path / "data"
        self._labelled(data_root, "train", "a")
        config_root = tmp_path / "config"
        config_root.mkdir()
        (config_root / "dataset.yaml").write_text(
            yaml.dump(
                {
                    "path": "../data",
                    "train": "images/train",
                    "names": {0: "cat"},
                }
            ),
            encoding="utf-8",
        )

        out = tmp_path / "out.csv"
        convert_from_yolo(config_root, out, read_all_sizes=True)

        assert pd.read_csv(out)["image_name"].tolist() == ["a.jpg"]

    def test_split_list_combines_directories_and_list_files(self, tmp_path: Path) -> None:
        root = tmp_path / "ds"
        self._labelled(root, "train", "a")
        self._labelled(root, "val", "b")
        list_file = root / "selected.txt"
        list_file.write_text("./images/val/b.jpg\nimages/train/a.jpg\n", encoding="utf-8")
        (root / "dataset.yaml").write_text(
            yaml.dump(
                {
                    "path": str(root),
                    "train": ["images/train", "selected.txt"],
                    "names": {0: "cat"},
                }
            ),
            encoding="utf-8",
        )

        out = tmp_path / "out.csv"
        convert_from_yolo(root, out, read_all_sizes=True)

        assert pd.read_csv(out)["image_name"].tolist() == ["a.jpg", "b.jpg"]

    def test_missing_first_listed_image_does_not_hide_later_image(self, tmp_path: Path) -> None:
        root = tmp_path / "ds"
        self._labelled(root, "train", "present")
        listing = root / "train.txt"
        listing.write_text("images/train/missing.jpg\nimages/train/present.jpg\n", encoding="utf-8")
        (root / "dataset.yaml").write_text(
            yaml.dump({"train": "train.txt", "names": {0: "cat"}}),
            encoding="utf-8",
        )

        out = tmp_path / "out.csv"
        convert_from_yolo(root, out, read_all_sizes=True)

        assert pd.read_csv(out)["image_name"].tolist() == ["present.jpg"]

    def test_direct_image_split_and_extension_filter(self, tmp_path: Path) -> None:
        root = tmp_path / "ds"
        image = root / "single.JpG"
        make_image(image)
        assert _images_from_split_source(image, root) == [image]

        note = root / "note.md"
        note.write_text("not an image", encoding="utf-8")
        assert _images_from_split_source(note, root) == []

    def test_list_dot_paths_are_relative_to_list_location(self, tmp_path: Path) -> None:
        root = tmp_path / "dataset"
        listing = tmp_path / "lists" / "train.txt"
        listing.parent.mkdir()
        assert _resolve_listed_image("./a.jpg", listing, root) == (listing.parent / "a.jpg").resolve()

    def test_empty_dataset_root_uses_yaml_directory(self, tmp_path: Path) -> None:
        yaml_path = tmp_path / "config" / "dataset.yaml"
        assert _resolve_dataset_root(yaml_path, "") == yaml_path.parent.resolve()

    def test_label_path_without_images_directory_uses_txt_suffix(self, tmp_path: Path) -> None:
        image = tmp_path / "photos" / "a.JPG"
        assert _label_path_for_image(image) == tmp_path / "photos" / "a.txt"

    def test_directory_split_is_recursive(self, tmp_path: Path) -> None:
        root = tmp_path / "ds"
        make_image(root / "images" / "train" / "nested" / "a.jpg")
        _write_yolo_label(root, "train/nested", "a", "0 0.5 0.5 0.2 0.2\n")
        _write_yolo_yaml(root, {0: "cat"}, ["train"])

        out = tmp_path / "out.csv"
        convert_from_yolo(root, out, read_all_sizes=True)

        assert pd.read_csv(out)["image_name"].tolist() == ["a.jpg"]

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
        (root / "dataset.yaml").write_text(f"train: images/train\n{names_value}", encoding="utf-8")

        with pytest.raises(
            Cveta2Error,
            match=r"names в .*dataset\.yaml должен быть списком или словарём",
        ):
            convert_from_yolo(root, tmp_path / "out.csv", read_all_sizes=False)

    @pytest.mark.parametrize("document", ["", "just-a-string"])
    def test_non_mapping_yaml_is_rejected(self, tmp_path: Path, document: str) -> None:
        """An empty or scalar dataset.yaml aborts with an explanation."""
        root = tmp_path / "ds"
        self._labelled(root, "train", "a")
        (root / "dataset.yaml").write_text(document, encoding="utf-8")

        with pytest.raises(Cveta2Error, match="не содержит YAML-словарь"):
            convert_from_yolo(root, tmp_path / "out.csv", read_all_sizes=False)


class TestFromYoloPredictions:
    """Tests for bare-.txt prediction mode."""

    @staticmethod
    def _names_file(tmp_path: Path, names: dict[int, str]) -> Path:
        path = tmp_path / "names.yaml"
        path.write_text(yaml.dump({"names": names}), encoding="utf-8")
        return path

    def test_ids_are_sequential_and_images_come_from_the_subdir(self, tmp_path: Path) -> None:
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
        assert df["image_name"].tolist() == ["a.jpg"] * 2 + ["b.jpg"] * 2 + ["c.jpg"] * 2
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

    def test_missing_image_is_collected_and_the_walk_continues(self, tmp_path: Path, capture_logs: list[str]) -> None:
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
            (pred_dir / f"{stem}.txt").write_text("0 0.5 0.5 0.2 0.2\n", encoding="utf-8")

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

    def test_non_positive_image_size_names_the_image(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A degenerate image size aborts, naming the offending file."""
        pred_dir = tmp_path / "preds"
        make_image(pred_dir / "images" / "flat.jpg")
        (pred_dir / "flat.txt").write_text("0 0.5 0.5 0.2 0.2\n", encoding="utf-8")
        monkeypatch.setattr(LocalConversionFiles, "image_size", staticmethod(lambda _path: (0, 10)))

        with pytest.raises(Cveta2Error, match=r"'flat\.jpg' \(0x10\)"):
            convert_from_yolo(pred_dir, tmp_path / "out.csv", read_all_sizes=False)


class TestLoadClassNamesYaml:
    """Tests for the ``--names`` file reader used by prediction mode."""

    def test_missing_file_is_rejected(self, tmp_path: Path) -> None:
        """The error names the path it could not find."""
        with pytest.raises(Cveta2Error, match="файл имён классов не найден"):
            _load_class_names_yaml(tmp_path / "nope.yaml")

    @pytest.mark.parametrize("document", [{"names": {0: "cat", 1: "dog"}}, {0: "cat", 1: "dog"}])
    def test_names_mapping_forms(self, tmp_path: Path, document: dict[object, object]) -> None:
        """Both ``{names: {...}}`` and a bare ``{0: cat}`` document are accepted."""
        path = tmp_path / "names.yaml"
        path.write_text(yaml.dump(document), encoding="utf-8")
        assert _load_class_names_yaml(path) == {0: "cat", 1: "dog"}

    @pytest.mark.parametrize(
        "document",
        [
            pytest.param("names\n", id="not-a-mapping"),
            pytest.param("names: [cat, 7]\n", id="non-string-name"),
        ],
    )
    def test_invalid_names_document_is_rejected(self, tmp_path: Path, document: str) -> None:
        """A non-mapping document or a non-string class name names the file.

        Asserted on the function, not through the CSV: ``pd.read_csv`` would
        coerce ``"7"`` back to an int and hide a missing ``str()``.
        """
        path = tmp_path / "names.yaml"
        path.write_text(document, encoding="utf-8")
        with pytest.raises(Cveta2Error, match=r"names\.yaml"):
            _load_class_names_yaml(path)

    @pytest.mark.parametrize("document", ["names: 3\n", "names: null\n"])
    def test_scalar_names_value_is_rejected(self, tmp_path: Path, document: str) -> None:
        """A mapping whose ``names`` is a scalar aborts, naming the file.

        A bare scalar document is also rejected (see the test above); the
        raise is reserved for an explicit ``names`` of the wrong type.
        """
        path = tmp_path / "names.yaml"
        path.write_text(document, encoding="utf-8")
        with pytest.raises(Cveta2Error, match=r"names в .*names\.yaml должен быть списком или словарём"):
            _load_class_names_yaml(path)
