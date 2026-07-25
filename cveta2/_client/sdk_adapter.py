"""CVAT SDK adapter implementing ``CvatApiPort``.

This is the only module that imports and interacts with ``cvat_sdk``.
It converts opaque SDK objects into typed DTOs from ``dtos.py``.
"""

from __future__ import annotations

import functools
import json
from typing import TYPE_CHECKING

import urllib3.exceptions
from loguru import logger

from cveta2._client.dtos import (
    RawIssue,
    RawJob,
)
from cveta2._client.sdk_convert import (
    convert_annotations,
    convert_data_meta,
    convert_label,
    convert_task,
    data_meta_from_dict,
)
from cveta2._client.sdk_requests import (
    build_data_request,
    build_delete_shapes_payload,
    build_deleted_frames_request,
    build_issue_request,
    build_job_patch_request,
    build_labels_patch_request,
    build_new_shapes_payload,
    build_task_write_request,
)
from cveta2._retry import network_retry
from cveta2.exceptions import CvatApiError
from cveta2.image_downloader import parse_cloud_storage
from cveta2.models import OrganizationInfo, ProjectInfo

if TYPE_CHECKING:
    from collections.abc import Callable

    from cvat_sdk import Client as CvatSdkClient

    from cveta2._client.dtos import (
        LabelPatch,
        NewIssue,
        NewShape,
        RawAnnotations,
        RawDataMeta,
        RawShape,
        UploadTaskSpec,
    )
    from cveta2.image_downloader import CloudStorageInfo
    from cveta2.models import LabelInfo, TaskInfo

from typing import ParamSpec, TypeVar

from cvat_sdk.api_client.exceptions import ApiException, ApiTypeError
from cvat_sdk.core.exceptions import BackgroundRequestException
from cvat_sdk.core.helpers import get_paginated_collection
from cvat_sdk.core.proxies.annotations import AnnotationUpdateAction

_P = ParamSpec("_P")
_R = TypeVar("_R")

_DATA_CHECK_PERIOD = 5
"""Seconds between status checks during data processing."""


def _translate_api_errors(func: Callable[_P, _R]) -> Callable[_P, _R]:
    """Convert SDK ``ApiException`` into :class:`CvatApiError`."""

    @functools.wraps(func)
    def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        try:
            return func(*args, **kwargs)
        except ApiException as e:
            status = int(getattr(e, "status", 0) or 0)
            raise CvatApiError(str(e), status_code=status) from e

    return wrapper


# urllib3 timeout errors are not OSError, hence urllib3.exceptions.HTTPError.
_api_retry = network_retry(
    (OSError, ConnectionError, urllib3.exceptions.HTTPError), label="CVAT API"
)

_CONNECT_TIMEOUT = 10.0


def apply_request_timeout(sdk_client: CvatSdkClient, timeout: float) -> None:
    """Enforce a default (connect, read) timeout on every CVAT HTTP request.

    Wraps the SDK's low-level ``rest_client.request`` so that requests
    without an explicit ``_request_timeout`` get ``(10.0, timeout)``.
    Explicit per-call timeouts set by the SDK are preserved.
    """
    rest_client = sdk_client.api_client.rest_client
    original_request: Callable[..., object] = rest_client.request

    @functools.wraps(original_request)
    def request_with_timeout(*args: object, **kwargs: object) -> object:
        if kwargs.get("_request_timeout") is None:
            kwargs["_request_timeout"] = (_CONNECT_TIMEOUT, timeout)
        return original_request(*args, **kwargs)

    rest_client.request = request_with_timeout


_GLOBAL_TIMEOUT_MARKER = "_cveta2_global_timeout"


def install_global_request_timeout(timeout: float) -> None:
    """Enforce the timeout on ALL CVAT SDK REST clients, present and future.

    ``apply_request_timeout`` wraps one opened client, but ``make_client``
    performs requests (server version check, login) before any wrapping is
    possible; a black-holed host hangs there forever. Patching
    ``RESTClientObject.request`` at class level covers that window too.
    Idempotent: repeated calls only update the timeout value.
    """
    from cvat_sdk.api_client.rest import RESTClientObject  # noqa: PLC0415

    if getattr(RESTClientObject, _GLOBAL_TIMEOUT_MARKER, None) is not None:
        setattr(RESTClientObject, _GLOBAL_TIMEOUT_MARKER, timeout)
        return

    original_request = RESTClientObject.request

    @functools.wraps(original_request)
    def request_with_timeout(
        self: RESTClientObject, *args: object, **kwargs: object
    ) -> object:
        if kwargs.get("_request_timeout") is None:
            read_timeout = getattr(RESTClientObject, _GLOBAL_TIMEOUT_MARKER)
            kwargs["_request_timeout"] = (_CONNECT_TIMEOUT, read_timeout)
        return original_request(self, *args, **kwargs)

    RESTClientObject.request = request_with_timeout
    setattr(RESTClientObject, _GLOBAL_TIMEOUT_MARKER, timeout)


class SdkCvatApiAdapter:
    """``CvatApiPort`` implementation backed by an open CVAT SDK client.

    The caller is responsible for opening and closing the SDK client.
    This adapter is a thin stateless converter: SDK objects in, DTOs out.
    All public methods are wrapped with retry logic for transient errors.
    """

    def __init__(self, client: CvatSdkClient) -> None:
        """Wrap an already-opened ``cvat_sdk`` client."""
        self.client = client

    @_api_retry
    @_translate_api_errors
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
        self.client.organization_slug = org
        logger.trace(f"Switched organization to: {org!r}")

    @_api_retry
    @_translate_api_errors
    def list_projects(self) -> list[ProjectInfo]:
        """Return all accessible projects."""
        raw = self.client.projects.list()
        return [ProjectInfo(id=p.id, name=p.name or "") for p in raw]

    @_api_retry
    @_translate_api_errors
    def get_project_tasks(self, project_id: int) -> list[TaskInfo]:
        """Return tasks belonging to a project."""
        project = self.client.projects.retrieve(project_id)
        tasks = project.get_tasks()
        return [convert_task(t) for t in tasks]

    @_api_retry
    @_translate_api_errors
    def get_project_labels(self, project_id: int) -> list[LabelInfo]:
        """Return label definitions for a project."""
        project = self.client.projects.retrieve(project_id)
        labels = project.get_labels()
        return [convert_label(lbl) for lbl in labels]

    @_api_retry
    @_translate_api_errors
    def get_task_data_meta(self, task_id: int) -> RawDataMeta:
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

    @_api_retry
    @_translate_api_errors
    def get_task_annotations(self, task_id: int) -> RawAnnotations:
        """Return shapes for a task."""
        tasks_api = self.client.api_client.tasks_api
        labeled_data, _ = tasks_api.retrieve_annotations(task_id)
        return convert_annotations(labeled_data)

    @_api_retry
    @_translate_api_errors
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
                ),
            )
        return result

    @_api_retry
    @_translate_api_errors
    def get_project_cloud_storage(self, project_id: int) -> CloudStorageInfo | None:
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

    @_api_retry
    @_translate_api_errors
    def get_task(self, task_id: int) -> TaskInfo:
        """Return one task by id (with its ``project_id``)."""
        return convert_task(self.client.tasks.retrieve(task_id))

    @_api_retry
    @_translate_api_errors
    def get_task_labels(self, task_id: int) -> list[LabelInfo]:
        """Return label definitions available in a task."""
        task_obj = self.client.tasks.retrieve(task_id)
        return [convert_label(lbl) for lbl in task_obj.get_labels()]

    @_api_retry
    @_translate_api_errors
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
            )
            for job in jobs
        ]

    @_api_retry
    @_translate_api_errors
    def get_task_size(self, task_id: int) -> int:
        """Return the number of frames in a task."""
        task_obj = self.client.tasks.retrieve(task_id)
        return int(task_obj.size or 0)

    @_translate_api_errors
    def create_task_with_data(self, spec: UploadTaskSpec) -> int:
        """Create a task, attach cloud-storage data, wait; return task id.

        Waits for CVAT to finish processing the cloud-storage files so
        that subsequent annotation uploads land on the correct frames.
        Raises ``RuntimeError`` when processing fails (e.g. images not
        found in cloud storage).
        """
        tasks_api = self.client.api_client.tasks_api
        task, _ = tasks_api.create(build_task_write_request(spec))
        logger.info(f"Создана задача: {task.name} (id={task.id})")

        result, _ = tasks_api.create_data(
            task.id,
            data_request=build_data_request(spec),
        )
        try:
            self.client.wait_for_completion(
                result.rq_id,
                status_check_period=_DATA_CHECK_PERIOD,
            )
        except BackgroundRequestException as exc:
            msg = f"Задача {task.id}: обработка данных не удалась — {exc}"
            raise RuntimeError(msg) from exc

        size = self.get_task_size(int(task.id))
        logger.info(
            f"Привязано {len(spec.server_files)} изображений к задаче {task.id} "
            f"(cloud_storage_id={spec.cloud_storage_id}, "
            f"segment_size={spec.segment_size}, size={size})"
        )
        return int(task.id)

    @_translate_api_errors
    def put_task_shapes(self, task_id: int, shapes: list[NewShape]) -> None:
        """Add annotation shapes to a task."""
        task_obj = self.client.tasks.retrieve(task_id)
        task_obj.update_annotations(
            build_new_shapes_payload(shapes),
            action=AnnotationUpdateAction.CREATE,
        )

    @_translate_api_errors
    def create_issue(self, issue: NewIssue) -> None:
        """Open a review issue on a job frame."""
        self.client.api_client.issues_api.create(build_issue_request(issue))

    @_translate_api_errors
    def set_deleted_frames(self, task_id: int, frame_ids: list[int]) -> None:
        """Replace the task's deleted-frames list."""
        self.client.api_client.tasks_api.partial_update_data_meta(
            task_id,
            patched_data_meta_write_request=build_deleted_frames_request(frame_ids),
        )

    @_translate_api_errors
    def delete_shapes(self, task_id: int, shapes: list[RawShape]) -> None:
        """Delete the given existing shapes from a task."""
        self.client.api_client.tasks_api.partial_update_annotations(
            "delete",
            task_id,
            patched_labeled_data_request=build_delete_shapes_payload(shapes),
        )

    @_translate_api_errors
    def delete_task(self, task_id: int) -> None:
        """Delete a task permanently."""
        self.client.api_client.tasks_api.destroy(task_id)

    @_translate_api_errors
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

    @_translate_api_errors
    def patch_project_labels(
        self,
        project_id: int,
        patches: list[LabelPatch],
    ) -> None:
        """Apply label additions/renames/deletions/recolors to a project."""
        if not patches:
            return
        self.client.api_client.projects_api.partial_update(
            project_id,
            patched_project_write_request=build_labels_patch_request(patches),
        )
