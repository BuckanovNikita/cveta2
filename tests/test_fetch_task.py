"""Tests for the ``cveta2 fetch-task`` command and its helpers."""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from cveta2.client import CvatClient
from cveta2.commands.fetch import (
    _resolve_images_dir,
    _resolve_task_selector,
    _warn_ignored_tasks,
    run_fetch_task,
)
from cveta2.config import CvatConfig, IgnoreConfig, IgnoredTask, ImageCacheConfig
from cveta2.exceptions import InteractiveModeRequiredError
from cveta2.models import CSV_COLUMNS
from tests.fixtures.fake_cvat_api import FakeCvatApi
from tests.fixtures.fake_cvat_project import (
    FakeProjectConfig,
    LoadedFixtures,
    build_fake_project,
    task_indices_by_names,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CFG = CvatConfig(host="http://fake-cvat")

_MODULE = "cveta2.commands.fetch"


def _build(
    base: LoadedFixtures,
    task_names: list[str],
    statuses: list[str] | None = None,
    **kwargs: object,
) -> LoadedFixtures:
    """Build a fake project from named base tasks with optional statuses."""
    indices = task_indices_by_names(base.tasks, task_names)
    config = FakeProjectConfig(
        task_indices=indices,
        task_statuses=statuses if statuses is not None else "keep",
        **kwargs,  # type: ignore[arg-type]
    )
    return build_fake_project(base, config)


def _client(fixtures: LoadedFixtures) -> CvatClient:
    """Create a CvatClient backed by fake API data."""
    return CvatClient(_CFG, api=FakeCvatApi(fixtures))


def _make_args(
    *,
    project: str | None = "1",
    task: list[str] | None = None,
    output_dir: str,
    completed_only: bool = False,
    no_images: bool = True,
) -> argparse.Namespace:
    """Build an argparse.Namespace that mimics parsed fetch-task CLI args."""
    return argparse.Namespace(
        project=project,
        task=task,
        output_dir=output_dir,
        completed_only=completed_only,
        no_images=no_images,
        images_dir=None,
    )


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
        patch(f"{_MODULE}.load_config", return_value=_CFG),
        patch(f"{_MODULE}.require_host"),
        patch(f"{_MODULE}.load_projects_cache", return_value=[]),
        patch(f"{_MODULE}.load_ignore_config", return_value=ic),
        patch(f"{_MODULE}.CvatClient", side_effect=make_client),
    ):
        run_fetch_task(args)


# ---------------------------------------------------------------------------
# Unit tests: _resolve_task_selector
# ---------------------------------------------------------------------------


class TestResolveTaskSelector:
    """Tests for ``_resolve_task_selector``."""

    def test_explicit_task_id(self, coco8_fixtures: LoadedFixtures) -> None:
        """Explicit task ID string is returned as-is."""
        fake = _build(coco8_fixtures, ["normal"], statuses=["completed"])
        client = _client(fake)
        task_id_str = str(fake.tasks[0].id)
        args = _make_args(task=[task_id_str], output_dir="unused")

        result = _resolve_task_selector(args, client, fake.project.id, None)

        assert result == [task_id_str]

    def test_explicit_task_name(self, coco8_fixtures: LoadedFixtures) -> None:
        """Explicit task name is returned as-is."""
        fake = _build(coco8_fixtures, ["normal"], statuses=["completed"])
        client = _client(fake)
        task_name = fake.tasks[0].name
        args = _make_args(task=[task_name], output_dir="unused")

        result = _resolve_task_selector(args, client, fake.project.id, None)

        assert result == [task_name]

    def test_multiple_explicit_tasks(self, coco8_fixtures: LoadedFixtures) -> None:
        """Multiple -t values are returned in order."""
        fake = _build(
            coco8_fixtures,
            ["normal", "all-empty"],
            statuses=["completed", "completed"],
        )
        client = _client(fake)
        ids = [str(t.id) for t in fake.tasks]
        args = _make_args(task=ids, output_dir="unused")

        result = _resolve_task_selector(args, client, fake.project.id, None)

        assert result == ids

    def test_empty_task_triggers_tui(self, coco8_fixtures: LoadedFixtures) -> None:
        """``-t`` without a value (empty string) falls through to TUI."""
        fake = _build(coco8_fixtures, ["normal"], statuses=["completed"])
        client = _client(fake)
        args = _make_args(task=[""], output_dir="unused")

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
        fake = _build(coco8_fixtures, ["normal"], statuses=["completed"])
        client = _client(fake)
        args = _make_args(task=None, output_dir="unused")

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
        fake = _build(coco8_fixtures, ["normal"], statuses=["completed"])
        client = _client(fake)
        task_name = fake.tasks[0].name
        args = _make_args(task=["  ", task_name, ""], output_dir="unused")

        result = _resolve_task_selector(args, client, fake.project.id, None)

        assert result == [task_name]


# ---------------------------------------------------------------------------
# Unit tests: _warn_ignored_tasks
# ---------------------------------------------------------------------------


class TestWarnIgnoredTasks:
    """Tests for ``_warn_ignored_tasks``."""

    def test_no_ignored_tasks(self) -> None:
        """Returns None when ignore config is empty for the project."""
        with patch(
            f"{_MODULE}.load_ignore_config",
            return_value=IgnoreConfig(),
        ):
            result = _warn_ignored_tasks("my-project")

        assert result is None

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
            result = _warn_ignored_tasks("my-project")

        assert result == {10, 20, 30}

    def test_different_project_returns_none(self) -> None:
        """Returns None when the project is not in the ignore config."""
        ignore_cfg = IgnoreConfig(
            projects={"other-project": [IgnoredTask(id=10, name="t10")]},
        )
        with patch(
            f"{_MODULE}.load_ignore_config",
            return_value=ignore_cfg,
        ):
            result = _warn_ignored_tasks("my-project")

        assert result is None


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

    def test_happy_path_output_files(
        self,
        coco8_fixtures: LoadedFixtures,
        tmp_path: Path,
    ) -> None:
        """Normal single-task fetch writes dataset.csv and deleted.txt."""
        fake = _build(coco8_fixtures, ["normal"], statuses=["completed"])
        task_name = fake.tasks[0].name
        args = _make_args(
            project=str(fake.project.id),
            task=[task_name],
            output_dir=str(tmp_path / "out"),
        )

        _run_fetch_task_with_fake(fake, args)

        dataset_csv = tmp_path / "out" / "dataset.csv"
        deleted_txt = tmp_path / "out" / "deleted.txt"
        assert dataset_csv.exists()
        assert deleted_txt.exists()

        df = pd.read_csv(dataset_csv)
        assert len(df) > 0
        assert set(CSV_COLUMNS).issubset(set(df.columns))

        deleted_content = deleted_txt.read_text(encoding="utf-8").strip()
        assert deleted_content == ""

    def test_output_csv_has_all_columns(
        self,
        coco8_fixtures: LoadedFixtures,
        tmp_path: Path,
    ) -> None:
        """Output dataset.csv contains all canonical CSV_COLUMNS."""
        fake = _build(coco8_fixtures, ["normal"], statuses=["completed"])
        args = _make_args(
            project=str(fake.project.id),
            task=[fake.tasks[0].name],
            output_dir=str(tmp_path / "out"),
        )

        _run_fetch_task_with_fake(fake, args)

        df = pd.read_csv(tmp_path / "out" / "dataset.csv")
        assert set(df.columns) == set(CSV_COLUMNS)

    def test_with_deleted_frames(
        self,
        coco8_fixtures: LoadedFixtures,
        tmp_path: Path,
    ) -> None:
        """Task with deleted frames writes image names to deleted.txt."""
        fake = _build(coco8_fixtures, ["all-removed"], statuses=["completed"])
        args = _make_args(
            project=str(fake.project.id),
            task=[fake.tasks[0].name],
            output_dir=str(tmp_path / "out"),
        )

        _run_fetch_task_with_fake(fake, args)

        deleted_txt = tmp_path / "out" / "deleted.txt"
        deleted_names = deleted_txt.read_text(encoding="utf-8").strip().splitlines()
        assert len(deleted_names) == 8

    def test_completed_only_filter(
        self,
        coco8_fixtures: LoadedFixtures,
        tmp_path: Path,
    ) -> None:
        """``--completed-only`` skips non-completed tasks."""
        fake = _build(
            coco8_fixtures,
            ["normal", "all-empty"],
            statuses=["completed", "annotation"],
        )
        args = _make_args(
            project=str(fake.project.id),
            task=[fake.tasks[0].name, fake.tasks[1].name],
            output_dir=str(tmp_path / "out"),
            completed_only=True,
        )

        _run_fetch_task_with_fake(fake, args)

        df = pd.read_csv(tmp_path / "out" / "dataset.csv")
        task_ids_in_csv = set(df["task_id"].unique())
        assert fake.tasks[0].id in task_ids_in_csv
        assert fake.tasks[1].id not in task_ids_in_csv

    def test_ignored_tasks_excluded(
        self,
        coco8_fixtures: LoadedFixtures,
        tmp_path: Path,
    ) -> None:
        """Tasks in the ignore config are excluded from results."""
        fake = _build(
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
        args = _make_args(
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
        fake = _build(coco8_fixtures, ["normal"], statuses=["completed"])
        args = _make_args(
            project=str(fake.project.id),
            task=["nonexistent-task-xyz"],
            output_dir=str(tmp_path / "out"),
        )

        with pytest.raises(SystemExit):
            _run_fetch_task_with_fake(fake, args)

    def test_multiple_tasks_combined(
        self,
        coco8_fixtures: LoadedFixtures,
        tmp_path: Path,
    ) -> None:
        """Fetching multiple tasks combines annotations in output."""
        fake = _build(
            coco8_fixtures,
            ["normal", "all-empty"],
            statuses=["completed", "completed"],
        )
        args = _make_args(
            project=str(fake.project.id),
            task=[fake.tasks[0].name, fake.tasks[1].name],
            output_dir=str(tmp_path / "out"),
        )

        _run_fetch_task_with_fake(fake, args)

        df = pd.read_csv(tmp_path / "out" / "dataset.csv")
        task_ids_in_csv = set(df["task_id"].unique())
        assert fake.tasks[0].id in task_ids_in_csv
        assert fake.tasks[1].id in task_ids_in_csv

    def test_output_dir_created_if_missing(
        self,
        coco8_fixtures: LoadedFixtures,
        tmp_path: Path,
    ) -> None:
        """Output directory is created automatically when it does not exist."""
        fake = _build(coco8_fixtures, ["normal"], statuses=["completed"])
        out_dir = tmp_path / "nested" / "deep" / "output"
        args = _make_args(
            project=str(fake.project.id),
            task=[fake.tasks[0].name],
            output_dir=str(out_dir),
        )

        _run_fetch_task_with_fake(fake, args)

        assert (out_dir / "dataset.csv").exists()
        assert (out_dir / "deleted.txt").exists()

    def test_bbox_annotations_in_csv(
        self,
        coco8_fixtures: LoadedFixtures,
        tmp_path: Path,
    ) -> None:
        """BBox annotations appear in the CSV with valid bbox coordinates."""
        fake = _build(coco8_fixtures, ["normal"], statuses=["completed"])
        args = _make_args(
            project=str(fake.project.id),
            task=[fake.tasks[0].name],
            output_dir=str(tmp_path / "out"),
        )

        _run_fetch_task_with_fake(fake, args)

        df = pd.read_csv(tmp_path / "out" / "dataset.csv")
        bbox_rows = df[df["instance_shape"] == "box"]
        assert len(bbox_rows) > 0
        for col in ("bbox_x_tl", "bbox_y_tl", "bbox_x_br", "bbox_y_br"):
            assert bbox_rows[col].notna().all()

    def test_without_annotations_rows_in_csv(
        self,
        coco8_fixtures: LoadedFixtures,
        tmp_path: Path,
    ) -> None:
        """Images without annotations appear as instance_shape='none' rows."""
        fake = _build(coco8_fixtures, ["all-empty"], statuses=["completed"])
        args = _make_args(
            project=str(fake.project.id),
            task=[fake.tasks[0].name],
            output_dir=str(tmp_path / "out"),
        )

        _run_fetch_task_with_fake(fake, args)

        df = pd.read_csv(tmp_path / "out" / "dataset.csv")
        without_rows = df[df["instance_shape"] == "none"]
        assert len(without_rows) == 8
        for col in ("bbox_x_tl", "bbox_y_tl", "bbox_x_br", "bbox_y_br"):
            assert without_rows[col].isna().all()
