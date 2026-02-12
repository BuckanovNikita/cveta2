#!/usr/bin/env python3
"""Dev tool: create a CVAT project and fill it with multiple tasks from a dataset YAML (e.g. coco8).

Uses dataset YAML format: path, train/val/test dirs, names (class id -> name).
Creates one project with labels from names, then N tasks each with the same set of images
(train + val). Imports bounding boxes from YOLO-style label files (labels/<split>/<stem>.txt:
one line per object: "class_id x_center y_center width height" normalized 0–1).

Example:
  uv run python scripts/upload_dataset_to_cvat.py
  uv run python scripts/upload_dataset_to_cvat.py --yaml tests/fixtures/data/coco8.yaml --tasks 3 --project "coco8-dev"
"""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml
from loguru import logger
from PIL import Image
from pydantic import BaseModel

# CVAT SDK only in this script (dev tool)
from cvat_sdk import make_client
from cvat_sdk.api_client import models as cvat_models
from cvat_sdk.core.proxies.annotations import AnnotationUpdateAction
from cvat_sdk.core.proxies.tasks import ResourceType

from cveta2.config import CvatConfig


# ---------------------------------------------------------------------------
# Dataset YAML schema (coco/ultralytics-style)
# ---------------------------------------------------------------------------


class DatasetYaml(BaseModel):
    """Minimal schema for dataset YAML: path, splits, class names."""

    path: str  # dataset root dir (relative to YAML dir or absolute)
    train: str | None = None
    val: str | None = None
    test: str | None = None
    names: dict[int | str, str]  # class id -> name

    def label_names_sorted(self) -> list[str]:
        """Label names in order of class id (0, 1, 2, ...)."""

        def _key(k: int | str) -> int | str:
            if isinstance(k, str) and k.isdigit():
                return int(k)
            return k

        keys = sorted(self.names.keys(), key=_key)
        return [self.names[k] for k in keys]


def load_dataset_yaml(path: Path) -> tuple[DatasetYaml, Path]:
    """Load dataset YAML and return (parsed model, dataset root dir).

    Dataset root = yaml_path.parent / path (path from YAML).
    """
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Invalid YAML: expected mapping, got {type(data)}")
    # Normalize names: YAML may have int or str keys
    names_raw = data.get("names") or {}
    names = {}
    for k, v in names_raw.items():
        key = int(k) if isinstance(k, str) and k.isdigit() else k
        names[key] = str(v)
    data["names"] = names
    model = DatasetYaml.model_validate(data)
    dataset_root = path.parent / model.path
    return model, dataset_root.resolve()


def collect_image_paths(
    dataset_root: Path, train: str | None, val: str | None
) -> list[Path]:
    """Collect image paths from train and val dirs. Skips non-image files."""
    exts = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp"}
    paths: list[Path] = []
    for part in (train, val):
        if not part:
            continue
        dir_path = dataset_root / part
        if not dir_path.is_dir():
            logger.warning(f"Dataset dir missing: {dir_path}")
            continue
        for p in sorted(dir_path.iterdir()):
            if p.suffix.lower() in exts:
                paths.append(p)
    return paths


def label_path_for_image(dataset_root: Path, image_path: Path) -> Path:
    """YOLO layout: images/train/foo.jpg -> labels/train/foo.txt."""
    # image_path is dataset_root / "images" / split / name.ext
    # or dataset_root / train_dir / name.ext when train is "images/train"
    rel = image_path.relative_to(dataset_root)
    parts = rel.parts
    if len(parts) >= 2 and parts[0] == "images":
        split = parts[1]
    else:
        split = parts[0] if parts else "train"
    return dataset_root / "labels" / split / f"{image_path.stem}.txt"


def parse_yolo_label_file(path: Path) -> list[tuple[int, float, float, float, float]]:
    """Parse YOLO .txt: one line per object = 'class_id x_center y_center width height' (normalized 0-1).
    Returns list of (class_id, x_center, y_center, width, height).
    """
    if not path.is_file():
        return []
    rows: list[tuple[int, float, float, float, float]] = []
    for line in path.read_text(encoding="utf-8").strip().splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 5:
            continue
        try:
            cid = int(parts[0])
            xc = float(parts[1])
            yc = float(parts[2])
            w = float(parts[3])
            h = float(parts[4])
            rows.append((cid, xc, yc, w, h))
        except (ValueError, IndexError):
            logger.warning(
                "Skipping malformed YOLO line in {}: {!r}",
                path,
                line,
            )
            continue
    return rows


def yolo_norm_to_pixel_bbox(
    x_center: float,
    y_center: float,
    width: float,
    height: float,
    img_width: int,
    img_height: int,
) -> list[float]:
    """Convert YOLO normalized (xc, yc, w, h) to CVAT rectangle points [x1, y1, x2, y2] in pixels."""
    x1 = (x_center - width / 2.0) * img_width
    y1 = (y_center - height / 2.0) * img_height
    x2 = (x_center + width / 2.0) * img_width
    y2 = (y_center + height / 2.0) * img_height
    return [x1, y1, x2, y2]


def load_bbox_annotations(
    dataset_root: Path,
    image_paths: list[Path],
) -> list[list[tuple[int, list[float]]]]:
    """For each image, load YOLO labels and return list of (class_id, [x1,y1,x2,y2]) per frame.
    Uses PIL to get image size for conversion to pixels.
    """
    result: list[list[tuple[int, list[float]]]] = []
    for img_path in image_paths:
        label_path = label_path_for_image(dataset_root, img_path)
        yolo_rows = parse_yolo_label_file(label_path)
        try:
            with Image.open(img_path) as im:
                w, h = im.size
        except OSError:
            logger.warning(f"Cannot read image size: {img_path}")
            w, h = 1, 1
        frame_boxes: list[tuple[int, list[float]]] = []
        for cid, xc, yc, bw, bh in yolo_rows:
            points = yolo_norm_to_pixel_bbox(xc, yc, bw, bh, w, h)
            frame_boxes.append((cid, points))
        result.append(frame_boxes)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create CVAT project and multiple tasks from dataset YAML (e.g. coco8)."
    )
    parser.add_argument(
        "--yaml",
        type=Path,
        default=Path("tests/fixtures/data/coco8.yaml"),
        help="Path to dataset YAML (path, train, val, names).",
    )
    parser.add_argument(
        "--project",
        type=str,
        default="coco8-dev",
        help="CVAT project name.",
    )
    parser.add_argument(
        "--tasks",
        type=int,
        default=2,
        help="Number of tasks to create (each with the same images).",
    )
    args = parser.parse_args()

    yaml_path = args.yaml.resolve()
    if not yaml_path.is_file():
        logger.error(f"YAML not found: {yaml_path}")
        raise SystemExit(1)

    dataset_spec, dataset_root = load_dataset_yaml(yaml_path)
    label_names = dataset_spec.label_names_sorted()
    image_paths = collect_image_paths(
        dataset_root,
        dataset_spec.train,
        dataset_spec.val,
    )
    if not image_paths:
        logger.error("No images found in train/val dirs.")
        raise SystemExit(1)

    bbox_annotations = load_bbox_annotations(dataset_root, image_paths)
    total_boxes = sum(len(f) for f in bbox_annotations)
    logger.info(
        f"Dataset: {dataset_root}, labels={len(label_names)}, images={len(image_paths)}, bboxes={total_boxes}"
    )

    cfg = CvatConfig.load()
    resolved = cfg.ensure_credentials()
    if not resolved.host:
        logger.error("CVAT host not set. Run cveta2 setup or set CVAT_HOST.")
        raise SystemExit(1)

    kwargs: dict = {"host": resolved.host}
    if resolved.token:
        kwargs["access_token"] = resolved.token
    else:
        kwargs["credentials"] = (resolved.username or "", resolved.password or "")

    with make_client(**kwargs) as client:
        if resolved.organization:
            client.organization_slug = resolved.organization

        # Create project with labels (no attributes for simplicity)
        project_spec = {
            "name": args.project,
            "labels": [{"name": name} for name in label_names],
        }
        project = client.projects.create(project_spec)
        logger.info(f"Created project: {project.name} (id={project.id})")

        # Create N tasks with the same image set and upload bbox annotations
        resource_list = [str(p) for p in image_paths]
        task_spec_base = {
            "project_id": project.id,
            "labels": [],  # inherit from project
        }
        for i in range(args.tasks):
            task_name = f"{args.project}-task-{i + 1}"
            task_spec = {"name": task_name, **task_spec_base}
            task = client.tasks.create_from_data(
                spec=task_spec,
                resource_type=ResourceType.LOCAL,
                resources=resource_list,
            )
            logger.info(f"Created task: {task.name} (id={task.id}, size={task.size})")

            # Upload bbox annotations: map class index to task label_id by name
            task_labels = task.get_labels()
            name_to_id = {label.name: label.id for label in task_labels}
            label_ids_by_class = [name_to_id[name] for name in label_names]

            shapes: list[cvat_models.LabeledShapeRequest] = []
            for frame_idx, frame_boxes in enumerate(bbox_annotations):
                for class_id, points in frame_boxes:
                    if class_id >= len(label_ids_by_class):
                        continue
                    shapes.append(
                        cvat_models.LabeledShapeRequest(
                            type=cvat_models.ShapeType("rectangle"),
                            frame=frame_idx,
                            label_id=label_ids_by_class[class_id],
                            points=points,
                        )
                    )
            if shapes:
                task.update_annotations(
                    cvat_models.PatchedLabeledDataRequest(shapes=shapes),
                    action=AnnotationUpdateAction.CREATE,
                )
                logger.info(
                    f"Uploaded {len(shapes)} bbox annotation(s) to task {task.id}"
                )

    logger.info(
        "Done. Use cveta2 fetch --project {} to export annotations.", args.project
    )


if __name__ == "__main__":
    main()
