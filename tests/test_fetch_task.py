"""Tests for the ``cveta2 fetch-task`` command and its helpers."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pandas as pd
import pytest

from cveta2.adapters.config.settings import (
    CvatConfig,
    IgnoreConfig,
    IgnoredTask,
    ImageCacheConfig,
    _parse_ignore_entry,
)
from cveta2.adapters.execution.concurrency import run_concurrent
from cveta2.application.client.fetch import (
    _filter_tasks_for_fetch,
    _select_tasks_for_fetch,
)
from cveta2.application.client.shared import _FetchAnnotationsOptions
from cveta2.application.use_cases.fetch import (
    FetchOptions,
    FetchTarget,
)
from cveta2.composition.client import CvatClient
from cveta2.composition.workflows import fetch_selected_tasks, load_ignore_sets
from cveta2.domain.errors import (
    CvatApiError,
    Cveta2Error,
    InteractiveModeRequiredError,
    TaskNotFoundError,
)
from cveta2.domain.models import CSV_COLUMNS, TaskInfo
from cveta2.interfaces.commands.fetch import (
    _resolve_images_dir,
    _resolve_task_selector,
    run_fetch_task,
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
    from collections.abc import Callable, Iterator

    from tests.fixtures.fake_cvat_project import LoadedFixtures

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MODULE = "cveta2.interfaces.commands.fetch"


# ---------------------------------------------------------------------------
# Unit tests: _resolve_task_selector
# ---------------------------------------------------------------------------


class TestResolveTaskSelector:
    """Tests for ``_resolve_task_selector``."""

    @pytest.mark.parametrize(
        "selectors",
        [
            lambda fake: [str(fake.tasks[0].id)],
            lambda fake: [fake.tasks[0].name],
            lambda fake: [str(t.id) for t in fake.tasks],
        ],
        ids=["id", "name", "several-in-order"],
    )
    def test_explicit_selectors_are_returned_as_given(
        self,
        coco8_fixtures: LoadedFixtures,
        selectors: Callable[[LoadedFixtures], list[str]],
    ) -> None:
        fake = build_fake(
            coco8_fixtures,
            ["normal", "all-empty"],
            statuses=["completed", "completed"],
        )
        wanted = selectors(fake)

        result = _resolve_task_selector(
            wanted, make_fake_client(fake), fake.project.id, None
        )

        assert result == wanted

    def test_no_explicit_tasks_triggers_tui(self, normal_fake: LoadedFixtures) -> None:
        """An empty list falls through to the interactive task picker."""
        fake = normal_fake
        client = make_fake_client(fake)

        with (
            patch(
                "cveta2.interfaces.commands.interactive.primitives.require_interactive",
                side_effect=InteractiveModeRequiredError("non-interactive"),
            ),
            pytest.raises(InteractiveModeRequiredError),
        ):
            _resolve_task_selector([], client, fake.project.id, None)


# ---------------------------------------------------------------------------
# Unit tests: load_ignore_sets
# ---------------------------------------------------------------------------


class TestWarnIgnoredTasks:
    """Tests for ``load_ignore_sets``."""

    @pytest.mark.parametrize(
        ("projects", "expected"),
        [
            ({}, (None, None)),
            ({"other-project": [IgnoredTask(id=10, name="t10")]}, (None, None)),
            (
                {
                    "my-project": [
                        IgnoredTask(id=10, name="t10"),
                        IgnoredTask(id=20, name="t20"),
                    ]
                },
                ({10, 20}, None),
            ),
            (
                {
                    "my-project": [
                        IgnoredTask(id=10, name="t10", silent=True),
                        IgnoredTask(id=20, name="t20"),
                        IgnoredTask(id=30, name="t30", silent=True),
                    ]
                },
                ({10, 20, 30}, {10, 30}),
            ),
        ],
        ids=["empty", "other-project", "loud-only", "silent-subset"],
    )
    def test_returns_ignored_and_silent_ids(
        self,
        projects: dict[str, list[IgnoredTask]],
        expected: tuple[set[int] | None, set[int] | None],
    ) -> None:
        with patch(
            "cveta2.adapters.config.settings.IgnoreConfig.load",
            return_value=IgnoreConfig(projects=projects),
        ):
            assert load_ignore_sets("my-project") == expected


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

        result, all_task_ids = _select_tasks_for_fetch(
            api, _PROJECT_ID, options, runner=run_concurrent, max_workers=1
        )

        assert [t.id for t in result] == [2, 3]
        assert all_task_ids is None
        assert api.call_counts["get_project_tasks"] == 0
        assert api.call_counts["get_task"] == 2

    def test_the_same_id_twice_is_requested_once(self) -> None:
        """Duplicate selectors collapse before any request is made."""
        api = FakeCvatApi.from_tasks([make_task(1), make_task(2)])
        options = _FetchAnnotationsOptions(task_selector=[2, "2"])

        result, all_task_ids = _select_tasks_for_fetch(
            api, _PROJECT_ID, options, runner=run_concurrent, max_workers=1
        )

        assert [t.id for t in result] == [2]
        assert all_task_ids is None
        assert api.call_counts["get_task"] == 1

    def test_completed_only_still_applies(self) -> None:
        """The status filter runs on the id path as it does on the listing."""
        api = FakeCvatApi.from_tasks(
            [make_task(1, status="completed"), make_task(2, status="annotation")]
        )
        options = _FetchAnnotationsOptions(task_selector=[1, 2], completed_only=True)

        result, all_task_ids = _select_tasks_for_fetch(
            api, _PROJECT_ID, options, runner=run_concurrent, max_workers=1
        )

        assert [t.id for t in result] == [1]
        assert all_task_ids is None

    def test_no_selector_lists_the_project(self) -> None:
        """A whole-project fetch still asks for every task."""
        api = FakeCvatApi.from_tasks([make_task(1), make_task(2)])

        result, all_task_ids = _select_tasks_for_fetch(
            api,
            _PROJECT_ID,
            _FetchAnnotationsOptions(),
            runner=run_concurrent,
            max_workers=1,
        )

        assert [t.id for t in result] == [1, 2]
        assert all_task_ids == frozenset({1, 2})
        assert api.call_counts["get_project_tasks"] == 1

    def test_name_selector_lists_the_project(self) -> None:
        """A name can only be matched against the full list."""
        api = FakeCvatApi.from_tasks([make_task(1, name="alpha"), make_task(2)])
        options = _FetchAnnotationsOptions(task_selector=["alpha"])

        result, all_task_ids = _select_tasks_for_fetch(
            api, _PROJECT_ID, options, runner=run_concurrent, max_workers=1
        )

        assert [t.id for t in result] == [1]
        assert all_task_ids == frozenset({1, 2})
        assert api.call_counts["get_project_tasks"] == 1
        assert api.call_counts["get_task"] == 0

    def test_one_name_among_ids_lists_the_project(self) -> None:
        """A single non-numeric selector sends the whole batch to the listing."""
        api = FakeCvatApi.from_tasks([make_task(1, name="alpha"), make_task(2)])
        options = _FetchAnnotationsOptions(task_selector=[2, "alpha"])

        result, all_task_ids = _select_tasks_for_fetch(
            api, _PROJECT_ID, options, runner=run_concurrent, max_workers=1
        )

        assert {t.id for t in result} == {1, 2}
        assert all_task_ids == frozenset({1, 2})
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

        result, all_task_ids = _select_tasks_for_fetch(
            api, _PROJECT_ID, options, runner=run_concurrent, max_workers=1
        )

        assert [t.id for t in result] == [7]
        assert all_task_ids == frozenset({7})
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
            _select_tasks_for_fetch(
                api, _PROJECT_ID, options, runner=run_concurrent, max_workers=1
            )

        assert excinfo.value.status_code == 500
        assert api.call_counts["get_project_tasks"] == 0

    def test_task_of_another_project_lists_the_project(self) -> None:
        """An id owned by a different project is the listing's to reject."""
        api = FakeCvatApi.from_tasks([make_task(1)])
        options = _FetchAnnotationsOptions(task_selector=[1])

        with pytest.raises(TaskNotFoundError):
            _select_tasks_for_fetch(
                api, _PROJECT_ID + 1, options, runner=run_concurrent, max_workers=1
            )

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
            _select_tasks_for_fetch(
                api, _PROJECT_ID, options, runner=run_concurrent, max_workers=1
            )

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

    @pytest.mark.parametrize("silent", [False, True], ids=["loud", "silent"])
    def test_ignored_task_is_filtered_and_warned_unless_silent(
        self, capture_logs: list[str], *, silent: bool
    ) -> None:
        options = _FetchAnnotationsOptions(
            ignore_task_ids={2},
            silent_task_ids={2} if silent else None,
        )

        result = _filter_tasks_for_fetch(self._make_tasks(), options)

        assert [t.id for t in result] == [1, 3]
        assert any("Пропускаем" in m for m in capture_logs) is not silent
        assert any("task-2" in m for m in capture_logs) is not silent

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

    @pytest.mark.parametrize(
        ("project", "expected"),
        [("proj", {1, 3}), ("loud", set()), ("never-configured", set())],
    )
    def test_get_silent_task_ids(self, project: str, expected: set[int]) -> None:
        """Only ``silent=True`` ids; an unconfigured project yields an empty set."""
        cfg = IgnoreConfig(
            projects={
                "proj": [
                    IgnoredTask(id=1, name="a", silent=True),
                    IgnoredTask(id=2, name="b"),
                    IgnoredTask(id=3, name="c", silent=True),
                ],
                "loud": [IgnoredTask(id=1, name="a")],
            },
        )
        assert cfg.get_silent_task_ids(project) == expected


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


# ---------------------------------------------------------------------------
# CLI smoke: run_fetch_task propagates Cveta2Error to the dispatch boundary
# ---------------------------------------------------------------------------


@contextmanager
def _patched_fetch_task_cli(fake: LoadedFixtures) -> Iterator[None]:
    """Route ``run_fetch_task`` onto *fake* with no ignore config or cloud storage."""
    fake_api = FakeCvatApi(fake)

    def make_client(cfg: CvatConfig, **_kw: object) -> CvatClient:
        return CvatClient(cfg, api=fake_api)

    with (
        patch_cli_client(factory=make_client, config=CFG),
        patch(
            "cveta2.adapters.config.settings.IgnoreConfig.load",
            return_value=IgnoreConfig(),
        ),
        patch(
            "cveta2.composition.client.CvatClient.detect_project_cloud_storage",
            return_value=None,
        ),
    ):
        yield


class TestRunFetchTaskProjectInference:
    """Without ``--project``, the project comes from the first numeric task id."""

    def test_infers_project_from_numeric_task_id(
        self,
        normal_fake: LoadedFixtures,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake = normal_fake
        monkeypatch.setenv("CVETA2_CONFIG", str(tmp_path / "missing-config.yaml"))
        args = make_fetch_args(
            project=None,
            task=[str(fake.tasks[0].id)],
            output_dir=str(tmp_path / "out"),
        )

        with _patched_fetch_task_cli(fake):
            run_fetch_task(args)

        assert (tmp_path / "out" / "dataset.csv").exists()


class TestRunFetchTaskTaskArgument:
    """``-t`` values are stripped once in ``run_fetch_task`` before dispatch."""

    @pytest.mark.parametrize("task", [None, [""], ["  "]])
    def test_blank_task_triggers_tui(
        self,
        normal_fake: LoadedFixtures,
        tmp_path: Path,
        task: list[str] | None,
    ) -> None:
        """No ``-t``, ``-t ""`` and ``-t "  "`` all open the task picker."""
        fake = normal_fake
        args = make_fetch_args(
            project=str(fake.project.id),
            task=task,
            output_dir=str(tmp_path / "out"),
        )

        with (
            _patched_fetch_task_cli(fake),
            patch(
                "cveta2.interfaces.commands.interactive.primitives.require_interactive",
                side_effect=InteractiveModeRequiredError("non-interactive"),
            ),
            pytest.raises(InteractiveModeRequiredError),
        ):
            run_fetch_task(args)

    def test_whitespace_only_values_filtered(
        self,
        normal_fake: LoadedFixtures,
        tmp_path: Path,
    ) -> None:
        """Blank ``-t`` values are dropped; the rest are stripped and kept."""
        fake = normal_fake
        task_name = fake.tasks[0].name
        args = make_fetch_args(
            project=str(fake.project.id),
            task=["  ", f" {task_name} ", ""],
            output_dir=str(tmp_path / "out"),
        )

        with (
            _patched_fetch_task_cli(fake),
            patch(f"{_MODULE}.fetch_selected_tasks") as fetch_mock,
        ):
            run_fetch_task(args)

        (_client, _target, options), _kwargs = fetch_mock.call_args
        assert options.task_selector == [task_name]


class TestRunFetchTaskCliExit:
    """``run_fetch_task`` raises ``Cveta2Error``; the CLI boundary exits."""

    def test_task_not_found_raises(
        self,
        normal_fake: LoadedFixtures,
        tmp_path: Path,
    ) -> None:
        """Non-existent task name raises ``TaskNotFoundError`` from the command."""
        fake = normal_fake
        args = make_fetch_args(
            project=str(fake.project.id),
            task=["nonexistent-task-xyz"],
            output_dir=str(tmp_path / "out"),
        )

        with _patched_fetch_task_cli(fake), pytest.raises(TaskNotFoundError):
            run_fetch_task(args)
