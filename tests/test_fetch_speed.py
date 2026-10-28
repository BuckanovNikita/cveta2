"""Deterministic effect and accounting regressions for faster fetches."""

from dataclasses import replace
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pandas as pd
import pytest

from cveta2.adapters.config.settings import CvatConfig
from cveta2.adapters.files.dataset import enrich_dataframe_paths, populate_record_paths
from cveta2.adapters.files.task_output import LocalWorkflowFiles
from cveta2.adapters.s3.task_cache import TaskAnnotationCache
from cveta2.application.client.shared import FetchContext
from cveta2.application.ports.cache import TaskCache
from cveta2.application.use_cases.fetch import (
    FetchOptions,
    FetchTarget,
    _CachePolicy,
    _fetch_and_save_tasks,
    _FetchStats,
    _retrieve_task,
    fetch_project,
)
from cveta2.composition.client import CvatClient
from cveta2.composition.workflows import fetch_dependencies
from cveta2.domain.errors import Cveta2Error
from cveta2.domain.models import ProjectAnnotations, TaskAnnotations
from tests.fixtures.fake_cvat_api import FakeCvatApi
from tests.helpers import build_fake, make_bbox, make_cs_info, make_task

if TYPE_CHECKING:
    from cveta2.application.ports.dtos import RawIssue
    from cveta2.domain.models import AnnotationRecord
    from tests.fixtures.fake_cvat_project import LoadedFixtures


def test_inventory_snapshot_precedes_filters(coco8_fixtures: "LoadedFixtures") -> None:
    fake = build_fake(
        coco8_fixtures,
        ["normal", "all-empty", "all-removed"],
        statuses=["completed", "annotation", "completed"],
    )
    api = FakeCvatApi(fake)
    client = CvatClient(CvatConfig(), api=api)

    context = client.prepare_fetch(
        fake.project.id, completed_only=True, ignore_task_ids={fake.tasks[2].id}
    )

    assert [task.id for task in context.tasks] == [fake.tasks[0].id]
    assert context.all_task_ids == frozenset(task.id for task in fake.tasks)
    assert api.call_counts["get_project_tasks"] == 1


def test_numeric_selection_has_no_complete_inventory(
    normal_fake: "LoadedFixtures",
) -> None:
    api = FakeCvatApi(normal_fake)
    client = CvatClient(CvatConfig(), api=api)
    context = client.prepare_fetch(
        normal_fake.project.id, task_selector=[normal_fake.tasks[0].id]
    )
    assert context.all_task_ids is None
    assert api.call_counts["get_project_tasks"] == 0


def test_full_fetch_prunes_from_single_complete_inventory(
    coco8_fixtures: "LoadedFixtures", tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = build_fake(
        coco8_fixtures,
        ["normal", "all-empty", "all-removed"],
        statuses=["completed", "annotation", "completed"],
    )
    api = FakeCvatApi(fake)
    cache = TaskAnnotationCache(tmp_path / "cache")
    for task_id in [*(task.id for task in fake.tasks), 999]:
        cache.put(
            make_task(task_id),
            TaskAnnotations(
                task_id=task_id, task_name="task", annotations=[], deleted_images=[]
            ),
        )
    target = FetchTarget(fake.project.id, fake.project.name, tmp_path / "output")
    options = FetchOptions(completed_only=True, ignore_task_ids={fake.tasks[2].id})
    deps = fetch_dependencies(target, options)
    monkeypatch.setattr(type(deps.caches), "create", lambda *_args, **_kwargs: cache)

    fetch_project(
        CvatClient(CvatConfig(), api=api),
        target,
        options,
        deps=replace(deps, cache_enabled=True),
    )

    assert api.call_counts["get_project_tasks"] == 1
    assert not ((tmp_path / "cache") / "task_999.json").exists()
    assert all(
        ((tmp_path / "cache") / f"task_{task.id}.json").exists() for task in fake.tasks
    )


@pytest.mark.parametrize("save_tasks", [False, True])
def test_task_csv_effects_are_opt_in(
    normal_fake: "LoadedFixtures", tmp_path: Path, *, save_tasks: bool
) -> None:
    fake = normal_fake
    task_dir = tmp_path / ".tasks"
    task_dir.mkdir()
    sentinel = task_dir / "keep.bin"
    sentinel.write_bytes(b"pre-existing")
    target = FetchTarget(fake.project.id, fake.project.name, tmp_path)
    options = FetchOptions(use_cache=False, save_tasks=save_tasks)
    deps = fetch_dependencies(target, options)
    files = Mock(wraps=LocalWorkflowFiles())
    client = CvatClient(CvatConfig(), api=FakeCvatApi(fake))

    _fetch_and_save_tasks(
        client,
        client.prepare_fetch(fake.project.id),
        tmp_path,
        _CachePolicy(),
        deps=replace(deps, files=files),
        save_tasks=save_tasks,
    )

    assert sentinel.read_bytes() == b"pre-existing"
    if save_tasks:
        files.prepare_tasks.assert_called_once_with(tmp_path)
        assert files.write_task_csv.call_count == len(fake.tasks)
        assert len(list(task_dir.glob("task_*.csv"))) == len(fake.tasks)
    else:
        files.prepare_tasks.assert_not_called()
        files.write_task_csv.assert_not_called()
        assert list(task_dir.iterdir()) == [sentinel]
    files.cleanup_tasks.assert_not_called()


def test_path_resolution_scales_with_unique_images(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("a.jpg", "b.jpg"):
        (tmp_path / name).write_bytes(b"image")
    records: list[AnnotationRecord] = [
        make_bbox(image_name=name) for name in ["a.jpg", "b.jpg"] * 20
    ]
    result = ProjectAnnotations(annotations=records, deleted_images=[])
    original_resolve = Path.resolve
    calls: list[Path] = []

    def counted_resolve(path: Path, *, strict: bool = False) -> Path:
        calls.append(path)
        return original_resolve(path, strict=strict)

    monkeypatch.setattr(Path, "resolve", counted_resolve)
    populate_record_paths(result, make_cs_info(prefix="images"), tmp_path)

    assert len(calls) <= 6
    assert {record.image_path for record in records} == {
        str(tmp_path / "a.jpg"),
        str(tmp_path / "b.jpg"),
    }


def test_dataframe_resolves_each_unique_destination_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "a.jpg"
    df = pd.DataFrame({"image_name": ["a.jpg", "alias.jpg"] * 20})
    original_resolve = Path.resolve
    calls: list[Path] = []

    def counted_resolve(value: Path, *, strict: bool = False) -> Path:
        calls.append(value)
        return original_resolve(value, strict=strict)

    monkeypatch.setattr(Path, "resolve", counted_resolve)
    result = enrich_dataframe_paths(
        df, make_cs_info(), {"a.jpg": path, "alias.jpg": path}
    )

    assert calls == [path]
    assert result["image_path"].tolist() == [str(path)] * 40


def test_repeated_destination_still_validates_every_lexical_key(tmp_path: Path) -> None:
    records: list[AnnotationRecord] = [
        make_bbox(image_name="a.jpg"),
        make_bbox(image_name="a.jpg", s3_image_path="images/dir/../a.jpg"),
    ]
    with pytest.raises(Cveta2Error, match=r"a\.jpg"):
        populate_record_paths(
            ProjectAnnotations(annotations=records, deleted_images=[]),
            make_cs_info(prefix="images"),
            tmp_path,
        )


def test_task_summary_reports_skipped_and_incomplete_without_cache(
    coco8_fixtures: "LoadedFixtures",
    tmp_path: Path,
    capture_info_logs: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = build_fake(
        coco8_fixtures,
        ["normal", "all-empty", "all-removed"],
        statuses=["completed"] * 3,
    )
    api = FakeCvatApi(fake)
    client = CvatClient(CvatConfig(), api=api)
    context = client.prepare_fetch(fake.project.id)
    complete = client.fetch_one_task(api, fake.tasks[0], context)
    assert complete is not None
    incomplete = complete.model_copy(update={"issues_complete": False})
    monkeypatch.setattr(
        client, "fetch_one_task", Mock(side_effect=[complete, None, incomplete])
    )
    target = FetchTarget(fake.project.id, fake.project.name, tmp_path)
    deps = fetch_dependencies(target, FetchOptions(use_cache=False))
    clock = Mock(side_effect=[100.0, 110.0, 112.0, 120.0, 124.0, 130.0, 135.0, 150.0])

    _fetch_and_save_tasks(
        client,
        context,
        tmp_path,
        _CachePolicy(),
        deps=replace(deps, clock=clock, cvat_workers=1),
        save_tasks=False,
    )

    summary = "\n".join(capture_info_logs)
    assert "из кэша: 0" in summary
    assert "загружено с CVAT: 2" in summary
    assert "пропущено: 1" in summary
    assert "неполные issues: 1" in summary
    assert "прошло 50.0 с" in summary
    assert "суммарное время работников" in summary
    assert str(fake.tasks[1].id) in summary
    assert str(fake.tasks[2].id) in summary


def test_skipped_task_has_separate_counter(
    normal_fake: "LoadedFixtures",
) -> None:
    api = FakeCvatApi(normal_fake, fail_task_ids={normal_fake.tasks[0].id})
    client = CvatClient(CvatConfig(), api=api)
    context = client.prepare_fetch(normal_fake.project.id)
    target = FetchTarget(
        normal_fake.project.id, normal_fake.project.name, Path("unused")
    )
    deps = replace(
        fetch_dependencies(target, FetchOptions()),
        clock=Mock(side_effect=[100.0, 102.0]),
    )
    stats = _FetchStats(lock=Lock())

    assert (
        _retrieve_task(
            client, context.tasks[0], context, _CachePolicy(), stats, deps=deps
        )
        is None
    )
    assert stats.skipped_task_ids == [context.tasks[0].id]
    assert stats.skipped_seconds == 2.0
    assert stats.fetched == 0


def test_legacy_context_does_not_claim_a_complete_inventory() -> None:
    assert FetchContext([], {}, {}).all_task_ids is None


def test_empty_complete_inventory_prunes_every_orphan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capture_info_logs: list[str]
) -> None:
    api = FakeCvatApi.from_tasks([])
    cache = TaskAnnotationCache(tmp_path / "cache")
    cache.put(
        make_task(999),
        TaskAnnotations(
            task_id=999, task_name="old", annotations=[], deleted_images=[]
        ),
    )
    target = FetchTarget(1, "fake", tmp_path / "out")
    options = FetchOptions()
    deps = fetch_dependencies(target, options)
    monkeypatch.setattr(type(deps.caches), "create", lambda *_args, **_kwargs: cache)

    fetch_project(
        CvatClient(CvatConfig(), api=api),
        target,
        options,
        deps=replace(deps, cache_enabled=True),
    )

    assert api.call_counts["get_project_tasks"] == 1
    assert not (tmp_path / "cache" / "task_999.json").exists()
    assert not (target.output_dir / ".tasks").exists()
    assert any("пропущено: 0, неполные issues: 0" in msg for msg in capture_info_logs)


def test_numeric_project_fetch_does_not_prune_without_complete_inventory(
    normal_fake: "LoadedFixtures", tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = FakeCvatApi(normal_fake)
    cache = TaskAnnotationCache(tmp_path / "cache")
    cache.put(
        make_task(999),
        TaskAnnotations(
            task_id=999, task_name="other", annotations=[], deleted_images=[]
        ),
    )
    target = FetchTarget(
        normal_fake.project.id, normal_fake.project.name, tmp_path / "out"
    )
    options = FetchOptions(task_selector=[normal_fake.tasks[0].id])
    deps = fetch_dependencies(target, options)
    monkeypatch.setattr(type(deps.caches), "create", lambda *_args, **_kwargs: cache)

    fetch_project(
        CvatClient(CvatConfig(), api=api),
        target,
        options,
        deps=replace(deps, cache_enabled=True),
    )

    assert api.call_counts["get_project_tasks"] == 0
    assert (tmp_path / "cache" / "task_999.json").exists()


def test_deletion_after_inventory_is_pruned_next_run(
    normal_fake: "LoadedFixtures", tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = FakeCvatApi(normal_fake)
    cache = TaskAnnotationCache(tmp_path / "cache")
    target = FetchTarget(
        normal_fake.project.id, normal_fake.project.name, tmp_path / "out"
    )
    options = FetchOptions()
    deps = fetch_dependencies(target, options)
    monkeypatch.setattr(type(deps.caches), "create", lambda *_args, **_kwargs: cache)
    original_get_issues = api.get_task_issues

    def delete_after_read(task_id: int) -> "list[RawIssue]":
        issues = original_get_issues(task_id)
        api.delete_task(task_id)
        return issues

    monkeypatch.setattr(api, "get_task_issues", delete_after_read)
    client = CvatClient(CvatConfig(), api=api)
    entry = tmp_path / "cache" / f"task_{normal_fake.tasks[0].id}.json"

    fetch_project(client, target, options, deps=replace(deps, cache_enabled=True))
    assert entry.exists()
    assert api.call_counts["get_project_tasks"] == 1

    fetch_project(client, target, options, deps=replace(deps, cache_enabled=True))
    assert not entry.exists()
    assert api.call_counts["get_project_tasks"] == 2


def test_skip_summary_never_reconstructs_a_credential_bearing_host(
    normal_fake: "LoadedFixtures", capture_logs: list[str]
) -> None:
    api = FakeCvatApi(normal_fake, fail_task_ids={normal_fake.tasks[0].id})
    client = CvatClient(
        CvatConfig(host="https://user:secret@cvat.example/?token=secret"), api=api
    )
    context = client.prepare_fetch(normal_fake.project.id)

    assert client.fetch_one_task(api, context.tasks[0], context) is None

    assert any(f"#{context.tasks[0].id}" in message for message in capture_logs)
    assert all("secret" not in message for message in capture_logs)


def test_empty_task_summary_reports_elapsed_time(
    tmp_path: Path, capture_info_logs: list[str]
) -> None:
    api = FakeCvatApi.from_tasks([])
    client = CvatClient(CvatConfig(), api=api)
    target = FetchTarget(1, "fake", tmp_path)
    deps = replace(
        fetch_dependencies(target, FetchOptions()),
        clock=Mock(side_effect=[100.0, 107.0]),
    )

    result = _fetch_and_save_tasks(
        client,
        FetchContext([], {}, {}),
        tmp_path,
        _CachePolicy(),
        deps=deps,
        save_tasks=False,
    )

    assert result.annotations == []
    assert any("прошло 7.0 с" in message for message in capture_info_logs)


def test_injected_cache_incomplete_issues_remain_visible_in_totals(
    normal_fake: "LoadedFixtures",
) -> None:
    api = FakeCvatApi(normal_fake)
    client = CvatClient(CvatConfig(), api=api)
    context = client.prepare_fetch(normal_fake.project.id)
    task = context.tasks[0]
    cached = TaskAnnotations(
        task_id=task.id,
        task_name=task.name,
        annotations=[],
        deleted_images=[],
        issues_complete=False,
    )
    cache = Mock(spec=TaskCache)
    cache.get.return_value = cached
    target = FetchTarget(
        normal_fake.project.id, normal_fake.project.name, Path("unused")
    )
    deps = replace(
        fetch_dependencies(target, FetchOptions()),
        clock=Mock(side_effect=[100.0, 103.0]),
    )
    stats = _FetchStats(lock=Lock())

    result = _retrieve_task(
        client,
        task,
        context,
        _CachePolicy(cache=cache),
        stats,
        deps=deps,
    )

    assert result is cached
    assert stats.degraded_task_ids == [task.id]
    assert (stats.cache_hits, stats.fetched, stats.hit_seconds) == (1, 0, 3.0)
    assert api.annotation_calls == []
    cache.put.assert_not_called()
