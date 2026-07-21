"""Tests for the public workflow API (cveta2.api)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd
import pytest

import cveta2
from cveta2.api import _open
from cveta2.exceptions import (
    Cveta2Error,
    LabelsMismatchError,
    MissingCredentialsError,
    MissingHostError,
)
from cveta2.models import CSV_COLUMNS
from tests.helpers import build_fake, csv_row, fake_connection, write_dataset_csv

if TYPE_CHECKING:
    from pathlib import Path

    from typing_extensions import Self

    from tests.fixtures.fake_cvat_project import LoadedFixtures


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CVETA2_CONFIG", str(tmp_path / "missing.yaml"))
    for var in ("CVAT_HOST", "CVAT_ORGANIZATION", "CVAT_USERNAME", "CVAT_PASSWORD"):
        monkeypatch.delenv(var, raising=False)


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

    def test_fetch_task_writes_csvs_matching_dataframe(
        self, normal_fake: LoadedFixtures, tmp_path: Path
    ) -> None:
        fake = normal_fake
        out = tmp_path / "out"

        df = cveta2.fetch_task(
            fake.project.id,
            [fake.tasks[0].name],
            out,
            download_images=False,
            connection=fake_connection(fake),
        )

        assert (out / "dataset.csv").exists()
        assert (out / "deleted.csv").exists()
        assert list(pd.read_csv(out / "dataset.csv").columns) == list(CSV_COLUMNS)
        assert len(df) == len(pd.read_csv(out / "dataset.csv"))

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


class TestUploadApi:
    def test_unknown_labels_raise_mismatch_end_to_end(
        self, normal_fake: LoadedFixtures, tmp_path: Path
    ) -> None:
        fake = normal_fake
        dataset = write_dataset_csv(
            tmp_path / "dataset.csv",
            [csv_row("a.jpg", label="ghost-label")],
            columns=CSV_COLUMNS,
        )

        with pytest.raises(LabelsMismatchError, match="ghost-label"):
            cveta2.upload(
                dataset,
                project=fake.project.id,
                name="api-upload",
                connection=fake_connection(fake),
            )

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

        result = cveta2.whats_new(
            fake.project.id, dataset, connection=fake_connection(fake)
        )

        assert {t.id for t in result.tasks} == {old_task.id, new_task.id}
        assert result.updated_task_ids == {old_task.id}


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
        assert [(e.id, e.silent) for e in added] == [(task.id, True)]

        listed = cveta2.ignore(fake.project.id, connection=connection)
        assert [e.id for e in listed] == [task.id]

        remaining = cveta2.ignore(
            fake.project.id, remove=[task.id], connection=connection
        )
        assert remaining == []


class TestTaskSetStatusApi:
    def test_invalid_state_rejected_before_remote_call(self) -> None:
        with pytest.raises(Cveta2Error, match="state"):
            cveta2.task_set_status(1, 1, state="in-progress")  # type: ignore[arg-type]

    def test_requires_stage_or_state(self) -> None:
        with pytest.raises(Cveta2Error, match="stage"):
            cveta2.task_set_status(1, 1)


class TestLabelsApi:
    def test_get_labels(self, normal_fake: LoadedFixtures) -> None:
        fake = normal_fake

        labels = cveta2.get_labels(fake.project.id, connection=fake_connection(fake))

        assert labels == fake.labels
