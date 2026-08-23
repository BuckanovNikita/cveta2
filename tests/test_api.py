"""Tests for the public workflow API (cveta2.api).

Beyond the happy paths, most of what lives here pins **argument wiring**:
``api.py`` is a 1:1 mirror of the CLI whose whole job is to translate
keyword arguments into service calls, so a silently dropped or nulled
argument is the characteristic defect. Tests that exist only to make one
such argument observable say so in their docstring.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from unittest.mock import patch

import pandas as pd
import pytest

import cveta2
from cveta2._client.dtos import LabelPatch
from cveta2.api import _open, _resolve_images_dir
from cveta2.config import IgnoreConfig, IgnoredTask
from cveta2.exceptions import (
    CvatApiError,
    Cveta2Error,
    LabelsMismatchError,
    MissingCredentialsError,
    MissingHostError,
    TaskNotFoundError,
)
from cveta2.image_uploader import UploadStats
from cveta2.models import CSV_COLUMNS
from cveta2.services.upload import UploadOutcome, UploadRequest
from tests.fixtures.fake_cvat_api import FakeCvatApi
from tests.fixtures.fake_s3 import FakeS3Client
from tests.helpers import (
    build_fake,
    client_with_api,
    csv_row,
    fake_connection,
    make_cs_info,
    write_config_yaml,
    write_dataset_csv,
)

if TYPE_CHECKING:
    from pathlib import Path

    from typing_extensions import Self

    from cveta2._client.dtos import RawShape
    from cveta2.image_downloader import CloudStorageInfo
    from cveta2.models import LabelInfo, TaskInfo
    from tests.fixtures.fake_cvat_project import LoadedFixtures


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _ProjectScopedApi(FakeCvatApi):
    """A fake CVAT API whose project-scoped reads reject a foreign project id.

    ``FakeCvatApi`` ignores ``project_id`` in ``get_project_tasks``,
    ``get_project_labels`` and ``get_project_cloud_storage``, so a call
    that passes ``None`` in place of the resolved id behaves exactly like
    the correct one and no assertion downstream can tell them apart.
    This subclass makes the id load-bearing, and can serve a real
    :class:`CloudStorageInfo` so that the ``cs_info`` a fetch computes
    shows up as ``s3_image_path`` in the output CSV.
    """

    def __init__(
        self,
        fixtures: LoadedFixtures,
        *,
        cloud_storage: CloudStorageInfo | None = None,
    ) -> None:
        """Wrap *fixtures*, optionally giving the project a cloud storage."""
        super().__init__(fixtures)
        self.project_id = fixtures.project.id
        self._cloud_storage = cloud_storage

    def _check_project(self, project_id: object) -> None:
        if project_id != self.project_id:
            raise CvatApiError(f"no such project: {project_id!r}", status_code=404)

    def get_project_tasks(self, _project_id: int) -> list[TaskInfo]:
        """Return the project's tasks, refusing any other project id."""
        self._check_project(_project_id)
        return super().get_project_tasks(_project_id)

    def get_project_labels(self, _project_id: int) -> list[LabelInfo]:
        """Return the project's labels, refusing any other project id."""
        self._check_project(_project_id)
        return super().get_project_labels(_project_id)

    def get_project_cloud_storage(self, _project_id: int) -> CloudStorageInfo | None:
        """Return the configured cloud storage, refusing any other project id."""
        self._check_project(_project_id)
        return self._cloud_storage

    def patch_project_labels(
        self,
        project_id: int,
        patches: list[LabelPatch],
    ) -> None:
        """Record label patches, refusing any other project id."""
        self._check_project(project_id)
        super().patch_project_labels(project_id, patches)


def _scoped(
    fixtures: LoadedFixtures,
    *,
    cloud_storage: CloudStorageInfo | None = None,
    config_path: Path | None = None,
) -> tuple[_ProjectScopedApi, cveta2.Connection]:
    """Build a project-id-checking fake plus a ``Connection`` around it."""
    api = _ProjectScopedApi(fixtures, cloud_storage=cloud_storage)
    return api, cveta2.Connection(client=client_with_api(api), config_path=config_path)


class _RecordingUploader:
    """``S3Uploader`` stand-in recording what the upload pipeline staged."""

    calls: list[dict[str, Path]] = []  # noqa: RUF012

    def upload(
        self,
        cs_info: CloudStorageInfo,
        images: dict[str, Path],
        name_to_server_file: dict[str, str] | None = None,
        existing_keys: set[str] | None = None,
    ) -> UploadStats:
        """Record *images* instead of talking to S3."""
        del cs_info, name_to_server_file, existing_keys
        type(self).calls.append(dict(images))
        return UploadStats(uploaded=len(images), total=len(images))


class TestOpenConnection:
    def test_injected_client_used_as_is(self) -> None:
        injected = cveta2.CvatClient(cveta2.CvatConfig(), api=object())  # type: ignore[arg-type]
        connection = cveta2.Connection(client=injected)
        with _open(connection) as client:
            assert client is injected

    def test_unentered_client_rejected(self) -> None:
        connection = cveta2.Connection(client=cveta2.CvatClient(cveta2.CvatConfig()))
        with (
            pytest.raises(Cveta2Error, match="не готов"),
            _open(connection),
        ):
            pytest.fail("must not yield")

    def test_missing_host_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "cveta2.api.CvatConfig.load", lambda *_a, **_k: cveta2.CvatConfig()
        )
        with (
            pytest.raises(MissingHostError, match="CVAT_HOST"),
            _open(None),
        ):
            pytest.fail("must not yield")

    def test_missing_credentials_raise(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "cveta2.api.CvatConfig.load", lambda *_a, **_k: cveta2.CvatConfig()
        )
        with (
            pytest.raises(MissingCredentialsError, match="CVAT_USERNAME"),
            _open(cveta2.Connection(host="http://cvat.test")),
        ):
            pytest.fail("must not yield")

    def test_explicit_settings_override_config(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "cveta2.api.CvatConfig.load",
            lambda *_a, **_k: cveta2.CvatConfig(host="http://from-config"),
        )
        captured: dict[str, str] = {}

        class _FakeClient:
            def __init__(self, cfg: cveta2.CvatConfig) -> None:
                captured["host"] = cfg.host
                captured["user"] = cfg.username or ""

            def __enter__(self) -> Self:
                return self

            def __exit__(self, *_exc: object) -> None:
                return None

        monkeypatch.setattr("cveta2.api.CvatClient", _FakeClient)
        connection = cveta2.Connection(
            host="http://explicit", username="user", password="pass"
        )
        with _open(connection):
            pass
        assert captured["host"] == "http://explicit"
        assert captured["user"] == "user"


def _images_dir(
    images_dir: str | Path | None,
    project_name: str,
    config_path: Path | None,
    *,
    download: bool,
) -> Path | None:
    """Call ``_resolve_images_dir`` with its boolean passed by keyword."""
    return _resolve_images_dir(images_dir, download, project_name, config_path)


class TestImagesDirResolution:
    """The four-branch precedence chain of ``_resolve_images_dir``."""

    def test_download_disabled_returns_none(self) -> None:
        assert _images_dir(None, "proj", None, download=False) is None

    def test_conflicting_arguments_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(Cveta2Error, match="несовместимы"):
            _images_dir(tmp_path, "proj", None, download=False)

    def test_explicit_dir_wins_and_is_made_absolute(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Only a returned path shows that ``images_dir`` reached ``Path()``.

        The pre-existing tests all took the error branch, where the
        argument is merely truthy, so nulling it changed nothing.
        """
        monkeypatch.chdir(tmp_path)

        resolved = _images_dir("imgs", "proj", None, download=True)

        assert resolved == (tmp_path / "imgs").resolve()

    def test_falls_back_to_the_configured_image_cache(self, tmp_path: Path) -> None:
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

    def test_project_without_image_cache_raises(self, tmp_path: Path) -> None:
        config = write_config_yaml(
            tmp_path / "explicit.yaml", image_cache={"proj": str(tmp_path)}
        )

        with pytest.raises(Cveta2Error, match="image_cache"):
            _images_dir(None, "other", config, download=True)


class TestFetchApi:
    def test_fetch_writes_csvs_and_returns_dataset(
        self, coco8_fixtures: LoadedFixtures, tmp_path: Path
    ) -> None:
        fake = build_fake(
            coco8_fixtures, ["normal", "all-empty"], statuses=["completed", "completed"]
        )
        out = tmp_path / "out"

        result = cveta2.fetch(
            fake.project.id,
            out,
            download_images=False,
            publish_clearml=False,
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

    def test_default_flags_skip_raw_task_csvs_and_publish_clearml(
        self, normal_fake: LoadedFixtures, tmp_path: Path
    ) -> None:
        """Pins the three keyword defaults that no other test exercises.

        ``raw``/``save_tasks`` default to False and ``publish_clearml``
        to True; flipping any default is invisible unless a call that
        passes none of them asserts the resulting side effects.
        """
        fake = normal_fake
        out = tmp_path / "out"

        with patch("cveta2._clearml.maybe_publish_clearml") as publish:
            cveta2.fetch(
                fake.project.id,
                out,
                download_images=False,
                connection=fake_connection(fake),
            )

        assert not (out / "raw.csv").exists()
        assert not (out / ".tasks").exists()
        publish.assert_called_once_with(fake.project.name, out)

    def test_raw_and_save_tasks_reach_the_pipeline(
        self, normal_fake: LoadedFixtures, tmp_path: Path
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
            publish_clearml=False,
            connection=fake_connection(fake),
        )

        assert (out / "raw.csv").exists()
        assert (out / ".tasks" / f"task_{fake.tasks[0].id}.csv").exists()

    def test_publish_clearml_false_suppresses_the_publish(
        self, normal_fake: LoadedFixtures, tmp_path: Path
    ) -> None:
        """``publish_clearml`` defaults to True in FetchOptions too.

        Only an explicit False can show that the keyword is forwarded
        rather than dropped.
        """
        fake = normal_fake

        with patch("cveta2._clearml.maybe_publish_clearml") as publish:
            cveta2.fetch(
                fake.project.id,
                tmp_path / "out",
                download_images=False,
                publish_clearml=False,
                connection=fake_connection(fake),
            )

        publish.assert_not_called()

    def test_completed_only_filters_the_task_list(
        self, coco8_fixtures: LoadedFixtures, tmp_path: Path
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
            publish_clearml=False,
            connection=fake_connection(fake),
        )
        only_done = cveta2.fetch(
            fake.project.id,
            tmp_path / "done",
            completed_only=True,
            download_images=False,
            publish_clearml=False,
            connection=fake_connection(fake),
        )

        assert _fetched_task_ids(every) == {done.id, ongoing.id}
        assert _fetched_task_ids(only_done) == {done.id}

    def test_sync_root_override_reaches_the_output_rows(
        self,
        normal_fake: LoadedFixtures,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``cs_info`` is otherwise invisible: the fixtures have no storage.

        With a cloud storage on the project and a ``sync_roots`` entry
        keyed by project *name*, the effective prefix lands in every
        row's ``s3_image_path`` — so the detection call, the override and
        the value handed to ``fetch_project`` all become observable.
        """
        fake = normal_fake
        config = write_config_yaml(
            tmp_path / "sync.yaml",
            sync_roots={fake.project.name: "s3://other-bucket/synced"},
        )
        monkeypatch.setenv("CVETA2_CONFIG", str(config))
        _api, connection = _scoped(
            fake, cloud_storage=make_cs_info(bucket="own-bucket", prefix="raw")
        )

        result = cveta2.fetch(
            fake.project.id,
            tmp_path / "out",
            download_images=False,
            publish_clearml=False,
            connection=connection,
        )

        assert not result.dataset.empty
        assert _s3_prefixes(result.dataset) == {"synced"}

    def test_ignore_list_is_read_from_the_connection_config(
        self, coco8_fixtures: LoadedFixtures, tmp_path: Path
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
            publish_clearml=False,
            connection=connection,
        )

        assert _fetched_task_ids(result) == {kept.id}

    def test_silent_ignored_tasks_are_not_warned_about(
        self, coco8_fixtures: LoadedFixtures, tmp_path: Path, capture_logs: list[str]
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
            publish_clearml=False,
            connection=connection,
        )

        assert not [m for m in capture_logs if "ignore-списка" in m]

    def test_non_silent_ignored_tasks_are_warned_about(
        self, coco8_fixtures: LoadedFixtures, tmp_path: Path, capture_logs: list[str]
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
            publish_clearml=False,
            connection=connection,
        )

        assert [m for m in capture_logs if "ignore-списка" in m]

    def test_configured_image_cache_is_used_as_the_download_target(
        self, normal_fake: LoadedFixtures, tmp_path: Path
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
            publish_clearml=False,
            connection=connection,
        )

        assert not result.dataset.empty
        assert result.dataset["image_path"].notna().all()

    def test_fetch_task_writes_csvs_matching_dataframe(
        self, normal_fake: LoadedFixtures, tmp_path: Path
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
        self, normal_fake: LoadedFixtures, tmp_path: Path
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
        self, normal_fake: LoadedFixtures, tmp_path: Path
    ) -> None:
        with pytest.raises(Cveta2Error, match="проект"):
            cveta2.fetch_task(
                [normal_fake.tasks[0].name],
                tmp_path / "out",
                download_images=False,
                connection=fake_connection(normal_fake),
            )

    def test_fetch_task_selects_only_the_named_tasks(
        self, coco8_fixtures: LoadedFixtures, tmp_path: Path
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
        self, normal_fake: LoadedFixtures, tmp_path: Path
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
        self, normal_fake: LoadedFixtures, tmp_path: Path
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
        self, coco8_fixtures: LoadedFixtures, tmp_path: Path
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

    def test_fetch_task_honours_the_sync_root_override(
        self,
        normal_fake: LoadedFixtures,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The ``fetch_task`` twin of the ``fetch`` cs_info wiring test."""
        fake = normal_fake
        env_config = write_config_yaml(
            tmp_path / "sync.yaml",
            sync_roots={fake.project.name: "s3://other-bucket/synced"},
        )
        monkeypatch.setenv("CVETA2_CONFIG", str(env_config))
        _api, connection = _scoped(
            fake, cloud_storage=make_cs_info(bucket="own-bucket", prefix="raw")
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
        self, normal_fake: LoadedFixtures, tmp_path: Path, capture_logs: list[str]
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
        self, normal_fake: LoadedFixtures, tmp_path: Path, capture_logs: list[str]
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
        self, normal_fake: LoadedFixtures, tmp_path: Path
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
        self, normal_fake: LoadedFixtures, tmp_path: Path
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
        self, normal_fake: LoadedFixtures, tmp_path: Path
    ) -> None:
        fake = normal_fake

        result = cveta2.fetch(
            fake.project.name,
            tmp_path / "out",
            download_images=False,
            publish_clearml=False,
            connection=fake_connection(fake),
        )

        assert not result.dataset.empty

    def test_invalid_cache_mode_raises(
        self, normal_fake: LoadedFixtures, tmp_path: Path
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
        self, normal_fake: LoadedFixtures, tmp_path: Path
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
        self, normal_fake: LoadedFixtures, tmp_path: Path
    ) -> None:
        fake = normal_fake

        with pytest.raises(Cveta2Error, match="image_cache"):
            cveta2.fetch(
                fake.project.id,
                tmp_path / "out",
                publish_clearml=False,
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
        fake: LoadedFixtures,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> tuple[_ProjectScopedApi, cveta2.Connection, Path]:
        monkeypatch.setenv("CVETA2_DISABLE_CACHE", "false")
        tasks_root = tmp_path / "task-cache"
        config = write_config_yaml(
            tmp_path / "cache.yaml",
            cache={"projects": {fake.project.name: {"tasks_root": str(tasks_root)}}},
        )
        api, connection = _scoped(fake, config_path=config)
        return api, connection, tasks_root

    @staticmethod
    def _cached_files(tasks_root: Path) -> list[Path]:
        return sorted(tasks_root.rglob("*.json")) if tasks_root.exists() else []

    def test_use_writes_the_cache_under_the_configured_root(
        self,
        normal_fake: LoadedFixtures,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake = normal_fake
        _api, connection, tasks_root = self._setup(fake, tmp_path, monkeypatch)

        cveta2.fetch(
            fake.project.id,
            tmp_path / "out",
            download_images=False,
            publish_clearml=False,
            connection=connection,
        )

        assert self._cached_files(tasks_root)

    def test_off_writes_nothing(
        self,
        normal_fake: LoadedFixtures,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake = normal_fake
        _api, connection, tasks_root = self._setup(fake, tmp_path, monkeypatch)

        cveta2.fetch(
            fake.project.id,
            tmp_path / "out",
            cache="off",
            download_images=False,
            publish_clearml=False,
            connection=connection,
        )

        assert not self._cached_files(tasks_root)

    def test_use_serves_the_second_run_from_the_cache(
        self,
        normal_fake: LoadedFixtures,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake = normal_fake
        api, connection, _root = self._setup(fake, tmp_path, monkeypatch)

        cveta2.fetch(
            fake.project.id,
            tmp_path / "first",
            download_images=False,
            publish_clearml=False,
            connection=connection,
        )
        after_first = list(api.annotation_calls)
        cveta2.fetch(
            fake.project.id,
            tmp_path / "second",
            download_images=False,
            publish_clearml=False,
            connection=connection,
        )

        assert api.annotation_calls == after_first

    def test_refresh_re_downloads_a_cached_task(
        self,
        normal_fake: LoadedFixtures,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``force`` is the only difference between ``use`` and ``refresh``."""
        fake = normal_fake
        api, connection, _root = self._setup(fake, tmp_path, monkeypatch)

        cveta2.fetch(
            fake.project.id,
            tmp_path / "first",
            download_images=False,
            publish_clearml=False,
            connection=connection,
        )
        after_first = list(api.annotation_calls)
        cveta2.fetch(
            fake.project.id,
            tmp_path / "second",
            cache="refresh",
            download_images=False,
            publish_clearml=False,
            connection=connection,
        )

        assert api.annotation_calls == [*after_first, fake.tasks[0].id]

    def test_fetch_task_cache_modes_share_the_mapping(
        self,
        normal_fake: LoadedFixtures,
        tmp_path: Path,
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
        normal_fake: LoadedFixtures,
        tmp_path: Path,
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


class TestUploadApi:
    """End-to-end uploads against the fake, with S3 stubbed out."""

    @staticmethod
    def _dataset(tmp_path: Path) -> Path:
        return write_dataset_csv(
            tmp_path / "dataset.csv",
            [
                csv_row("a.jpg", label="person"),
                csv_row("b.jpg", label="dog", issue_state="new", issue_text="check"),
                csv_row("c.jpg", shape="none", label=None),
                csv_row("d.jpg", shape="deleted", label=None),
            ],
            columns=CSV_COLUMNS,
        )

    @pytest.fixture(autouse=True)
    def _stub_s3(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _RecordingUploader.calls = []
        monkeypatch.setattr(
            "cveta2.services.upload.build_server_file_mapping",
            lambda _cs_info, names, pinned=None: (
                dict(pinned) if pinned is not None else {name: name for name in names},
                set(),
            ),
        )
        monkeypatch.setattr("cveta2.services.upload.S3Uploader", _RecordingUploader)

    def test_unknown_labels_raise_mismatch_end_to_end(
        self, normal_fake: LoadedFixtures, tmp_path: Path
    ) -> None:
        """The error names the project, which is the only use of that argument."""
        fake = normal_fake
        dataset = write_dataset_csv(
            tmp_path / "dataset.csv",
            [csv_row("a.jpg", label="ghost-label")],
            columns=CSV_COLUMNS,
        )
        _api, connection = _scoped(fake)

        with pytest.raises(LabelsMismatchError, match="ghost-label") as excinfo:
            cveta2.upload(
                dataset,
                project=fake.project.id,
                name="api-upload",
                connection=connection,
            )

        assert fake.project.name in str(excinfo.value)

    def test_empty_after_filtering_raises(
        self, normal_fake: LoadedFixtures, tmp_path: Path
    ) -> None:
        fake = normal_fake
        dataset = write_dataset_csv(
            tmp_path / "dataset.csv",
            [csv_row("a.jpg", label="cat")],
            columns=CSV_COLUMNS,
        )

        with pytest.raises(Cveta2Error, match="не осталось"):
            cveta2.upload(
                dataset,
                project=fake.project.id,
                name="api-upload",
                labels=["nonexistent"],
                connection=fake_connection(fake),
            )

    def test_full_upload_reports_and_creates_the_task(
        self, normal_fake: LoadedFixtures, tmp_path: Path
    ) -> None:
        """One successful run pins the whole request/result translation.

        ``UploadResult`` fields are required and typed, so every nulled
        or dropped field of the result dies here; ``UploadTaskSpec`` is
        recorded verbatim by the fake, which pins the request side.
        """
        fake = normal_fake
        config = write_config_yaml(
            tmp_path / "upload.yaml",
            upload={"images_per_job": 3, "image_quality": 55},
        )
        api, connection = _scoped(
            fake,
            cloud_storage=make_cs_info(cs_id=7, bucket="b", prefix="images"),
            config_path=config,
        )

        result = cveta2.upload(
            self._dataset(tmp_path),
            project=fake.project.id,
            name="api-upload",
            connection=connection,
        )

        spec = api.writes.created_tasks[0]
        assert spec.project_id == fake.project.id
        assert spec.name == "api-upload"
        assert spec.cloud_storage_id == 7
        assert spec.segment_size == 3
        assert spec.image_quality == 55
        assert spec.server_files == [
            "images/a.jpg",
            "images/b.jpg",
            "images/c.jpg",
            "images/d.jpg",
        ]
        assert result.task_id in {t.id for t in api.get_project_tasks(api.project_id)}
        assert result.task_name == "api-upload"
        assert result.url == f"http://fake-cvat/tasks/{result.task_id}"
        assert (result.images, result.deleted, result.annotations, result.issues) == (
            4,
            1,
            2,
            1,
        )

    def test_labels_none_uploads_every_label_and_unannotated_frames(
        self, normal_fake: LoadedFixtures, tmp_path: Path
    ) -> None:
        """``labels=None`` derives the label list *and* turns on unannotated.

        Both assignments are invisible unless a frame without a label has
        to survive the filter.
        """
        fake = normal_fake
        _api, connection = _scoped(
            fake, cloud_storage=make_cs_info(cs_id=7, bucket="b", prefix="images")
        )

        result = cveta2.upload(
            self._dataset(tmp_path),
            project=fake.project.id,
            name="api-upload",
            connection=connection,
        )

        assert result.images == 4

    def test_explicit_labels_drop_unannotated_frames_by_default(
        self, normal_fake: LoadedFixtures, tmp_path: Path
    ) -> None:
        """``include_unannotated`` defaults to False on both sides."""
        fake = normal_fake
        api, connection = _scoped(
            fake, cloud_storage=make_cs_info(cs_id=7, bucket="b", prefix="images")
        )

        result = cveta2.upload(
            self._dataset(tmp_path),
            project=fake.project.id,
            name="api-upload",
            labels=["person"],
            connection=connection,
        )

        assert api.writes.created_tasks[0].server_files == [
            "images/a.jpg",
            "images/d.jpg",
        ]
        assert result.images == 2

    def test_include_unannotated_adds_label_less_frames(
        self, normal_fake: LoadedFixtures, tmp_path: Path
    ) -> None:
        fake = normal_fake
        api, connection = _scoped(
            fake, cloud_storage=make_cs_info(cs_id=7, bucket="b", prefix="images")
        )

        cveta2.upload(
            self._dataset(tmp_path),
            project=fake.project.id,
            name="api-upload",
            labels=["person"],
            include_unannotated=True,
            connection=connection,
        )

        assert api.writes.created_tasks[0].server_files == [
            "images/a.jpg",
            "images/c.jpg",
            "images/d.jpg",
        ]

    def test_exclude_in_progress_removes_listed_frames(
        self, normal_fake: LoadedFixtures, tmp_path: Path
    ) -> None:
        """``exclude_in_progress`` is stringified before reaching the reader."""
        fake = normal_fake
        api, connection = _scoped(
            fake, cloud_storage=make_cs_info(cs_id=7, bucket="b", prefix="images")
        )
        in_progress = write_dataset_csv(
            tmp_path / "in_progress.csv", [csv_row("a.jpg", label="person")]
        )

        cveta2.upload(
            self._dataset(tmp_path),
            project=fake.project.id,
            name="api-upload",
            exclude_in_progress=in_progress,
            connection=connection,
        )

        assert api.writes.created_tasks[0].server_files == [
            "images/b.jpg",
            "images/c.jpg",
            "images/d.jpg",
        ]

    def test_mark_all_deleted_and_complete_are_forwarded(
        self, normal_fake: LoadedFixtures, tmp_path: Path
    ) -> None:
        """Both default to False in ``UploadOptions``; only True is visible."""
        fake = normal_fake
        api, connection = _scoped(
            fake, cloud_storage=make_cs_info(cs_id=7, bucket="b", prefix="images")
        )

        result = cveta2.upload(
            self._dataset(tmp_path),
            project=fake.project.id,
            name="api-upload",
            mark_all_deleted=True,
            complete=True,
            connection=connection,
        )

        assert api.writes.deleted_frames[result.task_id] == [0, 1, 2, 3]
        assert api.writes.job_updates == [
            (result.task_id, "acceptance", "completed"),
        ]

    def test_defaults_delete_only_deleted_rows_and_leave_jobs_alone(
        self, normal_fake: LoadedFixtures, tmp_path: Path
    ) -> None:
        fake = normal_fake
        api, connection = _scoped(
            fake, cloud_storage=make_cs_info(cs_id=7, bucket="b", prefix="images")
        )

        result = cveta2.upload(
            self._dataset(tmp_path),
            project=fake.project.id,
            name="api-upload",
            connection=connection,
        )

        assert api.writes.deleted_frames[result.task_id] == [3]
        assert api.writes.job_updates == []

    def test_image_dirs_are_searched_for_local_files(
        self, normal_fake: LoadedFixtures, tmp_path: Path
    ) -> None:
        """``image_dirs`` only matters through ``build_search_dirs``."""
        fake = normal_fake
        local = tmp_path / "local"
        local.mkdir()
        (local / "a.jpg").write_bytes(b"jpeg")
        _api, connection = _scoped(
            fake, cloud_storage=make_cs_info(cs_id=7, bucket="b", prefix="images")
        )

        cveta2.upload(
            self._dataset(tmp_path),
            project=fake.project.id,
            name="api-upload",
            image_dirs=[local],
            connection=connection,
        )

        assert [sorted(call) for call in _RecordingUploader.calls] == [["a.jpg"]]

    def test_project_image_cache_is_searched_when_no_dirs_given(
        self,
        normal_fake: LoadedFixtures,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``build_search_dirs`` needs the project *name* for that fallback."""
        fake = normal_fake
        cached = tmp_path / "cached"
        cached.mkdir()
        (cached / "b.jpg").write_bytes(b"jpeg")
        config = write_config_yaml(
            tmp_path / "images.yaml", image_cache={fake.project.name: str(cached)}
        )
        monkeypatch.setenv("CVETA2_CONFIG", str(config))
        _api, connection = _scoped(
            fake, cloud_storage=make_cs_info(cs_id=7, bucket="b", prefix="images")
        )

        cveta2.upload(
            self._dataset(tmp_path),
            project=fake.project.id,
            name="api-upload",
            connection=connection,
        )

        assert [sorted(call) for call in _RecordingUploader.calls] == [["b.jpg"]]

    def test_dataframe_input_is_accepted(
        self, normal_fake: LoadedFixtures, tmp_path: Path
    ) -> None:
        fake = normal_fake
        api, connection = _scoped(
            fake, cloud_storage=make_cs_info(cs_id=7, bucket="b", prefix="images")
        )
        df = pd.read_csv(self._dataset(tmp_path))

        cveta2.upload(
            df,
            project=fake.project.id,
            name="api-upload",
            connection=connection,
        )

        assert api.writes.created_tasks[0].name == "api-upload"


class TestS3SyncApi:
    """``s3_sync`` resolves the storage, applies overrides and strips prefixes."""

    @staticmethod
    def _fake_bucket(monkeypatch: pytest.MonkeyPatch) -> FakeS3Client:
        s3 = FakeS3Client(
            {"raw/a.jpg": b"A", "synced/sub/b.jpg": b"B"}, keyed_by_bucket=False
        )
        monkeypatch.setattr(
            "cveta2.image_downloader.make_s3_client", lambda _endpoint=None: s3
        )
        return s3

    def test_explicit_root_overrides_the_project_prefix(
        self,
        normal_fake: LoadedFixtures,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``root=`` must beat the storage the project itself reports.

        ``sync_project_images`` falls back to detecting the storage when
        it is handed None, so only a *differing* prefix shows that the
        override reached it.
        """
        self._fake_bucket(monkeypatch)
        target = tmp_path / "images"
        _api, connection = _scoped(
            normal_fake, cloud_storage=make_cs_info(bucket="bkt", prefix="raw")
        )

        stats = cveta2.s3_sync(
            normal_fake.project.id,
            target,
            root="s3://bkt/synced",
            connection=connection,
        )

        assert stats.downloaded == 1
        assert (target / "sub" / "b.jpg").exists()
        assert not (target / "a.jpg").exists()

    def test_sync_roots_config_and_ignored_prefix_shape_the_layout(
        self,
        normal_fake: LoadedFixtures,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Two per-project settings read from two different config files.

        ``sync_roots`` is loaded from the ambient config and keyed by
        project name; ``cache.projects.<name>.ignored_prefix`` comes from
        the connection's explicit config path. Between them they pin the
        project name, both config lookups and the ``ignored_prefix``
        keyword.
        """
        self._fake_bucket(monkeypatch)
        target = tmp_path / "images"
        env_config = write_config_yaml(
            tmp_path / "sync.yaml",
            sync_roots={normal_fake.project.name: "synced"},
        )
        monkeypatch.setenv("CVETA2_CONFIG", str(env_config))
        cache_config = write_config_yaml(
            tmp_path / "cache.yaml",
            cache={
                "projects": {normal_fake.project.name: {"ignored_prefix": "synced/sub"}}
            },
        )
        _api, connection = _scoped(
            normal_fake,
            cloud_storage=make_cs_info(bucket="bkt", prefix="raw"),
            config_path=cache_config,
        )

        cveta2.s3_sync(normal_fake.project.id, target, connection=connection)

        assert (target / "b.jpg").exists()
        assert not (target / "sub").exists()
        assert not (target / "raw").exists()

    def test_project_without_cloud_storage_syncs_nothing(
        self,
        normal_fake: LoadedFixtures,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The fallback detection inside the client needs the project id.

        With no storage anywhere, ``sync_project_images`` re-detects from
        the id it was given — the one place that argument is load-bearing.
        """
        self._fake_bucket(monkeypatch)
        _api, connection = _scoped(normal_fake)

        stats = cveta2.s3_sync(
            normal_fake.project.id, tmp_path / "images", connection=connection
        )

        assert stats.total == 0


class TestMergeApi:
    @staticmethod
    def _pair(tmp_path: Path) -> tuple[Path, Path]:
        old = write_dataset_csv(
            tmp_path / "old.csv",
            [
                csv_row("a.jpg", label="cat", updated="2026-05-01T00:00:00Z"),
                csv_row("b.jpg", label="cat", updated="2026-05-01T00:00:00Z"),
            ],
            columns=CSV_COLUMNS,
        )
        new = write_dataset_csv(
            tmp_path / "new.csv",
            [
                csv_row("a.jpg", label="dog", updated="2026-01-01T00:00:00Z"),
                csv_row("c.jpg", label="dog", updated="2026-01-01T00:00:00Z"),
            ],
            columns=CSV_COLUMNS,
        )
        return old, new

    def test_new_wins_and_the_output_is_written(self, tmp_path: Path) -> None:
        """Also pins ``by_time``'s default: old is the newer side here."""
        old, new = self._pair(tmp_path)
        output = tmp_path / "merged.csv"

        merged = cveta2.merge(old, new, output)

        assert output.exists()
        assert _labels_by_image(merged) == {
            "a.jpg": "dog",
            "b.jpg": "cat",
            "c.jpg": "dog",
        }

    def test_deleted_images_are_dropped(self, tmp_path: Path) -> None:
        old, new = self._pair(tmp_path)
        deleted = write_dataset_csv(tmp_path / "deleted.csv", [{"image_name": "b.jpg"}])

        merged = cveta2.merge(old, new, tmp_path / "merged.csv", deleted=deleted)

        assert set(merged["image_name"]) == {"a.jpg", "c.jpg"}

    def test_by_time_keeps_the_more_recent_side(self, tmp_path: Path) -> None:
        old, new = self._pair(tmp_path)

        merged = cveta2.merge(old, new, tmp_path / "merged.csv", by_time=True)

        assert _labels_by_image(merged)["a.jpg"] == "cat"


class TestWhatsNewApi:
    def test_lists_tasks_newer_than_dataset(
        self, coco8_fixtures: LoadedFixtures, tmp_path: Path
    ) -> None:
        fake = build_fake(
            coco8_fixtures, ["normal", "all-empty"], statuses=["completed", "completed"]
        )
        old_task, new_task = fake.tasks
        dataset = write_dataset_csv(
            tmp_path / "dataset.csv",
            [
                csv_row(
                    "a.jpg",
                    task_id=old_task.id,
                    updated="2020-01-01T00:00:00+00:00",
                )
            ],
        )
        _api, connection = _scoped(fake)

        result = cveta2.whats_new(fake.project.id, dataset, connection=connection)

        assert {t.id for t in result.tasks} == {old_task.id, new_task.id}
        assert result.updated_task_ids == {old_task.id}
        assert result.cutoff == "2020-01-01T00:00:00+00:00"

    def test_error_names_the_dataset_file(
        self, normal_fake: LoadedFixtures, tmp_path: Path
    ) -> None:
        """The CSV path is passed to ``compute_baseline`` only for this message."""
        dataset = write_dataset_csv(
            tmp_path / "dataset.csv",
            [csv_row("a.jpg", updated="")],
            columns=CSV_COLUMNS,
        )
        _api, connection = _scoped(normal_fake)

        with pytest.raises(Cveta2Error, match=re.escape(str(dataset))):
            cveta2.whats_new(normal_fake.project.id, dataset, connection=connection)


class TestIgnoreApi:
    def test_add_list_remove_roundtrip(self, normal_fake: LoadedFixtures) -> None:
        fake = normal_fake
        task = fake.tasks[0]
        connection = fake_connection(fake)

        added = cveta2.ignore(
            fake.project.id,
            add=[task.id],
            description="broken",
            silent=True,
            connection=connection,
        )
        assert [(e.id, e.description, e.silent) for e in added] == [
            (task.id, "broken", True)
        ]

        listed = cveta2.ignore(fake.project.id, connection=connection)
        assert [e.id for e in listed] == [task.id]

        remaining = cveta2.ignore(
            fake.project.id, remove=[task.id], connection=connection
        )
        assert remaining == []

    def test_add_defaults_persist_to_the_connection_config(
        self, normal_fake: LoadedFixtures, tmp_path: Path
    ) -> None:
        """Pins the keyword defaults *and* the config path on both ends.

        Seeding another project's entry makes a load from the wrong file
        visible too: saving a config that was read from somewhere else
        would drop it.
        """
        fake = normal_fake
        task = fake.tasks[0]
        config = write_config_yaml(
            tmp_path / "ignore.yaml",
            ignore={"other-project": [{"id": 99, "name": "keep-me"}]},
        )
        _api, connection = _scoped(fake, config_path=config)

        cveta2.ignore(fake.project.id, add=[task.id], connection=connection)

        persisted = IgnoreConfig.load(config)
        assert persisted.get_ignored_entries(fake.project.name) == [
            IgnoredTask(id=task.id, name=task.name, description="", silent=False)
        ]
        assert persisted.get_ignored_entries("other-project") == [
            IgnoredTask(id=99, name="keep-me")
        ]


class TestTaskOpsApi:
    def test_delete_removes_the_resolved_task(
        self, normal_fake: LoadedFixtures
    ) -> None:
        api, connection = _scoped(normal_fake)
        task = normal_fake.tasks[0]

        cveta2.task_delete(normal_fake.project.id, task.name, connection=connection)

        assert api.writes.deleted_tasks == [task.id]

    def test_drop_label_deletes_only_that_labels_shapes(
        self, normal_fake: LoadedFixtures
    ) -> None:
        api, connection = _scoped(normal_fake)
        task = normal_fake.tasks[0]
        label = next(lbl for lbl in normal_fake.labels if lbl.name == "bowl")
        expected = _shapes_with_label(normal_fake, task.id, label.id)

        removed = cveta2.task_drop_label(
            normal_fake.project.id, task.id, "bowl", connection=connection
        )

        assert removed == len(expected)
        assert {s.label_id for s in api.writes.deleted_shapes[task.id]} == {label.id}

    def test_mark_deleted_requires_frames_or_images(
        self, normal_fake: LoadedFixtures
    ) -> None:
        _api, connection = _scoped(normal_fake)

        with pytest.raises(Cveta2Error, match="frame"):
            cveta2.task_mark_deleted(
                normal_fake.project.id,
                normal_fake.tasks[0].id,
                connection=connection,
            )

    def test_mark_deleted_by_image_names(self, normal_fake: LoadedFixtures) -> None:
        api, connection = _scoped(normal_fake)
        task = normal_fake.tasks[0]
        names = [f.name for f in normal_fake.task_data[task.id][0].frames]

        marked = cveta2.task_mark_deleted(
            normal_fake.project.id,
            task.id,
            images=names[:2],
            connection=connection,
        )

        assert marked == 2
        assert api.writes.deleted_frames[task.id] == [0, 1]

    def test_mark_deleted_by_frame_ids(self, normal_fake: LoadedFixtures) -> None:
        api, connection = _scoped(normal_fake)
        task = normal_fake.tasks[0]

        marked = cveta2.task_mark_deleted(
            normal_fake.project.id, task.id, frames=[3], connection=connection
        )

        assert marked == 1
        assert api.writes.deleted_frames[task.id] == [3]

    def test_mark_deleted_sums_disjoint_names_and_ids(
        self, normal_fake: LoadedFixtures
    ) -> None:
        """Disjoint sets make the total distinguish sum from either half."""
        api, connection = _scoped(normal_fake)
        task = normal_fake.tasks[0]
        names = [f.name for f in normal_fake.task_data[task.id][0].frames]

        marked = cveta2.task_mark_deleted(
            normal_fake.project.id,
            task.id,
            images=[names[0]],
            frames=[5, 6],
            connection=connection,
        )

        assert marked == 3
        assert api.writes.deleted_frames[task.id] == [0, 5, 6]


class TestTaskSetStatusApi:
    def test_invalid_state_rejected_before_remote_call(self) -> None:
        with pytest.raises(Cveta2Error, match="state"):
            cveta2.task_set_status(1, 1, state="in-progress")  # type: ignore[arg-type]

    def test_invalid_stage_rejected_before_remote_call(self) -> None:
        with pytest.raises(Cveta2Error, match="stage"):
            cveta2.task_set_status(1, 1, stage="done")  # type: ignore[arg-type]

    def test_requires_stage_or_state(self) -> None:
        with pytest.raises(Cveta2Error, match="stage"):
            cveta2.task_set_status(1, 1)

    def test_stage_and_state_reach_every_job(self, normal_fake: LoadedFixtures) -> None:
        """Both must be non-None at once to tell the two keywords apart."""
        api, connection = _scoped(normal_fake)
        task = normal_fake.tasks[0]

        updated = cveta2.task_set_status(
            normal_fake.project.id,
            task.id,
            stage="acceptance",
            state="completed",
            connection=connection,
        )

        assert updated == 1
        assert api.writes.job_updates == [(task.id, "acceptance", "completed")]

    def test_stage_alone_is_accepted(self, normal_fake: LoadedFixtures) -> None:
        """A valid stage with no state must pass all three guards."""
        api, connection = _scoped(normal_fake)
        task = normal_fake.tasks[0]

        cveta2.task_set_status(
            normal_fake.project.id,
            task.id,
            stage="validation",
            connection=connection,
        )

        assert api.writes.job_updates == [(task.id, "validation", None)]

    def test_state_alone_is_accepted(self, normal_fake: LoadedFixtures) -> None:
        api, connection = _scoped(normal_fake)
        task = normal_fake.tasks[0]

        cveta2.task_set_status(
            normal_fake.project.id,
            task.id,
            state="rejected",
            connection=connection,
        )

        assert api.writes.job_updates == [(task.id, None, "rejected")]


class TestLabelsApi:
    def test_get_labels(self, normal_fake: LoadedFixtures) -> None:
        fake = normal_fake

        labels = cveta2.get_labels(fake.project.id, connection=fake_connection(fake))

        assert labels == fake.labels

    def test_get_labels_queries_the_resolved_project(
        self, normal_fake: LoadedFixtures
    ) -> None:
        """The shared fake serves labels for any id; this one does not."""
        _api, connection = _scoped(normal_fake)

        labels = cveta2.get_labels(normal_fake.project.id, connection=connection)

        assert labels == normal_fake.labels

    def test_update_labels_forwards_every_operation(
        self, normal_fake: LoadedFixtures
    ) -> None:
        """``update_labels`` had no test at all — all of it was unexecuted.

        The four operations produce four distinguishable patches, so one
        call pins every keyword as well as the project id.
        """
        api, connection = _scoped(normal_fake)
        by_name = {lbl.name: lbl for lbl in normal_fake.labels}

        cveta2.update_labels(
            normal_fake.project.id,
            add=["drone"],
            rename={by_name["person"].id: "human"},
            delete=[by_name["bicycle"].id],
            recolor={by_name["car"].id: "#ff0000"},
            connection=connection,
        )

        assert api.writes.label_patches[normal_fake.project.id] == [
            LabelPatch(name="drone"),
            LabelPatch(id=by_name["person"].id, name="human"),
            LabelPatch(id=by_name["bicycle"].id, deleted=True),
            LabelPatch(id=by_name["car"].id, color="#ff0000"),
        ]


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


def _labels_by_image(df: pd.DataFrame) -> dict[str, str]:
    return dict(zip(df["image_name"], df["instance_label"], strict=True))


def _shapes_with_label(
    fixtures: LoadedFixtures, task_id: int, label_id: int
) -> list[RawShape]:
    _meta, annotations = fixtures.task_data[task_id]
    return [s for s in annotations.shapes if s.label_id == label_id]


class TestUploadResumeWiring:
    """What `cveta2.upload` puts in the request that decides a resume."""

    @staticmethod
    def _capture(
        monkeypatch: pytest.MonkeyPatch, fake: LoadedFixtures, **kwargs: object
    ) -> UploadRequest:
        """Run ``upload`` far enough to see the request it builds."""
        seen: list[UploadRequest] = []

        def record(_client: object, request: UploadRequest) -> UploadOutcome:
            seen.append(request)
            return UploadOutcome(
                task_id=1,
                task_name=request.task_name,
                images=0,
                deleted=0,
                annotations=0,
                issues=0,
                jobs=0,
            )

        monkeypatch.setattr("cveta2.api.upload_dataset", record)
        cveta2.upload(
            pd.DataFrame([csv_row("a.jpg", label="cat")]),
            project=fake.project.id,
            name="t",
            connection=fake_connection(fake),
            **kwargs,  # type: ignore[arg-type]
        )
        return seen[0]

    def test_resume_reaches_the_request(
        self, normal_fake: LoadedFixtures, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert self._capture(monkeypatch, normal_fake, resume=True).resume is True

    def test_resume_is_off_unless_asked_for(
        self, normal_fake: LoadedFixtures, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A library caller must not silently adopt a stranded task."""
        assert self._capture(monkeypatch, normal_fake).resume is False

    def test_the_selected_labels_reach_the_request(
        self, normal_fake: LoadedFixtures, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """They are half the fingerprint that identifies the upload."""
        request = self._capture(monkeypatch, normal_fake, labels=["cat"])

        assert request.labels == ("cat",)

    def test_a_dataframe_input_has_no_dataset_path(
        self, normal_fake: LoadedFixtures, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """There is no file to name, and ``str(df)`` would dump the frame."""
        assert self._capture(monkeypatch, normal_fake).dataset_path == ""

    def test_a_csv_input_records_its_path(
        self,
        normal_fake: LoadedFixtures,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """It is what a mismatch report shows to identify the stranded run."""
        csv = tmp_path / "dataset.csv"
        csv.write_text("image_name,instance_label\na.jpg,cat\n", encoding="utf-8")
        seen: list[UploadRequest] = []

        def record(_client: object, request: UploadRequest) -> UploadOutcome:
            seen.append(request)
            return UploadOutcome(
                task_id=1,
                task_name=request.task_name,
                images=0,
                deleted=0,
                annotations=0,
                issues=0,
                jobs=0,
            )

        monkeypatch.setattr("cveta2.api.upload_dataset", record)
        cveta2.upload(
            csv,
            project=normal_fake.project.id,
            name="t",
            connection=fake_connection(normal_fake),
        )

        assert seen[0].dataset_path == str(csv)
