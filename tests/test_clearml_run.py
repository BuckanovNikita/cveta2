"""tests/integration/clearml_run.py against a fake ClearML API session.

The fake answers ``projects.get_all`` with the projects it holds and records
every ``projects.delete`` body, so the tests pin the wire shape the k8s-infra
``clearml.py`` helper uses and the order the run's projects go in.
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from tests.integration import clearml_run
from tests.integration.clearml_run import Project, RunError, RunSettings

REPO_ROOT = Path(__file__).resolve().parent.parent
TAG = "cveta2-claude-20260905-integration-k3x9"
ENV = {
    "INTEGRATION_RUN_TAG": TAG,
    "CLEARML_API_HOST": "https://api.clearml.k8s.docker.internal/",
    "CLEARML_API_ACCESS_KEY": "cak",
    "CLEARML_API_SECRET_KEY": "csk",
}


@dataclass
class Response:
    """The slice of ``requests.Response`` the run reads (``json`` is a method)."""

    ok: bool = True
    status_code: int = 200
    text: str = ""
    payload: dict[str, Any] = field(default_factory=dict)

    def json(self) -> dict[str, Any]:
        return self.payload


class FakeSession(BaseModel):
    """Every project the stand holds, as ``{"id": ..., "name": ...}`` items."""

    projects: list[dict[str, str]] = []
    failing_action: str | None = None
    requests: list[tuple[str, dict[str, Any]]] = []

    def send_request(
        self, service: str, action: str, *, json: dict[str, Any], method: str
    ) -> Response:
        assert service == "projects"
        assert method == "post"
        self.requests.append((action, json))
        if action == self.failing_action:
            return Response(
                ok=False, status_code=403, text="user has no permission for this"
            )
        if action == "get_all":
            start = json["page"] * json["page_size"]
            page = self.projects[start : start + json["page_size"]]
            return Response(payload={"data": {"projects": page}})
        self.projects = [p for p in self.projects if p["id"] != json["project"]]
        return Response(payload={"data": {"deleted": 1}})

    def deletions(self) -> list[dict[str, Any]]:
        return [body for action, body in self.requests if action == "delete"]


def stand(*names: str) -> FakeSession:
    return FakeSession(
        projects=[{"id": f"id{i}", "name": name} for i, name in enumerate(names)]
    )


class TestSettings:
    def test_from_env_reads_the_tag_and_the_stand(self) -> None:
        settings = RunSettings.from_env(ENV)
        assert settings.tag == TAG
        assert settings.api_host == "https://api.clearml.k8s.docker.internal"

    def test_every_missing_variable_is_named_at_once(self) -> None:
        env = {**ENV, "INTEGRATION_RUN_TAG": " ", "CLEARML_API_SECRET_KEY": ""}
        with pytest.raises(RunError) as excinfo:
            RunSettings.from_env(env)
        message = str(excinfo.value)
        assert "INTEGRATION_RUN_TAG, CLEARML_API_SECRET_KEY" in message


class TestNames:
    @pytest.mark.parametrize(
        ("name", "owned"),
        [
            (f"{TAG} clearml-publish", True),
            (f"{TAG} clearml-publish/.datasets/ds-1a2b3c4d", True),
            (f"{TAG}", True),
            (f"{TAG}-keep clearml-publish", False),
            (f"{TAG}x clearml-publish", False),
            (f"other/{TAG} clearml-publish", False),
            ("cveta2-main clearml-publish", False),
            ("", False),
        ],
    )
    def test_ownership_is_the_first_token_of_the_first_path_element(
        self, name: str, *, owned: bool
    ) -> None:
        assert clearml_run.owned_by_run(name, TAG) is owned

    def test_sub_projects_come_before_their_parents(self) -> None:
        ordered = clearml_run.deepest_first(
            [
                Project(id="1", name=f"{TAG} b"),
                Project(id="2", name=f"{TAG} a/.datasets/ds"),
                Project(id="3", name=f"{TAG} a"),
                Project(id="4", name=f"{TAG} a/.datasets/ds/deeper"),
            ]
        )
        assert [p.id for p in ordered] == ["4", "2", "3", "1"]


class TestDeleteRunProjects:
    def test_deletes_the_runs_projects_deepest_first_with_their_contents(
        self,
    ) -> None:
        session = stand(
            f"{TAG} clearml-publish",
            f"{TAG} clearml-publish/.datasets/ds-1",
            f"{TAG} clearml-skip",
            f"{TAG}-keep clearml-publish",
            "cveta2-main clearml-publish",
        )
        deleted = clearml_run.delete_run_projects(session, TAG)
        assert deleted == [
            f"{TAG} clearml-publish/.datasets/ds-1",
            f"{TAG} clearml-publish",
            f"{TAG} clearml-skip",
        ]
        assert session.deletions() == [
            {"project": "id1", "force": True, "delete_contents": True},
            {"project": "id0", "force": True, "delete_contents": True},
            {"project": "id2", "force": True, "delete_contents": True},
        ]
        assert [p["name"] for p in session.projects] == [
            f"{TAG}-keep clearml-publish",
            "cveta2-main clearml-publish",
        ]

    def test_the_listing_is_anchored_on_the_tag(self) -> None:
        session = stand()
        clearml_run.delete_run_projects(session, TAG)
        (action, body), *rest = session.requests
        assert not rest
        assert action == "get_all"
        assert body["name"] == f"^{re.escape(TAG)}"
        assert body["only_fields"] == ["id", "name"]
        assert body["page"] == 0
        assert body["page_size"] == clearml_run.PAGE_SIZE

    def test_a_full_page_is_followed_by_the_next(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(clearml_run, "PAGE_SIZE", 2)
        session = stand(f"{TAG} a", f"{TAG} b", f"{TAG} c")
        deleted = clearml_run.delete_run_projects(session, TAG)
        assert sorted(deleted) == [f"{TAG} a", f"{TAG} b", f"{TAG} c"]
        listings = [body for action, body in session.requests if action == "get_all"]
        assert [body["page"] for body in listings] == [0, 1]

    def test_a_refused_call_is_an_error_with_the_servers_answer(self) -> None:
        session = stand(f"{TAG} clearml-publish")
        session.failing_action = "delete"
        with pytest.raises(RunError, match="403"):
            clearml_run.delete_run_projects(session, TAG)


@pytest.mark.parametrize(
    "module", ["tests.integration.clearml_run", "tests.integration.test_clearml"]
)
def test_the_sdk_is_never_imported_at_module_level(module: str) -> None:
    """Importing ``clearml`` logs in to the configured server; collection must not."""
    probe = f"import sys, {module}; sys.exit('clearml' in sys.modules)"
    completed = subprocess.run(  # noqa: S603 - fixed probe of this repository
        [sys.executable, "-c", probe],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
