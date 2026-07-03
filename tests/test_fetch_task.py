"""Tests for the ``cveta2 fetch-task`` command and its helpers."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pandas as pd
import pytest

from cveta2.client import CvatClient, _FetchAnnotationsOptions, _filter_tasks_for_fetch
from cveta2.commands.fetch import (
    _resolve_images_dir,
    _resolve_task_selector,
    _warn_ignored_tasks,
    run_fetch_task,
)
from cveta2.config import (
    CvatConfig,
    IgnoreConfig,
    IgnoredTask,
    ImageCacheConfig,
    _parse_ignore_entry,
    _serialize_ignore_entry,
)
from cveta2.exceptions import InteractiveModeRequiredError
from cveta2.models import CSV_COLUMNS, TaskInfo
from tests.fixtures.fake_cvat_api import FakeCvatApi
from tests.helpers import CFG, build_fake, make_fake_client, make_fetch_args

if TYPE_CHECKING:
    from tests.fixtures.fake_cvat_project import LoadedFixtures

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MODULE = "cveta2.commands.fetch"


def _run_fetch_task_with_fake(
    fixtures: LoadedFixtures,
    args: argparse.Namespace,
    *,
    ignore_config: IgnoreConfig | None = None,
) -> None:
    """Execute ``run_fetch_task`` backed by fake CVAT data.

    Patches all config loading so no real filesystem or CVAT server is
    needed.  Uses FakeCvatApi for the API port via DI.
    """
    fake_api = FakeCvatApi(fixtures)

    def make_client(cfg: CvatConfig, **_kw: object) -> CvatClient:
        return CvatClient(cfg, api=fake_api)

    ic = ignore_config if ignore_config is not None else IgnoreConfig()

    with (
        patch("cveta2.commands._bootstrap.CvatConfig.load", return_value=CFG),
        patch("cveta2.commands._bootstrap.require_host"),
        patch("cveta2.commands._helpers.load_projects_cache", return_value=[]),
        patch(f"{_MODULE}.load_ignore_config", return_value=ic),
        patch("cveta2.commands._bootstrap.CvatClient", side_effect=make_client),
        patch(
            "cveta2.client.CvatClient.detect_project_cloud_storage",
            return_value=None,
        ),
    ):
        run_fetch_task(args)


# ---------------------------------------------------------------------------
# Unit tests: _resolve_task_selector
# ---------------------------------------------------------------------------


class TestResolveTaskSelector:
    """Tests for ``_resolve_task_selector``."""

    def test_explicit_task_id(self, coco8_fixtures: LoadedFixtures) -> None:
        """Explicit task ID string is returned as-is."""
        fake = build_fake(coco8_fixtures, ["normal"], statuses=["completed"])
        client = make_fake_client(fake)
        task_id_str = str(fake.tasks[0].id)
        args = make_fetch_args(task=[task_id_str], output_dir="unused")

        result = _resolve_task_selector(args, client, fake.project.id, None)

        assert result == [task_id_str]

    def test_explicit_task_name(self, coco8_fixtures: LoadedFixtures) -> None:
        """Explicit task name is returned as-is."""
        fake = build_fake(coco8_fixtures, ["normal"], statuses=["completed"])
        client = make_fake_client(fake)
        task_name = fake.tasks[0].name
        args = make_fetch_args(task=[task_name], output_dir="unused")

        result = _resolve_task_selector(args, client, fake.project.id, None)

        assert result == [task_name]

    def test_multiple_explicit_tasks(self, coco8_fixtures: LoadedFixtures) -> None:
        """Multiple -t values are returned in order."""
        fake = build_fake(
            coco8_fixtures,
            ["normal", "all-empty"],
            statuses=["completed", "completed"],
        )
        client = make_fake_client(fake)
        ids = [str(t.id) for t in fake.tasks]
        args = make_fetch_args(task=ids, output_dir="unused")

        result = _resolve_task_selector(args, client, fake.project.id, None)

        assert result == ids

    def test_empty_task_triggers_tui(self, coco8_fixtures: LoadedFixtures) -> None:
        """``-t`` without a value (empty string) falls through to TUI."""
        fake = build_fake(coco8_fixtures, ["normal"], statuses=["completed"])
        client = make_fake_client(fake)
        args = make_fetch_args(task=[""], output_dir="unused")

        with (
            patch(
                "cveta2.commands._task_selector.require_interactive",
                side_effect=InteractiveModeRequiredError("non-interactive"),
            ),
            pytest.raises(InteractiveModeRequiredError),
        ):
            _resolve_task_selector(args, client, fake.project.id, None)

    def test_none_task_triggers_tui(self, coco8_fixtures: LoadedFixtures) -> None:
        """``task=None`` (no -t flag at all) falls through to TUI."""
        fake = build_fake(coco8_fixtures, ["normal"], statuses=["completed"])
        client = make_fake_client(fake)
        args = make_fetch_args(task=None, output_dir="unused")

        with (
            patch(
                "cveta2.commands._task_selector.require_interactive",
                side_effect=InteractiveModeRequiredError("non-interactive"),
            ),
            pytest.raises(InteractiveModeRequiredError),
        ):
            _resolve_task_selector(args, client, fake.project.id, None)

    def test_whitespace_only_values_filtered(
        self,
        coco8_fixtures: LoadedFixtures,
    ) -> None:
        """Whitespace-only task values are stripped and filtered out."""
        fake = build_fake(coco8_fixtures, ["normal"], statuses=["completed"])
        client = make_fake_client(fake)
        task_name = fake.tasks[0].name
        args = make_fetch_args(task=["  ", task_name, ""], output_dir="unused")

        result = _resolve_task_selector(args, client, fake.project.id, None)

        assert result == [task_name]


# ---------------------------------------------------------------------------
# Unit tests: _warn_ignored_tasks
# ---------------------------------------------------------------------------


class TestWarnIgnoredTasks:
    """Tests for ``_warn_ignored_tasks``."""

    def test_no_ignored_tasks(self) -> None:
        """Returns (None, None) when ignore config is empty for the project."""
        with patch(
            f"{_MODULE}.load_ignore_config",
            return_value=IgnoreConfig(),
        ):
            ignore_set, silent_set = _warn_ignored_tasks("my-project")

        assert ignore_set is None
        assert silent_set is None

    def test_returns_set_of_ignored_ids(self) -> None:
        """Returns a set of task IDs from the ignore config."""
        ignore_cfg = IgnoreConfig(
            projects={
                "my-project": [
                    IgnoredTask(id=10, name="t10"),
                    IgnoredTask(id=20, name="t20"),
                    IgnoredTask(id=30, name="t30"),
                ],
            },
        )
        with patch(
            f"{_MODULE}.load_ignore_config",
            return_value=ignore_cfg,
        ):
            ignore_set, silent_set = _warn_ignored_tasks("my-project")

        assert ignore_set == {10, 20, 30}
        assert silent_set is None

    def test_different_project_returns_none(self) -> None:
        """Returns (None, None) when the project is not in the ignore config."""
        ignore_cfg = IgnoreConfig(
            projects={"other-project": [IgnoredTask(id=10, name="t10")]},
        )
        with patch(
            f"{_MODULE}.load_ignore_config",
            return_value=ignore_cfg,
        ):
            ignore_set, silent_set = _warn_ignored_tasks("my-project")

        assert ignore_set is None
        assert silent_set is None

    def test_returns_silent_task_ids(self) -> None:
        """Returns silent task IDs as the second element of the tuple."""
        ignore_cfg = IgnoreConfig(
            projects={
                "my-project": [
                    IgnoredTask(id=10, name="t10", silent=True),
                    IgnoredTask(id=20, name="t20"),
                    IgnoredTask(id=30, name="t30", silent=True),
                ],
            },
        )
        with patch(
            f"{_MODULE}.load_ignore_config",
            return_value=ignore_cfg,
        ):
            ignore_set, silent_set = _warn_ignored_tasks("my-project")

        assert ignore_set == {10, 20, 30}
        assert silent_set == {10, 30}


# ---------------------------------------------------------------------------
# Unit tests: _filter_tasks_for_fetch (silent ignored tasks)
# ---------------------------------------------------------------------------


class TestFilterTasksSilent:
    """Tests for silent ignored tasks in ``_filter_tasks_for_fetch``."""

    @staticmethod
    def _make_tasks() -> list[TaskInfo]:
        return [
            TaskInfo(
                id=1,
                name="task-1",
                status="completed",
                subset="",
                updated_date="2024-01-01",
            ),
            TaskInfo(
                id=2,
                name="task-2",
                status="completed",
                subset="",
                updated_date="2024-01-02",
            ),
            TaskInfo(
                id=3,
                name="task-3",
                status="completed",
                subset="",
                updated_date="2024-01-03",
            ),
        ]

    def test_silent_ignored_tasks_no_warning(self, capture_logs: list[str]) -> None:
        """Silent ignored tasks are filtered out but produce no warning."""
        tasks = self._make_tasks()
        options = _FetchAnnotationsOptions(
            ignore_task_ids={2},
            silent_task_ids={2},
        )

        result = _filter_tasks_for_fetch(tasks, options)

        assert [t.id for t in result] == [1, 3]
        assert not any("Пропускаем" in m for m in capture_logs)
        assert not any("task-2" in m for m in capture_logs)

    def test_non_silent_ignored_tasks_warn(self, capture_logs: list[str]) -> None:
        """Non-silent ignored tasks produce a warning."""
        tasks = self._make_tasks()
        options = _FetchAnnotationsOptions(
            ignore_task_ids={2},
        )

        result = _filter_tasks_for_fetch(tasks, options)

        assert [t.id for t in result] == [1, 3]
        assert any("Пропускаем" in m for m in capture_logs)
        assert any("task-2" in m for m in capture_logs)

    def test_mixed_silent_and_non_silent(self, capture_logs: list[str]) -> None:
        """Only non-silent ignored tasks appear in the warning."""
        tasks = self._make_tasks()
        options = _FetchAnnotationsOptions(
            ignore_task_ids={1, 2},
            silent_task_ids={1},
        )

        result = _filter_tasks_for_fetch(tasks, options)

        assert [t.id for t in result] == [3]
        all_text = " ".join(capture_logs)
        assert "Пропускаем 1 задач" in all_text
        assert "task-2" in all_text
        assert "task-1" not in all_text


# ---------------------------------------------------------------------------
# Unit tests: IgnoredTask silent field (config round-trip)
# ---------------------------------------------------------------------------


class TestIgnoredTaskSilent:
    """Tests for the ``silent`` field on ``IgnoredTask``."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (
                {"id": 5, "name": "t5", "silent": True},
                IgnoredTask(id=5, name="t5", silent=True),
            ),
            ({"id": 5, "name": "t5"}, IgnoredTask(id=5, name="t5", silent=False)),
        ],
    )
    def test_parse_silent(self, raw: dict[str, object], expected: IgnoredTask) -> None:
        """``_parse_ignore_entry`` reads ``silent`` (defaulting to False)."""
        entry = _parse_ignore_entry(raw)
        assert entry is not None
        assert entry.silent is expected.silent

    @pytest.mark.parametrize(
        ("entry", "expected"),
        [
            (IgnoredTask(id=5, name="t5", silent=True), {"silent": True}),
            (IgnoredTask(id=5, name="t5", silent=False), {}),
        ],
    )
    def test_serialize_silent(
        self, entry: IgnoredTask, expected: dict[str, object]
    ) -> None:
        """``_serialize_ignore_entry`` includes ``silent`` only when True."""
        data = _serialize_ignore_entry(entry)
        if "silent" in expected:
            assert data["silent"] == expected["silent"]
        else:
            assert "silent" not in data

    def test_get_silent_task_ids(self) -> None:
        """``get_silent_task_ids`` returns only IDs with ``silent=True``."""
        cfg = IgnoreConfig(
            projects={
                "proj": [
                    IgnoredTask(id=1, name="a", silent=True),
                    IgnoredTask(id=2, name="b"),
                    IgnoredTask(id=3, name="c", silent=True),
                ],
            },
        )
        assert cfg.get_silent_task_ids("proj") == {1, 3}

    def test_get_silent_task_ids_empty(self) -> None:
        """Returns empty set when no silent tasks."""
        cfg = IgnoreConfig(
            projects={"proj": [IgnoredTask(id=1, name="a")]},
        )
        assert cfg.get_silent_task_ids("proj") == set()

    def test_add_task_with_silent(self) -> None:
        """``add_task`` accepts ``silent`` keyword argument."""
        cfg = IgnoreConfig()
        cfg.add_task("proj", 42, "my-task", silent=True)
        entries = cfg.get_ignored_entries("proj")
        assert len(entries) == 1
        assert entries[0].silent is True


# ---------------------------------------------------------------------------
# Unit tests: _resolve_images_dir
# ---------------------------------------------------------------------------


class TestResolveImagesDir:
    """Tests for ``_resolve_images_dir``."""

    def test_no_images_flag(self) -> None:
        """``--no-images`` returns None regardless of other settings."""
        args = argparse.Namespace(no_images=True, images_dir="/some/path")

        result = _resolve_images_dir(args, "project-x")

        assert result is None

    def test_explicit_images_dir(self, tmp_path: Path) -> None:
        """``--images-dir`` takes top priority and returns resolved path."""
        images_dir = tmp_path / "images"
        args = argparse.Namespace(no_images=False, images_dir=str(images_dir))

        with patch(f"{_MODULE}.load_image_cache_config"):
            result = _resolve_images_dir(args, "project-x")

        assert result == images_dir.resolve()

    def test_cached_dir_from_config(self) -> None:
        """Returns cached directory from image cache config."""
        cached_path = Path("/data/images/project-x")
        ic_cfg = ImageCacheConfig(projects={"project-x": cached_path})
        args = argparse.Namespace(no_images=False, images_dir=None)

        with patch(
            f"{_MODULE}.load_image_cache_config",
            return_value=ic_cfg,
        ):
            result = _resolve_images_dir(args, "project-x")

        assert result == cached_path

    def test_non_interactive_exits_when_no_config(self) -> None:
        """Exits when no images dir is configured and interactive is disabled."""
        args = argparse.Namespace(no_images=False, images_dir=None)

        with (
            patch(
                f"{_MODULE}.load_image_cache_config",
                return_value=ImageCacheConfig(),
            ),
            patch(f"{_MODULE}.is_interactive_disabled", return_value=True),
            pytest.raises(SystemExit),
        ):
            _resolve_images_dir(args, "project-x")

    def test_interactive_prompt_empty_returns_none(self) -> None:
        """Interactive mode with empty path input returns None."""
        args = argparse.Namespace(no_images=False, images_dir=None)

        with (
            patch(
                f"{_MODULE}.load_image_cache_config",
                return_value=ImageCacheConfig(),
            ),
            patch(f"{_MODULE}.is_interactive_disabled", return_value=False),
            patch("builtins.input", return_value=""),
        ):
            result = _resolve_images_dir(args, "project-x")

        assert result is None

    def test_interactive_prompt_saves_config(self, tmp_path: Path) -> None:
        """Interactive mode saves the entered path to image cache config."""
        entered_path = str(tmp_path / "entered")
        args = argparse.Namespace(no_images=False, images_dir=None)
        ic_cfg = ImageCacheConfig()

        with (
            patch(
                f"{_MODULE}.load_image_cache_config",
                return_value=ic_cfg,
            ),
            patch(f"{_MODULE}.is_interactive_disabled", return_value=False),
            patch("builtins.input", return_value=entered_path),
            patch(f"{_MODULE}.save_image_cache_config") as mock_save,
        ):
            result = _resolve_images_dir(args, "project-x")

        assert result == Path(entered_path).resolve()
        mock_save.assert_called_once_with(ic_cfg)
        assert ic_cfg.get_cache_dir("project-x") == Path(entered_path).resolve()


# ---------------------------------------------------------------------------
# Integration tests: run_fetch_task
# ---------------------------------------------------------------------------


class TestRunFetchTaskIntegration:
    """Integration tests for ``run_fetch_task``."""

    def test_happy_path_writes_dataset_and_deleted(
        self,
        coco8_fixtures: LoadedFixtures,
        tmp_path: Path,
    ) -> None:
        """Combined fetch writes a full dataset.csv and deleted.csv output."""
        fake = build_fake(
            coco8_fixtures,
            ["normal", "all-empty", "all-removed"],
            statuses=["completed", "completed", "completed"],
        )
        out_dir = tmp_path / "nested" / "deep" / "output"
        args = make_fetch_args(
            project=str(fake.project.id),
            task=[t.name for t in fake.tasks],
            output_dir=str(out_dir),
        )

        _run_fetch_task_with_fake(fake, args)

        dataset_csv = out_dir / "dataset.csv"
        deleted_csv = out_dir / "deleted.csv"
        assert dataset_csv.exists()
        assert deleted_csv.exists()

        df = pd.read_csv(dataset_csv)
        assert set(df.columns) == set(CSV_COLUMNS)

        task_ids_in_csv = set(df["task_id"].unique())
        assert {fake.tasks[0].id, fake.tasks[1].id}.issubset(task_ids_in_csv)

        bbox_rows = df[df["instance_shape"] == "box"]
        assert len(bbox_rows) > 0
        for col in ("bbox_x_tl", "bbox_y_tl", "bbox_x_br", "bbox_y_br"):
            assert bbox_rows[col].notna().all()

        without_rows = df[df["instance_shape"] == "none"]
        assert len(without_rows) == 8
        for col in ("bbox_x_tl", "bbox_y_tl", "bbox_x_br", "bbox_y_br"):
            assert without_rows[col].isna().all()

        deleted_df = pd.read_csv(deleted_csv)
        assert set(CSV_COLUMNS).issubset(set(deleted_df.columns))
        assert len(deleted_df) == 8
        assert (deleted_df["instance_shape"] == "deleted").all()

    def test_ignored_tasks_excluded(
        self,
        coco8_fixtures: LoadedFixtures,
        tmp_path: Path,
    ) -> None:
        """Tasks in the ignore config are excluded from results."""
        fake = build_fake(
            coco8_fixtures,
            ["normal", "all-empty"],
            statuses=["completed", "completed"],
        )
        ignored_task_id = fake.tasks[1].id
        ignore_cfg = IgnoreConfig(
            projects={
                fake.project.name: [IgnoredTask(id=ignored_task_id, name="ignored")],
            },
        )
        args = make_fetch_args(
            project=str(fake.project.id),
            task=[fake.tasks[0].name],
            output_dir=str(tmp_path / "out"),
        )

        _run_fetch_task_with_fake(fake, args, ignore_config=ignore_cfg)

        df = pd.read_csv(tmp_path / "out" / "dataset.csv")
        task_ids_in_csv = set(df["task_id"].unique())
        assert fake.tasks[0].id in task_ids_in_csv
        assert ignored_task_id not in task_ids_in_csv

    def test_task_not_found_exits(
        self,
        coco8_fixtures: LoadedFixtures,
        tmp_path: Path,
    ) -> None:
        """Non-existent task name causes sys.exit via Cveta2Error."""
        fake = build_fake(coco8_fixtures, ["normal"], statuses=["completed"])
        args = make_fetch_args(
            project=str(fake.project.id),
            task=["nonexistent-task-xyz"],
            output_dir=str(tmp_path / "out"),
        )

        with pytest.raises(SystemExit):
            _run_fetch_task_with_fake(fake, args)
