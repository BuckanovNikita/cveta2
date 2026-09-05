"""The run's objects on the shared ClearML stand: their names and their removal.

The run acts as project ``cveta2`` under one run tag (``INTEGRATION_RUN_TAG``,
exported by ``scripts/integration_env.sh`` together with the ``CLEARML_*``
identity of the cveta2 Secret, which the ClearML SDK reads from the
environment). Everything the tests create on the stand is a project named
``"<tag> <what>"``; the SDK files a dataset under ``<project>/.datasets/<name>``,
so a run owns every project whose first ``/`` path element starts with the tag
as its first whitespace token - the rule ``clearml.py`` of the k8s-infra skill
applies too. ``delete_run_projects`` removes them deepest first, with their
contents, over the same ``projects.get_all`` / ``projects.delete`` calls the
skill uses; ``scripts/integration_stop.sh`` runs the skill's
``clearml.py --project cveta2 cleanup --prefix <tag>`` afterwards for whatever
a killed session left behind.
"""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING, Any, Protocol

from pydantic import BaseModel

if TYPE_CHECKING:
    from collections.abc import Mapping

PAGE_SIZE = 500
REQUIRED_ENV = (
    "INTEGRATION_RUN_TAG",
    "CLEARML_API_HOST",
    "CLEARML_API_ACCESS_KEY",
    "CLEARML_API_SECRET_KEY",
)


class RunError(RuntimeError):
    """A state the tests must not paper over with a skip."""


class RunSettings(BaseModel):
    tag: str
    api_host: str

    @classmethod
    def from_env(cls, environ: Mapping[str, str] = os.environ) -> RunSettings:
        values = {key: environ.get(key, "").strip() for key in REQUIRED_ENV}
        missing = [key for key, value in values.items() if not value]
        if missing:
            raise RunError(
                f"{', '.join(missing)} not set; run the suite through "
                "scripts/integration_test.sh, which exports the run tag and the "
                "cveta2 ClearML identity from the Secret through the k8s-infra skill"
            )
        return cls(
            tag=values["INTEGRATION_RUN_TAG"],
            api_host=values["CLEARML_API_HOST"].rstrip("/"),
        )


class Project(BaseModel):
    id: str
    name: str

    @property
    def depth(self) -> int:
        return self.name.count("/")


class ApiResponse(Protocol):
    @property
    def ok(self) -> bool: ...

    @property
    def status_code(self) -> int: ...

    @property
    def text(self) -> str: ...

    def json(self) -> Any: ...


class ApiSession(Protocol):
    """The slice of ``clearml.backend_api.Session`` the run needs."""

    def send_request(
        self, service: str, action: str, *, json: dict[str, Any], method: str
    ) -> ApiResponse: ...


def project_name(tag: str, what: str) -> str:
    return f"{tag} {what}"


def owned_by_run(name: str, tag: str) -> bool:
    """Whether a ClearML name belongs to the run: its tag token is the tag.

    The token is the first whitespace-delimited word of the first ``/`` path
    element, so ``"<tag> what/.datasets/ds"`` is the run's and
    ``"other/<tag> x"`` is not.
    """
    tokens = name.split("/", 1)[0].split()
    return bool(tokens) and tokens[0] == tag


def deepest_first(projects: list[Project]) -> list[Project]:
    """Sub-projects before their parents, so no deletion relies on a cascade."""
    return sorted(projects, key=lambda project: (-project.depth, project.name))


def call(session: ApiSession, action: str, body: dict[str, Any]) -> dict[str, Any]:
    response = session.send_request("projects", action, json=body, method="post")
    if not response.ok:
        raise RunError(
            f"projects.{action} failed: {response.status_code} {response.text[:300]}"
        )
    data = response.json().get("data", {})
    return data if isinstance(data, dict) else {}


def list_run_projects(session: ApiSession, tag: str) -> list[Project]:
    projects: list[Project] = []
    page = 0
    while True:
        body = {
            "name": f"^{re.escape(tag)}",
            "only_fields": ["id", "name"],
            "page": page,
            "page_size": PAGE_SIZE,
        }
        batch = call(session, "get_all", body).get("projects", [])
        projects.extend(
            Project(id=str(item["id"]), name=str(item["name"]))
            for item in batch
            if owned_by_run(str(item["name"]), tag)
        )
        if len(batch) < PAGE_SIZE:
            return projects
        page += 1


def delete_run_projects(session: ApiSession, tag: str) -> list[str]:
    """Delete every project of the run with its contents; return their names."""
    deleted: list[str] = []
    for project in deepest_first(list_run_projects(session, tag)):
        call(
            session,
            "delete",
            {"project": project.id, "force": True, "delete_contents": True},
        )
        deleted.append(project.name)
    return deleted


def open_session() -> ApiSession:
    """Open a ClearML API session on the ``CLEARML_*`` identity of the environment.

    Imported here, not at module level: the SDK is the optional ``clearml``
    extra, and importing the ``clearml`` package already logs in to the
    configured server (retrying for minutes when it is down), so no module of
    the suite may import it at collection.
    """
    from clearml.backend_api import Session

    session: ApiSession = Session()
    return session
