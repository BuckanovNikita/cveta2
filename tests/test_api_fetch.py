"""Public API fetch contracts."""

import re
from typing import TYPE_CHECKING
from unittest.mock import patch

import pandas as pd
import pytest

import cveta2
from cveta2.domain.errors import (
    Cveta2Error,
    TaskNotFoundError,
)
from cveta2.domain.models import CSV_COLUMNS
from cveta2.interfaces.api.fetch import _resolve_images_dir
from tests.helpers import (
    build_fake,
    fake_connection,
    make_cs_info,
    write_config_yaml,
)

if TYPE_CHECKING:
    from pathlib import Path

    from tests.api_helpers import _ProjectScopedApi
    from tests.fixtures.fake_cvat_project import LoadedFixtures

from tests.api_helpers import _scoped


def _images_dir(
    images_dir: "str | Path | None",
    project_name: str,
    config_path: "Path | None",
    *,
    download: bool,
) -> "Path | None":
    """Call ``_resolve_images_dir`` with its boolean passed by keyword."""
    return _resolve_images_dir(images_dir, download, project_name, config_path)


class TestImagesDirResolution:
    """The four-branch precedence chain of ``_resolve_images_dir``."""

    def test_download_disabled_returns_none(self) -> None:
        assert _images_dir(None, "proj", None, download=False) is None

    def test_conflicting_arguments_rejected(self, tmp_path: "Path") -> None:
        with pytest.raises(Cveta2Error, match="несовместимы"):
            _images_dir(tmp_path, "proj", None, download=False)

    def test_explicit_dir_wins_and_is_made_absolute(
        self, tmp_path: "Path", monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Only a returned path shows that ``images_dir`` reached ``Path()``.

        The pre-existing tests all took the error branch, where the
        argument is merely truthy, so nulling it changed nothing.
        """
        monkeypatch.chdir(tmp_path)

        resolved = _images_dir("imgs", "proj", None, download=True)

        assert resolved == (tmp_path / "imgs").resolve()

    def test_falls_back_to_the_configured_image_cache(self, tmp_path: "Path") -> None:
        """Both the project name and the explicit config path must survive.

        The configured directory is reachable only when
        ``resolve_images_cache_dir`` gets both arguments intact; dropping
        or nulling either one lands on the final ``raise`` instead.
        """
        cache_dir = tmp_path / "cached-images"
        config = write_config_yaml(
            tmp_path / "explicit.yaml", image_cache={"proj": str(cache_dir)}
        )

        assert _images_dir(None, "proj", config, download=True) == cache_dir

    def test_project_without_image_cache_raises(self, tmp_path: "Path") -> None:
        config = write_config_yaml(
            tmp_path / "explicit.yaml", image_cache={"proj": str(tmp_path)}
        )

        with pytest.raises(Cveta2Error, match="image_cache"):
            _images_dir(None, "other", config, download=True)


class TestFetchApi:
    def test_fetch_writes_csvs_and_returns_dataset(
        self, coco8_fixtures: "LoadedFixtures", tmp_path: "Path"
    ) -> None:
        fake = build_fake(
            coco8_fixtures, ["normal", "all-empty"], statuses=["completed", "completed"]
        )
        out = tmp_path / "out"

        result = cveta2.fetch(
            fake.project.id,
            out,
            download_images=False,
            connection=fake_connection(fake),
        )

        assert (out / "dataset.csv").exists()
        assert (out / "obsolete.csv").exists()
        assert (out / "in_progress.csv").exists()
        assert (out / "deleted.csv").exists()
        assert not result.dataset.empty
        assert set(result.dataset["task_id"].unique()) == {fake.tasks[1].id}
        assert len(result.obsolete) > 0
        assert len(pd.read_csv(out / "obsolete.csv")) == len(result.obsolete)

    def test_default_flags_skip_raw_task_csvs(
        self, normal_fake: "LoadedFixtures", tmp_path: "Path"
    ) -> None:
        """Default fetch writes partition CSVs without raw or task diagnostics."""
        fake = normal_fake
        out = tmp_path / "out"

        cveta2.fetch(
            fake.project.id,
            out,
            download_images=False,
            connection=fake_connection(fake),
        )

        assert not (out / "raw.csv").exists()
        assert not (out / ".tasks").exists()

    @pytest.mark.parametrize("legacy_switch", ["true", "false"])
    def test_legacy_configuration_cannot_publish_during_fetch(
        self,
        normal_fake: "LoadedFixtures",
        tmp_path: "Path",
        monkeypatch: pytest.MonkeyPatch,
        legacy_switch: str,
    ) -> None:
        """Old configuration and environment never initialize the ClearML SDK."""
        fake = normal_fake
        config = write_config_yaml(
            tmp_path / "team.yaml",
            clearml={
                "enabled": True,
                "projects": {
                    fake.project.name: {"clearml_project": "p", "clearml_dataset": "d"}
                },
            },
        )
        original = config.read_bytes()
        _api, connection = _scoped(fake, config_path=config)
        monkeypatch.setenv("CVETA2_CLEARML", legacy_switch)
        with patch(
            "cveta2.adapters.clearml.availability.is_clearml_available",
            side_effect=AssertionError("fetch must not inspect ClearML"),
        ):
            cveta2.fetch(
                fake.project.id,
                tmp_path / "out",
                download_images=False,
                connection=connection,
            )
        assert config.read_bytes() == original
        assert (tmp_path / "out" / "dataset.csv").is_file()

    def test_raw_and_save_tasks_reach_the_pipeline(
        self, normal_fake: "LoadedFixtures", tmp_path: "Path"
    ) -> None:
        """``raw=`` and ``save_tasks=`` must survive as far as FetchOptions.

        ``FetchOptions`` defaults both to False, so a dropped keyword is
        only visible when the caller asks for True.
        """
        fake = normal_fake
        out = tmp_path / "out"

        cveta2.fetch(
            fake.project.id,
            out,
            raw=True,
            save_tasks=True,
            download_images=False,
            connection=fake_connection(fake),
        )

        assert (out / "raw.csv").exists()
        assert (out / ".tasks" / f"task_{fake.tasks[0].id}.csv").exists()

    def test_completed_only_filters_the_task_list(
        self, coco8_fixtures: "LoadedFixtures", tmp_path: "Path"
    ) -> None:
        """Contrasts both values of ``completed_only`` on the same project."""
        fake = build_fake(
            coco8_fixtures,
            ["normal", "all-empty"],
            statuses=["completed", "annotation"],
        )
        done, ongoing = fake.tasks

        every = cveta2.fetch(
            fake.project.id,
            tmp_path / "all",
            download_images=False,
            connection=fake_connection(fake),
        )
        only_done = cveta2.fetch(
            fake.project.id,
            tmp_path / "done",
            completed_only=True,
            download_images=False,
            connection=fake_connection(fake),
        )

        assert _fetched_task_ids(every) == {done.id, ongoing.id}
        assert _fetched_task_ids(only_done) == {done.id}

    def test_sync_root_override_reaches_the_output_rows(
        self, normal_fake: "LoadedFixtures", tmp_path: "Path"
    ) -> None:
        """``cs_info`` is otherwise invisible: the fixtures have no storage.

        With a cloud storage on the project and a ``sync_roots`` entry
        keyed by project *name* in the connection's config file, the
        effective prefix lands in every row's ``s3_image_path`` — so the
        detection call, the override, the config path it reads and the
        value handed to ``fetch_project`` all become observable. The
        ambient config is empty, so only ``Connection.config_path`` can
        supply the override.
        """
        fake = normal_fake
        config = write_config_yaml(
            tmp_path / "sync.yaml",
            sync_roots={fake.project.name: "s3://other-bucket/synced"},
        )
        _api, connection = _scoped(
            fake,
            cloud_storage=make_cs_info(bucket="own-bucket", prefix="raw"),
            config_path=config,
        )

        result = cveta2.fetch(
            fake.project.id,
            tmp_path / "out",
            download_images=False,
            connection=connection,
        )

        assert not result.dataset.empty
        assert _s3_prefixes(result.dataset) == {"synced"}

    def test_ignore_list_is_read_from_the_connection_config(
        self, coco8_fixtures: "LoadedFixtures", tmp_path: "Path"
    ) -> None:
        """``load_ignore_sets`` needs the project name *and* the config path.

        The ignored task disappears from the fetch only when both arrive;
        a null or dropped argument silently fetches it.
        """
        fake = build_fake(
            coco8_fixtures, ["normal", "all-empty"], statuses=["completed", "completed"]
        )
        kept, ignored = fake.tasks
        config = write_config_yaml(
            tmp_path / "ignore.yaml",
            ignore={fake.project.name: [{"id": ignored.id, "name": ignored.name}]},
        )
        _api, connection = _scoped(fake, config_path=config)

        result = cveta2.fetch(
            fake.project.id,
            tmp_path / "out",
            download_images=False,
            connection=connection,
        )

        assert _fetched_task_ids(result) == {kept.id}

    def test_silent_ignored_tasks_are_not_warned_about(
        self,
        coco8_fixtures: "LoadedFixtures",
        tmp_path: "Path",
        capture_logs: list[str],
    ) -> None:
        """``silent_task_ids`` has no effect other than suppressing a warning.

        The companion case below shows the warning is really emitted
        without ``silent``, so the absence here is a signal rather than
        an accident.
        """
        fake = build_fake(
            coco8_fixtures, ["normal", "all-empty"], statuses=["completed", "completed"]
        )
        ignored = fake.tasks[1]
        config = write_config_yaml(
            tmp_path / "ignore.yaml",
            ignore={
                fake.project.name: [
                    {"id": ignored.id, "name": ignored.name, "silent": True}
                ]
            },
        )
        _api, connection = _scoped(fake, config_path=config)

        cveta2.fetch(
            fake.project.id,
            tmp_path / "out",
            download_images=False,
            connection=connection,
        )

        assert not [m for m in capture_logs if "ignore-списка" in m]

    def test_non_silent_ignored_tasks_are_warned_about(
        self,
        coco8_fixtures: "LoadedFixtures",
        tmp_path: "Path",
        capture_logs: list[str],
    ) -> None:
        fake = build_fake(
            coco8_fixtures, ["normal", "all-empty"], statuses=["completed", "completed"]
        )
        ignored = fake.tasks[1]
        config = write_config_yaml(
            tmp_path / "ignore.yaml",
            ignore={fake.project.name: [{"id": ignored.id, "name": ignored.name}]},
        )
        _api, connection = _scoped(fake, config_path=config)

        cveta2.fetch(
            fake.project.id,
            tmp_path / "out",
            download_images=False,
            connection=connection,
        )

        assert [m for m in capture_logs if "ignore-списка" in m]

    def test_configured_image_cache_is_used_as_the_download_target(
        self, normal_fake: "LoadedFixtures", tmp_path: "Path"
    ) -> None:
        """Exercises the *success* path of ``_resolve_images_dir`` inside fetch.

        Every earlier fetch test either disabled downloads or expected
        the "not configured" error, so the project name and config path
        it forwards were never load-bearing. Pre-seeding the cache
        directory keeps the run offline.
        """
        fake = normal_fake
        images_dir = tmp_path / "images"
        images_dir.mkdir()
        for frame in fake.task_data[fake.tasks[0].id][0].frames:
            (images_dir / frame.name).write_bytes(b"jpeg")
        config = write_config_yaml(
            tmp_path / "cache.yaml", image_cache={fake.project.name: str(images_dir)}
        )
        _api, connection = _scoped(fake, config_path=config)

        result = cveta2.fetch(
            fake.project.id,
            tmp_path / "out",
            connection=connection,
        )

        assert not result.dataset.empty
        assert result.dataset["image_path"].notna().all()

    def test_fetch_task_writes_csvs_matching_dataframe(
        self, normal_fake: "LoadedFixtures", tmp_path: "Path"
    ) -> None:
        fake = normal_fake
        out = tmp_path / "out"

        df = cveta2.fetch_task(
            [fake.tasks[0].name],
            out,
            project=fake.project.id,
            download_images=False,
            connection=fake_connection(fake),
        )

        assert (out / "dataset.csv").exists()
        assert (out / "deleted.csv").exists()
        assert not (out / ".tasks").exists()
        assert list(pd.read_csv(out / "dataset.csv").columns) == list(CSV_COLUMNS)
        assert len(df) == len(pd.read_csv(out / "dataset.csv"))

    def test_fetch_task_infers_project_from_task_id(
        self, normal_fake: "LoadedFixtures", tmp_path: "Path"
    ) -> None:
        fake = normal_fake
        out = tmp_path / "out"

        df = cveta2.fetch_task(
            [fake.tasks[0].id],
            out,
            download_images=False,
            connection=fake_connection(fake),
        )

        assert (out / "dataset.csv").exists()
        assert not df.empty

    def test_fetch_task_without_project_and_numeric_ids_raises(
        self, normal_fake: "LoadedFixtures", tmp_path: "Path"
    ) -> None:
        with pytest.raises(Cveta2Error, match="проект"):
            cveta2.fetch_task(
                [normal_fake.tasks[0].name],
                tmp_path / "out",
                download_images=False,
                connection=fake_connection(normal_fake),
            )

    def test_fetch_task_selects_only_the_named_tasks(
        self, coco8_fixtures: "LoadedFixtures", tmp_path: "Path"
    ) -> None:
        """``task_selector`` defaults to None (= every task) in FetchOptions."""
        fake = build_fake(
            coco8_fixtures, ["normal", "all-empty"], statuses=["completed", "completed"]
        )
        wanted = fake.tasks[1]

        df = cveta2.fetch_task(
            [wanted.name],
            tmp_path / "out",
            project=fake.project.id,
            download_images=False,
            connection=fake_connection(fake),
        )

        assert set(df["task_id"].unique()) == {wanted.id}

    def test_fetch_task_defaults_to_downloading_images(
        self, normal_fake: "LoadedFixtures", tmp_path: "Path"
    ) -> None:
        """``download_images`` defaults to True here as it does in ``fetch``.

        Every other ``fetch_task`` test passes False explicitly, so the
        default was never observed.
        """
        with pytest.raises(Cveta2Error, match="image_cache"):
            cveta2.fetch_task(
                [normal_fake.tasks[0].id],
                tmp_path / "out",
                connection=fake_connection(normal_fake),
            )

    def test_fetch_task_rejects_images_dir_without_downloads(
        self, normal_fake: "LoadedFixtures", tmp_path: "Path"
    ) -> None:
        """The conflict guard is the only place ``images_dir`` is observable.

        Every other ``fetch_task`` test leaves it unset, so nulling the
        argument on the way to ``_resolve_images_dir`` changed nothing.
        """
        with pytest.raises(Cveta2Error, match="несовместимы"):
            cveta2.fetch_task(
                [normal_fake.tasks[0].id],
                tmp_path / "out",
                images_dir=tmp_path / "imgs",
                download_images=False,
                connection=fake_connection(normal_fake),
            )

    def test_fetch_task_completed_only_filters_the_selection(
        self, coco8_fixtures: "LoadedFixtures", tmp_path: "Path"
    ) -> None:
        """Contrasts both values of ``completed_only`` on the same selection."""
        fake = build_fake(
            coco8_fixtures,
            ["normal", "all-empty"],
            statuses=["completed", "annotation"],
        )
        done, ongoing = fake.tasks

        every = cveta2.fetch_task(
            [done.name, ongoing.name],
            tmp_path / "all",
            project=fake.project.id,
            download_images=False,
            connection=fake_connection(fake),
        )
        only_done = cveta2.fetch_task(
            [done.name, ongoing.name],
            tmp_path / "done",
            project=fake.project.id,
            completed_only=True,
            download_images=False,
            connection=fake_connection(fake),
        )

        assert set(every["task_id"].unique()) == {done.id, ongoing.id}
        assert set(only_done["task_id"].unique()) == {done.id}

    def test_fetch_task_with_nothing_selected_keeps_the_columns(
        self, coco8_fixtures: "LoadedFixtures", tmp_path: "Path"
    ) -> None:
        """An empty result still has the documented ``CSV_COLUMNS`` columns.

        ``pd.DataFrame([])`` has no columns at all, so a caller indexing
        ``df["task_id"]`` on the result of an unfinished-task fetch crashed.
        """
        fake = build_fake(coco8_fixtures, ["normal"], statuses=["annotation"])

        df = cveta2.fetch_task(
            [fake.tasks[0].name],
            tmp_path / "out",
            project=fake.project.id,
            completed_only=True,
            download_images=False,
            connection=fake_connection(fake),
        )

        assert list(df.columns) == list(CSV_COLUMNS)
        assert len(df) == 0

    def test_fetch_task_honours_the_sync_root_override(
        self, normal_fake: "LoadedFixtures", tmp_path: "Path"
    ) -> None:
        """The ``fetch_task`` twin of the ``fetch`` cs_info wiring test."""
        fake = normal_fake
        config = write_config_yaml(
            tmp_path / "sync.yaml",
            sync_roots={fake.project.name: "s3://other-bucket/synced"},
        )
        _api, connection = _scoped(
            fake,
            cloud_storage=make_cs_info(bucket="own-bucket", prefix="raw"),
            config_path=config,
        )

        df = cveta2.fetch_task(
            [fake.tasks[0].id],
            tmp_path / "out",
            project=fake.project.id,
            download_images=False,
            connection=connection,
        )

        assert _s3_prefixes(df) == {"synced"}

    def test_fetch_task_rejects_a_task_on_the_ignore_list(
        self, normal_fake: "LoadedFixtures", tmp_path: "Path", capture_logs: list[str]
    ) -> None:
        """Ignored tasks are dropped *before* the selector is resolved.

        That is what makes the ignore config observable for
        ``fetch-task``: without it the task resolves and the fetch
        succeeds.
        """
        fake = normal_fake
        ignored = fake.tasks[0]
        config = write_config_yaml(
            tmp_path / "ignore.yaml",
            ignore={fake.project.name: [{"id": ignored.id, "name": ignored.name}]},
        )
        _api, connection = _scoped(fake, config_path=config)

        with pytest.raises(TaskNotFoundError, match=re.escape(ignored.name)):
            cveta2.fetch_task(
                [ignored.name],
                tmp_path / "out",
                project=fake.project.id,
                download_images=False,
                connection=connection,
            )

        assert [m for m in capture_logs if "ignore-списка" in m]

    def test_fetch_task_silent_ignored_task_is_not_warned_about(
        self, normal_fake: "LoadedFixtures", tmp_path: "Path", capture_logs: list[str]
    ) -> None:
        fake = normal_fake
        ignored = fake.tasks[0]
        config = write_config_yaml(
            tmp_path / "ignore.yaml",
            ignore={
                fake.project.name: [
                    {"id": ignored.id, "name": ignored.name, "silent": True}
                ]
            },
        )
        _api, connection = _scoped(fake, config_path=config)

        with pytest.raises(TaskNotFoundError):
            cveta2.fetch_task(
                [ignored.name],
                tmp_path / "out",
                project=fake.project.id,
                download_images=False,
                connection=connection,
            )

        assert not [m for m in capture_logs if "ignore-списка" in m]

    def test_fetch_task_uses_the_configured_image_cache(
        self, normal_fake: "LoadedFixtures", tmp_path: "Path"
    ) -> None:
        fake = normal_fake
        images_dir = tmp_path / "images"
        images_dir.mkdir()
        for frame in fake.task_data[fake.tasks[0].id][0].frames:
            (images_dir / frame.name).write_bytes(b"jpeg")
        config = write_config_yaml(
            tmp_path / "cache.yaml", image_cache={fake.project.name: str(images_dir)}
        )
        _api, connection = _scoped(fake, config_path=config)

        df = cveta2.fetch_task(
            [fake.tasks[0].id],
            tmp_path / "out",
            connection=connection,
        )

        assert not df.empty
        assert df["image_path"].notna().all()

    def test_fetch_task_writes_the_requested_output_dir(
        self, normal_fake: "LoadedFixtures", tmp_path: "Path"
    ) -> None:
        out = tmp_path / "nested" / "out"

        cveta2.fetch_task(
            [normal_fake.tasks[0].id],
            out,
            download_images=False,
            save_tasks=True,
            connection=fake_connection(normal_fake),
        )

        assert (out / "dataset.csv").exists()
        assert (out / ".tasks" / f"task_{normal_fake.tasks[0].id}.csv").exists()

    def test_fetch_by_project_name(
        self, normal_fake: "LoadedFixtures", tmp_path: "Path"
    ) -> None:
        fake = normal_fake

        result = cveta2.fetch(
            fake.project.name,
            tmp_path / "out",
            download_images=False,
            connection=fake_connection(fake),
        )

        assert not result.dataset.empty

    def test_invalid_cache_mode_raises(
        self, normal_fake: "LoadedFixtures", tmp_path: "Path"
    ) -> None:
        with pytest.raises(Cveta2Error, match="cache"):
            cveta2.fetch(
                normal_fake.project.id,
                tmp_path / "out",
                download_images=False,
                cache="bogus",  # type: ignore[arg-type]
                connection=fake_connection(normal_fake),
            )

    def test_images_dir_with_download_disabled_raises(
        self, normal_fake: "LoadedFixtures", tmp_path: "Path"
    ) -> None:
        with pytest.raises(Cveta2Error, match="несовместимы"):
            cveta2.fetch(
                normal_fake.project.id,
                tmp_path / "out",
                images_dir=tmp_path / "imgs",
                download_images=False,
                connection=fake_connection(normal_fake),
            )

    def test_fetch_without_images_dir_config_raises(
        self, normal_fake: "LoadedFixtures", tmp_path: "Path"
    ) -> None:
        fake = normal_fake

        with pytest.raises(Cveta2Error, match="image_cache"):
            cveta2.fetch(
                fake.project.id,
                tmp_path / "out",
                connection=fake_connection(fake),
            )


class TestFetchCacheModes:
    """``cache=`` maps onto ``(use_cache, force)``; both need the cache alive.

    An autouse fixture sets ``CVETA2_DISABLE_CACHE=true`` for the whole
    suite, which makes ``_build_task_cache`` return None and both flags
    unobservable. These tests opt back in and point ``cache.tasks_root``
    at a directory of their own, so the cache is also proof that the
    connection's config path reached ``FetchOptions``.
    """

    @staticmethod
    def _setup(
        fake: "LoadedFixtures",
        tmp_path: "Path",
        monkeypatch: pytest.MonkeyPatch,
    ) -> "tuple[_ProjectScopedApi, cveta2.Connection, Path]":
        monkeypatch.setenv("CVETA2_DISABLE_CACHE", "false")
        tasks_root = tmp_path / "task-cache"
        config = write_config_yaml(
            tmp_path / "cache.yaml",
            cache={"projects": {fake.project.name: {"tasks_root": str(tasks_root)}}},
        )
        api, connection = _scoped(fake, config_path=config)
        return api, connection, tasks_root

    @staticmethod
    def _cached_files(tasks_root: "Path") -> "list[Path]":
        return sorted(tasks_root.rglob("*.json")) if tasks_root.exists() else []

    def test_use_writes_the_cache_under_the_configured_root(
        self,
        normal_fake: "LoadedFixtures",
        tmp_path: "Path",
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake = normal_fake
        _api, connection, tasks_root = self._setup(fake, tmp_path, monkeypatch)

        cveta2.fetch(
            fake.project.id,
            tmp_path / "out",
            download_images=False,
            connection=connection,
        )

        assert self._cached_files(tasks_root)

    def test_off_writes_nothing(
        self,
        normal_fake: "LoadedFixtures",
        tmp_path: "Path",
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake = normal_fake
        _api, connection, tasks_root = self._setup(fake, tmp_path, monkeypatch)

        cveta2.fetch(
            fake.project.id,
            tmp_path / "out",
            cache="off",
            download_images=False,
            connection=connection,
        )

        assert not self._cached_files(tasks_root)

    def test_use_serves_the_second_run_from_the_cache(
        self,
        normal_fake: "LoadedFixtures",
        tmp_path: "Path",
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake = normal_fake
        api, connection, _root = self._setup(fake, tmp_path, monkeypatch)

        cveta2.fetch(
            fake.project.id,
            tmp_path / "first",
            download_images=False,
            connection=connection,
        )
        after_first = list(api.annotation_calls)
        cveta2.fetch(
            fake.project.id,
            tmp_path / "second",
            download_images=False,
            connection=connection,
        )

        assert api.annotation_calls == after_first

    def test_refresh_re_downloads_a_cached_task(
        self,
        normal_fake: "LoadedFixtures",
        tmp_path: "Path",
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``force`` is the only difference between ``use`` and ``refresh``."""
        fake = normal_fake
        api, connection, _root = self._setup(fake, tmp_path, monkeypatch)

        cveta2.fetch(
            fake.project.id,
            tmp_path / "first",
            download_images=False,
            connection=connection,
        )
        after_first = list(api.annotation_calls)
        cveta2.fetch(
            fake.project.id,
            tmp_path / "second",
            cache="refresh",
            download_images=False,
            connection=connection,
        )

        assert api.annotation_calls == [*after_first, fake.tasks[0].id]

    def test_fetch_task_cache_modes_share_the_mapping(
        self,
        normal_fake: "LoadedFixtures",
        tmp_path: "Path",
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake = normal_fake
        api, connection, tasks_root = self._setup(fake, tmp_path, monkeypatch)
        task = fake.tasks[0]

        cveta2.fetch_task(
            [task.id],
            tmp_path / "first",
            download_images=False,
            connection=connection,
        )
        after_first = list(api.annotation_calls)
        cveta2.fetch_task(
            [task.id],
            tmp_path / "second",
            download_images=False,
            connection=connection,
        )
        cveta2.fetch_task(
            [task.id],
            tmp_path / "third",
            cache="refresh",
            download_images=False,
            connection=connection,
        )

        assert self._cached_files(tasks_root)
        assert api.annotation_calls == [*after_first, task.id]

    def test_fetch_task_off_writes_nothing(
        self,
        normal_fake: "LoadedFixtures",
        tmp_path: "Path",
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake = normal_fake
        _api, connection, tasks_root = self._setup(fake, tmp_path, monkeypatch)

        cveta2.fetch_task(
            [fake.tasks[0].id],
            tmp_path / "out",
            cache="off",
            download_images=False,
            connection=connection,
        )

        assert not self._cached_files(tasks_root)


def _fetched_task_ids(result: cveta2.PartitionResult) -> set[int]:
    """Task ids appearing anywhere in a partitioned fetch result."""
    ids: set[int] = set()
    for frame in (result.dataset, result.obsolete, result.in_progress):
        ids |= set(frame["task_id"].dropna().astype(int).unique())
    return ids


def _s3_prefixes(df: pd.DataFrame) -> set[str]:
    """Leading key segment of every ``s3_image_path``.

    Deliberately not ``.str.startswith(...).all()``: a missing
    ``s3_image_path`` is NaN, ``startswith`` propagates it and ``all()``
    reads NaN as truthy, so that form passes even with no path at all.
    """
    return {str(path).split("/")[0] for path in df["s3_image_path"]}


@pytest.mark.parametrize("enabled", [False, True])
def test_fetch_forwards_skip_validation(
    normal_fake: "LoadedFixtures", tmp_path: "Path", *, enabled: bool
) -> None:
    """The public keyword opts into the service's promotion preflight."""
    with patch("cveta2.interfaces.api.fetch.fetch_project") as service:
        cveta2.fetch(
            normal_fake.project.id,
            tmp_path,
            skip_validation=enabled,
            download_images=False,
            connection=fake_connection(normal_fake),
        )
    assert service.call_args.args[2].skip_validation is enabled
