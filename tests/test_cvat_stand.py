"""tests/integration/cvat_stand.py against a fake CVAT SDK client.

The fake stands in for ``cvat_sdk.core.client.Client``: it knows one password,
one account, the organizations that account belongs to, and the objects in
the organization with their owners. It has no registration endpoint at all,
so any path that tried to create a user or an organization would fail here.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest
from cvat_sdk.api_client.exceptions import ApiException
from loguru import logger
from pydantic import BaseModel, ConfigDict

from tests.integration import cvat_stand

if TYPE_CHECKING:
    from collections.abc import Iterator

HOST = "http://cvat.k8s.localhost"
USER = "cveta2"
PASSWORD = "from-the-secret"
ORG = "agents"
TAG = "cveta2-claude-20260905-integration-k3x9"
CREATED = datetime(2026, 9, 1, tzinfo=timezone.utc)


def item(
    id_: int, name: str, owner: str | None, project_id: int | None = None
) -> SimpleNamespace:
    return SimpleNamespace(
        id=id_,
        name=name,
        display_name=name,
        owner=SimpleNamespace(username=owner) if owner else None,
        created_date=CREATED,
        project_id=project_id,
    )


class Page(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    results: list[Any]
    next: str | None = None


class Stand(BaseModel):
    """What the fake server knows; shared by every client the script opens."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    projects: list[SimpleNamespace] = []
    tasks: list[SimpleNamespace] = []
    storages: list[SimpleNamespace] = []
    organizations: list[str] = [ORG]
    self_username: str = USER
    sticky: bool = False
    logins: list[tuple[str, str]] = []
    destroyed: list[tuple[str, int]] = []
    org_slugs_seen: list[str | None] = []
    closed: int = 0

    def destroy(self, kind: str, id_: int) -> None:
        self.destroyed.append((kind, id_))
        if self.sticky:
            return
        if kind == "project":
            self.projects = [p for p in self.projects if p.id != id_]
            self.tasks = [t for t in self.tasks if t.project_id != id_]
        elif kind == "task":
            self.tasks = [t for t in self.tasks if t.id != id_]
        else:
            self.storages = [s for s in self.storages if s.id != id_]


def _paged(fetch: Any) -> Any:
    def list_(page: int, page_size: int) -> tuple[Page, None]:
        assert page == 1
        assert page_size == cvat_stand.PAGE_SIZE
        return Page(results=list(fetch())), None

    return SimpleNamespace(list=list_)


def fake_client_class(stand: Stand) -> type:
    class FakeClient:
        def __init__(self, url: str, *, check_server_version: bool = True) -> None:
            assert url == HOST
            assert check_server_version is False
            self.organization_slug: str | None = None
            self.api_client = SimpleNamespace(
                users_api=SimpleNamespace(
                    retrieve_self=lambda: (
                        SimpleNamespace(username=stand.self_username, id=7),
                        None,
                    )
                ),
                organizations_api=_paged(
                    lambda: [SimpleNamespace(slug=s) for s in stand.organizations]
                ),
                server_api=SimpleNamespace(
                    retrieve_about=lambda: (SimpleNamespace(version="2.30.0"), None)
                ),
                cloudstorages_api=SimpleNamespace(
                    list=_paged(lambda: stand.storages).list,
                    destroy=lambda id_: stand.destroy("storage", id_),
                ),
                projects_api=SimpleNamespace(
                    destroy=lambda id_: stand.destroy("project", id_)
                ),
                tasks_api=SimpleNamespace(
                    destroy=lambda id_: stand.destroy("task", id_)
                ),
            )
            self.projects = SimpleNamespace(list=lambda: list(stand.projects))
            self.tasks = SimpleNamespace(list=lambda: list(stand.tasks))

        def login(self, credentials: tuple[str, str]) -> None:
            if credentials != (USER, PASSWORD):
                raise ApiException(status=401, reason="Unauthorized")
            stand.logins.append(credentials)

        def close(self) -> None:
            stand.org_slugs_seen.append(self.organization_slug)
            stand.closed += 1

    return FakeClient


@pytest.fixture
def stand(monkeypatch: pytest.MonkeyPatch) -> Stand:
    fake = Stand()
    monkeypatch.setattr(cvat_stand, "Client", fake_client_class(fake))
    monkeypatch.setenv("CVAT_INTEGRATION_HOST", f"{HOST}/")
    monkeypatch.setenv("CVAT_INTEGRATION_USER", USER)
    monkeypatch.setenv("CVAT_INTEGRATION_PASSWORD", PASSWORD)
    monkeypatch.setenv("CVAT_INTEGRATION_ORG", ORG)
    return fake


@pytest.fixture
def logs() -> Iterator[list[str]]:
    records: list[str] = []
    handle = logger.add(
        lambda m: records.append(str(m).rstrip("\n")), format="{message}"
    )
    yield records
    logger.remove(handle)


def run(monkeypatch: pytest.MonkeyPatch, *argv: str) -> int:
    monkeypatch.setattr(sys, "argv", ["cvat_stand.py", *argv])
    return cvat_stand.main()


def seeded(stand: Stand) -> Stand:
    stand.projects = [
        item(1, f"{TAG} coco8-dev", USER),
        item(2, f"{TAG}-feature coco8-dev", USER),
        item(3, f"{TAG} theirs", "fat"),
        item(4, "cveta2-main coco8-dev", USER),
    ]
    stand.tasks = [
        item(10, "train", USER, project_id=1),
        item(11, f"{TAG} solo", USER),
        item(12, f"{TAG} their-solo", "fat"),
        item(13, f"{TAG} orphaned", None),
    ]
    stand.storages = [item(20, f"{TAG} minio", USER), item(21, f"{TAG} minio", "fat")]
    return stand


class TestSettings:
    def test_each_missing_variable_is_named(
        self, stand: Stand, monkeypatch: pytest.MonkeyPatch, logs: list[str]
    ) -> None:
        monkeypatch.delenv("CVAT_INTEGRATION_PASSWORD")
        monkeypatch.setenv("CVAT_INTEGRATION_ORG", "  ")
        assert run(monkeypatch, "verify") == 1
        assert "CVAT_INTEGRATION_PASSWORD, CVAT_INTEGRATION_ORG not set" in logs[-1]
        assert "integration_env.sh" in logs[-1]
        assert stand.logins == []

    @pytest.mark.usefixtures("stand")
    def test_host_loses_its_trailing_slash(self) -> None:
        assert cvat_stand.StandSettings.from_env().host == HOST


class TestVerify:
    def test_member_passes_with_one_login(
        self, stand: Stand, monkeypatch: pytest.MonkeyPatch, logs: list[str]
    ) -> None:
        assert run(monkeypatch, "verify") == 0
        assert stand.logins == [(USER, PASSWORD)]
        assert stand.closed == 1
        assert f"user '{USER}' is a member of organization '{ORG}'" in logs[-1]
        assert "2.30.0" in logs[-1]

    def test_rejected_login_points_at_the_secret(
        self, stand: Stand, monkeypatch: pytest.MonkeyPatch, logs: list[str]
    ) -> None:
        monkeypatch.setenv("CVAT_INTEGRATION_PASSWORD", "stale")
        assert run(monkeypatch, "verify") == 1
        assert f"login as '{USER}' at {HOST} failed: 401" in logs[-1]
        assert "deploy_cvat.sh" in logs[-1]
        assert stand.closed == 1

    def test_another_account_behind_the_password_is_refused(
        self, stand: Stand, monkeypatch: pytest.MonkeyPatch, logs: list[str]
    ) -> None:
        stand.self_username = "someone-else"
        assert run(monkeypatch, "verify") == 1
        assert "logged in as 'someone-else'" in logs[-1]
        assert f"CVAT_INTEGRATION_USER is '{USER}'" in logs[-1]

    def test_missing_membership_names_user_and_organization(
        self, stand: Stand, monkeypatch: pytest.MonkeyPatch, logs: list[str]
    ) -> None:
        stand.organizations = ["another-org", "other"]
        assert run(monkeypatch, "verify") == 1
        assert f"user '{USER}' is not a member of organization '{ORG}'" in logs[-1]
        assert "member of: another-org, other" in logs[-1]
        assert "never creates memberships" in logs[-1]
        assert stand.org_slugs_seen == [None]

    def test_no_membership_at_all(
        self, stand: Stand, monkeypatch: pytest.MonkeyPatch, logs: list[str]
    ) -> None:
        stand.organizations = []
        assert run(monkeypatch, "verify") == 1
        assert "member of: no organization" in logs[-1]

    def test_the_module_has_no_registration_path(self) -> None:
        source = Path(cvat_stand.__file__).read_text(encoding="utf-8")
        for forbidden in (
            "create_register",
            "RegisterSerializerExRequest",
            "OrganizationWriteRequest",
            "organizations_api.create",
        ):
            assert forbidden not in source


class TestLs:
    def test_lists_only_what_the_user_owns(
        self, stand: Stand, monkeypatch: pytest.MonkeyPatch, logs: list[str]
    ) -> None:
        seeded(stand)
        assert run(monkeypatch, "ls") == 0
        assert (
            f"organization {ORG}, owner {USER}: 3 project(s), 2 task(s), "
            "1 cloud storage(s)"
        ) in logs[0]
        rows = "\n".join(logs[1:])
        assert f"{TAG} coco8-dev" in rows
        assert f"{TAG}-feature coco8-dev" in rows
        assert "cveta2-main coco8-dev" in rows
        assert "train  (in project 1)" in rows
        assert f"{TAG} solo  (standalone)" in rows
        assert "theirs" not in rows
        assert "their-solo" not in rows
        assert "orphaned" not in rows
        assert stand.org_slugs_seen == [ORG]


class TestCleanup:
    def test_deletes_this_tag_and_this_owner_only(
        self, stand: Stand, monkeypatch: pytest.MonkeyPatch, logs: list[str]
    ) -> None:
        seeded(stand)
        assert run(monkeypatch, "cleanup", "--tag", TAG) == 0
        assert stand.destroyed == [("project", 1), ("task", 11), ("storage", 20)]
        assert [p.id for p in stand.projects] == [2, 3, 4]
        assert [t.id for t in stand.tasks] == [12, 13]
        assert [s.id for s in stand.storages] == [21]
        assert f"deleted 3 item(s) from organization {ORG}" in logs[-1]

    def test_durable_slot_is_reached_only_by_its_exact_name(
        self, stand: Stand, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seeded(stand)
        assert run(monkeypatch, "cleanup", "--tag", "cveta2-main") == 0
        assert stand.destroyed == [("project", 4)]

    def test_a_prefix_of_the_tag_reaches_nothing(
        self, stand: Stand, monkeypatch: pytest.MonkeyPatch, logs: list[str]
    ) -> None:
        seeded(stand)
        assert run(monkeypatch, "cleanup", "--tag", "cveta2") == 0
        assert stand.destroyed == []
        assert f"nothing of 'cveta2' owned by {USER}" in logs[-1]

    def test_dry_run_destroys_nothing(
        self, stand: Stand, monkeypatch: pytest.MonkeyPatch, logs: list[str]
    ) -> None:
        seeded(stand)
        assert run(monkeypatch, "cleanup", "--tag", TAG, "--dry-run") == 0
        assert stand.destroyed == []
        assert [line for line in logs if line.startswith("would delete")] == [
            f"would delete project 1 '{TAG} coco8-dev'",
            f"would delete task 11 '{TAG} solo'",
            f"would delete storage 20 '{TAG} minio'",
        ]

    def test_leftovers_fail_the_run(
        self, stand: Stand, monkeypatch: pytest.MonkeyPatch, logs: list[str]
    ) -> None:
        seeded(stand)
        stand.sticky = True
        assert run(monkeypatch, "cleanup", "--tag", TAG) == 1
        assert "cleanup left 3 item(s) behind" in logs[-1]
        assert stand.closed == 1


class TestParser:
    @pytest.mark.parametrize(
        "argv",
        [
            ["cleanup"],
            ["cleanup", "--stale", "24"],
            ["cleanup", "--stale"],
            ["bootstrap"],
            [],
        ],
        ids=["bare-cleanup", "stale-hours", "stale-flag", "bootstrap", "nothing"],
    )
    def test_retired_and_incomplete_commands_are_rejected(
        self, argv: list[str], capsys: pytest.CaptureFixture[str]
    ) -> None:
        with pytest.raises(SystemExit) as exit_info:
            cvat_stand.build_parser().parse_args(argv)
        assert exit_info.value.code == 2
        assert capsys.readouterr().err
