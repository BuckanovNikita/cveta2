"""Construct the supported CVAT client from resolved configuration and adapters."""

from dataclasses import replace

import pandas as pd

from cveta2.adapters.config.settings import CvatConfig, should_raise_on_fetch_failure
from cveta2.adapters.cvat.connection import SdkClientFactory, open_sdk_api
from cveta2.adapters.execution.concurrency import Workers, run_concurrent
from cveta2.adapters.s3.images import S3ImageReader
from cveta2.application.client import ApplicationClient
from cveta2.application.client.session import TaskWriteSession
from cveta2.application.client.shared import FetchContext
from cveta2.application.ports.client import ClientSettings
from cveta2.application.ports.cvat import CvatApiPort

__all__ = [
    "CvatClient",
    "FetchContext",
    "TaskWriteSession",
]


class CvatClient(ApplicationClient):
    """Compatible public client composed from production adapters."""

    def __init__(
        self,
        cfg: CvatConfig | None = None,
        client_factory: SdkClientFactory | None = None,
        *,
        api: CvatApiPort | None = None,
    ) -> None:
        """Resolve defaults while checking credentials only when entering."""
        self._cfg = cfg or CvatConfig.load()
        self._client_factory = client_factory
        super().__init__(
            ClientSettings(
                host=self._cfg.host,
                organization=self._cfg.organization,
                cvat_workers=Workers.cvat,
                raise_on_failure=should_raise_on_fetch_failure(),
            ),
            images=S3ImageReader(),
            runner=run_concurrent,
            session_factory=lambda: open_sdk_api(
                self._cfg.require_credentials(), self._client_factory
            ),
            api=api,
        )

    @property
    def host(self) -> str:
        """Read the retained public configuration, matching session construction."""
        return self._cfg.host or ""

    @property
    def default_organization(self) -> str | None:
        """Read the configured default independently of session organization."""
        return self._cfg.organization

    def _refresh_runtime_settings(self) -> None:
        """Resolve invocation-time policy at the public composition boundary."""
        self._settings = replace(
            self._settings,
            host=self._cfg.host,
            cvat_workers=Workers.cvat,
            raise_on_failure=should_raise_on_fetch_failure(),
        )

    def prepare_fetch(  # noqa: PLR0913
        self,
        project_id: int,
        *,
        completed_only: bool = False,
        ignore_task_ids: set[int] | None = None,
        silent_task_ids: set[int] | None = None,
        task_selector: list[int | str] | None = None,
        project_name: str = "",
    ) -> FetchContext:
        """Refresh resolved policies before preparing the requested fetch."""
        self._refresh_runtime_settings()
        return super().prepare_fetch(
            project_id,
            completed_only=completed_only,
            ignore_task_ids=ignore_task_ids,
            silent_task_ids=silent_task_ids,
            task_selector=task_selector,
            project_name=project_name,
        )

    def set_task_jobs_status(
        self,
        task_id: int,
        *,
        stage: str | None = None,
        state: str | None = None,
    ) -> int:
        """Refresh the worker policy before updating the task jobs."""
        self._refresh_runtime_settings()
        return super().set_task_jobs_status(task_id, stage=stage, state=state)

    def create_task_issues(
        self,
        task_id: int,
        annotations_df: pd.DataFrame,
        *,
        session: TaskWriteSession | None = None,
        skip_existing: bool = False,
    ) -> int:
        """Refresh the worker policy before creating task review issues."""
        self._refresh_runtime_settings()
        return super().create_task_issues(
            task_id, annotations_df, session=session, skip_existing=skip_existing
        )
