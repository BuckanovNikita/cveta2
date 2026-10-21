"""CVAT SDK adapter implementing ``CvatApiPort``.

SDK interaction stays within the CVAT adapter package. This boundary
converts opaque SDK objects into application-owned typed DTOs.
"""

import json
from typing import TYPE_CHECKING

from loguru import logger

from cveta2.adapters.cvat.sdk_convert import (
    convert_annotations,
    convert_data_meta,
    convert_label,
    convert_task,
    data_meta_from_dict,
)
from cveta2.adapters.cvat.sdk_requests import (
    build_data_request,
    build_delete_shapes_payload,
    build_deleted_frames_request,
    build_issue_request,
    build_job_patch_request,
    build_labels_patch_request,
    build_new_shapes_payload,
    build_task_write_request,
)
from cveta2.adapters.cvat.storage import parse_cloud_storage
from cveta2.adapters.cvat.transport import (
    cvat_idempotent_write,
    cvat_non_idempotent_write,
    cvat_read,
)
from cveta2.application.ports.dtos import (
    RawIssue,
    RawJob,
)
from cveta2.domain.errors import CvatApiError
from cveta2.domain.models import OrganizationInfo, ProjectInfo

if TYPE_CHECKING:
    from cvat_sdk import Client as CvatSdkClient

    from cveta2.application.ports.dtos import (
        LabelPatch,
        NewIssue,
        NewShape,
        RawAnnotations,
        RawDataMeta,
        RawShape,
        UploadTaskSpec,
    )
    from cveta2.domain.models import LabelInfo, TaskInfo
    from cveta2.domain.storage import CloudStorageInfo

from cvat_sdk.api_client.exceptions import (
    ApiAttributeError,
    ApiTypeError,
)
from cvat_sdk.core.exceptions import BackgroundRequestException
from cvat_sdk.core.helpers import get_paginated_collection
from cvat_sdk.core.proxies.annotations import AnnotationUpdateAction

_DATA_CHECK_PERIOD = 5
"""Seconds between status checks during data processing."""


class SdkCvatApiAdapter:
    """``CvatApiPort`` implementation backed by an open CVAT SDK client.

    The caller is responsible for opening and closing the SDK client.
    This adapter is a thin stateless converter: SDK objects in, DTOs out.
    Network calls use explicit retry policies for reads and each kind of write.
    """

    def __init__(self, client: "CvatSdkClient") -> None:
        """Wrap an already-opened ``cvat_sdk`` client."""
        self.client = client

    @cvat_read
    def list_organizations(self) -> list[OrganizationInfo]:
        """Return all organizations the user is a member of."""
        raw = get_paginated_collection(
            self.client.api_client.organizations_api.list_endpoint
        )
        return [
            OrganizationInfo(slug=str(o.slug), name=str(o.name or o.slug)) for o in raw
        ]

    def set_organization(self, org: str | None) -> None:
        """Scope subsequent requests to *org* (``None`` = personal workspace)."""
        self.client.organization_slug = "" if org is None else org
        logger.trace(f"Switched organization to: {org!r}")

    @cvat_read
    def list_projects(self) -> list[ProjectInfo]:
        """Return all accessible projects."""
        raw = self.client.projects.list()
        return [ProjectInfo(id=p.id, name=p.name or "") for p in raw]

    @cvat_read
    def get_project(self, project_id: int) -> ProjectInfo:
        """Return one project by id."""
        project = self.client.projects.retrieve(project_id)
        return ProjectInfo(id=project.id, name=project.name or "")

    @cvat_read
    def get_project_tasks(self, project_id: int) -> "list[TaskInfo]":
        """Return tasks belonging to a project."""
        project = self.client.projects.retrieve(project_id)
        tasks = project.get_tasks()
        return [convert_task(t) for t in tasks]

    @cvat_read
    def get_project_labels(self, project_id: int) -> "list[LabelInfo]":
        """Return label definitions for a project."""
        project = self.client.projects.retrieve(project_id)
        labels = project.get_labels()
        return [convert_label(lbl) for lbl in labels]

    @cvat_read
    def get_task_data_meta(self, task_id: int) -> "RawDataMeta":
        """Return frame metadata and deleted frame IDs for a task."""
        tasks_api = self.client.api_client.tasks_api
        try:
            data_meta, _ = tasks_api.retrieve_data_meta(task_id)
            return convert_data_meta(data_meta)
        except ApiTypeError as e:
            if "chunks_updated_date" not in str(e):
                raise
            # CVAT SDK ≤2.7 expects `chunks_updated_date` to be a datetime,
            # but CVAT server can return null for it, causing ApiTypeError
            # during deserialization.  Work around by re-fetching the raw JSON
            # and building RawDataMeta manually (skipping SDK parsing).
            _, response = tasks_api.retrieve_data_meta(task_id, _parse_response=False)
            body = (
                response.read()
                if hasattr(response, "read")
                else getattr(response, "data", b"")
            )
            data = json.loads(body.decode("utf-8"))
            return data_meta_from_dict(data)

    @cvat_read
    def get_task_annotations(self, task_id: int) -> "RawAnnotations":
        """Return shapes for a task."""
        tasks_api = self.client.api_client.tasks_api
        labeled_data, _ = tasks_api.retrieve_annotations(task_id)
        tracks = labeled_data.tracks or []
        if tracks:
            logger.warning(
                f"Задача {task_id}: проигнорировано треков CVAT: {len(tracks)}; "
                f"поддерживаются только отдельные rectangle и polygon shapes"
            )
        return convert_annotations(labeled_data)

    @cvat_read
    def get_task_issues(self, task_id: int) -> list[RawIssue]:
        """Return review issues for a task, each with its comment texts."""
        api_client = self.client.api_client
        issues = get_paginated_collection(
            api_client.issues_api.list_endpoint,
            task_id=task_id,
        )
        result: list[RawIssue] = []
        for issue in issues:
            comments = get_paginated_collection(
                api_client.comments_api.list_endpoint,
                issue_id=int(issue.id),
            )
            result.append(
                RawIssue(
                    id=int(issue.id),
                    frame=int(issue.frame),
                    resolved=bool(issue.resolved),
                    comments=[str(c.message or "") for c in comments],
                    position=[float(coordinate) for coordinate in issue.position],
                ),
            )
        return result

    @cvat_read
    def get_project_cloud_storage(self, project_id: int) -> "CloudStorageInfo | None":
        """Return the project's source cloud storage, or None.

        Uses ``getattr`` because ``source_storage`` may be an SDK object,
        a dict, or absent depending on the CVAT/SDK version.  This is an
        intentional exception to the project style rule "avoid getattr"
        (see CLAUDE.md).
        """
        project = self.client.projects.retrieve(project_id)
        source_storage = getattr(project, "source_storage", None)
        if source_storage is None:
            return None
        if isinstance(source_storage, dict):
            cs_id: int | None = source_storage.get("cloud_storage_id")
        else:
            cs_id = getattr(source_storage, "cloud_storage_id", None)
        if cs_id is None:
            return None
        cs_raw, _ = self.client.api_client.cloudstorages_api.retrieve(cs_id)
        return parse_cloud_storage(cs_raw)

    @cvat_read
    def get_task(self, task_id: int) -> "TaskInfo":
        """Return one task by id (with its ``project_id``)."""
        return convert_task(self.client.tasks.retrieve(task_id))

    @cvat_read
    def get_task_labels(self, task_id: int) -> "list[LabelInfo]":
        """Return label definitions available in a task."""
        task_obj = self.client.tasks.retrieve(task_id)
        return [convert_label(lbl) for lbl in task_obj.get_labels()]

    @cvat_read
    def get_task_jobs(self, task_id: int) -> list[RawJob]:
        """Return jobs (with frame ranges) of a task."""
        jobs = get_paginated_collection(
            self.client.api_client.jobs_api.list_endpoint,
            task_id=task_id,
        )
        return [
            RawJob(
                id=int(job.id),
                start_frame=int(job.start_frame),
                stop_frame=int(job.stop_frame),
                stage=str(job.stage or ""),
                state=str(job.state or ""),
                type=str(job.type or "annotation"),
            )
            for job in jobs
        ]

    @cvat_read
    def get_task_size(self, task_id: int) -> int:
        """Return the number of frames in a task.

        A task whose data was never attached carries no ``size`` field at
        all, and the SDK raises on the missing attribute rather than
        reporting zero.  That state is not exceptional here — it is exactly
        what ``upload --resume`` looks for to tell a task worth continuing
        from one worth replacing.
        """
        task_obj = self.client.tasks.retrieve(task_id)
        try:
            return int(task_obj.size or 0)
        except ApiAttributeError:
            return 0

    @cvat_non_idempotent_write
    def create_task(self, spec: "UploadTaskSpec") -> int:
        """Create an empty task and return its id.

        Kept separate from :meth:`attach_task_data` so each is retried on
        its own: retrying the pair as one unit after the *data* call was
        throttled would create a second task.  The split is also what lets
        the caller record the task id before the long data step runs.
        """
        tasks_api = self.client.api_client.tasks_api
        task, _ = tasks_api.create(build_task_write_request(spec))
        logger.info(f"Создана задача: {task.name} (id={task.id})")
        return int(task.id)

    def attach_task_data(self, task_id: int, spec: "UploadTaskSpec") -> None:
        """Attach cloud-storage files to *task_id* and wait for processing.

        Waits for CVAT to finish processing the cloud-storage files so
        that subsequent annotation uploads land on the correct frames.
        Raises :class:`CvatApiError` when processing fails (e.g. images
        not found in cloud storage).

        The data POST and the status poll are retried separately: the POST
        is not idempotent, so it gets the write policy on its own, while
        the poll is a plain read that may be repeated freely.  The trailing
        size read only feeds a log line and runs after the attach has
        already succeeded, so a failure there is logged, not raised.
        """
        rq_id = self._start_data_processing(task_id, spec)
        self._wait_for_data_processing(task_id, rq_id)
        try:
            size: int | str = self.get_task_size(task_id)
        except CvatApiError as exc:
            logger.warning(f"Задача {task_id}: не удалось прочитать size — {exc!r}")
            size = "?"
        logger.info(
            f"Привязано {len(spec.server_files)} изображений к задаче {task_id} "
            f"(cloud_storage_id={spec.cloud_storage_id}, "
            f"segment_size={spec.segment_size}, size={size})"
        )

    @cvat_non_idempotent_write
    def _start_data_processing(self, task_id: int, spec: "UploadTaskSpec") -> str:
        """Issue the data POST and return the id of CVAT's background request."""
        result, _ = self.client.api_client.tasks_api.create_data(
            task_id,
            data_request=build_data_request(spec),
        )
        return str(result.rq_id)

    @cvat_read
    def _wait_for_data_processing(self, task_id: int, rq_id: str) -> None:
        """Poll background request *rq_id* until CVAT has processed the data."""
        try:
            self.client.wait_for_completion(
                rq_id,
                status_check_period=_DATA_CHECK_PERIOD,
            )
        except BackgroundRequestException as exc:
            msg = f"Задача {task_id}: обработка данных не удалась — {exc}"
            raise CvatApiError(msg) from exc

    @cvat_non_idempotent_write
    def put_task_shapes(self, task_id: int, shapes: "list[NewShape]") -> None:
        """Add annotation shapes to a task."""
        task_obj = self.client.tasks.retrieve(task_id)
        task_obj.update_annotations(
            build_new_shapes_payload(shapes),
            action=AnnotationUpdateAction.CREATE,
        )

    @cvat_non_idempotent_write
    def create_issue(self, issue: "NewIssue") -> None:
        """Open a review issue on a job frame."""
        self.client.api_client.issues_api.create(build_issue_request(issue))

    @cvat_idempotent_write
    def set_deleted_frames(self, task_id: int, frame_ids: list[int]) -> None:
        """Replace the task's deleted-frames list."""
        self.client.api_client.tasks_api.partial_update_data_meta(
            task_id,
            patched_data_meta_write_request=build_deleted_frames_request(frame_ids),
        )

    @cvat_non_idempotent_write
    def delete_shapes(self, task_id: int, shapes: "list[RawShape]") -> None:
        """Delete the given existing shapes from a task."""
        self.client.api_client.tasks_api.partial_update_annotations(
            "delete",
            task_id,
            patched_labeled_data_request=build_delete_shapes_payload(shapes),
        )

    @cvat_non_idempotent_write
    def delete_task(self, task_id: int) -> None:
        """Delete a task permanently."""
        self.client.api_client.tasks_api.destroy(task_id)

    @cvat_idempotent_write
    def update_job(
        self,
        job_id: int,
        *,
        stage: str | None = None,
        state: str | None = None,
    ) -> None:
        """Patch stage and/or state of a job."""
        self.client.api_client.jobs_api.partial_update(
            job_id,
            patched_job_write_request=build_job_patch_request(stage=stage, state=state),
        )

    @cvat_non_idempotent_write
    def patch_project_labels(
        self,
        project_id: int,
        patches: "list[LabelPatch]",
    ) -> None:
        """Apply label additions/renames/deletions/recolors to a project."""
        self.client.api_client.projects_api.partial_update(
            project_id,
            patched_project_write_request=build_labels_patch_request(patches),
        )
