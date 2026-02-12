"""Load CVAT JSON fixtures into DTOs for tests.

Reads project.json and tasks/*.json from a project directory (e.g. coco8-dev)
and returns RawProject, list of RawTask, list of RawLabel, and a mapping
task_id -> (RawDataMeta, RawAnnotations). Uses cveta2._client.dtos.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cveta2._client.dtos import (
    RawAnnotations,
    RawAttribute,
    RawDataMeta,
    RawFrame,
    RawLabel,
    RawLabelAttribute,
    RawProject,
    RawShape,
    RawTask,
    RawTrack,
    RawTrackedShape,
)


def _dict_to_frame(d: dict[str, Any]) -> RawFrame:
    return RawFrame(
        name=d.get("name", "") or "",
        width=int(d.get("width", 0)),
        height=int(d.get("height", 0)),
    )


def _dict_to_attribute(d: dict[str, Any]) -> RawAttribute:
    return RawAttribute(spec_id=int(d.get("spec_id", 0)), value=str(d.get("value", "")))


def _dict_to_label_attribute(d: dict[str, Any]) -> RawLabelAttribute:
    return RawLabelAttribute(id=int(d.get("id", 0)), name=d.get("name", "") or "")


def _dict_to_shape(d: dict[str, Any]) -> RawShape:
    attrs = d.get("attributes") or []
    return RawShape(
        id=int(d.get("id", 0)),
        type=d.get("type", "") or "",
        frame=int(d.get("frame", 0)),
        label_id=int(d.get("label_id", 0)),
        points=list(d.get("points") or []),
        occluded=bool(d.get("occluded", False)),
        z_order=int(d.get("z_order", 0)),
        rotation=float(d.get("rotation", 0.0)),
        source=d.get("source", "") or "",
        attributes=[_dict_to_attribute(a) for a in attrs],
        created_by=d.get("created_by", "") or "",
    )


def _dict_to_tracked_shape(d: dict[str, Any]) -> RawTrackedShape:
    attrs = d.get("attributes") or []
    return RawTrackedShape(
        type=d.get("type", "") or "",
        frame=int(d.get("frame", 0)),
        points=list(d.get("points") or []),
        outside=bool(d.get("outside", False)),
        occluded=bool(d.get("occluded", False)),
        z_order=int(d.get("z_order", 0)),
        rotation=float(d.get("rotation", 0.0)),
        attributes=[_dict_to_attribute(a) for a in attrs],
        created_by=d.get("created_by", "") or "",
    )


def _dict_to_track(d: dict[str, Any]) -> RawTrack:
    shapes = d.get("shapes") or []
    return RawTrack(
        id=int(d.get("id", 0)),
        label_id=int(d.get("label_id", 0)),
        source=d.get("source", "") or "",
        shapes=[_dict_to_tracked_shape(s) for s in shapes],
        created_by=d.get("created_by", "") or "",
    )


def _dict_to_task(d: dict[str, Any]) -> RawTask:
    return RawTask(
        id=int(d.get("id", 0)),
        name=d.get("name", "") or "",
        status=d.get("status", "") or "",
        subset=d.get("subset", "") or "",
        updated_date=d.get("updated_date", "") or "",
    )


def _dict_to_data_meta(d: dict[str, Any]) -> RawDataMeta:
    frames = [_dict_to_frame(f) for f in (d.get("frames") or [])]
    deleted = list(d.get("deleted_frames") or [])
    return RawDataMeta(frames=frames, deleted_frames=deleted)


def _dict_to_annotations(d: dict[str, Any]) -> RawAnnotations:
    shapes = [_dict_to_shape(s) for s in (d.get("shapes") or [])]
    tracks = [_dict_to_track(t) for t in (d.get("tracks") or [])]
    return RawAnnotations(shapes=shapes, tracks=tracks)


def _dict_to_label(d: dict[str, Any]) -> RawLabel:
    attrs = d.get("attributes") or []
    return RawLabel(
        id=int(d.get("id", 0)),
        name=d.get("name", "") or "",
        attributes=[_dict_to_label_attribute(a) for a in attrs],
    )


def load_cvat_fixtures(
    project_dir: Path,
) -> tuple[
    RawProject,
    list[RawTask],
    list[RawLabel],
    dict[int, tuple[RawDataMeta, RawAnnotations]],
]:
    """Load project and task fixtures from a project directory.

    project_dir should contain project.json and a tasks/ subdir with
    <task_id>_<slug>.json files.

    Returns:
        (RawProject, list[RawTask], list[RawLabel], task_id -> (RawDataMeta,
        RawAnnotations))

    """
    project_dir = Path(project_dir)
    project_file = project_dir / "project.json"
    tasks_dir = project_dir / "tasks"

    if not project_file.is_file():
        raise FileNotFoundError(f"Missing {project_file}")
    if not tasks_dir.is_dir():
        raise FileNotFoundError(f"Missing directory {tasks_dir}")

    project_data = json.loads(project_file.read_text(encoding="utf-8"))
    project = RawProject(
        id=int(project_data.get("id", 0)),
        name=project_data.get("name", "") or "",
    )
    labels = [_dict_to_label(item) for item in (project_data.get("labels") or [])]

    tasks: list[RawTask] = []
    task_data_map: dict[int, tuple[RawDataMeta, RawAnnotations]] = {}

    for path in sorted(tasks_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        task = _dict_to_task(data.get("task") or {})
        data_meta = _dict_to_data_meta(data.get("data_meta") or {})
        annotations = _dict_to_annotations(data.get("annotations") or {})
        tasks.append(task)
        task_data_map[task.id] = (data_meta, annotations)

    return (project, tasks, labels, task_data_map)
