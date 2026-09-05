"""Unit tests for cveta2/services/convert/coco.py (CSV -> COCO detection)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from cveta2.services.convert import (
    convert_to_coco,
)
from tests.helpers import (
    csv_row,
    make_image,
    write_convert_csv,
)

if TYPE_CHECKING:
    from pathlib import Path


def _run_to_coco(tmp_path: Path, csv_path: Path, img_dir: Path) -> Path:
    out_dir = tmp_path / "coco_out"
    convert_to_coco(csv_path, out_dir, image_dirs=[str(img_dir)], link_mode="copy")
    return out_dir


class TestToCoco:
    """Tests for --to-coco CSV to COCO conversion."""

    @pytest.mark.parametrize("label", ["001", "NA"])
    def test_text_labels_survive_export(self, tmp_path: Path, label: str) -> None:
        images = tmp_path / "source"
        make_image(images / "a.jpg")
        csv_path = write_convert_csv(
            tmp_path, [csv_row("a.jpg", label=label, split="train")]
        )

        output = _run_to_coco(tmp_path, csv_path, images)

        data = json.loads((output / "train/_annotations.coco.json").read_text())
        assert data["categories"] == [{"id": 1, "name": label, "supercategory": "none"}]
        assert data["annotations"][0]["category_id"] == 1

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
        csv_path = write_convert_csv(tmp_path, rows)
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
        csv_path = write_convert_csv(tmp_path, rows)
        out_dir = _run_to_coco(tmp_path, csv_path, img_dir)

        assert (out_dir / "valid" / "_annotations.coco.json").is_file()
        assert not (out_dir / "val").exists()

    def test_none_shape_in_images_not_annotations(self, tmp_path: Path) -> None:
        """Images with shape=none appear in images but not annotations."""
        img_dir = tmp_path / "images"
        make_image(img_dir / "empty.jpg")

        rows = [csv_row("empty.jpg", shape="none", split="train")]
        csv_path = write_convert_csv(tmp_path, rows)
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
        csv_path = write_convert_csv(tmp_path, rows)
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
        csv_path = write_convert_csv(tmp_path, rows)
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
        csv_path = write_convert_csv(tmp_path, rows)
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
        csv_path = write_convert_csv(tmp_path, rows)

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
        csv_path = write_convert_csv(tmp_path, rows)

        out_dir = tmp_path / "deep" / "nested" / "coco_out"
        for _ in range(2):
            convert_to_coco(
                csv_path, out_dir, image_dirs=[str(img_dir)], link_mode="copy"
            )

        assert (out_dir / "train" / "_annotations.coco.json").is_file()
