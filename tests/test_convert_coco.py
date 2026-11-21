"""Unit tests for cveta2/services/convert/coco.py (CSV -> COCO detection)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from cveta2.composition.conversion import convert_to_coco
from cveta2.domain.errors import Cveta2Error
from tests.helpers import (
    csv_row,
    make_image,
    output_tree,
    write_convert_csv,
)


def _run_to_coco(tmp_path: Path, csv_path: Path, img_dir: Path) -> Path:
    out_dir = tmp_path / "coco_out"
    convert_to_coco(csv_path, out_dir, image_dirs=[str(img_dir)], link_mode="copy")
    return out_dir


_SPLIT_DIRS = {"train": "train", "val": "valid", "test": "test"}
# Text labels such as "001" and "NA" must survive pandas' type and NA guessing.
_LABELS = st.sampled_from(["zebra", "apple", "001", "NA"])


@st.composite
def _labelled_box(draw: st.DrawFn) -> tuple[str, float, float, float, float]:
    """Draw a label and a box on a quarter-pixel grid, at least 1 px each way, inside a 640x480 image."""
    x_tl = draw(st.integers(0, 639 * 4)) / 4
    y_tl = draw(st.integers(0, 479 * 4)) / 4
    x_br = draw(st.integers(int(x_tl * 4) + 4, 640 * 4)) / 4
    y_br = draw(st.integers(int(y_tl * 4) + 4, 480 * 4)) / 4
    return draw(_LABELS), x_tl, y_tl, x_br, y_br


# Per image: its split and its boxes; no boxes means one ``none`` row.
_EXPORTS = st.dictionaries(
    st.sampled_from(["a.jpg", "b.jpg", "c.jpg"]),
    st.tuples(
        st.sampled_from(list(_SPLIT_DIRS)),
        st.lists(_labelled_box(), max_size=3),
    ),
    min_size=1,
)


@pytest.fixture(scope="module")
def source_images(tmp_path_factory: pytest.TempPathFactory) -> Path:
    images = tmp_path_factory.mktemp("source")
    for name in ("a.jpg", "b.jpg", "c.jpg"):
        make_image(images / name)
    return images


@given(export=_EXPORTS)
# Pinned: every split, an image without boxes, and the text labels pandas
# would mangle.
@example(
    export={
        "a.jpg": ("train", [("001", 0.0, 0.0, 10.0, 10.0)]),
        "b.jpg": ("val", []),
        "c.jpg": ("test", [("NA", 5.0, 5.0, 15.0, 15.0)]),
    }
)
def test_to_coco_structure(
    source_images: Path,
    export: dict[str, tuple[str, list[tuple[str, float, float, float, float]]]],
) -> None:
    """Every split gets its images, boxes and 1-based sorted categories.

    ``val`` is written to ``valid/``; a ``none`` image is listed without
    annotations; annotation ids are unique and link to real image/category ids.
    """
    rows: list[dict[str, object]] = []
    for image, (split, boxes) in export.items():
        if not boxes:
            rows.append(csv_row(image, shape="none", split=split))
        for label, x_tl, y_tl, x_br, y_br in boxes:
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
    labels = sorted({box[0] for _, boxes in export.values() for box in boxes})
    splits = {split for split, _ in export.values()}
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        out = work / "coco"
        convert_to_coco(
            write_convert_csv(work, rows),
            out,
            image_dirs=[source_images],
            link_mode="copy",
        )
        assert {p.name for p in out.iterdir()} == {_SPLIT_DIRS[s] for s in splits}
        for split in splits:
            split_dir = out / _SPLIT_DIRS[split]
            coco = json.loads((split_dir / "_annotations.coco.json").read_text())
            names = sorted(name for name, (s, _) in export.items() if s == split)
            assert sorted(p.name for p in split_dir.glob("*.jpg")) == names
            assert [(im["file_name"], im["width"], im["height"]) for im in coco["images"]] == [
                (name, 640, 480) for name in names
            ]
            assert coco["categories"] == [
                {"id": i, "name": label, "supercategory": "none"} for i, label in enumerate(labels, start=1)
            ]
            image_ids = {im["id"]: im["file_name"] for im in coco["images"]}
            assert len(image_ids) == len(names)
            category = {c["id"]: c["name"] for c in coco["categories"]}
            ann_ids = [a["id"] for a in coco["annotations"]]
            assert len(set(ann_ids)) == len(ann_ids)
            assert all(ann_id > 0 for ann_id in ann_ids)
            got = sorted(
                (
                    image_ids[a["image_id"]],
                    category[a["category_id"]],
                    *a["bbox"],
                    a["area"],
                    a["iscrowd"],
                )
                for a in coco["annotations"]
            )
            want = sorted(
                (name, label, x, y, x2 - x, y2 - y, round((x2 - x) * (y2 - y), 2), 0)
                for name in names
                for label, x, y, x2, y2 in export[name][1]
            )
            assert got == want


class TestToCoco:
    """Example tests for --to-coco CSV to COCO conversion."""

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
        csv_path = write_convert_csv(tmp_path, rows)
        out_dir = _run_to_coco(tmp_path, csv_path, img_dir)

        with (out_dir / "train" / "_annotations.coco.json").open() as f:
            coco = json.load(f)

        ann = coco["annotations"][0]
        assert ann["bbox"] == [10.13, 20.24, 100.86, 100.64]
        assert ann["area"] == 10150.05

    def test_nested_output_dir_and_rerun(self, tmp_path: Path) -> None:
        """The split dirs survive a second run into the same output tree.

        Every COCO test ran once into a fresh directory, so ``exist_ok=False``
        on the split directory was never reached.
        """
        img_dir = tmp_path / "images"
        make_image(img_dir / "test.jpg")
        rows = [csv_row("test.jpg", label="cat", split="train")]
        csv_path = write_convert_csv(tmp_path, rows)

        out_dir = tmp_path / "deep" / "nested" / "coco_out"
        for _ in range(2):
            convert_to_coco(csv_path, out_dir, image_dirs=[str(img_dir)], link_mode="copy")

        assert (out_dir / "train" / "_annotations.coco.json").is_file()

    @pytest.mark.parametrize("shape", ["box", "none"])
    def test_missing_image_aborts_before_any_write(self, tmp_path: Path, shape: str) -> None:
        """A CSV image found in no search directory is an error, not an ``images`` entry without a file."""
        img_dir = tmp_path / "images"
        make_image(img_dir / "here.jpg")
        rows = [
            csv_row("here.jpg", split="train"),
            csv_row("phantom.jpg", shape=shape, split="val"),
            csv_row("ghost.jpg", shape=shape, split="val"),
        ]
        csv_path = write_convert_csv(tmp_path, rows)
        out_dir = tmp_path / "coco_out"

        with pytest.raises(Cveta2Error, match=r"не найдено 2 изображений: ghost\.jpg, phantom\.jpg"):
            convert_to_coco(csv_path, out_dir, image_dirs=[str(img_dir)], link_mode="copy")

        assert not out_dir.exists()

    def test_reexport_with_a_missing_image_leaves_the_previous_export_unchanged(self, tmp_path: Path) -> None:
        """The image a previous run placed is not a source: the rerun fails before any write or prune."""
        images = tmp_path / "source"
        make_image(images / "a.jpg")
        make_image(images / "b.jpg")
        rows = [csv_row("a.jpg", label="cat", split="train"), csv_row("b.jpg", label="cat", split="train")]
        output = tmp_path / "coco"
        convert_to_coco(write_convert_csv(tmp_path, rows), output, image_dirs=[images], link_mode="copy")
        before = output_tree(output)
        (images / "a.jpg").unlink()
        # Going through, this run would relabel a.jpg, move it to valid/ and prune train/.
        csv_path = write_convert_csv(tmp_path, [csv_row("a.jpg", label="dog", split="val")])

        with pytest.raises(Cveta2Error, match=r"не найдено 1 изображений: a\.jpg"):
            convert_to_coco(csv_path, output, image_dirs=[images], link_mode="copy")

        assert output_tree(output) == before


type _Box = tuple[float, float, float, float]


def _export_boxes(
    tmp_path: Path, boxes: dict[str, tuple[str, list[_Box]]]
) -> dict[str, dict[str, list[dict[str, object]]]]:
    """Export 640x480 images, each with its split and boxes, and return the COCO JSON of every split directory."""
    images = tmp_path / "source"
    rows: list[dict[str, object]] = []
    for name, (split, coords) in boxes.items():
        make_image(images / name)
        for x_tl, y_tl, x_br, y_br in coords:
            rows.append(
                csv_row(
                    name,
                    split=split,
                    bbox_x_tl=x_tl,
                    bbox_y_tl=y_tl,
                    bbox_x_br=x_br,
                    bbox_y_br=y_br,
                    annotation_id=len(rows) + 1,
                )
            )
    out = tmp_path / "coco"
    convert_to_coco(write_convert_csv(tmp_path, rows), out, image_dirs=[images], link_mode="copy")
    return {
        path.parent.name: json.loads(path.read_text(encoding="utf-8")) for path in out.glob("*/_annotations.coco.json")
    }


class TestOutOfImageBoxes:
    """Boxes crossing the image edge are clipped; boxes left under 1 px wide or high are dropped."""

    @pytest.mark.parametrize(
        ("box", "bbox", "area"),
        [
            ((-20.0, 20.0, 100.0, 200.0), [0.0, 20.0, 100.0, 180.0], 18000.0),
            ((10.0, -30.0, 100.0, 200.0), [10.0, 0.0, 90.0, 200.0], 18000.0),
            ((600.0, 20.0, 700.0, 200.0), [600.0, 20.0, 40.0, 180.0], 7200.0),
            ((10.0, 400.0, 100.0, 520.0), [10.0, 400.0, 90.0, 80.0], 7200.0),
            ((-10.0, -10.0, 650.0, 490.0), [0.0, 0.0, 640.0, 480.0], 307200.0),
        ],
    )
    def test_box_crossing_the_edge_is_written_clipped(
        self, tmp_path: Path, box: _Box, bbox: list[float], area: float, capture_logs: list[str]
    ) -> None:
        coco = _export_boxes(tmp_path, {"edge.jpg": ("train", [box])})["train"]

        assert [(a["bbox"], a["area"]) for a in coco["annotations"]] == [(bbox, area)]
        assert len(capture_logs) == 1
        assert "обрезан" in capture_logs[0]
        assert capture_logs[0].endswith(": 1 (edge.jpg)")

    def test_box_on_the_image_border_is_not_clipped(self, tmp_path: Path, capture_logs: list[str]) -> None:
        coco = _export_boxes(tmp_path, {"full.jpg": ("train", [(0.0, 0.0, 640.0, 480.0)])})["train"]

        assert [a["bbox"] for a in coco["annotations"]] == [[0.0, 0.0, 640.0, 480.0]]
        assert not capture_logs

    @pytest.mark.parametrize(
        "box",
        [
            pytest.param((700.0, 20.0, 800.0, 200.0), id="right-of-image"),
            pytest.param((-50.0, 20.0, -10.0, 200.0), id="left-of-image"),
            pytest.param((10.0, 500.0, 100.0, 600.0), id="below-image"),
            pytest.param((640.0, 20.0, 700.0, 200.0), id="clips-to-zero-width"),
            pytest.param((10.0, -40.0, 100.0, 0.0), id="clips-to-zero-height"),
            pytest.param((639.5, 20.0, 700.0, 200.0), id="clips-under-one-pixel-wide"),
            pytest.param((10.0, 479.5, 100.0, 520.0), id="clips-under-one-pixel-high"),
            pytest.param((100.0, 20.0, 100.5, 200.0), id="inside-under-one-pixel-wide"),
            pytest.param((100.0, 20.0, 200.0, 20.99), id="inside-just-under-one-pixel-high"),
        ],
    )
    def test_box_under_one_pixel_is_dropped_and_the_image_kept(
        self, tmp_path: Path, box: _Box, capture_logs: list[str]
    ) -> None:
        coco = _export_boxes(tmp_path, {"gone.jpg": ("train", [box])})["train"]

        assert coco["annotations"] == []
        assert [image["file_name"] for image in coco["images"]] == ["gone.jpg"]
        assert (tmp_path / "coco/train/gone.jpg").is_file()
        assert len(capture_logs) == 1
        assert "Пропущен" in capture_logs[0]
        assert capture_logs[0].endswith(": 1 (gone.jpg)")

    @pytest.mark.parametrize(
        ("box", "bbox"),
        [
            pytest.param((100.0, 20.0, 101.0, 21.0), [100.0, 20.0, 1.0, 1.0], id="one-pixel"),
            # 11.1 - 10.1 is just under 1 in binary floating point.
            pytest.param((10.1, 20.3, 11.1, 21.3), [10.1, 20.3, 1.0, 1.0], id="one-pixel-at-fractional-coordinates"),
            pytest.param((100.0, 20.0, 100.996, 200.0), [100.0, 20.0, 1.0, 180.0], id="written-as-one-pixel"),
            pytest.param((639.0, 479.0, 700.0, 520.0), [639.0, 479.0, 1.0, 1.0], id="clips-to-one-pixel"),
        ],
    )
    def test_box_written_as_one_pixel_is_kept(self, tmp_path: Path, box: _Box, bbox: list[float]) -> None:
        """The 1 px rule looks at the size as written, with two decimals."""
        coco = _export_boxes(tmp_path, {"small.jpg": ("train", [box])})["train"]

        assert [a["bbox"] for a in coco["annotations"]] == [bbox]

    def test_remaining_boxes_keep_consecutive_ids_and_both_counts_are_summarized_once(
        self, tmp_path: Path, capture_logs: list[str], capture_info_logs: list[str]
    ) -> None:
        boxes: dict[str, tuple[str, list[_Box]]] = {
            "a.jpg": (
                "train",
                [
                    (10.0, 20.0, 100.0, 200.0),
                    (700.0, 20.0, 800.0, 200.0),
                    (600.0, 20.0, 700.0, 200.0),
                    (-5.0, 30.0, 50.0, 90.0),
                    (10.0, 500.0, 90.0, 600.0),
                ],
            ),
            "b.jpg": ("val", [(-5.0, 20.0, 100.0, 200.0), (10.0, 480.0, 100.0, 500.0), (20.0, 30.0, 60.0, 90.0)]),
            "c.jpg": ("val", [(639.5, 20.0, 700.0, 200.0)]),
        }
        coco = _export_boxes(tmp_path, boxes)

        assert [(a["id"], a["bbox"]) for a in coco["train"]["annotations"]] == [
            (1, [10.0, 20.0, 90.0, 180.0]),
            (2, [600.0, 20.0, 40.0, 180.0]),
            (3, [0.0, 30.0, 50.0, 60.0]),
        ]
        assert [(a["id"], a["image_id"], a["bbox"]) for a in coco["valid"]["annotations"]] == [
            (1, 1, [0.0, 20.0, 100.0, 180.0]),
            (2, 1, [20.0, 30.0, 40.0, 60.0]),
        ]
        assert [image["file_name"] for image in coco["valid"]["images"]] == ["b.jpg", "c.jpg"]
        clipped = [message for message in capture_logs if "обрезан" in message]
        dropped = [message for message in capture_logs if "Пропущен" in message]
        assert len(capture_logs) == len(clipped) + len(dropped) == 2
        assert clipped[0].endswith(": 3 (a.jpg, b.jpg)")
        assert dropped[0].endswith(": 4 (a.jpg, b.jpg, c.jpg)")
        assert any(m.startswith("Split valid: 2 изображений, 2 аннотаций") for m in capture_info_logs)
