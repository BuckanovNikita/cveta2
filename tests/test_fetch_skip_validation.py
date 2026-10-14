"""Project promotion contracts over stateful CVAT and real task caches."""

import threading
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd
import pytest
from botocore.exceptions import ClientError

import cveta2
from cveta2.adapters.execution.concurrency import configure_workers
from cveta2.adapters.s3.task_cache import (
    S3CacheBackend,
    TaskAnnotationCache,
    get_task_cache_dir,
)
from cveta2.application.ports.dtos import RawAnnotations, RawDataMeta, RawFrame, RawJob
from cveta2.application.use_cases.fetch import FetchOptions, FetchTarget
from cveta2.composition.workflows import fetch_project
from cveta2.domain.errors import CvatApiError, Cveta2Error
from cveta2.domain.models import (
    ImageWithoutAnnotations,
    ProjectInfo,
    TaskAnnotations,
    TaskInfo,
)
from tests.fixtures.fake_cvat_api import FakeCvatApi
from tests.fixtures.fake_cvat_project import LoadedFixtures
from tests.fixtures.fake_s3 import FakeS3Client
from tests.helpers import client_with_api, write_config_yaml

if TYPE_CHECKING:
    from collections.abc import Callable

    from cveta2.domain.partition import PartitionResult


class PromotionApi(FakeCvatApi):
    """Persist job updates and derive fresh task status without timestamp edits."""

    def __init__(self, jobs: dict[int, list[RawJob]]) -> None:
        """Create one unannotated frame per task, with controlled live jobs."""
        fixtures = LoadedFixtures(
            project=ProjectInfo(id=1, name="promotion"),
            tasks=[
                TaskInfo(
                    id=task_id,
                    name=f"task-{task_id}",
                    status="annotation",
                    subset="train",
                    updated_date="unchanged",
                )
                for task_id in jobs
            ],
            labels=[],
            task_data={
                task_id: (
                    RawDataMeta(frames=[RawFrame(f"{task_id}.jpg", 10, 10)]),
                    RawAnnotations(),
                )
                for task_id in jobs
            },
        )
        super().__init__(fixtures)
        self.jobs = jobs
        self.job_reads: list[int] = []
        self.update_attempts: list[int] = []
        self.fail_job_reads: set[int] = set()
        self.fail_updates: set[int] = set()
        self.fail_project_reads = False
        self.before_update: Callable[[int], None] | None = None
        self.completion_at_annotations: list[dict[int, bool]] = []

    def get_project_tasks(self, project_id: int) -> list[TaskInfo]:
        tasks = super().get_project_tasks(project_id)
        if self.fail_project_reads:
            raise CvatApiError("list denied", status_code=403)
        return [
            task.model_copy(
                update={
                    "status": "completed"
                    if self.jobs[task.id]
                    and all(
                        job.stage == "acceptance" and job.state == "completed"
                        for job in self.jobs[task.id]
                    )
                    else "annotation"
                }
            )
            for task in tasks
        ]

    def get_task_jobs(self, task_id: int) -> list[RawJob]:
        self._raise_if_failing("get_task_jobs", task_id)
        self.job_reads.append(task_id)
        if task_id in self.fail_job_reads:
            raise CvatApiError("jobs denied", status_code=403)
        return list(self.jobs[task_id])

    def get_task_annotations(self, task_id: int) -> RawAnnotations:
        self.completion_at_annotations.append(
            {
                task_id: bool(jobs)
                and all(
                    job.stage == "acceptance" and job.state == "completed"
                    for job in jobs
                )
                for task_id, jobs in self.jobs.items()
            }
        )
        return super().get_task_annotations(task_id)

    def update_job(
        self, job_id: int, *, stage: str | None = None, state: str | None = None
    ) -> None:
        self.update_attempts.append(job_id)
        if self.before_update is not None:
            self.before_update(job_id)
        if job_id in self.fail_updates:
            raise CvatApiError("update denied", status_code=403)
        with self._lock:
            super().update_job(job_id, stage=stage, state=state)
            for task_id, jobs in self.jobs.items():
                self.jobs[task_id] = [
                    replace(job, stage=stage or job.stage, state=state or job.state)
                    if job.id == job_id
                    else job
                    for job in jobs
                ]


def _run(  # noqa: PLR0913
    api: PromotionApi,
    output: Path,
    *,
    completed_only: bool = False,
    ignore_task_ids: set[int] | None = None,
    silent_task_ids: set[int] | None = None,
    use_cache: bool = False,
    config_path: Path | None = None,
    images_dir: Path | None = None,
    publish_clearml: bool = False,
    save_tasks: bool = False,
    raw: bool = False,
) -> "PartitionResult":
    return fetch_project(
        client_with_api(api),
        FetchTarget(1, "promotion", output),
        FetchOptions(
            skip_validation=True,
            completed_only=completed_only,
            ignore_task_ids=ignore_task_ids,
            silent_task_ids=silent_task_ids,
            use_cache=use_cache,
            config_path=config_path,
            images_dir=images_dir,
            publish_clearml=publish_clearml,
            save_tasks=save_tasks,
            raw=raw,
        ),
    )


def _job(
    job_id: int,
    stage: str = "annotation",
    state: str = "completed",
    *,
    job_type: str = "annotation",
    frame: int = 0,
) -> RawJob:
    return RawJob(job_id, frame, frame, stage, state, job_type)


def test_accepts_finished_annotation_and_exports_fresh_completion(
    tmp_path: Path,
) -> None:
    api = PromotionApi({11: [RawJob(101, 0, 0, "annotation", "completed")]})
    partition = fetch_project(
        client_with_api(api),
        FetchTarget(1, "promotion", tmp_path),
        FetchOptions(skip_validation=True, use_cache=False, publish_clearml=False),
    )
    assert api.writes.job_updates == [(101, "acceptance", "completed")]
    assert set(partition.dataset["task_id"]) == {11}
    exported = pd.read_csv(tmp_path / "dataset.csv")
    assert set(exported["job_stage"]) == {"acceptance"}
    assert set(exported["job_state"]) == {"completed"}
    assert exported["task_completed"].all()


@pytest.mark.parametrize("completed_only", [False, True])
def test_promotes_all_eligible_jobs_and_retry_makes_no_redundant_updates(
    tmp_path: Path,
    *,
    completed_only: bool,
) -> None:
    api = PromotionApi(
        {
            11: [_job(101), _job(102)],
            12: [
                _job(201, "acceptance"),
                _job(202, job_type="ground_truth", frame=99),
                _job(203, job_type="replica", frame=100),
            ],
            13: [_job(301, "acceptance")],
        }
    )
    partition = _run(api, tmp_path, completed_only=completed_only)
    assert api.writes.job_updates == [
        (101, "acceptance", "completed"),
        (102, "acceptance", "completed"),
        (202, "acceptance", "completed"),
        (203, "acceptance", "completed"),
    ]
    assert set(partition.dataset["task_id"]) == {11, 12, 13}
    assert partition.in_progress.empty
    assert all(all(snapshot.values()) for snapshot in api.completion_at_annotations)
    assert set(partition.dataset["task_updated_date"]) == {"unchanged"}
    _run(api, tmp_path, completed_only=completed_only)
    assert api.update_attempts == [101, 102, 202, 203]


@pytest.mark.parametrize(
    "disallowed",
    [
        _job(102, state="new"),
        _job(102, state="in progress"),
        _job(102, state="rejected"),
        _job(102, "validation"),
        _job(102, "validation", "in progress"),
        _job(102, "acceptance", "rejected"),
        _job(102, "unknown"),
        _job(102, state="unknown"),
        _job(102, ""),
        _job(102, state=""),
        _job(102, job_type="ground_truth", state="new", frame=99),
        _job(102, job_type="replica", state="new", frame=100),
        _job(102, "validation", job_type="ground_truth", frame=101),
    ],
)
def test_one_disallowed_job_blocks_the_whole_task(
    tmp_path: Path,
    disallowed: RawJob,
) -> None:
    api = PromotionApi({11: [_job(101), disallowed]})
    partition = _run(api, tmp_path)
    assert api.update_attempts == []
    assert partition.dataset.empty
    assert set(partition.in_progress["task_id"]) == {11}


def test_zero_jobs_never_qualifies(tmp_path: Path) -> None:
    api = PromotionApi({11: []})
    partition = _run(api, tmp_path)
    assert api.update_attempts == []
    assert partition.dataset.empty


@pytest.mark.parametrize("silent", [False, True])
def test_ignored_tasks_are_never_inspected_for_promotion(
    tmp_path: Path,
    *,
    silent: bool,
) -> None:
    api = PromotionApi({11: [_job(101)], 12: [_job(201)]})
    api.fail_job_reads = {12}
    partition = _run(
        api, tmp_path, ignore_task_ids={12}, silent_task_ids={12} if silent else None
    )
    assert api.job_reads == [11, 11]
    assert api.update_attempts == [101]
    assert set(partition.dataset["task_id"]) == {11}


def test_option_default_preserves_normal_reads_and_leaves_jobs_unchanged(
    tmp_path: Path,
) -> None:
    api = PromotionApi({11: [_job(101)]})
    partition = fetch_project(
        client_with_api(api),
        FetchTarget(1, "promotion", tmp_path),
        FetchOptions(use_cache=False, publish_clearml=False),
    )
    assert api.update_attempts == []
    assert api.job_reads == [11]
    assert api.call_counts["get_project_tasks"] == 1
    assert partition.dataset.empty
    assert set(partition.in_progress["task_id"]) == {11}


def test_public_api_default_leaves_completed_annotation_jobs_unchanged(
    tmp_path: Path,
) -> None:
    api = PromotionApi({11: [_job(101)]})
    partition = cveta2.fetch(
        1,
        tmp_path,
        download_images=False,
        cache="off",
        publish_clearml=False,
        connection=cveta2.Connection(client=client_with_api(api)),
    )
    assert api.update_attempts == []
    assert api.job_reads == [11]
    assert partition.dataset.empty
    assert set(partition.in_progress["task_id"]) == {11}


class ConcurrentPromotionApi(PromotionApi):
    """Block first job reads in pairs to exercise the configured worker bound."""

    def __init__(self, jobs: dict[int, list[RawJob]]) -> None:
        """Arrange pairs of overlapping promotion reads."""
        super().__init__(jobs)
        self.first_reads: set[int] = set()
        self.active = 0
        self.max_active = 0
        self.pair = threading.Barrier(2)

    def get_task_jobs(self, task_id: int) -> list[RawJob]:
        with self._lock:
            first_read = task_id not in self.first_reads
            self.first_reads.add(task_id)
            if first_read:
                self.active += 1
                self.max_active = max(self.max_active, self.active)
        if first_read:
            try:
                self.pair.wait(timeout=3)
            finally:
                with self._lock:
                    self.active -= 1
        return super().get_task_jobs(task_id)


def test_worker_bound_and_barrier_precede_completed_only_and_annotations(
    tmp_path: Path,
) -> None:
    api = ConcurrentPromotionApi(
        {task_id: [_job(task_id * 10)] for task_id in [11, 12, 13, 14]}
    )
    configure_workers(s3=1, cvat=2)
    partition = _run(api, tmp_path, completed_only=True)
    assert api.max_active == 2
    assert set(partition.dataset["task_id"]) == {11, 12, 13, 14}
    assert len(api.completion_at_annotations) == 4
    assert all(all(snapshot.values()) for snapshot in api.completion_at_annotations)


def test_concurrent_failure_waits_for_in_flight_promotion_and_never_fetches(
    tmp_path: Path,
) -> None:
    api = PromotionApi({11: [_job(101)], 12: [_job(201)]})
    api.fail_updates = {101}
    second_started = threading.Event()
    first_failed = threading.Event()

    def before_update(job_id: int) -> None:
        if job_id == 101:
            assert second_started.wait(timeout=3)
            first_failed.set()
        else:
            second_started.set()
            assert first_failed.wait(timeout=3)

    api.before_update = before_update
    configure_workers(s3=1, cvat=2)
    with pytest.raises(Cveta2Error) as caught:
        _run(api, tmp_path)
    assert "11" in str(caught.value)
    assert "101" in str(caught.value)
    assert api.writes.job_updates == [(201, "acceptance", "completed")]
    assert api.annotation_calls == []
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("failure", ["project-list", "job-list"])
def test_promotion_read_failure_aborts_with_context_before_annotations(
    tmp_path: Path,
    failure: str,
) -> None:
    api = PromotionApi({11: [_job(101)]})
    api.fail_project_reads = failure == "project-list"
    api.fail_job_reads = {11} if failure == "job-list" else set()
    with pytest.raises(Cveta2Error) as caught:
        _run(api, tmp_path)
    message = str(caught.value)
    assert "promotion" in message or "1" in message
    if failure == "job-list":
        assert "11" in message
    assert api.annotation_calls == []
    assert api.update_attempts == []
    assert list(tmp_path.iterdir()) == []


def test_partial_update_failure_preserves_changes_aborts_outputs_and_can_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = PromotionApi({11: [_job(101), _job(102)]})
    api.fail_updates = {102}
    output = tmp_path / "output"
    output.mkdir()
    previous = output / "dataset.csv"
    previous.write_text("previous export", encoding="utf-8")

    def forbidden(*_args: object, **_kwargs: object) -> None:
        pytest.fail("failed promotion must not download or publish")

    monkeypatch.setattr(
        "cveta2.composition.client.CvatClient.download_images", forbidden
    )
    monkeypatch.setattr(
        "cveta2.composition.publishing.maybe_publish_clearml", forbidden
    )
    with pytest.raises(Cveta2Error) as caught:
        _run(
            api,
            output,
            images_dir=tmp_path / "images",
            publish_clearml=True,
            save_tasks=True,
            raw=True,
        )
    assert "11" in str(caught.value)
    assert "102" in str(caught.value)
    assert api.writes.job_updates == [(101, "acceptance", "completed")]
    assert api.annotation_calls == []
    assert previous.read_text(encoding="utf-8") == "previous export"
    assert [path.name for path in output.iterdir()] == ["dataset.csv"]
    assert not (tmp_path / "images").exists()
    api.fail_updates.clear()
    partition = _run(api, output)
    assert api.update_attempts == [101, 102, 102]
    assert set(partition.dataset["task_id"]) == {11}


def _seed_stale_cache(
    api: PromotionApi, root: Path, s3: FakeS3Client | None = None
) -> tuple[Path, str]:
    cache_dir = get_task_cache_dir(1, root=root)
    backend = (
        S3CacheBackend(s3, "cache-bucket", "custom-cache", explicit_location=True)
        if s3 is not None
        else None
    )
    cache = TaskAnnotationCache(cache_dir, s3=backend)
    task = api.get_project_tasks(1)[0].model_copy(update={"status": "completed"})
    stale = TaskAnnotations(
        task_id=11,
        task_name="task-11",
        deleted_images=[],
        annotations=[
            ImageWithoutAnnotations(
                image_name="stale.jpg",
                image_width=10,
                image_height=10,
                task_id=11,
                task_name="task-11",
                frame_id=0,
                job_stage="annotation",
                job_state="completed",
                task_completed=False,
                task_updated_date="unchanged",
            )
        ],
    )
    cache.put(task, stale)
    return (
        cache_dir / "task_11.json",
        "cache-bucket/custom-cache/task_annotations/task_11.json",
    )


def _custom_config(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "configured-tasks"
    config = write_config_yaml(
        tmp_path / "fetch-config.yaml",
        cache={
            "tasks_root": str(tmp_path / "global-tasks"),
            "projects": {
                "promotion": {
                    "tasks_root": str(root),
                    "task_cache_s3": "s3://cache-bucket/custom-cache",
                }
            },
        },
    )
    return config, root


def test_promotion_invalidates_custom_local_and_s3_caches_before_first_patch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CVETA2_DISABLE_CACHE", "false")
    api = PromotionApi({11: [_job(101), _job(102)]})
    config, root = _custom_config(tmp_path)
    s3 = FakeS3Client()
    stale_path, stale_key = _seed_stale_cache(api, root, s3)
    unrelated = root / "project_1" / "task_999.json"
    unrelated.write_text("other task", encoding="utf-8")
    s3.objects["other-bucket/other-key"] = b"unrelated"
    monkeypatch.setattr(
        "cveta2.adapters.s3.task_cache.make_s3_client", lambda _endpoint: s3
    )

    def before_update(_job_id: int) -> None:
        assert not stale_path.exists()
        assert stale_key not in s3.objects
        assert unrelated.read_text(encoding="utf-8") == "other task"
        assert s3.objects["other-bucket/other-key"] == b"unrelated"

    api.before_update = before_update
    partition = _run(api, tmp_path / "output", use_cache=True, config_path=config)
    assert s3.delete_calls == [stale_key]
    assert api.annotation_calls == [11]
    assert set(partition.dataset["image_name"]) == {"11.jpg"}
    assert set(partition.dataset["job_stage"]) == {"acceptance"}
    assert partition.dataset["task_completed"].all()
    assert b"stale.jpg" not in stale_path.read_bytes()


@pytest.mark.parametrize("disabled_by", ["option", "environment"])
def test_disabled_cache_still_invalidates_local_without_contacting_s3(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    disabled_by: str,
) -> None:
    monkeypatch.setenv(
        "CVETA2_DISABLE_CACHE", "true" if disabled_by == "environment" else "false"
    )
    api = PromotionApi({11: [_job(101)]})
    config, root = _custom_config(tmp_path)
    stale_path, _key = _seed_stale_cache(api, root)

    def forbidden(*_args: object, **_kwargs: object) -> None:
        pytest.fail("cache-disabled promotion must not contact S3")

    monkeypatch.setattr("cveta2.adapters.s3.task_cache.make_s3_client", forbidden)
    monkeypatch.setattr(
        "cveta2.composition.client.CvatClient.detect_project_cloud_storage", forbidden
    )

    def before_update(_job_id: int) -> None:
        assert not stale_path.exists()

    api.before_update = before_update
    partition = _run(
        api, tmp_path / "output", config_path=config, use_cache=disabled_by != "option"
    )
    assert not stale_path.exists()
    assert set(partition.dataset["image_name"]) == {"11.jpg"}


def test_partial_mutation_failure_leaves_both_cache_layers_invalidated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CVETA2_DISABLE_CACHE", "false")
    api = PromotionApi({11: [_job(101), _job(102)]})
    api.fail_updates = {102}
    config, root = _custom_config(tmp_path)
    s3 = FakeS3Client()
    stale_path, stale_key = _seed_stale_cache(api, root, s3)
    monkeypatch.setattr(
        "cveta2.adapters.s3.task_cache.make_s3_client", lambda _endpoint: s3
    )
    with pytest.raises(Cveta2Error):
        _run(api, tmp_path / "output", use_cache=True, config_path=config)
    assert not stale_path.exists()
    assert stale_key not in s3.objects
    assert s3.delete_calls == [stale_key]
    assert api.annotation_calls == []
    api.fail_updates.clear()
    partition = _run(api, tmp_path / "output", use_cache=True, config_path=config)
    assert api.update_attempts == [101, 102, 102]
    assert set(partition.dataset["image_name"]) == {"11.jpg"}


class FailingDeleteS3(FakeS3Client):
    def delete_object(self, *, Bucket: str, Key: str) -> None:  # noqa: N803
        self.delete_calls.append(self._store_key(Bucket, Key))
        raise ClientError({"Error": {"Code": "AccessDenied"}}, "DeleteObject")


@pytest.mark.parametrize("layer", ["local", "s3"])
def test_invalidation_failure_aborts_before_task_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    layer: str,
) -> None:
    monkeypatch.setenv("CVETA2_DISABLE_CACHE", "false")
    api = PromotionApi({11: [_job(101)]})
    config, root = _custom_config(tmp_path)
    s3 = FailingDeleteS3() if layer == "s3" else FakeS3Client()
    stale_path, _key = _seed_stale_cache(api, root, s3)
    monkeypatch.setattr(
        "cveta2.adapters.s3.task_cache.make_s3_client", lambda _endpoint: s3
    )
    if layer == "local":
        original_unlink = Path.unlink

        def deny_stale_unlink(path: Path, *, missing_ok: bool = False) -> None:
            if path == stale_path:
                raise PermissionError("cache deletion denied")
            original_unlink(path, missing_ok=missing_ok)

        monkeypatch.setattr(Path, "unlink", deny_stale_unlink)
    with pytest.raises(Cveta2Error) as caught:
        _run(api, tmp_path / "output", use_cache=True, config_path=config)
    assert "11" in str(caught.value)
    assert api.update_attempts == []
    assert api.annotation_calls == []
    assert not (tmp_path / "output").exists()
