"""tests/integration/clearml_run.py against a fake ClearML API session.

The fake answers ``projects.get_all`` with the projects it holds and records
every ``projects.delete`` body, so the tests pin the wire shape the k8s-infra
``clearml.py`` helper uses and the order the run's projects go in.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from tests.integration import clearml_run
from tests.integration.clearml_run import Project, RunError, RunSettings

INTEGRATION_DIR = Path(__file__).resolve().parent / "integration"
TAG = "cveta2-claude-20260905-integration-k3x9"
ENV = {
    "INTEGRATION_RUN_TAG": TAG,
    "CLEARML_API_HOST": "http://clearml-api.k8s.localhost/",
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
        assert settings.api_host == "http://clearml-api.k8s.localhost"

    def test_every_missing_variable_is_named_at_once(self) -> None:
        env = {**ENV, "INTEGRATION_RUN_TAG": " ", "CLEARML_API_SECRET_KEY": ""}
        with pytest.raises(RunError) as excinfo:
            RunSettings.from_env(env)
        message = str(excinfo.value)
        assert "INTEGRATION_RUN_TAG, CLEARML_API_SECRET_KEY not set" in message
        assert "scripts/integration_test.sh" in message


class TestNames:
    def test_projects_are_named_by_the_tag(self) -> None:
        assert clearml_run.project_name(TAG, "clearml-publish") == (
            f"{TAG} clearml-publish"
        )

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

    def test_nothing_of_the_run_means_no_deletion(self) -> None:
        session = stand("cveta2-main clearml-publish")
        assert clearml_run.delete_run_projects(session, TAG) == []
        assert session.deletions() == []

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
        with pytest.raises(RunError, match=r"projects\.delete failed: 403 user has no"):
            clearml_run.delete_run_projects(session, TAG)


@pytest.mark.parametrize("module", ["clearml_run.py", "test_clearml.py"])
def test_the_sdk_is_never_imported_at_module_level(module: str) -> None:
    """Importing ``clearml`` logs in to the configured server; collection must not."""
    lines = (INTEGRATION_DIR / module).read_text(encoding="utf-8").splitlines()
    top_level = [
        line for line in lines if line.startswith(("import clearml", "from clearml"))
    ]
    assert top_level == []
    nested = [
        line
        for line in lines
        if "clearml" in line
        and line.startswith(" ")
        and line.strip().startswith(("import clearml", "from clearml"))
    ]
    assert nested, "the scan found no clearml import at all - the pattern rotted"
