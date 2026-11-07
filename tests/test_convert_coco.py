"""Unit tests for cveta2/services/convert/coco.py (CSV -> COCO detection)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from cveta2.composition.conversion import convert_to_coco
from tests.helpers import (
    csv_row,
    make_image,
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
    """Draw a label and a quarter-pixel box inside a 640x480 image."""
    x_tl = draw(st.integers(0, 639 * 4)) / 4
    y_tl = draw(st.integers(0, 479 * 4)) / 4
    x_br = draw(st.integers(int(x_tl * 4) + 1, 640 * 4)) / 4
    y_br = draw(st.integers(int(y_tl * 4) + 1, 480 * 4)) / 4
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
