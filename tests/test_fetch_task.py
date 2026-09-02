"""Tests for the ``cveta2 fetch-task`` command and its helpers."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pandas as pd
import pytest

from cveta2._client_ops.fetch import (
    _filter_tasks_for_fetch,
    _select_tasks_for_fetch,
)
from cveta2._client_ops.shared import _FetchAnnotationsOptions
from cveta2.client import CvatClient
from cveta2.commands.fetch import (
    _resolve_images_dir,
    _resolve_task_selector,
    run_fetch_task,
)
from cveta2.config import (
    CvatConfig,
    IgnoreConfig,
    IgnoredTask,
    ImageCacheConfig,
    _parse_ignore_entry,
)
from cveta2.exceptions import (
    CvatApiError,
    Cveta2Error,
    InteractiveModeRequiredError,
    TaskNotFoundError,
)
from cveta2.models import CSV_COLUMNS, TaskInfo
from cveta2.services.fetch import (
    FetchOptions,
    FetchTarget,
    fetch_selected_tasks,
    load_ignore_sets,
)
from tests.fixtures.fake_cvat_api import FakeCvatApi
from tests.helpers import (
    CFG,
    build_fake,
    make_fake_client,
    make_fetch_args,
    make_task,
    patch_cli_client,
)

if TYPE_CHECKING:
    from tests.fixtures.fake_cvat_project import LoadedFixtures

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MODULE = "cveta2.commands.fetch"


# ---------------------------------------------------------------------------
# Unit tests: _resolve_task_selector
# ---------------------------------------------------------------------------


class TestResolveTaskSelector:
    """Tests for ``_resolve_task_selector``."""

    def test_explicit_task_id(self, normal_fake: LoadedFixtures) -> None:
        """Explicit task ID string is returned as-is."""
        fake = normal_fake
        client = make_fake_client(fake)
        task_id_str = str(fake.tasks[0].id)
        args = make_fetch_args(task=[task_id_str], output_dir="unused")

        result = _resolve_task_selector(args, client, fake.project.id, None)

        assert result == [task_id_str]

    def test_explicit_task_name(self, normal_fake: LoadedFixtures) -> None:
        """Explicit task name is returned as-is."""
        fake = normal_fake
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

    def test_empty_task_triggers_tui(self, normal_fake: LoadedFixtures) -> None:
        """``-t`` without a value (empty string) falls through to TUI."""
        fake = normal_fake
        client = make_fake_client(fake)
        args = make_fetch_args(task=[""], output_dir="unused")

        with (
            patch(
                "cveta2.commands.interactive.primitives.require_interactive",
                side_effect=InteractiveModeRequiredError("non-interactive"),
            ),
            pytest.raises(InteractiveModeRequiredError),
        ):
            _resolve_task_selector(args, client, fake.project.id, None)

    def test_none_task_triggers_tui(self, normal_fake: LoadedFixtures) -> None:
        """``task=None`` (no -t flag at all) falls through to TUI."""
        fake = normal_fake
        client = make_fake_client(fake)
        args = make_fetch_args(task=None, output_dir="unused")

        with (
            patch(
                "cveta2.commands.interactive.primitives.require_interactive",
                side_effect=InteractiveModeRequiredError("non-interactive"),
            ),
            pytest.raises(InteractiveModeRequiredError),
        ):
            _resolve_task_selector(args, client, fake.project.id, None)

    def test_whitespace_only_values_filtered(
        self,
        normal_fake: LoadedFixtures,
    ) -> None:
        """Whitespace-only task values are stripped and filtered out."""
        fake = normal_fake
        client = make_fake_client(fake)
        task_name = fake.tasks[0].name
        args = make_fetch_args(task=["  ", task_name, ""], output_dir="unused")

        result = _resolve_task_selector(args, client, fake.project.id, None)

        assert result == [task_name]


# ---------------------------------------------------------------------------
# Unit tests: load_ignore_sets
# ---------------------------------------------------------------------------


class TestWarnIgnoredTasks:
    """Tests for ``load_ignore_sets``."""

    def test_no_ignored_tasks(self) -> None:
        """Returns (None, None) when ignore config is empty for the project."""
        with patch(
            "cveta2.config.IgnoreConfig.load",
            return_value=IgnoreConfig(),
        ):
            ignore_set, silent_set = load_ignore_sets("my-project")

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
            "cveta2.config.IgnoreConfig.load",
            return_value=ignore_cfg,
        ):
            ignore_set, silent_set = load_ignore_sets("my-project")

        assert ignore_set == {10, 20, 30}
        assert silent_set is None

    def test_different_project_returns_none(self) -> None:
        """Returns (None, None) when the project is not in the ignore config."""
        ignore_cfg = IgnoreConfig(
            projects={"other-project": [IgnoredTask(id=10, name="t10")]},
        )
        with patch(
            "cveta2.config.IgnoreConfig.load",
            return_value=ignore_cfg,
        ):
            ignore_set, silent_set = load_ignore_sets("my-project")

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
            "cveta2.config.IgnoreConfig.load",
            return_value=ignore_cfg,
        ):
            ignore_set, silent_set = load_ignore_sets("my-project")

        assert ignore_set == {10, 20, 30}
        assert silent_set == {10, 30}


# ---------------------------------------------------------------------------
# Unit tests: _select_tasks_for_fetch (numeric selectors skip the task listing)
# ---------------------------------------------------------------------------

_PROJECT_ID = 1


def _raise_server_error(task_id: int) -> TaskInfo:
    """Stand in for a CVAT that is down rather than missing the task."""
    raise CvatApiError(f"boom on {task_id}", status_code=500)


class TestSelectTasksForFetch:
    """Numeric selectors are retrieved by id; everything else lists the project.

    Listing a project to find one task in it costs a serial page walk that
    grows with the project, so the id path must stay off it.  Each fallback
    below is a case the listing still owns, and every one of them ends in an
    error or a skip — which is what keeps the listing off the happy path.
    """

    def test_numeric_ids_are_retrieved_one_by_one(self) -> None:
        """Ids reach ``get_task`` directly, and the project is never listed."""
        api = FakeCvatApi.from_tasks([make_task(1), make_task(2), make_task(3)])
        options = _FetchAnnotationsOptions(task_selector=["2", 3])

        result = _select_tasks_for_fetch(api, _PROJECT_ID, options)

        assert [t.id for t in result] == [2, 3]
        assert api.call_counts["get_project_tasks"] == 0
        assert api.call_counts["get_task"] == 2

    def test_the_same_id_twice_is_requested_once(self) -> None:
        """Duplicate selectors collapse before any request is made."""
        api = FakeCvatApi.from_tasks([make_task(1), make_task(2)])
        options = _FetchAnnotationsOptions(task_selector=[2, "2"])

        result = _select_tasks_for_fetch(api, _PROJECT_ID, options)

        assert [t.id for t in result] == [2]
        assert api.call_counts["get_task"] == 1

    def test_completed_only_still_applies(self) -> None:
        """The status filter runs on the id path as it does on the listing."""
        api = FakeCvatApi.from_tasks(
            [make_task(1, status="completed"), make_task(2, status="annotation")]
        )
        options = _FetchAnnotationsOptions(task_selector=[1, 2], completed_only=True)

        result = _select_tasks_for_fetch(api, _PROJECT_ID, options)

        assert [t.id for t in result] == [1]

    def test_no_selector_lists_the_project(self) -> None:
        """A whole-project fetch still asks for every task."""
        api = FakeCvatApi.from_tasks([make_task(1), make_task(2)])

        result = _select_tasks_for_fetch(api, _PROJECT_ID, _FetchAnnotationsOptions())

        assert [t.id for t in result] == [1, 2]
        assert api.call_counts["get_project_tasks"] == 1

    def test_name_selector_lists_the_project(self) -> None:
        """A name can only be matched against the full list."""
        api = FakeCvatApi.from_tasks([make_task(1, name="alpha"), make_task(2)])
        options = _FetchAnnotationsOptions(task_selector=["alpha"])

        result = _select_tasks_for_fetch(api, _PROJECT_ID, options)

        assert [t.id for t in result] == [1]
        assert api.call_counts["get_project_tasks"] == 1
        assert api.call_counts["get_task"] == 0

    def test_one_name_among_ids_lists_the_project(self) -> None:
        """A single non-numeric selector sends the whole batch to the listing."""
        api = FakeCvatApi.from_tasks([make_task(1, name="alpha"), make_task(2)])
        options = _FetchAnnotationsOptions(task_selector=[2, "alpha"])

        result = _select_tasks_for_fetch(api, _PROJECT_ID, options)

        assert {t.id for t in result} == {1, 2}
        assert api.call_counts["get_project_tasks"] == 1
        assert api.call_counts["get_task"] == 0

    def test_unknown_id_falls_back_to_a_name_match(self) -> None:
        """A digit string names a task when no task carries it as an id.

        The listing path matches by id first and by name second, so a task
        literally called ``"12345"`` is reachable by that selector.  Taking
        the id shortcut must not turn that into "task not found".
        """
        api = FakeCvatApi.from_tasks([make_task(7, name="12345")])
        options = _FetchAnnotationsOptions(task_selector=["12345"])

        result = _select_tasks_for_fetch(api, _PROJECT_ID, options)

        assert [t.id for t in result] == [7]
        assert api.call_counts["get_project_tasks"] == 1

    def test_a_server_error_on_the_id_lookup_is_not_a_fallback(self) -> None:
        """Only a 404 means "ask the listing"; a 5xx is CVAT being broken.

        Falling back on any failure would hide an outage behind a slow
        path that is about to fail the same way.
        """
        api = FakeCvatApi.from_tasks([make_task(1)])
        api.get_task = _raise_server_error  # type: ignore[method-assign]
        options = _FetchAnnotationsOptions(task_selector=[1])

        with pytest.raises(CvatApiError) as excinfo:
            _select_tasks_for_fetch(api, _PROJECT_ID, options)

        assert excinfo.value.status_code == 500
        assert api.call_counts["get_project_tasks"] == 0

    def test_task_of_another_project_lists_the_project(self) -> None:
        """An id owned by a different project is the listing's to reject."""
        api = FakeCvatApi.from_tasks([make_task(1)])
        options = _FetchAnnotationsOptions(task_selector=[1])

        with pytest.raises(TaskNotFoundError):
            _select_tasks_for_fetch(api, _PROJECT_ID + 1, options)

        assert api.call_counts["get_project_tasks"] == 1

    def test_ignored_id_still_raises_task_not_found(self) -> None:
        """Asking for an ignored task fails; it must not fetch nothing quietly.

        The listing drops ignored tasks *before* resolving the selector, so
        the id never matches.  Filtering after an id lookup would instead
        write an empty dataset and exit successfully.
        """
        api = FakeCvatApi.from_tasks([make_task(1), make_task(2)])
        options = _FetchAnnotationsOptions(task_selector=[2], ignore_task_ids={2})

        with pytest.raises(TaskNotFoundError):
            _select_tasks_for_fetch(api, _PROJECT_ID, options)

        assert api.call_counts["get_project_tasks"] == 1


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
        """The saved ignore entry includes ``silent`` only when True."""
        raw = IgnoreConfig(projects={"p": [entry]})._to_raw()
        assert isinstance(raw, dict)
        data = raw["p"][0]
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

    def test_get_silent_task_ids_unknown_project(self) -> None:
        """An unconfigured project yields an empty set, not an error.

        Every earlier call passed a project that was present, so the ``[]``
        default of the lookup was never used.
        """
        assert IgnoreConfig().get_silent_task_ids("never-configured") == set()


class TestParseIgnoreEntry:
    """Tests for ``_parse_ignore_entry``'s three accepted input shapes.

    The only earlier coverage was the ``silent`` flag on the dict form, which
    left the legacy formats (bare int, digit string) and every default of the
    dict form unexercised.
    """

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (
                {"id": 7, "name": "t7", "description": "why", "silent": True},
                IgnoredTask(id=7, name="t7", description="why", silent=True),
            ),
            ({"id": "8"}, IgnoredTask(id=8, name="", description="", silent=False)),
            (9, IgnoredTask(id=9, name="")),
            ("10", IgnoredTask(id=10, name="")),
            (" 11 ", IgnoredTask(id=11, name="")),
        ],
        ids=["full_dict", "id_only_dict", "legacy_int", "digit_str", "padded_digits"],
    )
    def test_accepted_shapes(self, raw: object, expected: IgnoredTask) -> None:
        """Both legacy formats parse, and the dict form's defaults are blank."""
        assert _parse_ignore_entry(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        [{"id": "abc"}, {"name": "no id"}, "abc", None, [1], 1.5],
        ids=["bad_id", "dict_without_id", "non_digit_str", "none", "list", "float"],
    )
    def test_rejected_shapes(self, raw: object) -> None:
        """Anything else is dropped rather than raising into the config load.

        ``dict_without_id`` is what pins the ``and`` in the first guard: with
        ``or`` the branch is entered for every dict and ``raw["id"]`` raises a
        ``KeyError`` the surrounding ``except`` does not catch.
        """
        assert _parse_ignore_entry(raw) is None


class TestIgnoreConfigEntries:
    """Tests for adding and removing entries on ``IgnoreConfig``."""

    def test_add_task_defaults_to_a_blank_loud_entry(self) -> None:
        """Omitted ``description``/``silent`` must land as ``""`` / ``False``."""
        cfg = IgnoreConfig()

        cfg.add_task("proj", 1, "one")

        entry = cfg.get_ignored_entries("proj")[0]
        assert entry.description == ""
        assert entry.silent is False

    def test_add_task_stores_the_description(self) -> None:
        """The description reaches the entry rather than being dropped."""
        cfg = IgnoreConfig()

        cfg.add_task("proj", 1, "one", "flaky annotations")

        assert cfg.get_ignored_entries("proj")[0].description == "flaky annotations"

    def test_add_task_appends_new_ids_and_ignores_duplicates(self) -> None:
        """The duplicate guard must match on the id, not on "any other id".

        A single-entry project cannot tell ``e.id == task_id`` from
        ``e.id != task_id``; adding a second, different task can.
        """
        cfg = IgnoreConfig()

        cfg.add_task("proj", 1, "one")
        cfg.add_task("proj", 2, "two")
        cfg.add_task("proj", 1, "one-again")

        assert cfg.get_ignored_tasks("proj") == [1, 2]

    def test_add_task_reports_whether_anything_was_added(self) -> None:
        """A repeat id is left exactly as it was, and the caller learns so.

        The command layer turns ``False`` into a warning; a batch
        ``cveta2.ignore("p", add=[...])`` with default flags must never blank
        an earlier description or un-silence an entry.
        """
        cfg = IgnoreConfig()

        assert cfg.add_task("proj", 1, "one", "flaky", silent=True) is True
        assert cfg.add_task("proj", 1, "one-again", "other") is False

        entry = cfg.get_ignored_entries("proj")[0]
        assert (entry.name, entry.description, entry.silent) == (
            "one",
            "flaky",
            True,
        )

    def test_remove_task_keeps_the_project_while_entries_remain(self) -> None:
        """The project key is deleted only once its last entry is gone."""
        cfg = IgnoreConfig(
            projects={
                "proj": [IgnoredTask(id=1, name="a"), IgnoredTask(id=2, name="b")]
            }
        )

        assert cfg.remove_task("proj", 1) is True
        assert cfg.get_ignored_tasks("proj") == [2]

        assert cfg.remove_task("proj", 2) is True
        assert cfg.projects == {}

    def test_remove_task_reports_false_for_unknown_project_or_id(self) -> None:
        """A miss returns False and leaves the list untouched."""
        cfg = IgnoreConfig(projects={"proj": [IgnoredTask(id=1, name="a")]})

        assert cfg.remove_task("proj", 99) is False
        assert cfg.remove_task("never-configured", 1) is False
        assert cfg.get_ignored_tasks("proj") == [1]


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

        with patch(f"{_MODULE}.ImageCacheConfig.load"):
            result = _resolve_images_dir(args, "project-x")

        assert result == images_dir.resolve()

    def test_cached_dir_from_config(self) -> None:
        """Returns cached directory from image cache config."""
        cached_path = Path("/data/images/project-x")
        ic_cfg = ImageCacheConfig(projects={"project-x": cached_path})
        args = argparse.Namespace(no_images=False, images_dir=None)

        with patch(
            f"{_MODULE}.ImageCacheConfig.load",
            return_value=ic_cfg,
        ):
            result = _resolve_images_dir(args, "project-x")

        assert result == cached_path

    def test_non_interactive_exits_when_no_config(self) -> None:
        """Raises when no images dir is configured and interactive is disabled."""
        args = argparse.Namespace(no_images=False, images_dir=None)

        with (
            patch(
                f"{_MODULE}.ImageCacheConfig.load",
                return_value=ImageCacheConfig(),
            ),
            patch(f"{_MODULE}.is_interactive_disabled", return_value=True),
            pytest.raises(Cveta2Error),
        ):
            _resolve_images_dir(args, "project-x")

    def test_interactive_prompt_empty_returns_none(self) -> None:
        """Interactive mode with empty path input returns None."""
        args = argparse.Namespace(no_images=False, images_dir=None)

        with (
            patch(
                f"{_MODULE}.ImageCacheConfig.load",
                return_value=ImageCacheConfig(),
            ),
            patch(f"{_MODULE}.is_interactive_disabled", return_value=False),
            patch(f"{_MODULE}.interactive.path", return_value=None),
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
                f"{_MODULE}.ImageCacheConfig.load",
                return_value=ic_cfg,
            ),
            patch(f"{_MODULE}.is_interactive_disabled", return_value=False),
            patch(
                f"{_MODULE}.interactive.path",
                return_value=Path(entered_path).resolve(),
            ),
            patch(f"{_MODULE}.ImageCacheConfig.save") as mock_save,
        ):
            result = _resolve_images_dir(args, "project-x")

        assert result == Path(entered_path).resolve()
        mock_save.assert_called_once_with()
        assert ic_cfg.get_cache_dir("project-x") == Path(entered_path).resolve()


# ---------------------------------------------------------------------------
# Service tests: fetch_selected_tasks
# ---------------------------------------------------------------------------


class TestFetchSelectedTasks:
    """Tests for ``fetch_selected_tasks`` (fetch-task at the service layer)."""

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

        fetch_selected_tasks(
            make_fake_client(fake),
            FetchTarget(fake.project.id, fake.project.name, out_dir, None),
            FetchOptions(
                task_selector=[t.name for t in fake.tasks],
                use_cache=False,
            ),
        )

        dataset_csv = out_dir / "dataset.csv"
        deleted_csv = out_dir / "deleted.csv"
        assert dataset_csv.exists()
        assert deleted_csv.exists()

        df = pd.read_csv(dataset_csv)
        assert set(df.columns) == set(CSV_COLUMNS)

        task_ids_in_csv = set(df["task_id"].unique())
        assert {fake.tasks[0].id, fake.tasks[1].id}.issubset(task_ids_in_csv)

        # This test owns CSV *writing*; annotation-count semantics are covered
        # by test_fetch_service.py::test_mixed_tasks_aggregation. Assert only
        # that bbox rows carry coords and "none" rows leave them empty.
        bbox_rows = df[df["instance_shape"] == "box"]
        assert len(bbox_rows) > 0
        for col in ("bbox_x_tl", "bbox_y_tl", "bbox_x_br", "bbox_y_br"):
            assert bbox_rows[col].notna().all()

        without_rows = df[df["instance_shape"] == "none"]
        for col in ("bbox_x_tl", "bbox_y_tl", "bbox_x_br", "bbox_y_br"):
            assert without_rows[col].isna().all()

        deleted_df = pd.read_csv(deleted_csv)
        assert set(CSV_COLUMNS).issubset(set(deleted_df.columns))
        assert (deleted_df["instance_shape"] == "deleted").all()

    def test_ignored_tasks_excluded(
        self,
        coco8_fixtures: LoadedFixtures,
        tmp_path: Path,
    ) -> None:
        """Tasks in ``ignore_task_ids`` are excluded from results."""
        fake = build_fake(
            coco8_fixtures,
            ["normal", "all-empty"],
            statuses=["completed", "completed"],
        )
        ignored_task_id = fake.tasks[1].id
        out_dir = tmp_path / "out"

        fetch_selected_tasks(
            make_fake_client(fake),
            FetchTarget(fake.project.id, fake.project.name, out_dir, None),
            FetchOptions(
                task_selector=[fake.tasks[0].name],
                ignore_task_ids={ignored_task_id},
                use_cache=False,
            ),
        )

        df = pd.read_csv(out_dir / "dataset.csv")
        task_ids_in_csv = set(df["task_id"].unique())
        assert fake.tasks[0].id in task_ids_in_csv
        assert ignored_task_id not in task_ids_in_csv

    def test_numeric_selector_matches_the_name_selector_without_listing(
        self,
        coco8_fixtures: LoadedFixtures,
        tmp_path: Path,
    ) -> None:
        """Fetching by id writes what fetching by name writes, minus the listing.

        The name selector still walks the project task list, so it is the
        reference the id shortcut has to reproduce byte for byte.
        """
        fake = build_fake(
            coco8_fixtures,
            ["normal", "all-empty"],
            statuses=["completed", "completed"],
        )
        by_name_api = FakeCvatApi(fake)
        by_id_api = FakeCvatApi(fake)
        by_name = tmp_path / "by-name"
        by_id = tmp_path / "by-id"

        for api, out_dir, selector in (
            (by_name_api, by_name, [t.name for t in fake.tasks]),
            (by_id_api, by_id, [t.id for t in fake.tasks]),
        ):
            fetch_selected_tasks(
                CvatClient(CFG, api=api),
                FetchTarget(fake.project.id, fake.project.name, out_dir, None),
                FetchOptions(task_selector=list(selector), use_cache=False),
            )

        for name in ("dataset.csv", "deleted.csv"):
            assert (by_id / name).read_bytes() == (by_name / name).read_bytes()
        assert by_name_api.call_counts["get_project_tasks"] == 1
        assert by_id_api.call_counts["get_project_tasks"] == 0
        assert by_id_api.call_counts["get_task"] == len(fake.tasks)

    def test_task_not_found_raises(
        self,
        normal_fake: LoadedFixtures,
        tmp_path: Path,
    ) -> None:
        """Non-existent task selector raises ``TaskNotFoundError``."""
        fake = normal_fake

        with pytest.raises(TaskNotFoundError):
            fetch_selected_tasks(
                make_fake_client(fake),
                FetchTarget(fake.project.id, fake.project.name, tmp_path / "out", None),
                FetchOptions(
                    task_selector=["nonexistent-task-xyz"],
                    use_cache=False,
                ),
            )


# ---------------------------------------------------------------------------
# CLI smoke: run_fetch_task propagates Cveta2Error to the dispatch boundary
# ---------------------------------------------------------------------------


class TestRunFetchTaskProjectInference:
    """Without ``--project``, the project comes from the first numeric task id."""

    def test_infers_project_from_numeric_task_id(
        self,
        normal_fake: LoadedFixtures,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake = normal_fake
        fake_api = FakeCvatApi(fake)
        monkeypatch.setenv("CVETA2_CONFIG", str(tmp_path / "missing-config.yaml"))

        def make_client(cfg: CvatConfig, **_kw: object) -> CvatClient:
            return CvatClient(cfg, api=fake_api)

        args = make_fetch_args(
            project=None,
            task=[str(fake.tasks[0].id)],
            output_dir=str(tmp_path / "out"),
        )

        with (
            patch_cli_client(factory=make_client, config=CFG),
            patch(
                "cveta2.config.IgnoreConfig.load",
                return_value=IgnoreConfig(),
            ),
            patch(
                "cveta2.client.CvatClient.detect_project_cloud_storage",
                return_value=None,
            ),
        ):
            run_fetch_task(args)

        assert (tmp_path / "out" / "dataset.csv").exists()


class TestRunFetchTaskCliExit:
    """``run_fetch_task`` raises ``Cveta2Error``; the CLI boundary exits."""

    def test_task_not_found_raises(
        self,
        normal_fake: LoadedFixtures,
        tmp_path: Path,
    ) -> None:
        """Non-existent task name raises ``TaskNotFoundError`` from the command."""
        fake = normal_fake
        fake_api = FakeCvatApi(fake)

        def make_client(cfg: CvatConfig, **_kw: object) -> CvatClient:
            return CvatClient(cfg, api=fake_api)

        args = make_fetch_args(
            project=str(fake.project.id),
            task=["nonexistent-task-xyz"],
            output_dir=str(tmp_path / "out"),
        )

        with (
            patch_cli_client(factory=make_client, config=CFG),
            patch(
                "cveta2.config.IgnoreConfig.load",
                return_value=IgnoreConfig(),
            ),
            patch(
                "cveta2.client.CvatClient.detect_project_cloud_storage",
                return_value=None,
            ),
            pytest.raises(TaskNotFoundError),
        ):
            run_fetch_task(args)
