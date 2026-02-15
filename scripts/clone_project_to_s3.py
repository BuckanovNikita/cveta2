#!/usr/bin/env python3
"""Clone a CVAT project, moving all task images to an existing S3 cloud storage.

Downloads frames from the source project, uploads them to the S3 bucket
referenced by the CVAT cloud storage, then creates a new project with
identical labels + tasks + annotations pointing at the cloud storage files.

Credentials:
  - CVAT: reads from ~/.config/cveta2/config.yaml (CvatConfig)
  - S3:   reads from ~/.aws/credentials (boto3 default chain)

Example:
  uv run python scripts/clone_project_to_s3.py \\
      --source coco8-dev --dest coco8-dev-s3 --cloud-storage-id 1
"""

from __future__ import annotations

import argparse
import time
from urllib.parse import parse_qs

import boto3
from cvat_sdk import make_client
from cvat_sdk.api_client import models as cvat_models
from cvat_sdk.core.proxies.annotations import AnnotationUpdateAction
from loguru import logger
from pydantic import BaseModel

from cveta2.config import CvatConfig


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class CloudStorageInfo(BaseModel):
    """Parsed cloud storage metadata from CVAT."""

    id: int
    bucket: str
    prefix: str
    endpoint_url: str


def parse_cloud_storage(cs: object) -> CloudStorageInfo:
    """Extract bucket, prefix, endpoint from CVAT cloud storage object."""
    specific = str(cs.specific_attributes or "")
    parsed = parse_qs(specific)
    prefix = (parsed.get("prefix") or [""])[0]
    endpoint_url = (parsed.get("endpoint_url") or [""])[0]
    return CloudStorageInfo(
        id=int(cs.id),
        bucket=str(cs.resource),
        prefix=prefix,
        endpoint_url=endpoint_url,
    )


# ---------------------------------------------------------------------------
# S3 helpers
# ---------------------------------------------------------------------------


def upload_bytes_to_s3(
    s3_client: object,
    bucket: str,
    key: str,
    data: bytes,
) -> None:
    """Upload raw bytes to S3."""
    s3_client.put_object(Bucket=bucket, Key=key, Body=data)  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# CVAT helpers
# ---------------------------------------------------------------------------


def download_task_frames(
    cvat_client: object,
    task_id: int,
    frame_ids: list[int],
) -> dict[int, bytes]:
    """Download original-quality frames from a CVAT task. Returns {frame_id: raw_bytes}."""
    task = cvat_client.tasks.retrieve(task_id)  # type: ignore[union-attr]
    result: dict[int, bytes] = {}
    for fid in frame_ids:
        stream = task.get_frame(fid, quality="original")
        result[fid] = stream.read()
    return result


def build_label_id_map(
    src_labels: list[cvat_models.Label],
    dst_labels: list[cvat_models.Label],
) -> dict[int, int]:
    """Map source label IDs to destination label IDs by name."""
    dst_by_name: dict[str, int] = {}
    for lbl in dst_labels:
        dst_by_name[lbl.name] = lbl.id

    mapping: dict[int, int] = {}
    for lbl in src_labels:
        if lbl.name in dst_by_name:
            mapping[lbl.id] = dst_by_name[lbl.name]
        else:
            logger.warning(f"Label {lbl.name!r} (id={lbl.id}) not found in destination")
    return mapping


def build_attr_id_map(
    src_labels: list[cvat_models.Label],
    dst_labels: list[cvat_models.Label],
) -> dict[int, int]:
    """Map source attribute spec_ids to destination ones by (label_name, attr_name)."""
    # Build dst index: (label_name, attr_name) -> attr_id
    dst_index: dict[tuple[str, str], int] = {}
    for lbl in dst_labels:
        for attr in lbl.attributes or []:
            dst_index[(lbl.name, attr.name)] = attr.id

    mapping: dict[int, int] = {}
    for lbl in src_labels:
        for attr in lbl.attributes or []:
            key = (lbl.name, attr.name)
            if key in dst_index:
                mapping[attr.id] = dst_index[key]
    return mapping


def remap_shapes(
    shapes: list[cvat_models.LabeledShape],
    label_map: dict[int, int],
    attr_map: dict[int, int],
) -> list[cvat_models.LabeledShapeRequest]:
    """Convert source shapes to destination shape requests with remapped IDs."""
    result: list[cvat_models.LabeledShapeRequest] = []
    for s in shapes:
        new_label_id = label_map.get(s.label_id)
        if new_label_id is None:
            logger.warning(f"Skipping shape with unknown label_id={s.label_id}")
            continue
        attrs = []
        for a in s.attributes or []:
            new_spec_id = attr_map.get(a.spec_id, a.spec_id)
            attrs.append(
                cvat_models.AttributeValRequest(
                    spec_id=new_spec_id, value=str(a.value or "")
                )
            )

        result.append(
            cvat_models.LabeledShapeRequest(
                type=s.type,
                frame=s.frame,
                label_id=new_label_id,
                occluded=bool(s.occluded),
                z_order=int(s.z_order or 0),
                rotation=float(s.rotation or 0.0),
                points=list(s.points or []),
                source=str(s.source or ""),
                attributes=attrs,
            )
        )
    return result


def remap_tracks(
    tracks: list[cvat_models.LabeledTrack],
    label_map: dict[int, int],
    attr_map: dict[int, int],
) -> list[cvat_models.LabeledTrackRequest]:
    """Convert source tracks to destination track requests with remapped IDs."""
    result: list[cvat_models.LabeledTrackRequest] = []
    for t in tracks:
        new_label_id = label_map.get(t.label_id)
        if new_label_id is None:
            logger.warning(f"Skipping track with unknown label_id={t.label_id}")
            continue
        attrs = []
        for a in t.attributes or []:
            new_spec_id = attr_map.get(a.spec_id, a.spec_id)
            attrs.append(
                cvat_models.AttributeValRequest(
                    spec_id=new_spec_id, value=str(a.value or "")
                )
            )

        tracked_shapes: list[cvat_models.TrackedShapeRequest] = []
        for ts in t.shapes or []:
            ts_attrs = []
            for a in ts.attributes or []:
                new_spec_id = attr_map.get(a.spec_id, a.spec_id)
                ts_attrs.append(
                    cvat_models.AttributeValRequest(
                        spec_id=new_spec_id, value=str(a.value or "")
                    )
                )
            tracked_shapes.append(
                cvat_models.TrackedShapeRequest(
                    type=ts.type,
                    frame=ts.frame,
                    occluded=bool(ts.occluded),
                    outside=bool(ts.outside),
                    z_order=int(ts.z_order or 0),
                    rotation=float(ts.rotation or 0.0),
                    points=list(ts.points or []),
                    attributes=ts_attrs,
                )
            )

        result.append(
            cvat_models.LabeledTrackRequest(
                frame=t.frame,
                label_id=new_label_id,
                source=str(t.source or ""),
                attributes=attrs,
                shapes=tracked_shapes,
            )
        )
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Clone a CVAT project, moving images to S3 cloud storage."
    )
    parser.add_argument(
        "--source",
        default="coco8-dev",
        help="Source project name (default: coco8-dev).",
    )
    parser.add_argument(
        "--dest",
        default=None,
        help="Destination project name (default: <source>-s3).",
    )
    parser.add_argument(
        "--cloud-storage-id",
        type=int,
        default=1,
        help="CVAT cloud storage ID to use (default: 1).",
    )
    parser.add_argument(
        "--s3-subdir",
        default=None,
        help="Subdirectory within cloud storage prefix for images (default: dest project name).",
    )
    args = parser.parse_args()

    dest_name: str = args.dest or f"{args.source}-s3"
    s3_subdir: str = args.s3_subdir or dest_name

    # ── Load CVAT config ──────────────────────────────────────────────
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

    with make_client(**kwargs) as cvat:
        if resolved.organization:
            cvat.organization_slug = resolved.organization

        # ── Resolve source project ────────────────────────────────────
        projects = cvat.projects.list()
        src_project = None
        for p in projects:
            if (p.name or "").strip().lower() == args.source.strip().lower():
                src_project = p
                break
        if src_project is None:
            logger.error(f"Source project not found: {args.source!r}")
            raise SystemExit(1)

        src_project = cvat.projects.retrieve(src_project.id)
        src_labels = src_project.get_labels()
        src_tasks = src_project.get_tasks()
        logger.info(
            f"Source project: {src_project.name} (id={src_project.id}), {len(src_tasks)} tasks"
        )

        # ── Read cloud storage info ───────────────────────────────────
        cs_api = cvat.api_client.cloudstorages_api
        cs_raw, _ = cs_api.retrieve(args.cloud_storage_id)
        cs_info = parse_cloud_storage(cs_raw)
        logger.info(
            f"Cloud storage #{cs_info.id}: bucket={cs_info.bucket}, "
            f"prefix={cs_info.prefix}, endpoint={cs_info.endpoint_url}"
        )

        # ── Init S3 client ────────────────────────────────────────────
        s3 = boto3.Session().client("s3", endpoint_url=cs_info.endpoint_url)

        # ── Download images from the first task (all tasks share same images) ─
        # Pick any task to download the canonical image set
        ref_task_id = src_tasks[0].id
        tasks_api = cvat.api_client.tasks_api
        ref_meta, _ = tasks_api.retrieve_data_meta(ref_task_id)
        frame_names: list[str] = [f.name for f in ref_meta.frames]
        frame_ids = list(range(len(frame_names)))

        logger.info(f"Downloading {len(frame_ids)} frames from task {ref_task_id}...")
        frame_bytes = download_task_frames(cvat, ref_task_id, frame_ids)

        # ── Upload images to S3 ──────────────────────────────────────
        # Files go to: s3://<bucket>/<prefix>/<s3_subdir>/<filename>
        s3_file_keys: list[str] = []
        for fid, name in enumerate(frame_names):
            if cs_info.prefix:
                key = f"{cs_info.prefix}/{s3_subdir}/{name}"
            else:
                key = f"{s3_subdir}/{name}"
            logger.info(f"Uploading {name} -> s3://{cs_info.bucket}/{key}")
            upload_bytes_to_s3(s3, cs_info.bucket, key, frame_bytes[fid])
            s3_file_keys.append(key)

        # server_files paths must include the prefix (full path from bucket root)
        if cs_info.prefix:
            server_files = [
                f"{cs_info.prefix}/{s3_subdir}/{name}" for name in frame_names
            ]
        else:
            server_files = [f"{s3_subdir}/{name}" for name in frame_names]
        logger.info(f"Uploaded {len(server_files)} files to S3")

        # ── Create destination project ────────────────────────────────
        label_specs = []
        for lbl in src_labels:
            attr_specs = []
            for attr in lbl.attributes or []:
                attr_specs.append({"name": attr.name})
            label_specs.append({"name": lbl.name, "attributes": attr_specs})

        dst_project = cvat.projects.create({"name": dest_name, "labels": label_specs})
        logger.info(f"Created project: {dst_project.name} (id={dst_project.id})")

        dst_project = cvat.projects.retrieve(dst_project.id)
        dst_labels = dst_project.get_labels()

        label_map = build_label_id_map(src_labels, dst_labels)
        attr_map = build_attr_id_map(src_labels, dst_labels)

        # ── Clone each task ───────────────────────────────────────────
        for src_task in src_tasks:
            logger.info(f"Cloning task: {src_task.name} (id={src_task.id})...")

            # Create task with source_storage pointing at the cloud storage.
            # Without this, cveta2 fetch cannot auto-detect cloud storage
            # for image download (it reads task.source_storage.cloud_storage_id).
            task_write = cvat_models.TaskWriteRequest(
                name=src_task.name,
                project_id=dst_project.id,
                subset=src_task.subset or "",
                source_storage=cvat_models.StorageRequest(
                    cloud_storage_id=cs_info.id,
                    location=cvat_models.LocationEnum("cloud_storage"),
                ),
            )
            dst_task_raw, _ = tasks_api.create(task_write)
            dst_task_id = dst_task_raw.id

            # Attach cloud storage images via low-level API
            data_request = cvat_models.DataRequest(
                image_quality=70,
                server_files=server_files,
                cloud_storage_id=cs_info.id,
                use_cache=True,
                sorting_method=cvat_models.SortingMethod("natural"),
            )
            tasks_api.create_data(dst_task_id, data_request=data_request)

            # Wait for data processing to finish
            for _ in range(30):
                time.sleep(1)
                dst_task_obj = cvat.tasks.retrieve(dst_task_id)
                if dst_task_obj.size and dst_task_obj.size > 0:
                    break
            else:
                logger.warning(f"  Task {dst_task_id} data processing timed out")

            logger.info(
                f"  Created task {dst_task_id} ({dst_task_obj.name}) "
                f"with {dst_task_obj.size} cloud storage files"
            )

            # Get source annotations
            src_ann, _ = tasks_api.retrieve_annotations(src_task.id)
            src_meta, _ = tasks_api.retrieve_data_meta(src_task.id)
            deleted_frames = list(src_meta.deleted_frames or [])

            # Copy annotations (remap label/attr IDs)
            new_shapes = remap_shapes(list(src_ann.shapes or []), label_map, attr_map)
            new_tracks = remap_tracks(list(src_ann.tracks or []), label_map, attr_map)

            if new_shapes or new_tracks:
                dst_task_obj.update_annotations(
                    cvat_models.PatchedLabeledDataRequest(
                        shapes=new_shapes,
                        tracks=new_tracks,
                    ),
                    action=AnnotationUpdateAction.CREATE,
                )
                logger.info(
                    f"  Uploaded {len(new_shapes)} shapes, {len(new_tracks)} tracks"
                )

            # Replicate deleted frames
            if deleted_frames:
                dst_task_obj = cvat.tasks.retrieve(dst_task_id)
                dst_task_obj.remove_frames_by_ids(deleted_frames)
                logger.info(f"  Deleted frames: {deleted_frames}")

    logger.info(f"Done! New project: {dest_name}")


if __name__ == "__main__":
    main()
