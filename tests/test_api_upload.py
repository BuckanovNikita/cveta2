"""Public API upload contracts."""

from importlib import import_module
from typing import TYPE_CHECKING

import pandas as pd
import pytest

import cveta2
from cveta2.application.use_cases.upload import UploadOutcome, UploadRequest
from cveta2.domain.errors import (
    Cveta2Error,
    LabelsMismatchError,
)
from cveta2.domain.models import CSV_COLUMNS
from cveta2.domain.paths import build_s3_key
from cveta2.domain.storage import UploadStats
from tests.helpers import (
    csv_row,
    fake_connection,
    make_cs_info,
    write_config_yaml,
    write_dataset_csv,
)

if TYPE_CHECKING:
    from pathlib import Path

    from cveta2.domain.storage import CloudStorageInfo
    from tests.fixtures.fake_cvat_project import LoadedFixtures

from tests.api_helpers import _scoped


class _RecordingUploader:
    """``S3Uploader`` stand-in recording what the upload pipeline staged."""

    calls: "list[dict[str, Path]]" = []  # noqa: RUF012

    def upload(
        self,
        cs_info: "CloudStorageInfo",
        images: "dict[str, Path]",
        name_to_server_file: dict[str, str] | None = None,
        existing_keys: set[str] | None = None,
    ) -> UploadStats:
        """Record *images* instead of talking to S3."""
        del cs_info, name_to_server_file, existing_keys
        type(self).calls.append(dict(images))
        return UploadStats(uploaded=len(images), total=len(images))


class TestUploadApi:
    """End-to-end uploads against the fake, with S3 stubbed out."""

    @staticmethod
    def _dataset(tmp_path: "Path") -> "Path":
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

        def mapping_with_every_image_on_s3(
            cs_info: "CloudStorageInfo",
            names: list[str],
            pinned: dict[str, str] | None = None,
        ) -> tuple[dict[str, str], set[str]]:
            mapping = dict(pinned) if pinned is not None else {n: n for n in names}
            return mapping, {
                build_s3_key(cs_info.prefix, sf) for sf in mapping.values()
            }

        monkeypatch.setattr(
            "cveta2.adapters.s3.upload.S3UploadStorage.mapping",
            staticmethod(mapping_with_every_image_on_s3),
        )
        monkeypatch.setattr(
            "cveta2.adapters.s3.upload.S3UploadStorage.upload",
            staticmethod(_RecordingUploader().upload),
        )

    def test_unknown_labels_raise_mismatch_end_to_end(
        self, normal_fake: "LoadedFixtures", tmp_path: "Path"
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
        self, normal_fake: "LoadedFixtures", tmp_path: "Path"
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
        self, normal_fake: "LoadedFixtures", tmp_path: "Path"
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
        self, normal_fake: "LoadedFixtures", tmp_path: "Path"
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
        self, normal_fake: "LoadedFixtures", tmp_path: "Path"
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
        self, normal_fake: "LoadedFixtures", tmp_path: "Path"
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
        self, normal_fake: "LoadedFixtures", tmp_path: "Path"
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
        self, normal_fake: "LoadedFixtures", tmp_path: "Path"
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
        self, normal_fake: "LoadedFixtures", tmp_path: "Path"
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
        self, normal_fake: "LoadedFixtures", tmp_path: "Path"
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
        self, normal_fake: "LoadedFixtures", tmp_path: "Path"
    ) -> None:
        """``build_search_dirs`` needs the project *name* and the config path.

        The ``image_cache`` entry lives only in the connection's config
        file; the ambient config is empty, so the fallback is found only
        if ``Connection.config_path`` reaches the lookup.
        """
        fake = normal_fake
        cached = tmp_path / "cached"
        cached.mkdir()
        (cached / "b.jpg").write_bytes(b"jpeg")
        config = write_config_yaml(
            tmp_path / "images.yaml", image_cache={fake.project.name: str(cached)}
        )
        _api, connection = _scoped(
            fake,
            cloud_storage=make_cs_info(cs_id=7, bucket="b", prefix="images"),
            config_path=config,
        )

        cveta2.upload(
            self._dataset(tmp_path),
            project=fake.project.id,
            name="api-upload",
            connection=connection,
        )

        assert [sorted(call) for call in _RecordingUploader.calls] == [["b.jpg"]]

    def test_dataframe_input_is_accepted(
        self, normal_fake: "LoadedFixtures", tmp_path: "Path"
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


class TestUploadResumeWiring:
    """What `cveta2.upload` puts in the request that decides a resume."""

    @staticmethod
    def _capture(
        monkeypatch: pytest.MonkeyPatch, fake: "LoadedFixtures", **kwargs: object
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

        monkeypatch.setattr(
            import_module("cveta2.interfaces.api.upload"), "upload_cvat_dataset", record
        )
        cveta2.upload(
            pd.DataFrame([csv_row("a.jpg", label="cat")]),
            project=fake.project.id,
            name="t",
            connection=fake_connection(fake),
            **kwargs,  # type: ignore[arg-type]
        )
        return seen[0]

    def test_resume_reaches_the_request(
        self, normal_fake: "LoadedFixtures", monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert self._capture(monkeypatch, normal_fake, resume=True).resume is True

    def test_resume_is_off_unless_asked_for(
        self, normal_fake: "LoadedFixtures", monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A library caller must not silently adopt a stranded task."""
        assert self._capture(monkeypatch, normal_fake).resume is False

    def test_the_selected_labels_reach_the_request(
        self, normal_fake: "LoadedFixtures", monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """They are half the fingerprint that identifies the upload."""
        request = self._capture(monkeypatch, normal_fake, labels=["cat"])

        assert request.labels == ("cat",)

    def test_a_dataframe_input_has_no_dataset_path(
        self, normal_fake: "LoadedFixtures", monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """There is no file to name, and ``str(df)`` would dump the frame."""
        assert self._capture(monkeypatch, normal_fake).dataset_path == ""

    def test_a_csv_input_records_its_path(
        self,
        normal_fake: "LoadedFixtures",
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: "Path",
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

        monkeypatch.setattr(
            import_module("cveta2.interfaces.api.upload"), "upload_cvat_dataset", record
        )
        cveta2.upload(
            csv,
            project=normal_fake.project.id,
            name="t",
            connection=fake_connection(normal_fake),
        )

        assert seen[0].dataset_path == str(csv)
