"""End-to-end tests for the upload service against the recording fakes.

``_stage_images``, ``_push_to_cvat`` and ``upload_dataset`` used to appear
in the suite only as patch targets, so no assertion covered the chain they
drive.  These tests run the real pipeline over :class:`FakeCvatApi` and an
in-memory S3, which is what makes the argument-level behaviour of each step
observable.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pandas as pd
import pytest
from botocore.exceptions import ClientError

from cveta2.exceptions import CvatApiError, Cveta2Error, LabelsMismatchError
from cveta2.models import CSV_COLUMNS, LabelInfo, ProjectInfo
from cveta2.s3_utils import build_s3_key
from cveta2.services.upload import (
    UploadOptions,
    UploadPlan,
    UploadRequest,
    _stage_images,
    upload_dataset,
)
from cveta2.task_cache import get_task_cache_dir
from cveta2.upload_manifest import (
    compute_fingerprint,
    list_manifests,
    new_manifest,
    save_manifest,
)
from tests.fixtures.fake_cvat_api import FakeCvatApi, RecordedWrites
from tests.fixtures.fake_cvat_project import LoadedFixtures
from tests.fixtures.fake_s3 import FakeS3Client
from tests.helpers import client_with_api, make_cs_info

if TYPE_CHECKING:
    from collections.abc import Iterator

    from cveta2._client.dtos import NewIssue, RawDataMeta
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


def seeded_bucket(names: list[str]) -> _ListCountingS3:
    """Build a bucket already holding *names* at the prefix root, no month folder.

    That is the layout an earlier upload leaves behind, and the one
    :func:`_seed_manifest_for` assumes when it maps every name to itself.
    Staging refuses an image that is neither local nor on S3, so a test
    that hands the service no ``search_dirs`` seeds its images here.
    """
    return _ListCountingS3(
        {f"{BUCKET}/{build_s3_key(PREFIX, name)}": b"seeded" for name in names}
    )


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


def make_request(  # noqa: PLR0913
    *,
    image_names: list[str],
    deleted_names: list[str] | None = None,
    rows: list[dict[str, object]] | None = None,
    search_dirs: list[Path] | None = None,
    task_name: str = "upload-1",
    resume: bool = False,
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
        dataset_path="dataset.csv",
        labels=("car",),
        resume=resume,
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
        each of those visible: ``a.jpg`` is absent locally but keeps the
        month folder it already occupies on S3 — reported missing, *not*
        re-uploaded and not refused — while ``b.jpg`` is assigned the
        current month and uploaded.  A single ``list_objects_v2`` call is
        the contract behind passing ``existing_keys`` down to the uploader.
        """
        s3 = _ListCountingS3({f"{BUCKET}/{SEEDED_KEY}": b"seeded"})
        make_s3(monkeypatch, s3)
        image_dir = make_local_images(tmp_path, ["b.jpg"])
        cs_info = make_cs_info(bucket=BUCKET, prefix=PREFIX)
        client = make_client(cloud_storage=cs_info)
        request = make_request(
            image_names=["a.jpg", "b.jpg"],
            search_dirs=[image_dir],
        )

        staged = _stage_images(client, request)

        assert staged.cs_info == cs_info
        assert staged.task_image_names == [SEEDED_KEY, current_month_key("b.jpg")]
        assert staged.annotations["s3_image_path"].tolist() == staged.task_image_names
        image_paths = staged.annotations["image_path"]
        assert pd.isna(image_paths.iloc[0])
        assert image_paths.iloc[1] == str((image_dir / "b.jpg").resolve())
        assert s3.uploaded_keys == [current_month_key("b.jpg")]
        assert s3.list_calls == 1
        assert any("a.jpg" in message for message in capture_logs)

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

    def test_a_dataset_of_only_deleted_rows_still_creates_the_task(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``deleted.csv`` on its own is a valid upload.

        The annotation frame is empty but keeps every ``CSV_COLUMNS``
        column, exactly as :func:`read_dataset_csv` yields it, so the whole
        write chain — shapes, issues, deleted frames — has to survive
        having nothing to annotate.
        """
        make_s3(monkeypatch, _ListCountingS3())
        image_dir = make_local_images(tmp_path, ["d.jpg"])
        client = make_client(cloud_storage=make_cs_info(bucket=BUCKET, prefix=PREFIX))
        request = UploadRequest(
            project_id=PROJECT_ID,
            project_name=PROJECT_NAME,
            task_name="deleted-only",
            plan=UploadPlan(
                annotations=pd.DataFrame(columns=list(CSV_COLUMNS)),
                image_names=[],
                deleted_names=["d.jpg"],
            ),
            options=UploadOptions(search_dirs=[image_dir]),
        )

        outcome = upload_dataset(client, request)

        api = client.api
        assert isinstance(api, _ProjectScopedFake)
        assert api.writes.created_tasks[0].server_files == [current_month_key("d.jpg")]
        assert api.writes.shapes.get(NEW_TASK_ID) is None
        assert api.writes.deleted_frames[NEW_TASK_ID] == [0]
        assert outcome.images == 1
        assert outcome.deleted == 1
        assert outcome.annotations == 0
        assert outcome.issues == 0

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


# ---------------------------------------------------------------------------
# upload --resume
# ---------------------------------------------------------------------------


class _InterruptedRunError(RuntimeError):
    """Stands in for the process dying between task creation and the rest."""


def _writes_of(client: CvatClient) -> RecordedWrites:
    """Return the recording fake behind *client*, typed for assertions.

    ``client.api`` is declared as the port, which carries no ``writes``.
    """
    return cast("FakeCvatApi", client.api).writes


@contextmanager
def _dies_attaching_frames(client: CvatClient) -> Iterator[None]:
    """Let the task be created, then fail where a real run would be killed.

    Restores the port method by hand rather than through ``monkeypatch``:
    undoing that would also undo the fixture pointing XDG_CACHE_HOME at
    tmp_path, and the resumed half of the test would look for its manifest
    in the developer's real cache.
    """
    original = client.api.attach_task_data

    def die(_task_id: int, _spec: object) -> None:
        raise _InterruptedRunError

    client.api.attach_task_data = die  # type: ignore[assignment]
    try:
        yield
    finally:
        client.api.attach_task_data = original  # type: ignore[method-assign]


def _seed_manifest_for(
    client: CvatClient, request: UploadRequest, task_id: int
) -> None:
    """Recreate the manifest a finished upload deleted, pointing at *task_id*.

    Standing in for a run that got as far as the annotations and then died
    before it could clean up.
    """
    cs_info = client.detect_project_cloud_storage(PROJECT_ID)
    assert cs_info is not None
    names = [*request.plan.image_names, *request.plan.deleted_names]
    mapping = {name: name for name in names}
    manifest = new_manifest(
        dataset_path=request.dataset_path,
        fingerprint=compute_fingerprint(
            request.plan.image_names, request.plan.deleted_names, request.labels
        ),
        project_id=PROJECT_ID,
        task_name=request.task_name,
        cs_info=cs_info,
        name_to_server_file=mapping,
        task_image_names=[build_s3_key(cs_info.prefix, mapping[n]) for n in names],
        host=client.host,
    )
    manifest.task_id = task_id
    save_manifest(manifest)


@contextmanager
def _dies_uploading_annotations(client: CvatClient) -> Iterator[None]:
    """Die after the frames are attached but before the shapes go up."""
    original = client.api.put_task_shapes

    def die(_task_id: int, _shapes: object) -> None:
        raise _InterruptedRunError

    client.api.put_task_shapes = die  # type: ignore[assignment]
    try:
        yield
    finally:
        client.api.put_task_shapes = original  # type: ignore[method-assign]


def _resume_request(image_names: list[str]) -> UploadRequest:
    """Build the same request the interrupted run used, with --resume set."""
    return make_request(image_names=image_names, resume=True)


class TestResume:
    """Recovery is driven by reading CVAT back, not by trusting the manifest.

    The manifest exists to know *which* task to look at; what that task
    already holds is a question only the server can answer, because losing
    track of it is the failure being recovered from.
    """

    def test_a_manifest_from_another_host_cannot_delete_a_task(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        first = make_client(cloud_storage=make_cs_info(bucket=BUCKET, prefix=PREFIX))
        second = make_client(cloud_storage=make_cs_info(bucket=BUCKET, prefix=PREFIX))
        second._cfg = second._cfg.model_copy(update={"host": "http://other-cvat"})
        make_s3(monkeypatch, seeded_bucket(["a.jpg"]))
        with _dies_attaching_frames(first), pytest.raises(_InterruptedRunError):
            upload_dataset(first, make_request(image_names=["a.jpg"]))
        unrelated_id = second.create_upload_task(PROJECT_ID, "unrelated", [], 1)

        with pytest.raises(Cveta2Error):
            upload_dataset(second, _resume_request(["a.jpg"]))

        assert second.get_task(unrelated_id).name == "unrelated"
        assert _writes_of(second).deleted_tasks == []
        assert _writes_of(second).shapes == {}
        assert len(_writes_of(second).created_tasks) == 1
        assert len(list_manifests(PROJECT_ID, host=first.host)) == 1

    @pytest.mark.parametrize("frames", [[], ["a.jpg"]])
    def test_a_task_in_another_project_is_never_resumed_or_deleted(
        self, monkeypatch: pytest.MonkeyPatch, frames: list[str]
    ) -> None:
        client = make_client(cloud_storage=make_cs_info(bucket=BUCKET, prefix=PREFIX))
        make_s3(monkeypatch, seeded_bucket(["a.jpg"]))
        task_id = client.create_upload_task(999, "unrelated", frames, 1)
        _seed_manifest_for(client, make_request(image_names=["a.jpg"]), task_id)

        with pytest.raises(Cveta2Error) as caught:
            upload_dataset(client, _resume_request(["a.jpg"]))

        assert "999" in str(caught.value)
        assert str(PROJECT_ID) in str(caught.value)
        assert client.get_task(task_id).project_id == 999
        assert _writes_of(client).deleted_tasks == []
        assert _writes_of(client).shapes == {}
        assert len(_writes_of(client).created_tasks) == 1
        assert len(list_manifests(PROJECT_ID, host=client.host)) == 1

    def test_a_fresh_upload_leaves_no_manifest_behind(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A finished upload has nothing to resume; a stale file would mislead."""
        client = make_client(cloud_storage=make_cs_info(bucket=BUCKET, prefix=PREFIX))
        make_s3(monkeypatch, seeded_bucket(["a.jpg"]))

        upload_dataset(client, make_request(image_names=["a.jpg"]))

        assert list_manifests(PROJECT_ID, host=client.host) == []

    def test_the_task_id_is_recorded_before_the_frames_are_attached(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """That window is the whole reason the port call was split in two.

        A crash while CVAT processes the images leaves a task that only the
        manifest knows about; without this checkpoint it is orphaned.
        """
        client = make_client(cloud_storage=make_cs_info(bucket=BUCKET, prefix=PREFIX))
        make_s3(monkeypatch, seeded_bucket(["a.jpg"]))

        with _dies_attaching_frames(client), pytest.raises(_InterruptedRunError):
            upload_dataset(client, make_request(image_names=["a.jpg"]))

        pending = list_manifests(PROJECT_ID, host=client.host)
        assert len(pending) == 1
        assert pending[0].task_id is not None

    def test_resume_replaces_a_task_whose_frames_never_attached(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An empty task is useless and cannot be repaired in place.

        Re-running without --resume would leave it behind *and* create a
        second one; the frame count is what tells the two apart.
        """
        client = make_client(cloud_storage=make_cs_info(bucket=BUCKET, prefix=PREFIX))
        names = ["a.jpg", "b.jpg"]
        make_s3(monkeypatch, seeded_bucket(names))

        with _dies_attaching_frames(client), pytest.raises(_InterruptedRunError):
            upload_dataset(client, make_request(image_names=names))
        stranded = list_manifests(PROJECT_ID, host=client.host)[0].task_id

        outcome = upload_dataset(client, _resume_request(names))

        assert _writes_of(client).deleted_tasks == [stranded]
        assert len(_writes_of(client).created_tasks) == 2
        assert outcome.images == len(names)
        assert list_manifests(PROJECT_ID, host=client.host) == []

    def test_resume_keeps_a_task_whose_frames_did_attach(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The common recovery: the server finished, only the reply was lost.

        Recreating here would abandon a fully processed task and pay for
        the upload twice, which is exactly what --resume exists to avoid.
        """
        client = make_client(cloud_storage=make_cs_info(bucket=BUCKET, prefix=PREFIX))
        names = ["a.jpg", "b.jpg"]
        make_s3(monkeypatch, seeded_bucket(names))

        outcome = upload_dataset(client, make_request(image_names=names))
        _seed_manifest_for(client, make_request(image_names=names), outcome.task_id)

        resumed = upload_dataset(client, _resume_request(names))

        assert resumed.task_id == outcome.task_id
        assert _writes_of(client).deleted_tasks == []
        assert len(_writes_of(client).created_tasks) == 1

    def test_resume_refuses_a_task_built_from_different_frames(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Guessing which frames it holds would misplace every annotation."""
        client = make_client(cloud_storage=make_cs_info(bucket=BUCKET, prefix=PREFIX))
        make_s3(monkeypatch, seeded_bucket(["a.jpg", "b.jpg"]))

        outcome = upload_dataset(client, make_request(image_names=["a.jpg", "b.jpg"]))
        request = make_request(image_names=["a.jpg"])
        _seed_manifest_for(client, request, outcome.task_id)

        with pytest.raises(Cveta2Error, match=r"task delete"):
            upload_dataset(client, _resume_request(["a.jpg"]))

    def test_resume_uploads_annotations_the_first_run_never_reached(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The task is complete but empty: crashed between attach and shapes.

        Skipping here would leave a task of frames with no annotations at
        all, which looks finished and is not.
        """
        client = make_client(cloud_storage=make_cs_info(bucket=BUCKET, prefix=PREFIX))
        names = ["a.jpg", "b.jpg"]
        make_s3(monkeypatch, seeded_bucket(names))

        with _dies_uploading_annotations(client), pytest.raises(_InterruptedRunError):
            upload_dataset(client, make_request(image_names=names))
        stranded = list_manifests(PROJECT_ID, host=client.host)[0].task_id

        outcome = upload_dataset(client, _resume_request(names))

        assert outcome.task_id == stranded
        assert outcome.annotations == len(names)
        assert _writes_of(client).deleted_tasks == []

    def test_resume_does_not_duplicate_annotations(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """put_task_shapes appends, so a second pass would double every bbox.

        This is the corruption the 429-only write-retry policy and this
        readback both exist to prevent.
        """
        client = make_client(cloud_storage=make_cs_info(bucket=BUCKET, prefix=PREFIX))
        names = ["a.jpg", "b.jpg"]
        make_s3(monkeypatch, seeded_bucket(names))

        outcome = upload_dataset(client, make_request(image_names=names))
        before = len(_writes_of(client).shapes[outcome.task_id])
        _seed_manifest_for(client, make_request(image_names=names), outcome.task_id)

        resumed = upload_dataset(client, _resume_request(names))

        assert resumed.task_id == outcome.task_id
        assert len(_writes_of(client).shapes[outcome.task_id]) == before
        assert before > 0

    def test_resume_without_a_matching_manifest_reports_the_others(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The likely mistake is a different CSV, so name what *is* pending."""
        client = make_client(cloud_storage=make_cs_info(bucket=BUCKET, prefix=PREFIX))
        make_s3(monkeypatch, seeded_bucket(["a.jpg"]))

        with _dies_attaching_frames(client), pytest.raises(_InterruptedRunError):
            upload_dataset(client, make_request(image_names=["a.jpg"]))

        with pytest.raises(Cveta2Error, match=r"dataset\.csv") as caught:
            upload_dataset(client, _resume_request(["other.jpg"]))

        assert "--resume" in str(caught.value)

    def test_resume_with_nothing_pending_says_so(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = make_client(cloud_storage=make_cs_info(bucket=BUCKET, prefix=PREFIX))
        make_s3(monkeypatch, _ListCountingS3())

        with pytest.raises(Cveta2Error, match="нечего продолжать"):
            upload_dataset(client, _resume_request(["a.jpg"]))

    def test_resume_keeps_the_server_paths_the_first_run_chose(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """``_assign_month_folder`` reads the clock.

        A run resumed in a later month would otherwise place its remaining
        images in a different folder than the frame order already promised,
        and the task would bind keys that do not exist.
        """
        client = make_client(cloud_storage=make_cs_info(bucket=BUCKET, prefix=PREFIX))
        make_s3(monkeypatch, _ListCountingS3())
        names = ["a.jpg", "b.jpg"]
        image_dir = make_local_images(tmp_path, names)
        monkeypatch.setattr(
            "cveta2.image_uploader._assign_month_folder",
            lambda name: f"2026-01/{name}",
        )

        with _dies_attaching_frames(client), pytest.raises(_InterruptedRunError):
            upload_dataset(
                client, make_request(image_names=names, search_dirs=[image_dir])
            )
        pinned = list_manifests(PROJECT_ID, host=client.host)[0]

        # The clock has moved on, and the bucket lost what the first run put
        # there, so a recomputed mapping would send every image somewhere new.
        make_s3(monkeypatch, _ListCountingS3())
        monkeypatch.setattr(
            "cveta2.image_uploader._assign_month_folder",
            lambda name: f"9999-12/{name}",
        )
        upload_dataset(
            client,
            make_request(image_names=names, search_dirs=[image_dir], resume=True),
        )

        attached = _writes_of(client).created_tasks[-1].server_files
        assert attached == pinned.task_image_names
        assert all("2026-01" in key for key in attached)


class TestManifestLifecycle:
    def test_a_fresh_run_warns_before_forgetting_a_stranded_task(
        self, monkeypatch: pytest.MonkeyPatch, capture_logs: list[str]
    ) -> None:
        """Overwriting the manifest loses the only record of that task id.

        Without the warning the task stays in CVAT with nothing pointing at
        it, and `--resume` can no longer reach it.
        """
        client = make_client(cloud_storage=make_cs_info(bucket=BUCKET, prefix=PREFIX))
        names = ["a.jpg"]
        make_s3(monkeypatch, seeded_bucket(names))

        with _dies_attaching_frames(client), pytest.raises(_InterruptedRunError):
            upload_dataset(client, make_request(image_names=names))
        stranded = list_manifests(PROJECT_ID, host=client.host)[0].task_id

        upload_dataset(client, make_request(image_names=names))

        assert any(str(stranded) in message for message in capture_logs)
        assert any("--resume" in message for message in capture_logs)

    def test_a_first_run_warns_about_nothing(
        self, monkeypatch: pytest.MonkeyPatch, capture_logs: list[str]
    ) -> None:
        """The warning must key on a real stranded task, not on any manifest."""
        client = make_client(cloud_storage=make_cs_info(bucket=BUCKET, prefix=PREFIX))
        make_s3(monkeypatch, seeded_bucket(["a.jpg"]))

        upload_dataset(client, make_request(image_names=["a.jpg"]))

        assert not any("--resume" in message for message in capture_logs)

    def test_one_upload_fetches_the_frame_metadata_once(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Annotations, issues and deleted frames all need the frame map.

        Fetching it per step is what the shared write session exists to
        avoid, and on a task of tens of thousands of frames that reply is
        not small.
        """
        client = make_client(cloud_storage=make_cs_info(bucket=BUCKET, prefix=PREFIX))
        make_s3(monkeypatch, seeded_bucket(["a.jpg", "b.jpg", "c.jpg"]))

        upload_dataset(
            client,
            make_request(image_names=["a.jpg", "b.jpg"], deleted_names=["c.jpg"]),
        )

        api = cast("FakeCvatApi", client.api)
        assert api.call_counts["get_task_data_meta"] == 1


class TestS3FailureAbortsBeforeTaskCreation:
    def test_a_failed_transfer_stops_the_upload(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Every name enters ``server_files`` whether it uploaded or not.

        Continuing would bind a key that is not on S3, and the only signal
        would be CVAT failing to process the data — after the task exists
        and there is something to clean up.
        """

        class _FailingS3(_ListCountingS3):
            def upload_file(self, filename: str, _bucket: str, _key: str) -> None:
                # AccessDenied rather than a transport error: the retry
                # policy correctly backs off on the latter, and this test is
                # about what happens once the transfer has finally failed.
                raise ClientError(
                    {"Error": {"Code": "AccessDenied", "Message": filename}},
                    "PutObject",
                )

        client = make_client(cloud_storage=make_cs_info(bucket=BUCKET, prefix=PREFIX))
        make_s3(monkeypatch, _FailingS3())
        image_dir = make_local_images(tmp_path, ["a.jpg"])

        with pytest.raises(Cveta2Error, match="S3"):
            upload_dataset(
                client,
                make_request(image_names=["a.jpg"], search_dirs=[image_dir]),
            )

        assert _writes_of(client).created_tasks == []

    def test_an_image_found_nowhere_stops_the_upload(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A name that is neither local nor on S3 reaches the same dead end.

        Bound into the task anyway, CVAT would reject the data after the
        task and its manifest exist, and every ``--resume`` would recreate
        the empty task and fail again without ever naming the image.
        """
        s3 = _ListCountingS3()
        make_s3(monkeypatch, s3)
        client = make_client(cloud_storage=make_cs_info(bucket=BUCKET, prefix=PREFIX))
        image_dir = make_local_images(tmp_path, ["a.jpg"])

        with pytest.raises(Cveta2Error, match=r"c\.jpg") as caught:
            upload_dataset(
                client,
                make_request(image_names=["a.jpg", "c.jpg"], search_dirs=[image_dir]),
            )

        assert "a.jpg" not in str(caught.value)
        assert s3.uploaded_keys == [current_month_key("a.jpg")]
        assert _writes_of(client).created_tasks == []
        assert list_manifests(PROJECT_ID, host=client.host) == []


class TestResumeWithIssues:
    def test_partial_same_text_issues_resume_each_bbox(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = make_client(cloud_storage=make_cs_info(bucket=BUCKET, prefix=PREFIX))
        make_s3(monkeypatch, seeded_bucket(["a.jpg"]))
        rows = [
            annotation_row(
                "a.jpg", issue_state="new", issue_text="проверь", bbox_x_tl=x
            )
            for x in (1.0, 2.0)
        ]
        original = client.api.create_issue
        calls = 0

        def interrupt_second(issue: NewIssue) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise CvatApiError("interrupted")
            original(issue)

        with monkeypatch.context() as interrupted:
            interrupted.setattr(client.api, "create_issue", interrupt_second)
            with pytest.raises(CvatApiError):
                upload_dataset(client, make_request(image_names=["a.jpg"], rows=rows))

        assert len(_writes_of(client).issues) == 1
        outcome = upload_dataset(
            client, make_request(image_names=["a.jpg"], rows=rows, resume=True)
        )
        assert outcome.issues == 1
        assert [issue.position for issue in _writes_of(client).issues] == [
            [1.0, 2.0, 3.0, 4.0],
            [2.0, 2.0, 3.0, 4.0],
        ]
        assert list_manifests(PROJECT_ID, host=client.host) == []

    def test_resuming_does_not_reopen_the_issues_already_created(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Issues are one request each, so a half-applied set is real.

        Re-creating them would leave every annotator comment duplicated on
        the frame, which no read-back can undo.
        """
        client = make_client(cloud_storage=make_cs_info(bucket=BUCKET, prefix=PREFIX))
        make_s3(monkeypatch, seeded_bucket(["a.jpg"]))
        rows = [
            annotation_row("a.jpg", issue_state="new", issue_text="смотри"),
        ]
        request = make_request(image_names=["a.jpg"], rows=rows)

        outcome = upload_dataset(client, request)
        created = len(_writes_of(client).issues)
        _seed_manifest_for(client, request, outcome.task_id)

        upload_dataset(
            client, make_request(image_names=["a.jpg"], rows=rows, resume=True)
        )

        assert created == 1
        assert len(_writes_of(client).issues) == created


class TestResumeAfterManualDeletion:
    def test_a_task_deleted_in_the_ui_is_recreated(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Deleting the stranded task by hand is the likeliest intervention.

        Without this the read-back raises a bare 404 — correctly not
        retried, and unhelpful: the run has everything it needs to start
        over.
        """
        client = make_client(cloud_storage=make_cs_info(bucket=BUCKET, prefix=PREFIX))
        names = ["a.jpg"]
        make_s3(monkeypatch, seeded_bucket(names))

        with _dies_attaching_frames(client), pytest.raises(_InterruptedRunError):
            upload_dataset(client, make_request(image_names=names))
        stranded = list_manifests(PROJECT_ID, host=client.host)[0].task_id
        assert stranded is not None
        client.delete_task(stranded)

        outcome = upload_dataset(client, _resume_request(names))

        assert outcome.images == len(names)
        assert list_manifests(PROJECT_ID, host=client.host) == []

    def test_another_error_reading_the_task_still_surfaces(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Only 404 means "gone"; a 500 must not be read as one."""
        client = make_client(cloud_storage=make_cs_info(bucket=BUCKET, prefix=PREFIX))
        names = ["a.jpg"]
        make_s3(monkeypatch, seeded_bucket(names))

        with _dies_attaching_frames(client), pytest.raises(_InterruptedRunError):
            upload_dataset(client, make_request(image_names=names))

        def boom(_task_id: int) -> int:
            raise CvatApiError("server error", status_code=500)

        monkeypatch.setattr(client.api, "get_task_size", boom)

        with pytest.raises(CvatApiError):
            upload_dataset(client, _resume_request(names))
