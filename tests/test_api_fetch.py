"""Public API fetch contracts."""

import re
from typing import TYPE_CHECKING, TypedDict, Unpack
from unittest.mock import patch

import pandas as pd
import pytest

import cveta2
from cveta2.domain.errors import (
    Cveta2Error,
    TaskNotFoundError,
)
from cveta2.domain.managed.models import MigrationRequired
from cveta2.domain.models import CSV_COLUMNS
from cveta2.interfaces.api.fetch import _resolve_images_dir
from tests.helpers import (
    build_fake,
    fake_connection,
    make_cs_info,
    write_config_yaml,
    write_split_config_yaml,
)

if TYPE_CHECKING:
    from pathlib import Path

    from cveta2.domain.models import TaskInfo
    from cveta2.interfaces.api.types import CacheMode
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

    def test_explicit_dir_wins_and_is_made_absolute(self, tmp_path: "Path", monkeypatch: pytest.MonkeyPatch) -> None:
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
        config = write_config_yaml(tmp_path / "explicit.yaml", image_cache={"proj": str(cache_dir)})

        assert _images_dir(None, "proj", config, download=True) == cache_dir

    def test_project_without_image_cache_raises(self, tmp_path: "Path") -> None:
        config = write_config_yaml(tmp_path / "explicit.yaml", image_cache={"proj": str(tmp_path)})

        with pytest.raises(Cveta2Error, match="image_cache"):
            _images_dir(None, "other", config, download=True)


class TestFetchApi:
    def test_fetch_writes_csvs_and_returns_dataset(self, coco8_fixtures: "LoadedFixtures", tmp_path: "Path") -> None:
        fake = build_fake(coco8_fixtures, ["normal", "all-empty"], statuses=["completed", "completed"])
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
        # Raw and per-task diagnostics are opt-in.
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
                "projects": {fake.project.name: {"clearml_project": "p", "clearml_dataset": "d"}},
            },
        )
        original = config.read_bytes()
        _api, connection = _scoped(fake, config_path=config)
        monkeypatch.setenv("CVETA2_CLEARML", legacy_switch)
        with (
            patch(
                "cveta2.adapters.clearml.availability.is_clearml_available",
                side_effect=AssertionError("fetch must not inspect ClearML"),
            ),
            pytest.raises(MigrationRequired, match="migrate-config"),
        ):
            cveta2.fetch(
                fake.project.id,
                tmp_path / "out",
                download_images=False,
                connection=connection,
            )
        assert config.read_bytes() == original
        assert not (tmp_path / "out").exists()

    def test_raw_and_save_tasks_reach_the_pipeline(self, normal_fake: "LoadedFixtures", tmp_path: "Path") -> None:
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

    def test_fetch_task_writes_csvs_matching_dataframe(self, normal_fake: "LoadedFixtures", tmp_path: "Path") -> None:
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

    def test_fetch_task_infers_project_from_task_id(self, normal_fake: "LoadedFixtures", tmp_path: "Path") -> None:
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

    def test_fetch_task_selects_only_the_named_tasks(self, coco8_fixtures: "LoadedFixtures", tmp_path: "Path") -> None:
        """``task_selector`` defaults to None (= every task) in FetchOptions."""
        fake = build_fake(coco8_fixtures, ["normal", "all-empty"], statuses=["completed", "completed"])
        wanted = fake.tasks[1]

        df = cveta2.fetch_task(
            [wanted.name],
            tmp_path / "out",
            project=fake.project.id,
            download_images=False,
            connection=fake_connection(fake),
        )

        assert set(df["task_id"].unique()) == {wanted.id}

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

    def test_fetch_task_writes_the_requested_output_dir(self, normal_fake: "LoadedFixtures", tmp_path: "Path") -> None:
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

    def test_fetch_by_project_name(self, normal_fake: "LoadedFixtures", tmp_path: "Path") -> None:
        fake = normal_fake

        result = cveta2.fetch(
            fake.project.name,
            tmp_path / "out",
            download_images=False,
            connection=fake_connection(fake),
        )

        assert not result.dataset.empty

    def test_invalid_cache_mode_raises(self, normal_fake: "LoadedFixtures", tmp_path: "Path") -> None:
        with pytest.raises(Cveta2Error, match="cache"):
            cveta2.fetch(
                normal_fake.project.id,
                tmp_path / "out",
                download_images=False,
                cache="bogus",  # type: ignore[arg-type]
                connection=fake_connection(normal_fake),
            )


_ENTRY_POINTS = ["fetch", "fetch_task"]


class _EntryOptions(TypedDict, total=False):
    """Keywords both public fetch entry points accept with the same meaning."""

    completed_only: bool
    images_dir: "Path"
    download_images: bool
    cache: "CacheMode"


def _run_entry(
    entry: str,
    fake: "LoadedFixtures",
    output_dir: "Path",
    connection: cveta2.Connection,
    **options: Unpack[_EntryOptions],
) -> "tuple[pd.DataFrame, set[int]]":
    """Run a public fetch entry point over every task of *fake*.

    Returns the dataset rows and the ids of every task the run fetched
    (``fetch`` partitions them, ``fetch_task`` returns one frame).
    """
    if entry == "fetch":
        result = cveta2.fetch(fake.project.id, output_dir, connection=connection, **options)
        return result.dataset, _fetched_task_ids(result)
    df = cveta2.fetch_task(
        [task.name for task in fake.tasks],
        output_dir,
        project=fake.project.id,
        connection=connection,
        **options,
    )
    return df, set(df["task_id"].dropna().astype(int).unique())


def _ignore_config(tmp_path: "Path", fake: "LoadedFixtures", ignored: "TaskInfo", *, silent: bool) -> "Path":
    entry: dict[str, object] = {"id": ignored.id, "name": ignored.name}
    if silent:
        entry["silent"] = True
    return write_split_config_yaml(
        tmp_path / "ignore.yaml",
        project_ids={fake.project.name: fake.project.id},
        ignore={fake.project.name: [entry]},
    )


@pytest.mark.parametrize("entry", _ENTRY_POINTS)
class TestFetchEntryPoints:
    """Contracts ``fetch`` and ``fetch_task`` share, run through both."""

    def test_completed_only_filters_the_tasks(
        self, coco8_fixtures: "LoadedFixtures", tmp_path: "Path", entry: str
    ) -> None:
        """Contrasts both values of ``completed_only`` on the same project."""
        fake = build_fake(
            coco8_fixtures,
            ["normal", "all-empty"],
            statuses=["completed", "annotation"],
        )
        done, ongoing = fake.tasks
        connection = fake_connection(fake)

        _df, every = _run_entry(entry, fake, tmp_path / "all", connection, download_images=False)
        _df, only_done = _run_entry(
            entry,
            fake,
            tmp_path / "done",
            connection,
            completed_only=True,
            download_images=False,
        )

        assert every == {done.id, ongoing.id}
        assert only_done == {done.id}

    def test_sync_root_override_reaches_the_output_rows(
        self, normal_fake: "LoadedFixtures", tmp_path: "Path", entry: str
    ) -> None:
        """``cs_info`` is otherwise invisible: the fixtures have no storage.

        With a cloud storage on the project and a ``sync_roots`` entry
        keyed by project *name* in the connection's config file, the
        effective prefix lands in every row's ``s3_image_path`` — so the
        detection call, the override, the config path it reads and the
        value handed to the service all become observable. The ambient
        config is empty, so only ``Connection.config_path`` can supply
        the override.
        """
        fake = normal_fake
        config = write_split_config_yaml(
            tmp_path / "sync.yaml",
            project_ids={fake.project.name: fake.project.id},
            sync_roots={fake.project.name: "s3://other-bucket/synced"},
        )
        _api, connection = _scoped(
            fake,
            cloud_storage=make_cs_info(bucket="own-bucket", prefix="raw"),
            config_path=config,
        )

        df, _ids = _run_entry(entry, fake, tmp_path / "out", connection, download_images=False)

        assert not df.empty
        assert _s3_prefixes(df) == {"synced"}

    def test_configured_image_cache_is_used_as_the_download_target(
        self, normal_fake: "LoadedFixtures", tmp_path: "Path", entry: str
    ) -> None:
        """Exercises the *success* path of ``_resolve_images_dir``.

        Pre-seeding the cache directory keeps the run offline.
        """
        fake = normal_fake
        images_dir = tmp_path / "images"
        images_dir.mkdir()
        for frame in fake.task_data[fake.tasks[0].id][0].frames:
            (images_dir / frame.name).write_bytes(b"jpeg")
        config = write_config_yaml(tmp_path / "cache.yaml", image_cache={fake.project.name: str(images_dir)})
        _api, connection = _scoped(fake, config_path=config)

        df, _ids = _run_entry(entry, fake, tmp_path / "out", connection)

        assert not df.empty
        assert df["image_path"].notna().all()

    def test_downloads_by_default_and_need_a_configured_image_cache(
        self, normal_fake: "LoadedFixtures", tmp_path: "Path", entry: str
    ) -> None:
        with pytest.raises(Cveta2Error, match="image_cache"):
            _run_entry(entry, normal_fake, tmp_path / "out", fake_connection(normal_fake))

    def test_images_dir_with_download_disabled_raises(
        self, normal_fake: "LoadedFixtures", tmp_path: "Path", entry: str
    ) -> None:
        with pytest.raises(Cveta2Error, match="несовместимы"):
            _run_entry(
                entry,
                normal_fake,
                tmp_path / "out",
                fake_connection(normal_fake),
                images_dir=tmp_path / "imgs",
                download_images=False,
            )

    @pytest.mark.parametrize("silent", [False, True], ids=["loud", "silent"])
    def test_ignore_list_comes_from_the_connection_config(
        self,
        coco8_fixtures: "LoadedFixtures",
        tmp_path: "Path",
        capture_logs: list[str],
        entry: str,
        *,
        silent: bool,
    ) -> None:
        """``load_ignore_sets`` needs the project name *and* the config path.

        ``fetch`` drops the ignored task; ``fetch_task`` drops it *before*
        resolving the selector, so asking for it fails. ``silent`` has no
        effect other than suppressing the warning.
        """
        fake = build_fake(coco8_fixtures, ["normal", "all-empty"], statuses=["completed", "completed"])
        kept, ignored = fake.tasks
        config = _ignore_config(tmp_path, fake, ignored, silent=silent)
        _api, connection = _scoped(fake, config_path=config)

        if entry == "fetch":
            _df, ids = _run_entry(entry, fake, tmp_path / "out", connection, download_images=False)
            assert ids == {kept.id}
        else:
            with pytest.raises(TaskNotFoundError, match=re.escape(ignored.name)):
                _run_entry(entry, fake, tmp_path / "out", connection, download_images=False)

        warned = [m for m in capture_logs if "ignore-списка" in m]
        assert bool(warned) is not silent


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

    @staticmethod
    def _run(
        entry: str,
        fake: "LoadedFixtures",
        output_dir: "Path",
        connection: cveta2.Connection,
        cache: "CacheMode" = "use",
    ) -> None:
        if entry == "fetch":
            cveta2.fetch(
                fake.project.id,
                output_dir,
                download_images=False,
                cache=cache,
                connection=connection,
            )
        else:
            cveta2.fetch_task(
                [fake.tasks[0].id],
                output_dir,
                download_images=False,
                cache=cache,
                connection=connection,
            )

    @pytest.mark.parametrize("entry", _ENTRY_POINTS)
    def test_use_writes_the_cache_and_serves_the_second_run(
        self,
        normal_fake: "LoadedFixtures",
        tmp_path: "Path",
        monkeypatch: pytest.MonkeyPatch,
        entry: str,
    ) -> None:
        fake = normal_fake
        api, connection, tasks_root = self._setup(fake, tmp_path, monkeypatch)

        self._run(entry, fake, tmp_path / "first", connection)
        assert self._cached_files(tasks_root)
        after_first = list(api.annotation_calls)
        self._run(entry, fake, tmp_path / "second", connection)

        assert api.annotation_calls == after_first

    @pytest.mark.parametrize("entry", _ENTRY_POINTS)
    def test_off_writes_nothing(
        self,
        normal_fake: "LoadedFixtures",
        tmp_path: "Path",
        monkeypatch: pytest.MonkeyPatch,
        entry: str,
    ) -> None:
        fake = normal_fake
        _api, connection, tasks_root = self._setup(fake, tmp_path, monkeypatch)

        self._run(entry, fake, tmp_path / "out", connection, cache="off")

        assert not self._cached_files(tasks_root)

    @pytest.mark.parametrize("entry", _ENTRY_POINTS)
    def test_refresh_re_downloads_a_cached_task(
        self,
        normal_fake: "LoadedFixtures",
        tmp_path: "Path",
        monkeypatch: pytest.MonkeyPatch,
        entry: str,
    ) -> None:
        """``force`` is the only difference between ``use`` and ``refresh``."""
        fake = normal_fake
        api, connection, _root = self._setup(fake, tmp_path, monkeypatch)

        self._run(entry, fake, tmp_path / "first", connection)
        after_first = list(api.annotation_calls)
        self._run(entry, fake, tmp_path / "second", connection, cache="refresh")

        assert api.annotation_calls == [*after_first, fake.tasks[0].id]


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
def test_fetch_forwards_skip_validation(normal_fake: "LoadedFixtures", tmp_path: "Path", *, enabled: bool) -> None:
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
