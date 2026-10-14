"""Conversion and merge application workflows accept in-memory file ports."""

from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from cveta2.application.use_cases.merge import merge_datasets


def test_merge_uses_supplied_files_without_touching_paths() -> None:
    old = pd.DataFrame(
        [{"image_name": "same.jpg", "task_id": 9, "instance_label": "old"}]
    )
    new = pd.DataFrame(
        [{"image_name": "same.jpg", "task_id": 2, "instance_label": "new"}]
    )
    writes: list[tuple[pd.DataFrame, Path]] = []
    files = SimpleNamespace(
        read_dataset_csv=lambda path, _columns, **_kwargs: (
            old if path.name == "old.csv" else new
        ),
        read_deleted_names=lambda _path: set(),
        save_csv=lambda df, path: writes.append((df, path)),
    )
    result = merge_datasets(
        "/missing/old.csv",
        "/missing/new.csv",
        "/missing/result.csv",
        by_task=True,
        files=files,
    )
    assert result["instance_label"].tolist() == ["old"]
    assert writes[0][0] is result
    assert writes[0][1] == Path("/missing/result.csv")


def test_yolo_export_uses_port_and_preserves_utf8_label_order() -> None:
    from cveta2.application.use_cases.convert.yolo import convert_to_yolo

    frame = pd.DataFrame(
        [
            {
                "image_name": "кошка.jpg",
                "instance_shape": "box",
                "instance_label": label,
                "split": "train",
                "image_width": 100,
                "image_height": 50,
                "bbox_x_tl": 10,
                "bbox_y_tl": 5,
                "bbox_x_br": 30,
                "bbox_y_br": 15,
            }
            for label in ("zebra", "кошка")
        ]
    )
    output: dict[Path, str] = {}
    materialized: list[tuple[Path, Path, str]] = []
    files = SimpleNamespace(
        read_dataset_csv=lambda _path, _required: frame,
        resolve_images=lambda _names, _dirs: (
            {"кошка.jpg": Path("/input/кошка.jpg")},
            [],
        ),
        prepare_yolo_output=lambda _path, _splits: None,
        materialize_image=lambda src, dst, mode: materialized.append((src, dst, mode)),
        write_output_text=lambda path, text: output.update({path: text}),
        prune_yolo_output=lambda _ctx: None,
        resolved_output_dir=lambda path: path,
    )
    result = convert_to_yolo(
        "/missing/data.csv", "/output", files=files, link_mode="copy"
    )
    assert result == Path("/output")
    assert output[Path("/output/labels/train/кошка.txt")] == (
        "0 0.200000 0.200000 0.200000 0.200000\n1 0.200000 0.200000 0.200000 0.200000\n"
    )
    assert materialized == [
        (Path("/input/кошка.jpg"), Path("/output/images/train/кошка.jpg"), "copy")
    ]
    assert "zebra" in output[Path("/output/dataset.yaml")]


def test_yolo_import_uses_port_and_keeps_confidence() -> None:
    from cveta2.application.use_cases.convert.yolo import convert_from_yolo

    rows: list[dict[str, object]] = []
    files = SimpleNamespace(
        dataset_yaml_available=lambda _path: False,
        prediction_labels=lambda _path: [Path("/missing/zebra.txt")],
        label_text=lambda _path: "2 .5 .5 .2 .4 .91\n",
        find_image_by_stem=lambda _stem, _dirs, **_kwargs: Path("/input/zebra.jpg"),
        image_size=lambda _path: (100, 50),
        write_conversion_csv=lambda data, _path: rows.extend(data),
    )
    result = convert_from_yolo("/missing", "/output.csv", files=files)
    assert result == Path("/output.csv")
    assert len(rows) == 1
    assert rows[0]["image_name"] == "zebra.jpg"
    assert rows[0]["confidence"] == 0.91
    assert rows[0]["bbox_x_tl"] == 40
    assert rows[0]["bbox_y_tl"] == 15
    assert rows[0]["instance_label"] == "class_2"


def test_baseline_keeps_unfinished_sibling_task_eligible() -> None:
    from cveta2.application.use_cases.whats_new import compute_baseline

    frame = pd.DataFrame(
        [{"task_id": 3, "job_stage": "acceptance", "job_state": "completed"}]
    )
    sibling = pd.DataFrame(
        [
            {"task_id": 8, "job_stage": "acceptance", "job_state": "completed"},
            {"task_id": 8, "job_stage": "annotation", "job_state": "new"},
            {"task_id": 9, "job_stage": "acceptance", "job_state": "completed"},
        ]
    )
    files = SimpleNamespace(read_baseline_siblings=lambda _path: [sibling])
    baseline = compute_baseline(frame, Path("/missing/data.csv"), files=files)
    assert baseline.cutoff == 3
    assert baseline.known_task_ids == {3, 9}


def test_empty_coco_export_creates_output_root(tmp_path: Path) -> None:
    from cveta2.composition.conversion import convert_to_coco

    source = tmp_path / "empty.csv"
    source.write_text(
        "image_name,instance_shape,split,image_width,image_height\n",
        encoding="utf-8",
    )
    output = tmp_path / "nested" / "coco"
    assert convert_to_coco(source, output) == output
    assert output.is_dir()


def test_yolo_dataset_import_does_not_discover_image_cache_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cveta2.adapters.config.settings import ImageCacheConfig
    from cveta2.composition.conversion import convert_from_yolo

    source = tmp_path / "yolo"
    source.mkdir()
    (source / "dataset.yaml").write_text("names: {0: cat}\n", encoding="utf-8")

    def unexpected_load() -> ImageCacheConfig:
        raise AssertionError(
            "Dataset imports do not use configured prediction search directories"
        )

    monkeypatch.setattr(ImageCacheConfig, "load", unexpected_load)
    output = tmp_path / "output.csv"
    assert convert_from_yolo(source, output) == output
    assert output.is_file()
