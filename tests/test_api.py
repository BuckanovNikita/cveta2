"""Tests for the public workflow API (cveta2.api)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd
import pytest

import cveta2
from cveta2.api import _resolve_client
from cveta2.exceptions import (
    Cveta2Error,
    LabelsMismatchError,
    MissingCredentialsError,
    MissingHostError,
)
from cveta2.models import CSV_COLUMNS
from tests.helpers import build_fake, csv_row, make_fake_client, write_dataset_csv

if TYPE_CHECKING:
    from pathlib import Path

    from typing_extensions import Self

    from tests.fixtures.fake_cvat_project import LoadedFixtures


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CVETA2_CONFIG", str(tmp_path / "missing.yaml"))
    for var in ("CVAT_HOST", "CVAT_ORGANIZATION", "CVAT_USERNAME", "CVAT_PASSWORD"):
        monkeypatch.delenv(var, raising=False)


class TestResolveClient:
    def test_injected_client_used_as_is(self) -> None:
        sentinel = object()
        with _resolve_client(sentinel, None, None, None, None, None) as client:  # type: ignore[arg-type]
            assert client is sentinel

    def test_missing_host_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "cveta2.api.CvatConfig.load", lambda *_a, **_k: cveta2.CvatConfig()
        )
        with (
            pytest.raises(MissingHostError, match="CVAT_HOST"),
            _resolve_client(None, None, None, None, None, None),
        ):
            pytest.fail("must not yield")

    def test_missing_credentials_raise(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "cveta2.api.CvatConfig.load", lambda *_a, **_k: cveta2.CvatConfig()
        )
        with (
            pytest.raises(MissingCredentialsError, match="CVAT_USERNAME"),
            _resolve_client(None, "http://cvat.test", None, None, None, None),
        ):
            pytest.fail("must not yield")

    def test_kwargs_override_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
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
        with _resolve_client(None, "http://explicit", "user", "pass", None, None):
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

        df = cveta2.fetch(
            fake.project.id,
            out,
            download_images=False,
            publish_clearml=False,
            client=make_fake_client(fake),
        )

        assert (out / "dataset.csv").exists()
        assert (out / "obsolete.csv").exists()
        assert (out / "in_progress.csv").exists()
        assert (out / "deleted.csv").exists()
        assert not df.empty
        assert set(df["task_id"].unique()) == {fake.tasks[1].id}
        assert len(pd.read_csv(out / "obsolete.csv")) > 0

    def test_fetch_task_returns_dataframe(
        self, normal_fake: LoadedFixtures, tmp_path: Path
    ) -> None:
        fake = normal_fake
        out = tmp_path / "out"

        df = cveta2.fetch_task(
            fake.project.id,
            [fake.tasks[0].name],
            out,
            download_images=False,
            client=make_fake_client(fake),
        )

        assert (out / "dataset.csv").exists()
        assert (out / "deleted.csv").exists()
        assert isinstance(df, pd.DataFrame)
        assert list(pd.read_csv(out / "dataset.csv").columns) == list(CSV_COLUMNS)
        assert len(df) == len(pd.read_csv(out / "dataset.csv"))

    def test_fetch_by_project_name(
        self, normal_fake: LoadedFixtures, tmp_path: Path
    ) -> None:
        fake = normal_fake

        df = cveta2.fetch(
            fake.project.name,
            tmp_path / "out",
            download_images=False,
            publish_clearml=False,
            client=make_fake_client(fake),
        )

        assert not df.empty

    def test_fetch_without_images_dir_config_raises(
        self, normal_fake: LoadedFixtures, tmp_path: Path
    ) -> None:
        fake = normal_fake

        with pytest.raises(Cveta2Error, match="image_cache"):
            cveta2.fetch(
                fake.project.id,
                tmp_path / "out",
                publish_clearml=False,
                client=make_fake_client(fake),
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
                client=make_fake_client(fake),
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
                client=make_fake_client(fake),
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

        tasks = cveta2.whats_new(
            fake.project.id, dataset, client=make_fake_client(fake)
        )

        assert {t.id for t in tasks} == {old_task.id, new_task.id}


class TestLabelsApi:
    def test_get_labels(self, normal_fake: LoadedFixtures) -> None:
        fake = normal_fake

        labels = cveta2.get_labels(fake.project.id, client=make_fake_client(fake))

        assert labels == fake.labels
