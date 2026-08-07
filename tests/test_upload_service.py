"""End-to-end tests for the upload service against the recording fakes.

``_stage_images``, ``_push_to_cvat`` and ``upload_dataset`` used to appear
in the suite only as patch targets, so no assertion covered the chain they
drive.  These tests run the real pipeline over :class:`FakeCvatApi` and an
in-memory S3, which is what makes the argument-level behaviour of each step
observable.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pandas as pd
import pytest

from cveta2.exceptions import Cveta2Error, LabelsMismatchError
from cveta2.models import LabelInfo, ProjectInfo
from cveta2.services.upload import (
    UploadOptions,
    UploadPlan,
    UploadRequest,
    _stage_images,
    upload_dataset,
)
from cveta2.task_cache import get_task_cache_dir
from tests.fixtures.fake_cvat_api import FakeCvatApi
from tests.fixtures.fake_cvat_project import LoadedFixtures
from tests.fixtures.fake_s3 import FakeS3Client
from tests.helpers import client_with_api, make_cs_info

if TYPE_CHECKING:
    from cveta2._client.dtos import RawDataMeta
    from cveta2.client import CvatClient
    from cveta2.image_downloader import CloudStorageInfo

PROJECT_ID = 7
PROJECT_NAME = "proj"
BUCKET = "test-bucket"
PREFIX = "images"
LABEL = "car"
# Seeded under a month that is not the current one, so the server_file the
# mapping reuses for an already-uploaded image is a fixed literal.
SEEDED_SERVER_FILE = "2020-01/a.jpg"
SEEDED_KEY = f"{PREFIX}/{SEEDED_SERVER_FILE}"
# The task id FakeCvatApi allocates for the first task of an empty project.
NEW_TASK_ID = 1


def current_month_key(name: str) -> str:
    """S3 key a brand-new image gets: ``<prefix>/<current UTC month>/<name>``."""
    month = datetime.now(tz=timezone.utc).strftime("%Y-%m")
    return f"{PREFIX}/{month}/{name}"


class _ProjectScopedFake(FakeCvatApi):
    """A fake whose project-scoped reads actually depend on the project id.

    :class:`FakeCvatApi` answers ``get_project_labels`` and
    ``get_project_cloud_storage`` identically for every id, so a call that
    passed the wrong project — or ``None`` — was indistinguishable from a
    correct one.  It also counts ``get_task_data_meta`` calls: reusing one
    :class:`~cveta2._client_ops.session.TaskWriteSession` across the write
    chain is only observable as the number of metadata fetches.
    """

    def __init__(
        self,
        fixtures: LoadedFixtures,
        *,
        cloud_storage: CloudStorageInfo | None,
    ) -> None:
        """Serve *cloud_storage* for the fixture project only."""
        super().__init__(fixtures)
        self._cloud_storage = cloud_storage
        self.data_meta_calls: list[int] = []

    def get_project_labels(self, _project_id: int) -> list[LabelInfo]:
        """Return the fixture labels only for the fixture project."""
        if _project_id != self._project.id:
            return []
        return list(self._labels)

    def get_project_cloud_storage(self, _project_id: int) -> CloudStorageInfo | None:
        """Return the configured storage only for the fixture project."""
        if _project_id != self._project.id:
            return None
        return self._cloud_storage

    def get_task_data_meta(self, task_id: int) -> RawDataMeta:
        """Record the fetch, then delegate to the in-memory task store."""
        self.data_meta_calls.append(task_id)
        return super().get_task_data_meta(task_id)


class _ListCountingS3(FakeS3Client):
    """In-memory S3 that counts listings and records uploaded keys.

    ``build_server_file_mapping`` hands its listing to ``S3Uploader`` as
    ``existing_keys`` precisely so the bucket is listed once per upload;
    without a counter, dropping that argument is invisible.
    """

    def __init__(self, objects: dict[str, bytes] | None = None) -> None:
        """Seed the store and start with empty call logs."""
        super().__init__(objects)
        self.list_calls = 0
        self.uploaded_keys: list[str] = []

    def list_objects_v2(self, **kwargs: str) -> dict[str, Any]:
        """Count the listing, then delegate."""
        self.list_calls += 1
        return super().list_objects_v2(**kwargs)

    def upload_file(self, filename: str, bucket: str, key: str) -> None:
        """Record the key and store the file, rejecting a non-file path.

        Being handed something that is not a local file is a caller bug,
        not a transient fault.  Letting it surface as the ``OSError`` that
        ``Path.read_bytes`` would raise sends ``s3_retry`` into its
        backoff loop, which stalls the run instead of failing it.
        """
        if not Path(filename).is_file():
            msg = f"S3Uploader was handed a non-file path: {filename!r}"
            raise RuntimeError(msg)
        self.uploaded_keys.append(key)
        super().upload_file(filename, bucket, key)


def make_client(
    *,
    labels: list[str] | None = None,
    cloud_storage: CloudStorageInfo | None = None,
) -> CvatClient:
    """Build a CvatClient over a project-scoped fake with no tasks yet."""
    fixtures = LoadedFixtures(
        project=ProjectInfo(id=PROJECT_ID, name=PROJECT_NAME),
        tasks=[],
        labels=[
            LabelInfo(id=index + 1, name=name)
            for index, name in enumerate(labels if labels is not None else [LABEL])
        ],
        task_data={},
    )
    api = _ProjectScopedFake(fixtures, cloud_storage=cloud_storage)
    return client_with_api(api)


def make_s3(monkeypatch: pytest.MonkeyPatch, s3: _ListCountingS3) -> None:
    """Route every ``make_s3_client`` call in the uploader at *s3*."""
    monkeypatch.setattr("cveta2.image_uploader.make_s3_client", lambda _url=None: s3)


def make_local_images(tmp_path: Path, names: list[str]) -> Path:
    """Create placeholder files for *names* and return their directory."""
    image_dir = tmp_path / "images"
    image_dir.mkdir(exist_ok=True)
    for name in names:
        (image_dir / name).write_bytes(b"x")
    return image_dir


def annotation_row(name: str, **overrides: object) -> dict[str, object]:
    """One bbox row with the columns the upload chain actually reads."""
    row: dict[str, object] = {
        "image_name": name,
        "instance_label": LABEL,
        "bbox_x_tl": 1.0,
        "bbox_y_tl": 2.0,
        "bbox_x_br": 3.0,
        "bbox_y_br": 4.0,
    }
    row.update(overrides)
    return row


def make_request(
    *,
    image_names: list[str],
    deleted_names: list[str] | None = None,
    rows: list[dict[str, object]] | None = None,
    search_dirs: list[Path] | None = None,
    task_name: str = "upload-1",
    **option_overrides: object,
) -> UploadRequest:
    """Assemble an :class:`UploadRequest` from plain names and rows."""
    frame_rows = rows if rows is not None else [annotation_row(n) for n in image_names]
    plan = UploadPlan(
        annotations=pd.DataFrame(frame_rows),
        image_names=image_names,
        deleted_names=deleted_names if deleted_names is not None else [],
    )
    return UploadRequest(
        project_id=PROJECT_ID,
        project_name=PROJECT_NAME,
        task_name=task_name,
        plan=plan,
        options=UploadOptions(
            search_dirs=search_dirs if search_dirs is not None else [],
            **option_overrides,  # type: ignore[arg-type]
        ),
    )


# ---------------------------------------------------------------------------
# _stage_images
# ---------------------------------------------------------------------------


class TestStageImages:
    """The S3 half of the pipeline, run against a real in-memory bucket."""

    def test_reuses_existing_server_file_and_uploads_only_the_new_image(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capture_logs: list[str],
    ) -> None:
        """Pin every argument ``_stage_images`` forwards to the S3 helpers.

        The previous ``_stage_images`` test stubbed ``resolve_images`` and
        ``build_server_file_mapping`` out, so nothing distinguished a call
        that passed ``cs_info`` / ``found_images`` /
        ``name_to_server_file`` from one that passed ``None`` or dropped
        the argument.  Running the real helpers over a seeded bucket makes
        each of those visible: ``a.jpg`` keeps the month folder it already
        occupies on S3 and is *not* re-uploaded, ``b.jpg`` is assigned the
        current month and uploaded, and ``c.jpg`` is only reported missing.
        A single ``list_objects_v2`` call is the contract behind passing
        ``existing_keys`` down to the uploader.
        """
        s3 = _ListCountingS3({f"{BUCKET}/{SEEDED_KEY}": b"seeded"})
        make_s3(monkeypatch, s3)
        image_dir = make_local_images(tmp_path, ["a.jpg", "b.jpg"])
        cs_info = make_cs_info(bucket=BUCKET, prefix=PREFIX)
        client = make_client(cloud_storage=cs_info)
        request = make_request(
            image_names=["a.jpg", "b.jpg", "c.jpg"],
            search_dirs=[image_dir],
        )

        staged = _stage_images(client, request)

        assert staged.cs_info == cs_info
        assert staged.task_image_names == [
            SEEDED_KEY,
            current_month_key("b.jpg"),
            current_month_key("c.jpg"),
        ]
        assert staged.annotations["s3_image_path"].tolist() == staged.task_image_names
        image_paths = staged.annotations["image_path"]
        assert image_paths.tolist()[:2] == [
            str((image_dir / "a.jpg").resolve()),
            str((image_dir / "b.jpg").resolve()),
        ]
        assert pd.isna(image_paths.iloc[2])
        assert s3.uploaded_keys == [current_month_key("b.jpg")]
        assert s3.list_calls == 1
        assert any("c.jpg" in message for message in capture_logs)

    def test_missing_cloud_storage_names_the_project(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The cloud-storage error must carry the project it failed for.

        ``Cveta2Error(None)`` raised on this path was indistinguishable
        from the real message because nothing asserted the text.
        """
        make_s3(monkeypatch, _ListCountingS3())
        client = make_client(cloud_storage=None)
        request = make_request(
            image_names=["a.jpg"],
            search_dirs=[make_local_images(tmp_path, ["a.jpg"])],
        )

        with pytest.raises(Cveta2Error, match=PROJECT_NAME):
            _stage_images(client, request)

    def test_unknown_label_error_names_the_project(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``validate_labels`` must receive the request's project name.

        Passing ``project_name=None`` only ever surfaces inside
        :class:`LabelsMismatchError`, so the raise itself is not enough.
        """
        make_s3(monkeypatch, _ListCountingS3())
        client = make_client(labels=["person"], cloud_storage=make_cs_info())
        request = make_request(image_names=["a.jpg"])

        with pytest.raises(LabelsMismatchError) as exc_info:
            _stage_images(client, request)

        assert PROJECT_NAME in str(exc_info.value)


# ---------------------------------------------------------------------------
# _push_to_cvat / upload_dataset
# ---------------------------------------------------------------------------


class TestUploadDataset:
    """The full chain: S3 → task → annotations → issues → deleted → complete."""

    def test_pushes_every_step_with_one_metadata_fetch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Cover the whole write chain and pin what each step is handed.

        Nothing executed ``_push_to_cvat`` before, so all of its mutants
        were reported as uncovered.  The task spec fields, the recorded
        shapes/issues/deleted frames and the returned outcome pin the
        arguments; ``data_meta_calls`` pins the shared session — every
        write that opens its own session instead adds a fetch.
        """
        s3 = _ListCountingS3()
        make_s3(monkeypatch, s3)
        image_dir = make_local_images(tmp_path, ["a.jpg", "b.jpg", "d.jpg"])
        client = make_client(cloud_storage=make_cs_info(bucket=BUCKET, prefix=PREFIX))
        request = make_request(
            image_names=["a.jpg", "b.jpg"],
            deleted_names=["d.jpg"],
            rows=[
                annotation_row("a.jpg", issue_state="new", issue_text="look here"),
                annotation_row("b.jpg", issue_state="", issue_text=""),
            ],
            search_dirs=[image_dir],
            task_name="upload-42",
            segment_size=2,
            image_quality=70,
            complete=True,
        )

        outcome = upload_dataset(client, request)

        api = client.api
        assert isinstance(api, _ProjectScopedFake)
        spec = api.writes.created_tasks[0]
        assert spec.project_id == PROJECT_ID
        assert spec.name == "upload-42"
        assert spec.cloud_storage_id == make_cs_info().id
        assert spec.segment_size == 2
        assert spec.image_quality == 70
        assert spec.server_files == [
            current_month_key(name) for name in ("a.jpg", "b.jpg", "d.jpg")
        ]
        assert [shape.frame for shape in api.writes.shapes[NEW_TASK_ID]] == [0, 1]
        assert [issue.message for issue in api.writes.issues] == ["look here"]
        assert api.writes.deleted_frames[NEW_TASK_ID] == [2]
        assert api.writes.job_updates == [(NEW_TASK_ID, "acceptance", "completed")]
        assert api.data_meta_calls == [NEW_TASK_ID]

        assert outcome.task_id == NEW_TASK_ID
        assert outcome.task_name == "upload-42"
        assert outcome.images == 3
        assert outcome.deleted == 1
        assert outcome.annotations == 2
        assert outcome.issues == 1
        assert outcome.jobs == 2

    def test_without_issue_columns_no_issues_are_opened(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A dataset without ``issue_state`` must report zero issues.

        Together with the previous test this pins both directions of the
        ``"issue_state" in columns`` guard and the ``num_issues = 0``
        seed, which an inverted guard or a non-zero seed would change.
        """
        make_s3(monkeypatch, _ListCountingS3())
        image_dir = make_local_images(tmp_path, ["a.jpg"])
        client = make_client(cloud_storage=make_cs_info(bucket=BUCKET, prefix=PREFIX))
        request = make_request(image_names=["a.jpg"], search_dirs=[image_dir])

        outcome = upload_dataset(client, request)

        api = client.api
        assert isinstance(api, _ProjectScopedFake)
        assert api.writes.issues == []
        assert outcome.issues == 0
        assert api.writes.job_updates == []

    @pytest.mark.parametrize(
        ("mark_all_deleted", "deleted_names", "expected_frames"),
        [
            pytest.param(True, [], [0, 1], id="mark-all"),
            pytest.param(False, ["d.jpg"], [2], id="deleted-only"),
            pytest.param(False, [], None, id="nothing-deleted"),
        ],
    )
    def test_deleted_frame_matrix(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        *,
        mark_all_deleted: bool,
        deleted_names: list[str],
        expected_frames: list[int] | None,
    ) -> None:
        """Each arm of the deleted-frames branch marks a different frame set.

        ``mark_all_deleted`` covers plan images *and* deleted names, the
        ``elif`` covers only the deleted names, and with neither the task
        must be left untouched — a single-case test could not tell the
        three apart.
        """
        make_s3(monkeypatch, _ListCountingS3())
        image_dir = make_local_images(tmp_path, ["a.jpg", "b.jpg", "d.jpg"])
        client = make_client(cloud_storage=make_cs_info(bucket=BUCKET, prefix=PREFIX))
        request = make_request(
            image_names=["a.jpg", "b.jpg"],
            deleted_names=deleted_names,
            search_dirs=[image_dir],
            mark_all_deleted=mark_all_deleted,
        )

        upload_dataset(client, request)

        api = client.api
        assert isinstance(api, _ProjectScopedFake)
        assert api.writes.deleted_frames.get(NEW_TASK_ID) == expected_frames
        assert api.data_meta_calls == [NEW_TASK_ID]

    @pytest.mark.parametrize(
        ("segment_size", "expected_jobs"),
        [
            # 5 images over segments of 2 need a third, partly filled job:
            # this pins the +segment_size-1 ceiling term.
            pytest.param(2, 3, id="ceil-rounds-up"),
            # 7 // 3 == 2 but 7 / 3 == 2.33, which is what separates the
            # floor division from a plain divide.
            pytest.param(3, 2, id="floor-division"),
        ],
    )
    def test_job_count_is_a_ceiling_division(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        *,
        segment_size: int,
        expected_jobs: int,
    ) -> None:
        """``UploadOutcome.jobs`` was never asserted by any test."""
        make_s3(monkeypatch, _ListCountingS3())
        names = [f"img{index}.jpg" for index in range(5)]
        image_dir = make_local_images(tmp_path, names)
        client = make_client(cloud_storage=make_cs_info(bucket=BUCKET, prefix=PREFIX))
        request = make_request(
            image_names=names,
            search_dirs=[image_dir],
            segment_size=segment_size,
        )

        outcome = upload_dataset(client, request)

        assert outcome.jobs == expected_jobs

    def test_invalidates_the_cache_entry_of_the_created_task(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        isolated_config_path: Path,
    ) -> None:
        """The upload must drop the cache entry for *this* project and task.

        A per-project ``tasks_root`` makes all three arguments matter: the
        project id names the directory, the task id names the file, and
        the project name selects the root.  Without it the call resolved
        to the same path however it was spelled.
        """
        make_s3(monkeypatch, _ListCountingS3())
        tasks_root = tmp_path / "per-project"
        isolated_config_path.write_text(
            "cache:\n"
            f"  tasks_root: {tmp_path / 'global'}\n"
            "  projects:\n"
            f"    {PROJECT_NAME}:\n"
            f"      tasks_root: {tasks_root}\n",
            encoding="utf-8",
        )
        cache_dir = get_task_cache_dir(PROJECT_ID, root=tasks_root)
        cache_dir.mkdir(parents=True)
        entry = cache_dir / f"task_{NEW_TASK_ID}.json"
        entry.write_text("{}", encoding="utf-8")
        image_dir = make_local_images(tmp_path, ["a.jpg"])
        client = make_client(cloud_storage=make_cs_info(bucket=BUCKET, prefix=PREFIX))
        request = make_request(image_names=["a.jpg"], search_dirs=[image_dir])

        upload_dataset(client, request)

        assert not entry.exists()
