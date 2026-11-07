#!/usr/bin/env python3
"""Measure the real fetch pipeline with controlled remote latency and local files.

Run from a checkout with ``uv run python -m scripts.benchmark_fetch --output out.json``.
To measure another source revision, put its extracted tree first on PYTHONPATH and
invoke this same script by absolute path. The JSON fingerprints the imported fetch
module; no live CVAT/S3 credentials or endpoints are used. Remote calls are in-process
fixtures with a fixed artificial latency, so results are workload comparisons,
not predictions of production network throughput.
"""

import argparse
import hashlib
import io
import json
import statistics
import tempfile
import threading
import time
from collections import Counter
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from unittest.mock import patch

from loguru import logger

import cveta2.application.use_cases.fetch as fetch_module
from cveta2.adapters.execution.concurrency import configure_workers, run_concurrent
from cveta2.adapters.files.task_output import LocalWorkflowFiles
from cveta2.adapters.s3.images import S3ImageReader
from cveta2.adapters.s3.task_cache import TaskAnnotationCache
from cveta2.application.client import ApplicationClient
from cveta2.application.ports.client import ClientSettings
from cveta2.application.ports.dtos import (
    RawAnnotations,
    RawDataMeta,
    RawFrame,
    RawShape,
)
from cveta2.application.settings import CacheProjectSettings
from cveta2.application.use_cases.fetch import (
    FetchDependencies,
    FetchOptions,
    FetchTarget,
    fetch_project,
)
from cveta2.domain.models import LabelInfo, ProjectInfo, TaskAnnotations, TaskInfo
from cveta2.domain.storage import CloudStorageInfo
from tests.fixtures.fake_cvat_api import FakeCvatApi
from tests.fixtures.fake_cvat_project import LoadedFixtures
from tests.fixtures.fake_s3 import FakeS3Client


@dataclass(frozen=True)
class Workload:
    """Fixed data volume and cache/key-layout choices for one scenario."""

    name: str
    images: int
    tasks: int
    boxes_per_image: int
    image_bytes: int
    warm: bool = False
    fallback: bool = False


WORKLOADS = (
    Workload("cold", 80, 8, 3, 32 * 1024),
    Workload("warm", 80, 8, 3, 32 * 1024, warm=True),
    Workload("fallback", 80, 8, 3, 32 * 1024, fallback=True),
    Workload("large-image", 12, 4, 3, 8 * 1024 * 1024),
    Workload("annotation-heavy", 80, 8, 150, 32 * 1024),
    Workload("large-batch", 2048, 8, 1, 4 * 1024),
)
_STORAGE = CloudStorageInfo(id=1, bucket="benchmark", prefix="images", endpoint_url="")
_CSV_NAMES = ("dataset.csv", "obsolete.csv", "in_progress.csv", "deleted.csv")


class _TimedCvat(FakeCvatApi):
    """Reusable typed CVAT fixture with identical per-call delay in both revisions."""

    def __init__(self, fixtures: LoadedFixtures, delay: float) -> None:
        super().__init__(fixtures)
        self._delay = delay

    def _enter(self, method: str) -> None:
        time.sleep(self._delay)
        super()._enter(method)

    def _raise_if_failing(self, method: str, task_id: int) -> None:
        time.sleep(self._delay)
        super()._raise_if_failing(method, task_id)

    def get_project_labels(self, _project_id: int) -> list[LabelInfo]:
        self._enter("get_project_labels")
        return super().get_project_labels(_project_id)

    def get_project_cloud_storage(self, _project_id: int) -> CloudStorageInfo:
        self._enter("get_project_cloud_storage")
        return _STORAGE


class _Body(io.BytesIO):
    """Support both all-at-once and chunked S3 streaming consumers."""

    def iter_chunks(self, chunk_size: int = 1024) -> Iterator[bytes]:
        while chunk := self.read(chunk_size):
            yield chunk


class _TimedS3(FakeS3Client):
    """Count S3 operations while returning real byte streams."""

    def __init__(self, objects: dict[str, bytes], delay: float) -> None:
        super().__init__(objects, keyed_by_bucket=False)
        self._delay = delay

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:  # noqa: N803
        time.sleep(self._delay)
        super().get_object(Bucket=Bucket, Key=Key)
        return {"Body": _Body(self.objects[Key])}

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:  # noqa: N803
        time.sleep(self._delay)
        return super().head_object(Bucket=Bucket, Key=Key)

    def list_objects_v2(self, **kwargs: str) -> dict[str, Any]:
        time.sleep(self._delay)
        return super().list_objects_v2(**kwargs)

    def clear_counts(self) -> None:
        self.get_calls.clear()
        self.head_calls.clear()
        self.list_requests.clear()


class _LocalCacheFactory:
    """Use the production local annotation cache without an S3 mirror."""

    def __init__(self, directory: Path) -> None:
        self._cache = TaskAnnotationCache(directory)

    def create(
        self,
        project_id: int,
        cs_info: CloudStorageInfo | None,
        settings: CacheProjectSettings,
        *,
        local_only: bool = False,
    ) -> TaskAnnotationCache:
        del project_id, cs_info, settings, local_only
        return self._cache


class _CountedFiles(LocalWorkflowFiles):
    """Count debug-file operations while executing the production file adapter."""

    def __init__(self) -> None:
        self.counts: Counter[str] = Counter()
        self._lock = threading.Lock()

    def _record(self, operation: str) -> None:
        with self._lock:
            self.counts[operation] += 1

    def prepare_tasks(self, output_dir: Path) -> Path:
        self._record("prepare_tasks")
        return super().prepare_tasks(output_dir)

    def write_task_csv(self, task: TaskInfo, result: TaskAnnotations, tasks_dir: Path) -> None:
        self._record("task_csv_writes")
        super().write_task_csv(task, result, tasks_dir)

    def cleanup_tasks(self, tasks_dir: Path) -> None:
        self._record("cleanup_tasks")
        super().cleanup_tasks(tasks_dir)


def _shape(frame: int, shape_id: int) -> RawShape:
    return RawShape(
        id=shape_id,
        type="rectangle",
        frame=frame,
        label_id=1,
        points=[10.0, 20.0, 30.0, 40.0],
        occluded=False,
        z_order=0,
        rotation=0.0,
        source="manual",
        attributes=[],
        created_by="benchmark",
    )


def _fixtures(workload: Workload) -> LoadedFixtures:
    tasks = [
        TaskInfo(
            id=index + 1,
            name=f"task-{index + 1}",
            status="completed",
            subset="",
            updated_date="2026-10-28T00:00:00Z",
            project_id=1,
        )
        for index in range(workload.tasks)
    ]
    data: dict[int, tuple[RawDataMeta, RawAnnotations]] = {}
    for index, task in enumerate(tasks):
        image_ids = range(index, workload.images, workload.tasks)
        frames = [RawFrame(name=f"image-{image_id:05}.jpg", width=640, height=480) for image_id in image_ids]
        shapes = [
            _shape(frame, frame * workload.boxes_per_image + box + 1)
            for frame in range(len(frames))
            for box in range(workload.boxes_per_image)
        ]
        data[task.id] = (RawDataMeta(frames=frames), RawAnnotations(shapes=shapes))
    return LoadedFixtures(ProjectInfo(id=1, name="benchmark"), tasks, [LabelInfo(id=1, name="box")], data)


def _csv_digest(directory: Path, root: Path) -> str:
    digest = hashlib.sha256()
    for name in _CSV_NAMES:
        digest.update(name.encode())
        digest.update((directory / name).read_bytes().replace(str(root).encode(), b"<ROOT>"))
    return digest.hexdigest()


def _measure(workload: Workload, options: argparse.Namespace) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="cveta2-fetch-benchmark-") as temporary:
        root = Path(temporary)
        return _run_workload(workload, options, root)


def _run_workload(workload: Workload, options: argparse.Namespace, root: Path) -> dict[str, object]:
    delay = options.latency_ms / 1000.0
    api = _TimedCvat(_fixtures(workload), delay)
    object_prefix = "images/legacy" if workload.fallback else "images"
    payload = b"x" * workload.image_bytes
    s3 = _TimedS3(
        {f"{object_prefix}/image-{index:05}.jpg": payload for index in range(workload.images)},
        delay,
    )
    files = _CountedFiles()
    client = ApplicationClient(
        ClientSettings(host="https://benchmark.invalid", cvat_workers=options.cvat_workers),
        images=S3ImageReader(),
        runner=run_concurrent,
        api=api,
    )
    deps = FetchDependencies(
        caches=_LocalCacheFactory(root / "cache"),
        files=files,
        runner=run_concurrent,
        clock=time.perf_counter,
        lock_factory=threading.Lock,
        cache_settings=CacheProjectSettings(tasks_root=root / "cache"),
        cvat_workers=options.cvat_workers,
    )
    target = FetchTarget(1, "benchmark", root / "output", cs_info=_STORAGE)
    fetch_options = FetchOptions(images_dir=root / "images")
    resolve_count = 0
    count_lock = threading.Lock()
    original_resolve = Path.resolve

    def counted_resolve(path: Path, *, strict: bool = False) -> Path:
        nonlocal resolve_count
        with count_lock:
            resolve_count += 1
        return original_resolve(path, strict=strict)

    with patch("cveta2.adapters.s3.download.make_s3_client", return_value=s3):
        if workload.warm:
            fetch_project(client, target, fetch_options, deps=deps)
            api.call_counts.clear()
            s3.clear_counts()
            files.counts.clear()
        with patch.object(Path, "resolve", counted_resolve):
            started = time.perf_counter()
            result = fetch_project(client, target, fetch_options, deps=deps)
            elapsed = time.perf_counter() - started
    image_files = [path for path in (root / "images").rglob("*") if path.is_file()]
    image_bytes = sum(path.stat().st_size for path in image_files)
    expected_rows = workload.images * workload.boxes_per_image
    if len(result.dataset) != expected_rows or len(image_files) != workload.images:
        raise RuntimeError("Benchmark fetch produced incomplete rows or images")
    if image_bytes != workload.images * workload.image_bytes:
        raise RuntimeError("Benchmark image byte count differs from source")
    return {
        "elapsed_seconds": elapsed,
        "counts": {
            "s3_get": len(s3.get_calls),
            "s3_head": len(s3.head_calls),
            "s3_list": len(s3.list_requests),
            "task_inventory": api.call_counts["get_project_tasks"],
            "task_annotations": api.call_counts["get_task_annotations"],
            "prepare_tasks": files.counts["prepare_tasks"],
            "task_csv_writes": files.counts["task_csv_writes"],
            "cleanup_tasks": files.counts["cleanup_tasks"],
            "path_resolve": resolve_count,
        },
        "rows": len(result.dataset),
        "image_files": len(image_files),
        "image_bytes": image_bytes,
        "csv_sha256": _csv_digest(target.output_dir, root),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--label", default="working-tree")
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--latency-ms", type=float, default=2.0)
    parser.add_argument("--s3-workers", type=int, default=4)
    parser.add_argument("--cvat-workers", type=int, default=2)
    parser.add_argument("--workload", choices=[case.name for case in WORKLOADS], action="append")
    options = parser.parse_args()
    if options.repetitions < 1 or options.latency_ms < 0:
        parser.error("repetitions must be positive and latency nonnegative")
    configure_workers(s3=options.s3_workers, cvat=options.cvat_workers)
    logger.remove()
    selected = [case for case in WORKLOADS if not options.workload or case.name in options.workload]
    records: list[dict[str, object]] = []
    for case in selected:
        samples = [_measure(case, options) for _ in range(options.repetitions)]
        elapsed = [float(str(sample["elapsed_seconds"])) for sample in samples]
        records.append(
            {
                "workload": asdict(case),
                "median_seconds": statistics.median(elapsed),
                "samples": samples,
            }
        )
        print(f"{case.name}: median {statistics.median(elapsed):.4f} s", flush=True)
    source_path = fetch_module.__file__
    if source_path is None:
        raise RuntimeError("Cannot identify the imported fetch implementation")
    report = {
        "label": options.label,
        "imported_fetch_sha256": hashlib.sha256(Path(source_path).read_bytes()).hexdigest(),
        "configuration": {
            "repetitions": options.repetitions,
            "latency_ms": options.latency_ms,
            "s3_workers": options.s3_workers,
            "cvat_workers": options.cvat_workers,
        },
        "workloads": records,
    }
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
