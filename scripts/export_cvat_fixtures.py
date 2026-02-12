#!/usr/bin/env python3
"""Export CVAT project/task data to JSON fixtures for tests.

Uses only cvat_sdk (no cveta2 client). Credentials via env: CVAT_HOST,
CVAT_USERNAME, CVAT_PASSWORD. Output mirrors cveta2._client.dtos shape.

Example:
  CVAT_HOST=http://localhost:8080 CVAT_USERNAME=admin CVAT_PASSWORD=... \\
  uv run python scripts/export_cvat_fixtures.py --project coco8-dev
"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

from cvat_sdk import make_client
from cvat_sdk.api_client import models as cvat_models
from loguru import logger


def _slug(name: str) -> str:
    """Sanitize task name for filename: lowercase, spaces/spaces to single hyphen."""
    s = re.sub(r"[^\w\s-]", "", name)
    s = re.sub(r"[-\s]+", "-", s).strip("-").lower()
    return s or "task"


def _extract_updated_date(task: cvat_models.TaskRead) -> str:
    raw = getattr(task, "updated_date", None) or getattr(task, "updated_at", None)
    if raw is None:
        return ""
    isoformat = getattr(raw, "isoformat", None)
    if callable(isoformat):
        return str(isoformat())
    return str(raw)


def _extract_creator_username(item: object) -> str:
    user_obj = getattr(item, "created_by", None) or getattr(item, "owner", None)
    if user_obj is None:
        return ""
    username = getattr(user_obj, "username", None) or getattr(user_obj, "name", None)
    if username is not None:
        return str(username)
    if isinstance(user_obj, dict):
        return str(user_obj.get("username") or user_obj.get("name") or "")
    return ""


def task_to_dict(task: cvat_models.TaskRead) -> dict:
    return {
        "id": task.id,
        "name": task.name or "",
        "status": str(task.status or ""),
        "subset": task.subset or "",
        "updated_date": _extract_updated_date(task),
    }


def label_to_dict(label: cvat_models.Label) -> dict:
    raw_attrs = label.attributes or []
    attrs = [{"id": a.id, "name": a.name or ""} for a in raw_attrs]
    return {"id": label.id, "name": label.name, "attributes": attrs}


def data_meta_to_dict(data_meta: cvat_models.DataMetaRead) -> dict:
    frames_raw = data_meta.frames or []
    frames = [
        {"name": f.name or "", "width": int(f.width or 0), "height": int(f.height or 0)}
        for f in frames_raw
    ]
    deleted = list(data_meta.deleted_frames or [])
    return {"frames": frames, "deleted_frames": deleted}


def _attributes_to_list(
    raw_attrs: list[cvat_models.AttributeVal] | None,
) -> list[dict]:
    if not raw_attrs:
        return []
    return [{"spec_id": a.spec_id, "value": str(a.value or "")} for a in raw_attrs]


def shape_to_dict(shape: cvat_models.LabeledShape) -> dict:
    type_val = shape.type.value if shape.type else str(shape.type)
    return {
        "id": shape.id or 0,
        "type": type_val,
        "frame": shape.frame,
        "label_id": shape.label_id,
        "points": list(shape.points or []),
        "occluded": bool(shape.occluded),
        "z_order": int(shape.z_order or 0),
        "rotation": float(shape.rotation or 0.0),
        "source": str(shape.source or ""),
        "attributes": _attributes_to_list(shape.attributes),
        "created_by": _extract_creator_username(shape),
    }


def tracked_shape_to_dict(ts: cvat_models.TrackedShape) -> dict:
    type_str = ts.type.value if ts.type else str(ts.type)
    return {
        "type": type_str,
        "frame": ts.frame,
        "points": list(ts.points or []),
        "outside": bool(ts.outside),
        "occluded": bool(ts.occluded),
        "z_order": int(ts.z_order or 0),
        "rotation": float(ts.rotation or 0.0),
        "attributes": _attributes_to_list(ts.attributes),
        "created_by": _extract_creator_username(ts),
    }


def track_to_dict(track: cvat_models.LabeledTrack) -> dict:
    raw_shapes = track.shapes or []
    return {
        "id": track.id or 0,
        "label_id": track.label_id,
        "source": str(track.source or ""),
        "shapes": [tracked_shape_to_dict(s) for s in raw_shapes],
        "created_by": _extract_creator_username(track),
    }


def annotations_to_dict(labeled_data: cvat_models.LabeledData) -> dict:
    raw_shapes = labeled_data.shapes or []
    raw_tracks = labeled_data.tracks or []
    return {
        "shapes": [shape_to_dict(s) for s in raw_shapes],
        "tracks": [track_to_dict(t) for t in raw_tracks],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Export CVAT project to JSON fixtures")
    parser.add_argument(
        "--project",
        default="coco8-dev",
        help="Project name to export (default: coco8-dev)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("tests/fixtures/cvat/coco8-dev"),
        help="Output directory for project.json and tasks/ (default: tests/fixtures/cvat/coco8-dev)",
    )
    args = parser.parse_args()

    host = os.environ.get("CVAT_HOST", "").strip()
    username = os.environ.get("CVAT_USERNAME", "").strip()
    password = os.environ.get("CVAT_PASSWORD", "").strip()
    if not host or not username or not password:
        logger.error("Set CVAT_HOST, CVAT_USERNAME, CVAT_PASSWORD in the environment")
        raise SystemExit(1)

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    tasks_dir = output_dir / "tasks"
    tasks_dir.mkdir(exist_ok=True)

    with make_client(host=host, credentials=(username, password)) as client:
        projects = client.projects.list()
        project = None
        for p in projects:
            if (p.name or "").strip().lower() == args.project.strip().lower():
                project = p
                break
        if project is None:
            logger.error(f"Project not found: {args.project!r}")
            raise SystemExit(1)

        project_id = project.id
        project = client.projects.retrieve(project_id)
        tasks = project.get_tasks()
        labels = project.get_labels()

        project_payload = {
            "id": project_id,
            "name": project.name or "",
            "labels": [label_to_dict(lbl) for lbl in labels],
        }
        (output_dir / "project.json").write_text(
            json.dumps(project_payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info(f"Wrote {output_dir / 'project.json'}")

        tasks_api = client.api_client.tasks_api
        for task in tasks:
            data_meta, _ = tasks_api.retrieve_data_meta(task.id)
            labeled_data, _ = tasks_api.retrieve_annotations(task.id)
            slug = _slug(task.name or "")
            task_filename = f"{task.id}_{slug}.json"
            task_payload = {
                "task": task_to_dict(task),
                "data_meta": data_meta_to_dict(data_meta),
                "annotations": annotations_to_dict(labeled_data),
            }
            (tasks_dir / task_filename).write_text(
                json.dumps(task_payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            logger.info(f"Wrote {tasks_dir / task_filename}")

    logger.info("Export done.")


if __name__ == "__main__":
    main()
