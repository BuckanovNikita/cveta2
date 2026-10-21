"""Public API api helpers contracts."""

from typing import TYPE_CHECKING

import cveta2
from cveta2.application.ports.dtos import LabelPatch
from cveta2.domain.errors import (
    CvatApiError,
)
from tests.fixtures.fake_cvat_api import FakeCvatApi
from tests.helpers import (
    client_with_api,
)

if TYPE_CHECKING:
    from pathlib import Path

    from cveta2.domain.models import LabelInfo, TaskInfo
    from cveta2.domain.storage import CloudStorageInfo
    from tests.fixtures.fake_cvat_project import LoadedFixtures


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
        fixtures: "LoadedFixtures",
        *,
        cloud_storage: "CloudStorageInfo | None" = None,
    ) -> None:
        """Wrap *fixtures*, optionally giving the project a cloud storage."""
        super().__init__(fixtures)
        self.project_id = fixtures.project.id
        self._cloud_storage = cloud_storage

    def _check_project(self, project_id: object) -> None:
        if project_id != self.project_id:
            raise CvatApiError(f"no such project: {project_id!r}", status_code=404)

    def get_project_tasks(self, _project_id: int) -> "list[TaskInfo]":
        """Return the project's tasks, refusing any other project id."""
        self._check_project(_project_id)
        return super().get_project_tasks(_project_id)

    def get_project_labels(self, _project_id: int) -> "list[LabelInfo]":
        """Return the project's labels, refusing any other project id."""
        self._check_project(_project_id)
        return super().get_project_labels(_project_id)

    def get_project_cloud_storage(self, _project_id: int) -> "CloudStorageInfo | None":
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
    fixtures: "LoadedFixtures",
    *,
    cloud_storage: "CloudStorageInfo | None" = None,
    config_path: "Path | None" = None,
) -> tuple[_ProjectScopedApi, cveta2.Connection]:
    """Build a project-id-checking fake plus a ``Connection`` around it."""
    api = _ProjectScopedApi(fixtures, cloud_storage=cloud_storage)
    return api, cveta2.Connection(client=client_with_api(api), config_path=config_path)
