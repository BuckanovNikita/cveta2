"""Canonical fetch-service/client scenarios over FakeCvatApi + CvatClient.

Owns the coco8 fixture scenarios (normal, all-empty, all-removed,
frames-1-2-removed, zero-frame-empty-last-removed) exercised end-to-end
through the fetch service and :class:`CvatClient`.
"""

from __future__ import annotations

import shutil
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING
from unittest.mock import patch

import pandas as pd
import pytest

import cveta2
from cveta2.adapters.config.settings import CvatConfig
from cveta2.adapters.execution.concurrency import configure_workers
from cveta2.adapters.files.dataset import read_dataset_csv
from cveta2.adapters.s3.task_cache import TaskAnnotationCache
from cveta2.application.ports.dtos import (
    RawAnnotations,
    RawDataMeta,
    RawFrame,
    RawJob,
)
from cveta2.application.use_cases.fetch import (
    FetchDependencies,
    FetchOptions,
    FetchTarget,
    _CachePolicy,
    _FetchStats,
    _retrieve_task,
)
from cveta2.composition.client import CvatClient
from cveta2.composition.workflows import fetch_dependencies, fetch_project
from cveta2.domain.errors import CvatApiError
from cveta2.domain.models import (
    CSV_COLUMNS,
    BBoxAnnotation,
    DeletedImage,
    ProjectAnnotations,
    ProjectInfo,
    TaskAnnotations,
    TaskInfo,
)
from cveta2.domain.partition import (
    PartitionResult,
    completed_task_ids,
    partition_annotations_df,
)
from tests.fixtures.fake_cvat_api import FakeCvatApi
from tests.fixtures.fake_cvat_project import LoadedFixtures
from tests.fixtures.fake_s3 import FakeS3Client
from tests.helpers import (
    build_fake,
    fetch_all_annotations,
    make_cs_info,
    make_fake_client,
    make_raw_shape,
    make_task,
    split_records,
    write_split_config_yaml,
)

if TYPE_CHECKING:
    from cveta2.composition.client import FetchContext

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


@pytest.mark.parametrize(
    ("scenario", "expected"),
    [
        # (box count, annotated frames, frames without boxes, deleted frames)
        ("normal", (30, set(range(8)), set(), set())),
        ("all-empty", (0, set(), set(range(8)), set())),
        # Shapes on deleted frames are still extracted.
        ("all-removed", (30, set(range(8)), set(), set(range(8)))),
        ("frames-1-2-removed", (30, set(range(8)), set(), {1, 2})),
        ("zero-frame-empty-last-removed", (17, set(range(1, 7)), {0}, {7})),
    ],
)
def test_single_task_scenario_records(
    coco8_fixtures: LoadedFixtures,
    scenario: str,
    expected: tuple[int, set[int], set[int], set[int]],
) -> None:
    """Each coco8 scenario yields its boxes, empty frames and deletions."""
    bbox_count, annotated, without, deleted = expected
    fake = build_fake(coco8_fixtures, [scenario], statuses=["completed"])
    result = fetch_all_annotations(make_fake_client(fake), fake.project.id)

    bbox_records, without_records = split_records(result)
    assert len(bbox_records) == bbox_count
    assert {a.frame_id for a in bbox_records} == annotated
    assert {w.frame_id for w in without_records} == without
    assert len(without_records) == len(without)
    assert {d.frame_id for d in result.deleted_images} == deleted
    assert len(result.deleted_images) == len(deleted)
    for record in [*result.annotations, *result.deleted_images]:
        assert record.image_name == _IMAGE_NAMES[record.frame_id]


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
    - a frame deleted in an earlier completed task but re-annotated in a
      later one is NOT reported deleted (restore wins).  ``build_fake``
      numbers the tasks ascending in the order named below, so
      ``all-removed`` is the earlier task and ``normal`` the later one;
    - a non-completed task fetched alongside produces ``in_progress`` rows;
    - an externally-injected deletion from a task id above every fixture
      task wins, sending its images to ``deleted``/``obsolete``.
    """
    fake = build_fake(
        coco8_fixtures,
        ["all-removed", "normal", "all-empty"],
        statuses=["completed", "completed", "annotation"],
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

    # Only the external deletion survives; the earlier all-removed deletions
    # are overridden by the later normal re-annotation (restore wins).
    assert [d.image_name for d in partition.deleted_images] == [_IMAGE_NAMES[0]]
    assert _IMAGE_NAMES[0] in set(partition.obsolete["image_name"])

    # The non-completed all-empty task contributes in_progress rows.
    assert len(partition.in_progress) > 0
    assert fake.tasks[2].id in set(partition.in_progress["task_id"].unique())

    # The completed normal task feeds the dataset for its non-deleted frames.
    assert len(partition.dataset) > 0
    assert fake.tasks[1].id in set(partition.dataset["task_id"].unique())


@pytest.mark.parametrize(
    "fail_methods",
    [
        ("get_task_data_meta", "get_task_annotations"),
        # The jobs decide which partition every row lands on, so a 5xx on
        # them skips the task rather than emitting it without job positions.
        ("get_task_jobs",),
    ],
    ids=["data", "jobs"],
)
def test_a_5xx_task_is_skipped(
    coco8_fixtures: LoadedFixtures, fail_methods: tuple[str, ...]
) -> None:
    """When one task returns 5xx, that task is skipped and others are processed."""
    fake = build_fake(
        coco8_fixtures,
        ["normal", "all-empty"],
        statuses=["completed", "completed"],
    )
    api = FakeCvatApi(fake, fail_task_ids={fake.tasks[1].id}, fail_methods=fail_methods)

    result = fetch_all_annotations(
        CvatClient(CvatConfig(), api=api), fake.project.id, project_name="test-project"
    )

    bbox_records = [a for a in result.annotations if isinstance(a, BBoxAnnotation)]
    assert len(bbox_records) == 30
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


@pytest.mark.parametrize(
    ("status", "raise_on_failure"),
    [(404, False), (500, True)],
    ids=["4xx", "5xx-with-raise-on-failure"],
)
def test_fatal_task_errors_propagate(
    coco8_fixtures: LoadedFixtures,
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    *,
    raise_on_failure: bool,
) -> None:
    """A non-5xx error, or any error under CVETA2_RAISE_ON_FAILURE, is re-raised."""
    fake = build_fake(
        coco8_fixtures,
        ["normal", "all-empty"],
        statuses=["completed", "completed"],
    )
    api = FakeCvatApi(fake, fail_task_ids={fake.tasks[1].id}, fail_status=status)
    if raise_on_failure:
        monkeypatch.setenv("CVETA2_RAISE_ON_FAILURE", "true")

    with pytest.raises(CvatApiError) as exc_info:
        fetch_all_annotations(CvatClient(CvatConfig(), api=api), fake.project.id)
    assert exc_info.value.status_code == status


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
    from cveta2.domain.errors import ProjectNotFoundError

    client = make_fake_client(normal_fake)

    with pytest.raises(ProjectNotFoundError, match="does-not-exist"):
        client.resolve_project_id("does-not-exist")


def test_resolve_project_id_live_identity_wins_over_stale_cache() -> None:
    """A cached name must not authorize a stale project ID on an active client."""
    api = FakeCvatApi.from_tasks([], project_name="shared")
    client = CvatClient(CvatConfig(), api=api)

    resolved = client.resolve_project_id(
        "shared",
        cached=[ProjectInfo(id=99, name="shared")],
    )

    assert resolved == 1


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
    from cveta2.domain.output import count_images

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

    from cveta2.adapters.files.dataset import write_raw_csv

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
    from cveta2.application.client.assembly import task_to_records
    from cveta2.application.ports.dtos import RawAnnotations, RawDataMeta, RawFrame

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


def _accounting_dependencies(fake: LoadedFixtures) -> FetchDependencies:
    return fetch_dependencies(
        FetchTarget(fake.project.id, fake.project.name, Path("unused")), FetchOptions()
    )


class TestRetrieveTaskAccounting:
    """``_FetchStats`` is what tells the user how much of a fetch was cached."""

    @pytest.mark.parametrize("cached", [True, False], ids=["hits", "live"])
    def test_counts_and_elapsed_time_accumulate(
        self,
        normal_fake: LoadedFixtures,
        tmp_path: Path,
        *,
        cached: bool,
    ) -> None:
        """Two retrievals report two of a kind and the *sum* of their durations."""
        fake = normal_fake
        client = CvatClient(CvatConfig(), api=FakeCvatApi(fake))
        ctx = _fetch_context(client, fake)
        task = ctx.tasks[0]
        policy = _CachePolicy()
        if cached:
            cache = TaskAnnotationCache(tmp_path / "cache")
            cache.put(task, _fetched(client, task, ctx))
            policy = _CachePolicy(cache=cache)
        stats = _FetchStats(lock=Lock())

        deps = replace(
            _accounting_dependencies(fake),
            clock=_ScriptedClock([100.0, 101.5, 200.0, 203.0]).monotonic,
        )
        assert _retrieve_task(client, task, ctx, policy, stats, deps=deps) is not None
        assert _retrieve_task(client, task, ctx, policy, stats, deps=deps) is not None

        counted = (2, pytest.approx(4.5))
        idle = (0, 0.0)
        assert (stats.cache_hits, stats.hit_seconds) == (counted if cached else idle)
        assert (stats.fetched, stats.fetch_seconds) == (idle if cached else counted)

    def test_a_skipped_task_has_its_own_counter(
        self, normal_fake: LoadedFixtures
    ) -> None:
        """A 5xx skip must not inflate the fetched count or its timer."""
        fake = normal_fake
        api = FakeCvatApi(fake, fail_task_ids={fake.tasks[0].id})
        client = CvatClient(CvatConfig(), api=api)
        ctx = _fetch_context(client, fake)
        stats = _FetchStats(lock=Lock())
        deps = replace(
            _accounting_dependencies(fake),
            clock=_ScriptedClock([100.0, 102.0]).monotonic,
        )

        assert (
            _retrieve_task(client, ctx.tasks[0], ctx, _CachePolicy(), stats, deps=deps)
            is None
        )

        assert stats.skipped_task_ids == [ctx.tasks[0].id]
        assert stats.skipped_seconds == 2.0
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
        stats = _FetchStats(lock=Lock())

        _retrieve_task(
            client,
            task,
            ctx,
            _CachePolicy(cache=cache, force=True),
            stats,
            deps=_accounting_dependencies(fake),
        )

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
    def test_a_leftover_tasks_directory_is_reused_and_never_removed(
        self,
        normal_fake: LoadedFixtures,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Re-running into an output directory with ``.tasks/`` must not fail.

        A killed run leaves ``.tasks/`` behind, and ``--save-tasks`` leaves it
        behind on purpose; an ordinary fetch never removes that possibly
        unrelated debug directory.
        """
        removals: list[Path] = []

        def rmtree(path: Path, *, ignore_errors: bool = False) -> None:
            removals.append(path)
            if not ignore_errors:
                raise PermissionError(path)

        monkeypatch.setattr(shutil, "rmtree", rmtree)
        fake = normal_fake
        out = tmp_path / "out"
        (out / ".tasks").mkdir(parents=True)

        partition = _fetch_project(FakeCvatApi(fake), fake, out, FetchOptions())

        assert removals == []
        assert (out / ".tasks").is_dir()
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

        partition = _fetch_project(api, fake, tmp_path / "out", FetchOptions())

        assert set(partition.dataset["task_id"].unique()) == {fake.tasks[1].id}

    def test_a_fetch_that_selects_nothing_writes_readable_csvs(
        self, coco8_fixtures: LoadedFixtures, tmp_path: Path
    ) -> None:
        """``--completed-only`` with no finished task still writes the schema.

        The partition CSVs used to be a lone newline, which
        ``upload``/``whats-new``/``merge`` then failed on with a pandas
        traceback instead of reading an empty dataset.
        """
        fake = build_fake(coco8_fixtures, ["normal"], statuses=["annotation"])
        out = tmp_path / "out"

        partition = _fetch_project(
            FakeCvatApi(fake),
            fake,
            out,
            FetchOptions(completed_only=True),
        )

        assert partition.dataset.empty
        for name in ("dataset.csv", "obsolete.csv", "in_progress.csv", "deleted.csv"):
            df = read_dataset_csv(out / name, set(CSV_COLUMNS))
            assert list(df.columns) == list(CSV_COLUMNS), name
            assert len(df) == 0, name

    def test_a_shapeless_all_deleted_task_still_reports_its_deletions(
        self, coco8_fixtures: LoadedFixtures, tmp_path: Path
    ) -> None:
        """Deleted frames reach deleted.csv even when no annotation row exists.

        The ``all-removed`` fixture keeps its shapes, so the fetch always had
        rows to partition. Without them the frame is column-less, and the
        partition's empty-frame shortcut used to drop the deletions with it.
        """
        fake = build_fake(coco8_fixtures, ["all-removed"], statuses=["completed"])
        shapeless = fake._replace(
            task_data={
                task_id: (meta, RawAnnotations())
                for task_id, (meta, _) in fake.task_data.items()
            }
        )
        out = tmp_path / "out"

        partition = _fetch_project(
            FakeCvatApi(shapeless), shapeless, out, FetchOptions()
        )

        assert {d.image_name for d in partition.deleted_images} == set(_IMAGE_NAMES)
        deleted = read_dataset_csv(out / "deleted.csv", set(CSV_COLUMNS))
        assert set(deleted["image_name"]) == set(_IMAGE_NAMES)
        assert len(read_dataset_csv(out / "dataset.csv", set(CSV_COLUMNS))) == 0

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
            FetchOptions(save_tasks=True),
        )

        task_df = pd.read_csv(out / ".tasks" / f"task_{fake.tasks[0].id}.csv")
        assert list(task_df.columns) == list(CSV_COLUMNS)
        assert set(task_df["task_id"].unique()) == {fake.tasks[0].id}
        assert len(task_df) == len(pd.read_csv(out / "dataset.csv"))


# ---------------------------------------------------------------------------
# _fetch_core: what it forwards to the downloader and to the path population
# ---------------------------------------------------------------------------


class TestFetchCoreImageForwarding:
    """Each argument decides *whether* or *where* images land on disk."""

    _STORAGE = make_cs_info(bucket="bkt", prefix="data/proj", endpoint_url="")

    def _bucket(self, monkeypatch: pytest.MonkeyPatch) -> None:
        objects = {f"data/proj/{name}": b"IMG" for name in _IMAGE_NAMES}
        s3 = FakeS3Client(objects, keyed_by_bucket=False)
        monkeypatch.setattr(
            "cveta2.adapters.s3.download.make_s3_client", lambda _endpoint=None: s3
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
            FetchOptions(images_dir=images),
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
            CvatClient(
                CvatConfig(), api=FakeCvatApi(fake, cloud_storage=self._STORAGE)
            ),
            FetchTarget(fake.project.id, fake.project.name, tmp_path / "out", None),
            FetchOptions(images_dir=images),
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
        config_path = write_split_config_yaml(
            tmp_path / "cfg.yaml",
            project_ids={fake.project.name: fake.project.id},
            cache={"projects": {fake.project.name: {"ignored_prefix": "data"}}},
        )

        fetch_project(
            CvatClient(CvatConfig(), api=FakeCvatApi(fake)),
            FetchTarget(
                fake.project.id, fake.project.name, tmp_path / "out", self._STORAGE
            ),
            FetchOptions(
                images_dir=images,
                config_path=config_path,
            ),
        )

        assert (images / "proj" / _IMAGE_NAMES[0]).read_bytes() == b"IMG"
        assert not (images / _IMAGE_NAMES[0]).exists()

        dataset = pd.read_csv(tmp_path / "out" / "dataset.csv")
        local_paths = set(dataset["image_path"].dropna())
        assert local_paths
        assert all("/images/proj/" in path for path in local_paths)


def _one_frame_connection(
    tmp_path: Path, task: TaskInfo, frame_name: str = "a.jpg"
) -> tuple[cveta2.Connection, FakeCvatApi]:
    """Build a one-task, one-frame project behind the public API."""
    api = FakeCvatApi(
        LoadedFixtures(
            project=ProjectInfo(id=1, name="audit-project"),
            tasks=[task],
            labels=[],
            task_data={
                task.id: (RawDataMeta([RawFrame(frame_name, 20, 20)]), RawAnnotations())
            },
        )
    )
    config = tmp_path / "config.yaml"
    config.write_text(f"cache:\n  tasks_root: {tmp_path / 'cache'}\n", encoding="utf-8")
    return cveta2.Connection(
        client=CvatClient(CvatConfig(), api=api), config_path=config
    ), api


@pytest.mark.parametrize(
    "frame_name",
    ["/images/nested/a.jpg", "images/nested/a.jpg", "a.jpg", "stale/a.jpg"],
)
def test_downloaded_paths_survive_csv_and_cache_hit(
    tmp_path: Path, frame_name: str
) -> None:
    connection, api = _one_frame_connection(tmp_path, make_task(), frame_name)
    storage = make_cs_info(bucket="bucket", prefix="images")
    s3 = FakeS3Client({"bucket/images/nested/a.jpg": b"image"})
    with (
        patch.object(api, "get_project_cloud_storage", return_value=storage),
        patch("cveta2.adapters.s3.download.make_s3_client", return_value=s3),
    ):
        for run in range(2):
            result = cveta2.fetch(
                "audit-project",
                tmp_path / f"out-{run}",
                connection=connection,
                images_dir=tmp_path / "images",
                cache="off",
            )
            row = result.dataset.iloc[0]
            assert row["s3_image_path"] == "images/nested/a.jpg"
            assert row["image_path"] == str(tmp_path / "images" / "nested" / "a.jpg")
    expected = ["bucket/images/nested/a.jpg"]
    if frame_name in {"a.jpg", "stale/a.jpg"}:
        # Each pass first tries the canonical key. The fallback destination is
        # cached on pass two, so its bytes are downloaded only once.
        missing_key = f"bucket/images/{frame_name}"
        expected = [missing_key, *expected, missing_key]
    assert s3.get_calls == expected
    assert s3.head_calls == []


# ---------------------------------------------------------------------------
# Task completion is derived from every job of the task
# ---------------------------------------------------------------------------


def _fetch_with_jobs(
    tmp_path: Path, jobs: list[RawJob], **api_returns: object
) -> PartitionResult:
    """Fetch the one-frame project with *jobs* and patched API answers."""
    connection, api = _one_frame_connection(tmp_path, make_task(status="annotation"))
    with ExitStack() as stack:
        stack.enter_context(patch.object(api, "get_task_jobs", return_value=jobs))
        for name, value in api_returns.items():
            stack.enter_context(patch.object(api, name, return_value=value))
        return cveta2.fetch(
            "audit-project",
            tmp_path / "output",
            connection=connection,
            download_images=False,
            cache="off",
        )


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("unfinished_type", ["annotation", "ground_truth"])
def test_overlapping_jobs_never_promote_unfinished_task(
    tmp_path: Path, unfinished_type: str, *, reverse: bool
) -> None:
    finished_type = "ground_truth" if unfinished_type == "annotation" else "annotation"
    jobs = [
        RawJob(1, 0, 0, "annotation", "new", type=unfinished_type),
        RawJob(2, 0, 0, "acceptance", "completed", type=finished_type),
    ]
    if reverse:
        jobs.reverse()

    result = _fetch_with_jobs(tmp_path, jobs)

    assert result.dataset.empty
    assert list(result.in_progress["image_name"]) == ["a.jpg"]
    saved = pd.read_csv(tmp_path / "output" / "in_progress.csv")
    assert not bool(saved.loc[0, "task_completed"])
    assert partition_annotations_df(saved, []).dataset.empty


def test_job_without_exported_frames_still_prevents_completion(tmp_path: Path) -> None:
    jobs = [
        RawJob(1, 0, 0, "acceptance", "completed"),
        RawJob(2, 10, 10, "annotation", "new", type="ground_truth"),
    ]

    result = _fetch_with_jobs(tmp_path, jobs)

    assert result.dataset.empty
    assert result.in_progress.loc[0, "job_state"] == "completed"
    assert not bool(result.in_progress.loc[0, "task_completed"])


_UNFINISHED_GROUND_TRUTH = [
    RawJob(1, 0, 0, "acceptance", "completed"),
    RawJob(2, 0, 0, "annotation", "new", type="ground_truth"),
]


def test_annotated_frames_preserve_unfinished_ground_truth_job(tmp_path: Path) -> None:
    """A bbox must carry task-wide completion independently of its own job."""
    result = _fetch_with_jobs(
        tmp_path,
        _UNFINISHED_GROUND_TRUTH,
        get_task_annotations=RawAnnotations([make_raw_shape(frame=0)]),
    )

    assert result.dataset.empty
    assert result.in_progress["instance_shape"].tolist() == ["box"]
    assert result.in_progress["task_completed"].tolist() == [False]


def test_deleted_frames_preserve_unfinished_ground_truth_job(tmp_path: Path) -> None:
    """Deleting every frame does not make an unfinished job disappear."""
    result = _fetch_with_jobs(
        tmp_path,
        _UNFINISHED_GROUND_TRUTH,
        get_task_data_meta=RawDataMeta([RawFrame("a.jpg", 20, 20)], deleted_frames=[0]),
    )

    assert len(result.deleted_images) == 1
    assert completed_task_ids(result.dataset, result.deleted_images) == set()
    saved = pd.read_csv(tmp_path / "output" / "deleted.csv")
    assert saved["task_completed"].tolist() == [False]


@pytest.mark.parametrize("legacy_value", [None, float("nan")])
def test_missing_completion_values_use_legacy_jobs_but_false_excludes_task(
    legacy_value: float | None,
) -> None:
    row = {"job_stage": "acceptance", "job_state": "completed"}
    rows = pd.DataFrame(
        [
            {
                "image_name": "legacy.jpg",
                "task_id": 1,
                **row,
                "task_completed": legacy_value,
            },
            {
                "image_name": "explicit.jpg",
                "task_id": 2,
                **row,
                "task_completed": False,
            },
            {
                "image_name": "other.jpg",
                "task_id": 2,
                **row,
                "task_completed": legacy_value,
            },
        ]
    )
    result = partition_annotations_df(rows, [])
    assert list(result.dataset["image_name"]) == ["legacy.jpg"]
    assert set(result.in_progress["image_name"]) == {"explicit.jpg", "other.jpg"}


# ---------------------------------------------------------------------------
# concurrent task fetching
# ---------------------------------------------------------------------------


def test_concurrent_fetch_produces_the_same_dataset_as_a_serial_one(
    coco8_fixtures: LoadedFixtures, tmp_path: Path
) -> None:
    """Worker count is a throughput knob and must not touch the output.

    Per-task results are merged positionally, so a loop that appended in
    completion order would reorder rows for the same input — invisible
    until two tasks annotate the same image.  Re-fetching a task would
    double its rows and its CVAT load.
    """
    fake = build_fake(
        coco8_fixtures,
        ["normal", "all-empty", "all-bboxes-moved", "frames-1-2-removed"],
        statuses=["completed"] * 4,
    )
    options = FetchOptions()

    configure_workers(s3=1, cvat=1)
    serial = _fetch_project(FakeCvatApi(fake), fake, tmp_path / "serial", options)

    configure_workers(s3=1, cvat=8)
    parallel_api = FakeCvatApi(fake)
    parallel = _fetch_project(parallel_api, fake, tmp_path / "parallel", options)

    assert parallel.dataset.equals(serial.dataset)
    assert len(serial.dataset) > 0
    assert sorted(parallel_api.annotation_calls) == sorted(t.id for t in fake.tasks)


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
        _fetch_project(api, fake, tmp_path / "out", FetchOptions())
