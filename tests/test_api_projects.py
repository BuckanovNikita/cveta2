"""Public API projects contracts."""

import re
from typing import TYPE_CHECKING
from unittest.mock import patch

import pandas as pd
import pytest

import cveta2
from cveta2.adapters.config.settings import IgnoreConfig, IgnoredTask
from cveta2.application.ports.dtos import LabelPatch
from cveta2.domain.errors import (
    Cveta2Error,
    TaskNotFoundError,
)
from cveta2.domain.models import CSV_COLUMNS
from tests.fixtures.fake_s3 import FakeS3Client
from tests.helpers import (
    build_fake,
    csv_row,
    fake_connection,
    make_cs_info,
    write_config_yaml,
    write_dataset_csv,
)

if TYPE_CHECKING:
    from pathlib import Path

    from tests.fixtures.fake_cvat_project import LoadedFixtures

from tests.api_helpers import _scoped


class TestS3SyncApi:
    """``s3_sync`` resolves the storage, applies overrides and strips prefixes."""

    @staticmethod
    def _fake_bucket(monkeypatch: pytest.MonkeyPatch) -> FakeS3Client:
        s3 = FakeS3Client(
            {"raw/a.jpg": b"A", "synced/sub/b.jpg": b"B"}, keyed_by_bucket=False
        )
        monkeypatch.setattr(
            "cveta2.adapters.s3.download.make_s3_client", lambda _endpoint=None: s3
        )
        return s3

    def test_explicit_root_overrides_the_project_prefix(
        self,
        normal_fake: "LoadedFixtures",
        tmp_path: "Path",
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
        normal_fake: "LoadedFixtures",
        tmp_path: "Path",
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Two per-project settings read from the connection's config file.

        ``sync_roots`` and ``cache.projects.<name>.ignored_prefix`` are
        both keyed by project name and both come from
        ``Connection.config_path`` — the ambient config is empty. Between
        them they pin the project name, both config lookups and the
        ``ignored_prefix`` keyword.
        """
        self._fake_bucket(monkeypatch)
        target = tmp_path / "images"
        config = write_config_yaml(
            tmp_path / "sync.yaml",
            sync_roots={normal_fake.project.name: "synced"},
            cache={
                "projects": {normal_fake.project.name: {"ignored_prefix": "synced/sub"}}
            },
        )
        _api, connection = _scoped(
            normal_fake,
            cloud_storage=make_cs_info(bucket="bkt", prefix="raw"),
            config_path=config,
        )

        cveta2.s3_sync(normal_fake.project.id, target, connection=connection)

        assert (target / "b.jpg").exists()
        assert not (target / "sub").exists()
        assert not (target / "raw").exists()

    def test_project_without_cloud_storage_syncs_nothing(
        self,
        normal_fake: "LoadedFixtures",
        tmp_path: "Path",
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
    def _pair(tmp_path: "Path") -> "tuple[Path, Path]":
        old = write_dataset_csv(
            tmp_path / "old.csv",
            [
                csv_row("a.jpg", label="cat", task_id=9),
                csv_row("b.jpg", label="cat", task_id=9),
            ],
            columns=CSV_COLUMNS,
        )
        new = write_dataset_csv(
            tmp_path / "new.csv",
            [
                csv_row("a.jpg", label="dog", task_id=3),
                csv_row("c.jpg", label="dog", task_id=3),
            ],
            columns=CSV_COLUMNS,
        )
        return old, new

    def test_new_wins_and_the_output_is_written(self, tmp_path: "Path") -> None:
        """Also pins ``by_task``'s default: old holds the later task here."""
        old, new = self._pair(tmp_path)
        output = tmp_path / "merged.csv"

        merged = cveta2.merge(old, new, output)

        assert output.exists()
        assert _labels_by_image(merged) == {
            "a.jpg": "dog",
            "b.jpg": "cat",
            "c.jpg": "dog",
        }

    def test_deleted_images_are_dropped(self, tmp_path: "Path") -> None:
        old, new = self._pair(tmp_path)
        deleted = write_dataset_csv(tmp_path / "deleted.csv", [{"image_name": "b.jpg"}])

        merged = cveta2.merge(old, new, tmp_path / "merged.csv", deleted=deleted)

        assert set(merged["image_name"]) == {"a.jpg", "c.jpg"}

    def test_by_task_keeps_the_later_task_side(self, tmp_path: "Path") -> None:
        old, new = self._pair(tmp_path)

        merged = cveta2.merge(old, new, tmp_path / "merged.csv", by_task=True)

        assert _labels_by_image(merged)["a.jpg"] == "cat"


class TestWhatsNewApi:
    def test_lists_tasks_newer_than_dataset(
        self, coco8_fixtures: "LoadedFixtures", tmp_path: "Path"
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

        assert {t.id for t in result.tasks} == {new_task.id}
        assert result.cutoff == old_task.id

    def test_error_names_the_dataset_file(
        self, normal_fake: "LoadedFixtures", tmp_path: "Path"
    ) -> None:
        """The CSV path is passed to ``compute_baseline`` only for this message."""
        dataset = write_dataset_csv(
            tmp_path / "dataset.csv",
            [csv_row("a.jpg") | {"task_id": None}],
            columns=CSV_COLUMNS,
        )
        _api, connection = _scoped(normal_fake)

        with pytest.raises(Cveta2Error, match=re.escape(str(dataset))):
            cveta2.whats_new(normal_fake.project.id, dataset, connection=connection)


class TestIgnoreApi:
    def test_remove_name_resolves_remote_identity(
        self, normal_fake: "LoadedFixtures", tmp_path: "Path"
    ) -> None:
        task = normal_fake.tasks[0]
        project = normal_fake.project
        config = write_config_yaml(
            tmp_path / "ignore.yaml",
            ignore={project.name: [{"id": task.id, "name": task.name}]},
        )
        _api, connection = _scoped(normal_fake, config_path=config)
        assert (
            cveta2.ignore(project.id, remove=[task.name], connection=connection) == []
        )
        assert IgnoreConfig.load(config).get_ignored_entries(project.name) == []

    def test_unknown_id_requires_remote_resolution(
        self, normal_fake: "LoadedFixtures", tmp_path: "Path"
    ) -> None:
        config = write_config_yaml(tmp_path / "ignore.yaml", ignore={})
        _api, connection = _scoped(normal_fake, config_path=config)
        with pytest.raises(TaskNotFoundError):
            cveta2.ignore(
                normal_fake.project.id, remove=[999999], connection=connection
            )

    @pytest.mark.parametrize("selector", [999999, "999999"])
    def test_remove_stored_id_without_remote_task(
        self, normal_fake: "LoadedFixtures", tmp_path: "Path", selector: int | str
    ) -> None:
        config = write_config_yaml(
            tmp_path / "ignore.yaml",
            ignore={normal_fake.project.name: [{"id": 999999, "name": "deleted"}]},
        )
        _api, connection = _scoped(normal_fake, config_path=config)
        with patch.object(
            connection.client,
            "list_project_tasks",
            side_effect=AssertionError("remote task lookup"),
        ):
            assert (
                cveta2.ignore(
                    normal_fake.project.id, remove=[selector], connection=connection
                )
                == []
            )
        assert (
            IgnoreConfig.load(config).get_ignored_entries(normal_fake.project.name)
            == []
        )

    def test_add_list_remove_roundtrip(self, normal_fake: "LoadedFixtures") -> None:
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
        self, normal_fake: "LoadedFixtures", tmp_path: "Path"
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


class TestLabelsApi:
    def test_get_labels(self, normal_fake: "LoadedFixtures") -> None:
        fake = normal_fake

        labels = cveta2.get_labels(fake.project.id, connection=fake_connection(fake))

        assert labels == fake.labels

    def test_get_labels_queries_the_resolved_project(
        self, normal_fake: "LoadedFixtures"
    ) -> None:
        """The shared fake serves labels for any id; this one does not."""
        _api, connection = _scoped(normal_fake)

        labels = cveta2.get_labels(normal_fake.project.id, connection=connection)

        assert labels == normal_fake.labels

    def test_update_labels_forwards_every_operation(
        self, normal_fake: "LoadedFixtures"
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


def _labels_by_image(df: pd.DataFrame) -> dict[str, str]:
    return dict(zip(df["image_name"], df["instance_label"], strict=True))
