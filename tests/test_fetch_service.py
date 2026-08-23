"""Canonical fetch-service/client scenarios over FakeCvatApi + CvatClient.

Owns the coco8 fixture scenarios (normal, all-empty, all-removed,
frames-1-2-removed, zero-frame-empty-last-removed) exercised end-to-end
through the fetch service and :class:`CvatClient`.
"""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

import pandas as pd
import pytest

from cveta2._concurrency import configure_workers
from cveta2.client import CvatClient
from cveta2.config import CvatConfig
from cveta2.dataset_partition import PartitionResult, partition_annotations_df
from cveta2.exceptions import CvatApiError
from cveta2.models import (
    CSV_COLUMNS,
    BBoxAnnotation,
    DeletedImage,
    ProjectAnnotations,
    ProjectInfo,
    TaskAnnotations,
    TaskInfo,
)
from cveta2.services import fetch as fetch_service
from cveta2.services.fetch import (
    FetchOptions,
    FetchTarget,
    _CachePolicy,
    _FetchStats,
    _retrieve_task,
    fetch_project,
)
from cveta2.task_cache import TaskAnnotationCache
from tests.fixtures.fake_cvat_api import FakeCvatApi
from tests.fixtures.fake_s3 import FakeS3Client
from tests.helpers import (
    build_fake,
    fetch_all_annotations,
    make_cs_info,
    make_fake_client,
    split_records,
    write_config_yaml,
)

if TYPE_CHECKING:
    from pathlib import Path

    from cveta2._client.dtos import RawAnnotations, RawDataMeta
    from cveta2.client import FetchContext
    from cveta2.image_downloader import CloudStorageInfo
    from tests.fixtures.fake_cvat_project import LoadedFixtures

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_IMAGE_NAMES = [
    "000000000009.jpg",
    "000000000025.jpg",
    "000000000030.jpg",
    "000000000034.jpg",
    "000000000036.jpg",
    "000000000042.jpg",
    "000000000049.jpg",
    "000000000061.jpg",
]


def _with_dates(
    fixtures: LoadedFixtures,
    dates: dict[int, str],
) -> LoadedFixtures:
    """Return fixtures with updated_date overrides by task position."""
    new_tasks = [
        task.model_copy(update={"updated_date": dates[i]}) if i in dates else task
        for i, task in enumerate(fixtures.tasks)
    ]
    new_data: dict[int, tuple[RawDataMeta, RawAnnotations]] = {
        t.id: fixtures.task_data[fixtures.tasks[i].id] for i, t in enumerate(new_tasks)
    }
    return fixtures._replace(tasks=new_tasks, task_data=new_data)


def _fetch_and_partition(
    fake: LoadedFixtures,
) -> tuple[ProjectAnnotations, PartitionResult]:
    """Fetch annotations and partition them."""
    result = fetch_all_annotations(make_fake_client(fake), fake.project.id)
    rows = result.to_csv_rows()
    df = pd.DataFrame(rows)
    partition = partition_annotations_df(df, result.deleted_images)
    return result, partition


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_normal_project_annotations(normal_fake: LoadedFixtures) -> None:
    """Normal task produces the expected number of annotations."""
    fake = normal_fake
    result = fetch_all_annotations(make_fake_client(fake), fake.project.id)

    bbox_records, without_records = split_records(result)
    assert len(bbox_records) == 30
    assert len(result.deleted_images) == 0
    annotated_frames = {a.frame_id for a in bbox_records}
    without_frames = {w.frame_id for w in without_records}
    assert annotated_frames | without_frames == set(range(8))


def test_all_empty_images_without_annotations(
    coco8_fixtures: LoadedFixtures,
) -> None:
    """all-empty task: no annotations, all frames without."""
    fake = build_fake(coco8_fixtures, ["all-empty"], statuses=["completed"])
    result = fetch_all_annotations(make_fake_client(fake), fake.project.id)

    _, without_records = split_records(result)
    assert len(result.annotations) == 8
    assert len(result.deleted_images) == 0
    assert len(without_records) == 8
    without_names = {w.image_name for w in without_records}
    assert without_names == set(_IMAGE_NAMES)


def test_all_removed_only_deleted(coco8_fixtures: LoadedFixtures) -> None:
    """all-removed task: all 8 frames in deleted_images."""
    fake = build_fake(coco8_fixtures, ["all-removed"], statuses=["completed"])
    result = fetch_all_annotations(make_fake_client(fake), fake.project.id)

    assert len(result.deleted_images) == 8
    assert {d.image_name for d in result.deleted_images} == set(_IMAGE_NAMES)
    # Shapes exist but reference deleted frames -- still extracted
    bbox_records, without_records = split_records(result)
    assert len(bbox_records) == 30
    assert len(without_records) == 0


def test_frames_1_2_removed(coco8_fixtures: LoadedFixtures) -> None:
    """frames-1-2-removed: frames 1,2 deleted; others have annotations or not."""
    fake = build_fake(coco8_fixtures, ["frames-1-2-removed"], statuses=["completed"])
    result = fetch_all_annotations(make_fake_client(fake), fake.project.id)

    deleted_frame_ids = {d.frame_id for d in result.deleted_images}
    assert deleted_frame_ids == {1, 2}

    bbox_records, without_records = split_records(result)
    annotated_frames = {a.frame_id for a in bbox_records}
    without_frames = {w.frame_id for w in without_records}
    # Together they cover all 8 frames
    assert (annotated_frames | without_frames | deleted_frame_ids) == set(range(8))
    # without_annotations has no overlap with deleted or annotated
    assert without_frames.isdisjoint(deleted_frame_ids | annotated_frames)


def test_zero_frame_empty_last_removed(
    coco8_fixtures: LoadedFixtures,
) -> None:
    """zero-frame-empty-last-removed: frame 0 unannotated, frame 7 deleted."""
    fake = build_fake(
        coco8_fixtures,
        ["zero-frame-empty-last-removed"],
        statuses=["completed"],
    )
    result = fetch_all_annotations(make_fake_client(fake), fake.project.id)

    assert result.deleted_images[0].frame_id == 7
    bbox_records, without_records = split_records(result)
    without_frame_ids = {w.frame_id for w in without_records}
    assert 0 in without_frame_ids
    assert 0 not in {a.frame_id for a in bbox_records}
    assert len(bbox_records) == 17


def test_mixed_tasks_aggregation(coco8_fixtures: LoadedFixtures) -> None:
    """Three tasks aggregated: normal + all-empty + all-removed."""
    fake = build_fake(
        coco8_fixtures,
        ["normal", "all-empty", "all-removed"],
        statuses=["completed", "completed", "completed"],
    )
    result = fetch_all_annotations(make_fake_client(fake), fake.project.id)

    bbox_records, without_records = split_records(result)
    assert len(bbox_records) == 60  # 30 + 0 + 30
    assert len(result.deleted_images) == 8  # only from all-removed
    assert len(without_records) == 8  # only from all-empty


def test_completed_only_filter(coco8_fixtures: LoadedFixtures) -> None:
    """completed_only=True skips non-completed tasks."""
    fake = build_fake(
        coco8_fixtures,
        ["normal", "all-empty"],
        statuses=["completed", "annotation"],
    )
    result = fetch_all_annotations(
        make_fake_client(fake), fake.project.id, completed_only=True
    )

    # Only the "normal" (completed) task processed; "all-empty" skipped entirely
    bbox_records, without_records = split_records(result)
    assert len(bbox_records) == 30
    # All 8 frames accounted for across annotations + without_annotations
    annotated_frames = {a.frame_id for a in bbox_records}
    without_frames = {w.frame_id for w in without_records}
    assert annotated_frames | without_frames == set(range(8))


def test_csv_rows_structure(normal_fake: LoadedFixtures) -> None:
    """to_csv_rows() output has all CSV_COLUMNS keys."""
    fake = normal_fake
    result = fetch_all_annotations(make_fake_client(fake), fake.project.id)

    rows = result.to_csv_rows()
    assert len(rows) > 0

    expected_keys = set(CSV_COLUMNS)
    for row in rows:
        assert set(row.keys()) == expected_keys
        assert isinstance(row["attributes"], str)


def test_fetch_to_partition_restore_and_three_way(
    coco8_fixtures: LoadedFixtures,
) -> None:
    """Fetch feeds partition: restore wins, non-completed -> in_progress.

    Combines three pipeline behaviours end-to-end:
    - a frame deleted in an older completed task but re-annotated in a
      newer completed task is NOT reported deleted (restore wins);
    - a non-completed task fetched alongside produces ``in_progress`` rows;
    - an externally-injected deletion newer than every task wins, sending
      its images to ``deleted``/``obsolete``.
    """
    fake = build_fake(
        coco8_fixtures,
        ["all-removed", "normal", "all-empty"],
        statuses=["completed", "completed", "annotation"],
    )
    fake = _with_dates(
        fake,
        {
            0: "2026-01-01T00:00:00+00:00",
            1: "2026-02-01T00:00:00+00:00",
            2: "2026-01-15T00:00:00+00:00",
        },
    )

    result = fetch_all_annotations(make_fake_client(fake), fake.project.id)
    df = pd.DataFrame(result.to_csv_rows())

    external_delete = DeletedImage(
        task_id=999,
        task_name="external-delete",
        task_updated_date="2026-03-01T00:00:00+00:00",
        frame_id=0,
        image_name=_IMAGE_NAMES[0],
    )
    all_deleted = [*result.deleted_images, external_delete]
    partition = partition_annotations_df(df, all_deleted)

    # Only the external deletion survives; the older all-removed deletions
    # are overridden by the newer normal re-annotation (restore wins).
    assert [d.image_name for d in partition.deleted_images] == [_IMAGE_NAMES[0]]
    assert _IMAGE_NAMES[0] in set(partition.obsolete["image_name"])

    # The non-completed all-empty task contributes in_progress rows.
    assert len(partition.in_progress) > 0
    assert fake.tasks[2].id in set(partition.in_progress["task_id"].unique())

    # The completed normal task feeds the dataset for its non-deleted frames.
    assert len(partition.dataset) > 0
    assert fake.tasks[1].id in set(partition.dataset["task_id"].unique())


def test_5xx_task_skipped(coco8_fixtures: LoadedFixtures) -> None:
    """When one task returns 5xx, that task is skipped and others are processed."""
    fake = build_fake(
        coco8_fixtures,
        ["normal", "all-empty"],
        statuses=["completed", "completed"],
    )
    failing_task_id = fake.tasks[1].id
    api = FakeCvatApi(fake, fail_task_ids={failing_task_id})
    client = CvatClient(CvatConfig(), api=api)

    result = fetch_all_annotations(
        client,
        fake.project.id,
        project_name="test-project",
    )

    # Only first task (normal) data; second task (all-empty) was skipped due to 5xx
    bbox_records = [a for a in result.annotations if isinstance(a, BBoxAnnotation)]
    task_ids = {a.task_id for a in result.annotations}
    assert len(bbox_records) == 30
    assert task_ids == {fake.tasks[0].id}
    assert failing_task_id not in task_ids


def test_a_task_whose_jobs_cannot_be_read_is_skipped(
    coco8_fixtures: LoadedFixtures,
) -> None:
    """The jobs request is load-bearing, so its 5xx skips the task.

    Unlike issues, ``job_stage``/``job_state`` decide which side of the
    partition every row lands on.  Emitting the task without them would
    quietly move a finished task into ``in_progress``, so the task is
    dropped with the same warning a 5xx on the frame metadata produces.
    """
    fake = build_fake(
        coco8_fixtures,
        ["normal", "all-empty"],
        statuses=["completed", "completed"],
    )
    failing_task_id = fake.tasks[1].id
    api = FakeCvatApi(
        fake,
        fail_task_ids={failing_task_id},
        fail_methods=("get_task_jobs",),
    )
    client = CvatClient(CvatConfig(), api=api)

    result = fetch_all_annotations(
        client,
        fake.project.id,
        project_name="test-project",
    )

    assert {a.task_id for a in result.annotations} == {fake.tasks[0].id}


def test_job_position_reaches_every_record(normal_fake: LoadedFixtures) -> None:
    """Each record carries the stage/state of the job that owns its frame."""
    client = CvatClient(CvatConfig(), api=FakeCvatApi(normal_fake))

    result = fetch_all_annotations(
        client,
        normal_fake.project.id,
        project_name="test-project",
    )

    assert result.annotations
    assert {(a.job_stage, a.job_state) for a in result.annotations} == {
        ("acceptance", "completed")
    }


def test_4xx_error_propagated(normal_fake: LoadedFixtures) -> None:
    """Non-5xx CvatApiError (e.g. 404) is re-raised, not swallowed."""
    fake = normal_fake

    api = FakeCvatApi(fake, fail_task_ids={fake.tasks[0].id}, fail_status=404)
    client = CvatClient(CvatConfig(), api=api)

    with pytest.raises(CvatApiError) as exc_info:
        fetch_all_annotations(client, fake.project.id)
    assert exc_info.value.status_code == 404


def test_5xx_raise_on_failure(
    coco8_fixtures: LoadedFixtures,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When CVETA2_RAISE_ON_FAILURE=true, 5xx is re-raised immediately."""
    fake = build_fake(
        coco8_fixtures,
        ["normal", "all-empty"],
        statuses=["completed", "completed"],
    )
    failing_task_id = fake.tasks[1].id
    api = FakeCvatApi(fake, fail_task_ids={failing_task_id})
    client = CvatClient(CvatConfig(), api=api)

    monkeypatch.setenv("CVETA2_RAISE_ON_FAILURE", "true")
    with pytest.raises(CvatApiError) as exc_info:
        fetch_all_annotations(client, fake.project.id)
    assert exc_info.value.status_code == 500


# ---------------------------------------------------------------------------
# resolve_project_id
# ---------------------------------------------------------------------------


def test_resolve_project_id_digit_string(normal_fake: LoadedFixtures) -> None:
    """Digit-string input returns the integer directly."""
    client = make_fake_client(normal_fake)
    assert client.resolve_project_id("42") == 42


def test_resolve_project_id_casefold_name(normal_fake: LoadedFixtures) -> None:
    """Name matching is case-insensitive."""
    fake = normal_fake
    client = make_fake_client(fake)
    name = fake.project.name
    # Use uppercased name — should still resolve
    result = client.resolve_project_id(name.upper(), cached=[fake.project])
    assert result == fake.project.id


def test_resolve_project_id_not_found(normal_fake: LoadedFixtures) -> None:
    """Non-existent project name raises ProjectNotFoundError naming the spec.

    The message is the only place the rejected spec appears; replacing it
    wholesale left the raise indistinguishable from a bare one.
    """
    from cveta2.exceptions import ProjectNotFoundError

    client = make_fake_client(normal_fake)

    with pytest.raises(ProjectNotFoundError, match="does-not-exist"):
        client.resolve_project_id("does-not-exist")


def test_resolve_project_id_cached_wins_over_the_api() -> None:
    """Cached list and API deliberately disagree about the same name.

    Every other cached test names a project that both sources resolve to
    the same id, so deleting the cached lookup entirely -- or never
    matching in it -- produced the same answer via the API round-trip.
    """
    api = FakeCvatApi.from_tasks([], project_name="shared")
    client = CvatClient(CvatConfig(), api=api)

    resolved = client.resolve_project_id(
        "shared",
        cached=[ProjectInfo(id=99, name="shared")],
    )

    assert resolved == 99


def test_resolve_project_id_picks_the_named_project_from_the_api() -> None:
    """A second, differently named project makes the name match load-bearing."""
    api = FakeCvatApi.from_tasks(
        [],
        project_name="first",
        other_projects=[ProjectInfo(id=42, name="second")],
    )

    assert CvatClient(CvatConfig(), api=api).resolve_project_id("second") == 42


def test_count_images_unique_and_empty() -> None:
    """count_images counts unique image names; empty/columnless frames give 0."""
    from cveta2.services.output import count_images

    df = pd.DataFrame(
        {"image_name": ["a.jpg", "a.jpg", "b.jpg"], "instance_label": ["x", "y", "x"]}
    )
    assert count_images(df) == 2
    assert count_images(pd.DataFrame()) == 0
    assert count_images(pd.DataFrame({"other": [1]})) == 0


def test_raw_csv_includes_deleted_images(
    coco8_fixtures: LoadedFixtures,
    tmp_path: Path,
) -> None:
    """--raw produces raw.csv containing both annotation and deletion rows."""
    fake = build_fake(
        coco8_fixtures,
        ["normal", "all-removed"],
        statuses=["completed", "completed"],
    )
    result = fetch_all_annotations(make_fake_client(fake), fake.project.id)

    from cveta2.services.output import write_raw_csv

    write_raw_csv(result, tmp_path / "out")

    raw_csv = tmp_path / "out" / "raw.csv"
    assert raw_csv.exists()

    raw_df = pd.read_csv(raw_csv)
    shapes = set(raw_df["instance_shape"].dropna().unique())
    assert "deleted" in shapes, "raw.csv must include deletion rows"
    assert "box" in shapes, "raw.csv must include annotation rows"

    # Total rows = annotations + deleted
    annotation_rows = result.to_csv_rows()
    expected_total = len(annotation_rows) + len(result.deleted_images)
    assert len(raw_df) == expected_total


def test_task_to_records_unknown_deleted_frame_id() -> None:
    """Deleted frame_id not in frames produces '<unknown>' image_name."""
    from cveta2._client.assembly import task_to_records
    from cveta2._client.dtos import RawAnnotations, RawDataMeta, RawFrame

    task = TaskInfo(
        id=99,
        name="test",
        status="completed",
        subset="",
        updated_date="2026-01-01T00:00:00",
    )
    data_meta = RawDataMeta(
        frames=[RawFrame(name="a.jpg", width=640, height=480)],
        deleted_frames=[999],  # frame 999 doesn't exist
    )
    annotations = RawAnnotations(shapes=[])

    _records, deleted = task_to_records(task, data_meta, annotations, {}, {})

    assert len(deleted) == 1
    assert deleted[0].image_name == "<unknown>"
    assert deleted[0].frame_id == 999


# ---------------------------------------------------------------------------
# _retrieve_task: the per-task cache-hit vs live-fetch accounting
# ---------------------------------------------------------------------------


class _ScriptedClock:
    """``time`` stand-in handing out a fixed sequence of monotonic readings.

    The accounting below is arithmetic on wall-clock deltas, so a real clock
    can only support "roughly zero" assertions — under which ``+=`` and ``=``
    are indistinguishable and a sign flip hides in the noise. Scripting the
    readings makes every field exactly predictable.
    """

    def __init__(self, readings: list[float]) -> None:
        self._readings = iter(readings)

    def monotonic(self) -> float:
        return next(self._readings)


def _fetch_context(client: CvatClient, fake: LoadedFixtures) -> FetchContext:
    return client.prepare_fetch(fake.project.id, project_name=fake.project.name)


def _fetched(client: CvatClient, task: TaskInfo, ctx: FetchContext) -> TaskAnnotations:
    """Fetch one task, failing the test rather than the type checker on a skip."""
    result = client.fetch_one_task(client.api, task, ctx)
    assert result is not None
    return result


class TestRetrieveTaskAccounting:
    """``_FetchStats`` is what tells the user how much of a fetch was cached."""

    def test_cache_hits_and_their_elapsed_time_accumulate(
        self,
        normal_fake: LoadedFixtures,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Two hits report two hits and the *sum* of their durations."""
        fake = normal_fake
        client = CvatClient(CvatConfig(), api=FakeCvatApi(fake))
        ctx = _fetch_context(client, fake)
        task = ctx.tasks[0]

        cache = TaskAnnotationCache(tmp_path / "cache")
        cache.put(task, _fetched(client, task, ctx))
        policy = _CachePolicy(cache=cache)
        stats = _FetchStats()

        monkeypatch.setattr(
            fetch_service, "time", _ScriptedClock([100.0, 101.5, 200.0, 203.0])
        )
        assert _retrieve_task(client, task, ctx, policy, stats) is not None
        assert _retrieve_task(client, task, ctx, policy, stats) is not None

        assert stats.cache_hits == 2
        assert stats.hit_seconds == pytest.approx(4.5)
        assert stats.fetched == 0
        assert stats.fetch_seconds == 0.0

    def test_live_fetches_and_their_elapsed_time_accumulate(
        self,
        normal_fake: LoadedFixtures,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Without a cache every task is a live fetch, counted the same way."""
        fake = normal_fake
        client = CvatClient(CvatConfig(), api=FakeCvatApi(fake))
        ctx = _fetch_context(client, fake)
        task = ctx.tasks[0]
        policy = _CachePolicy()
        stats = _FetchStats()

        monkeypatch.setattr(
            fetch_service, "time", _ScriptedClock([10.0, 12.0, 30.0, 34.0])
        )
        assert _retrieve_task(client, task, ctx, policy, stats) is not None
        assert _retrieve_task(client, task, ctx, policy, stats) is not None

        assert stats.fetched == 2
        assert stats.fetch_seconds == pytest.approx(6.0)
        assert stats.cache_hits == 0
        assert stats.hit_seconds == 0.0

    def test_a_skipped_task_is_counted_as_neither(
        self, normal_fake: LoadedFixtures
    ) -> None:
        """A 5xx skip must not inflate the fetched count or its timer."""
        fake = normal_fake
        api = FakeCvatApi(fake, fail_task_ids={fake.tasks[0].id})
        client = CvatClient(CvatConfig(), api=api)
        ctx = _fetch_context(client, fake)
        stats = _FetchStats()

        assert _retrieve_task(client, ctx.tasks[0], ctx, _CachePolicy(), stats) is None

        assert (stats.fetched, stats.fetch_seconds) == (0, 0.0)
        assert (stats.cache_hits, stats.hit_seconds) == (0, 0.0)

    def test_force_bypasses_a_populated_cache(
        self, normal_fake: LoadedFixtures, tmp_path: Path
    ) -> None:
        """``--force`` must re-fetch even when the entry is valid."""
        fake = normal_fake
        client = CvatClient(CvatConfig(), api=FakeCvatApi(fake))
        ctx = _fetch_context(client, fake)
        task = ctx.tasks[0]
        cache = TaskAnnotationCache(tmp_path / "cache")
        cache.put(task, _fetched(client, task, ctx))
        stats = _FetchStats()

        _retrieve_task(client, task, ctx, _CachePolicy(cache=cache, force=True), stats)

        assert (stats.cache_hits, stats.fetched) == (0, 1)


# ---------------------------------------------------------------------------
# _fetch_and_save_tasks: the per-task CSV directory and the skip path
# ---------------------------------------------------------------------------


def _fetch_project(
    api: FakeCvatApi,
    fake: LoadedFixtures,
    output_dir: Path,
    options: FetchOptions,
) -> PartitionResult:
    return fetch_project(
        CvatClient(CvatConfig(), api=api),
        FetchTarget(fake.project.id, fake.project.name, output_dir, None),
        options,
    )


class TestTaskCsvDirectory:
    def test_a_leftover_tasks_directory_is_reused(
        self, normal_fake: LoadedFixtures, tmp_path: Path
    ) -> None:
        """Re-running into the same output directory must not fail.

        A killed run leaves ``.tasks/`` behind, and ``--save-tasks`` leaves it
        behind on purpose, so the second run always finds it there.
        """
        fake = normal_fake
        out = tmp_path / "out"
        (out / ".tasks").mkdir(parents=True)

        partition = _fetch_project(
            FakeCvatApi(fake), fake, out, FetchOptions(publish_clearml=False)
        )

        assert len(partition.dataset) > 0

    def test_a_cleanup_failure_does_not_fail_the_fetch(
        self,
        normal_fake: LoadedFixtures,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Removing ``.tasks/`` is best effort — the annotations are the point.

        The stand-in mirrors ``shutil.rmtree``'s own contract (``ignore_errors``
        swallows the failure, its absence re-raises), so the assertion is that
        the call site passes it — reached through the real call, not by
        inspecting arguments. A shared output directory owned by another user
        is the case that provokes this for real.
        """
        removals: list[Path] = []

        def rmtree(path: Path, *, ignore_errors: bool = False) -> None:
            removals.append(path)
            if not ignore_errors:
                raise PermissionError(path)

        monkeypatch.setattr(shutil, "rmtree", rmtree)
        fake = normal_fake
        out = tmp_path / "out"

        partition = _fetch_project(
            FakeCvatApi(fake), fake, out, FetchOptions(publish_clearml=False)
        )

        assert removals == [out / ".tasks"]
        assert len(partition.dataset) > 0

    def test_a_skipped_task_does_not_end_the_loop(
        self, coco8_fixtures: LoadedFixtures, tmp_path: Path
    ) -> None:
        """A 5xx on the *first* task must not discard every task after it.

        Every existing skip scenario failed the last task, where abandoning
        the loop and continuing it produce the same output.
        """
        fake = build_fake(
            coco8_fixtures,
            ["all-empty", "normal"],
            statuses=["completed", "completed"],
        )
        api = FakeCvatApi(fake, fail_task_ids={fake.tasks[0].id})

        partition = _fetch_project(
            api, fake, tmp_path / "out", FetchOptions(publish_clearml=False)
        )

        assert set(partition.dataset["task_id"].unique()) == {fake.tasks[1].id}

    def test_the_saved_per_task_csv_holds_that_task_s_rows(
        self, normal_fake: LoadedFixtures, tmp_path: Path
    ) -> None:
        """``--save-tasks`` writes real rows in the canonical column order.

        Existing tests only asserted the file exists, which an empty frame or
        an extra index column satisfies just as well.
        """
        fake = normal_fake
        out = tmp_path / "out"

        _fetch_project(
            FakeCvatApi(fake),
            fake,
            out,
            FetchOptions(save_tasks=True, publish_clearml=False),
        )

        task_df = pd.read_csv(out / ".tasks" / f"task_{fake.tasks[0].id}.csv")
        assert list(task_df.columns) == list(CSV_COLUMNS)
        assert set(task_df["task_id"].unique()) == {fake.tasks[0].id}
        assert len(task_df) == len(pd.read_csv(out / "dataset.csv"))


# ---------------------------------------------------------------------------
# _fetch_core: what it forwards to the downloader and to the path population
# ---------------------------------------------------------------------------


class _FakeApiWithStorage(FakeCvatApi):
    """``FakeCvatApi`` whose project reports a cloud storage.

    The base fake answers ``None``, which makes the ``project_id`` fallback
    inside ``download_images`` unreachable from any service-level test.
    """

    def __init__(self, fake: LoadedFixtures, storage: CloudStorageInfo) -> None:
        super().__init__(fake)
        self._storage = storage

    def get_project_cloud_storage(self, _project_id: int) -> CloudStorageInfo | None:
        return self._storage


class TestFetchCoreImageForwarding:
    """Each argument decides *whether* or *where* images land on disk."""

    _STORAGE = make_cs_info(bucket="bkt", prefix="data/proj", endpoint_url="")

    def _bucket(self, monkeypatch: pytest.MonkeyPatch) -> None:
        objects = {f"data/proj/{name}": b"IMG" for name in _IMAGE_NAMES}
        s3 = FakeS3Client(objects, keyed_by_bucket=False)
        monkeypatch.setattr(
            "cveta2.image_downloader.make_s3_client", lambda _endpoint=None: s3
        )

    def test_the_given_storage_is_what_gets_downloaded_from(
        self,
        normal_fake: LoadedFixtures,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A caller-supplied storage must reach the downloader.

        The fixture project reports no storage of its own, so dropping the
        argument leaves the downloader with nothing and every image is
        counted as failed — a silent zero-download fetch.
        """
        self._bucket(monkeypatch)
        fake = normal_fake
        images = tmp_path / "images"

        fetch_project(
            CvatClient(CvatConfig(), api=FakeCvatApi(fake)),
            FetchTarget(
                fake.project.id, fake.project.name, tmp_path / "out", self._STORAGE
            ),
            FetchOptions(images_dir=images, publish_clearml=False),
        )

        assert (images / _IMAGE_NAMES[0]).read_bytes() == b"IMG"

    def test_without_a_storage_the_project_id_finds_one(
        self,
        normal_fake: LoadedFixtures,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """With no storage passed, the project id is the only way to get one."""
        self._bucket(monkeypatch)
        fake = normal_fake
        images = tmp_path / "images"

        fetch_project(
            CvatClient(CvatConfig(), api=_FakeApiWithStorage(fake, self._STORAGE)),
            FetchTarget(fake.project.id, fake.project.name, tmp_path / "out", None),
            FetchOptions(images_dir=images, publish_clearml=False),
        )

        assert (images / _IMAGE_NAMES[0]).read_bytes() == b"IMG"

    def test_the_configured_ignored_prefix_shapes_both_paths(
        self,
        normal_fake: LoadedFixtures,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``ignored_prefix`` reaches the download *and* the CSV path column.

        It strips less of the S3 key than the storage prefix, so the S3
        hierarchy below it survives locally.  Dropping it on either call
        flattens the tree — same file count, different paths, which no
        counter notices.  The two calls are asserted separately because
        each keeps its own copy of the argument.
        """
        self._bucket(monkeypatch)
        fake = normal_fake
        images = tmp_path / "images"
        config_path = write_config_yaml(
            tmp_path / "cfg.yaml",
            cache={"projects": {fake.project.name: {"ignored_prefix": "data"}}},
        )

        fetch_project(
            CvatClient(CvatConfig(), api=FakeCvatApi(fake)),
            FetchTarget(
                fake.project.id, fake.project.name, tmp_path / "out", self._STORAGE
            ),
            FetchOptions(
                images_dir=images,
                publish_clearml=False,
                config_path=config_path,
            ),
        )

        assert (images / "proj" / _IMAGE_NAMES[0]).read_bytes() == b"IMG"
        assert not (images / _IMAGE_NAMES[0]).exists()

        dataset = pd.read_csv(tmp_path / "out" / "dataset.csv")
        local_paths = set(dataset["image_path"].dropna())
        assert local_paths
        assert all("/images/proj/" in path for path in local_paths)


# ---------------------------------------------------------------------------
# concurrent task fetching
# ---------------------------------------------------------------------------


def test_concurrent_fetch_produces_the_same_dataset_as_a_serial_one(
    coco8_fixtures: LoadedFixtures, tmp_path: Path
) -> None:
    """Worker count is a throughput knob and must not touch the output.

    Per-task results are merged positionally, so a loop that appended in
    completion order would reorder rows for the same input — invisible
    until two tasks annotate the same image.
    """
    fake = build_fake(
        coco8_fixtures,
        ["normal", "all-empty", "all-bboxes-moved", "frames-1-2-removed"],
        statuses=["completed"] * 4,
    )
    options = FetchOptions(publish_clearml=False)

    configure_workers(s3=1, cvat=1)
    serial = _fetch_project(FakeCvatApi(fake), fake, tmp_path / "serial", options)

    configure_workers(s3=1, cvat=8)
    parallel = _fetch_project(FakeCvatApi(fake), fake, tmp_path / "parallel", options)

    assert parallel.dataset.equals(serial.dataset)
    assert len(serial.dataset) > 0


def test_every_task_is_fetched_exactly_once_under_concurrency(
    coco8_fixtures: LoadedFixtures, tmp_path: Path
) -> None:
    """Re-fetching a task would double its rows and its CVAT load."""
    fake = build_fake(
        coco8_fixtures,
        ["normal", "all-empty", "all-bboxes-moved", "frames-1-2-removed"],
        statuses=["completed"] * 4,
    )
    api = FakeCvatApi(fake)
    configure_workers(s3=1, cvat=8)

    _fetch_project(api, fake, tmp_path / "out", FetchOptions(publish_clearml=False))

    assert sorted(api.annotation_calls) == sorted(task.id for task in fake.tasks)


def test_a_failing_task_still_aborts_the_whole_fetch(
    coco8_fixtures: LoadedFixtures, tmp_path: Path
) -> None:
    """Concurrency must not turn a fatal error into a partial dataset."""
    fake = build_fake(
        coco8_fixtures,
        ["normal", "all-empty", "all-bboxes-moved", "frames-1-2-removed"],
        statuses=["completed"] * 4,
    )
    api = FakeCvatApi(fake, fail_task_ids={fake.tasks[0].id}, fail_status=403)
    configure_workers(s3=1, cvat=8)

    with pytest.raises(CvatApiError):
        _fetch_project(api, fake, tmp_path / "out", FetchOptions(publish_clearml=False))
