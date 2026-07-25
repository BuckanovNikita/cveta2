"""Tests for the org-paginated interactive project picker."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from cveta2.commands.interactive.entities import (
    _NEXT_ORG_VALUE,
    _RESCAN_VALUE,
    select_project,
)
from cveta2.models import OrganizationInfo, ProjectInfo
from cveta2.projects_cache import OrgProjects

_ENTITIES = "cveta2.commands.interactive.entities"


def _pages() -> list[OrgProjects]:
    return [
        OrgProjects(
            slug="",
            name="Личное пространство",
            projects=[ProjectInfo(id=1, name="personal-proj")],
        ),
        OrgProjects(
            slug="acme",
            name="Acme",
            projects=[ProjectInfo(id=2, name="acme-proj")],
        ),
    ]


def _client(org: str | None = None) -> MagicMock:
    client = MagicMock()
    client.organization = org
    return client


def test_first_page_is_default_org_and_selection_switches_org() -> None:
    client = _client(org="acme")
    with (
        patch(f"{_ENTITIES}.load_orgs_cache", return_value=_pages()),
        patch(f"{_ENTITIES}.primitives.select_one", return_value=2) as select_one,
    ):
        assert select_project(client) == (2, "acme-proj")
    assert "Acme" in select_one.call_args.args[0]
    client.set_organization.assert_called_once_with("acme")


def test_next_org_navigates_to_second_page() -> None:
    client = _client(org="acme")
    with (
        patch(f"{_ENTITIES}.load_orgs_cache", return_value=_pages()),
        patch(
            f"{_ENTITIES}.primitives.select_one",
            side_effect=[_NEXT_ORG_VALUE, 1],
        ) as select_one,
    ):
        assert select_project(client) == (1, "personal-proj")
    assert "Личное пространство" in select_one.call_args.args[0]
    client.set_organization.assert_called_once_with(None)


def test_rescan_fetches_all_orgs_and_saves_cache() -> None:
    client = _client(org=None)
    client.list_organizations.return_value = [
        OrganizationInfo(slug="acme", name="Acme"),
    ]
    client.list_projects.side_effect = [
        [ProjectInfo(id=1, name="personal-proj")],
        [ProjectInfo(id=2, name="acme-proj")],
    ]
    with (
        patch(f"{_ENTITIES}.load_orgs_cache", return_value=_pages()),
        patch(f"{_ENTITIES}.save_orgs_cache") as save_cache,
        patch(
            f"{_ENTITIES}.primitives.select_one",
            side_effect=[_RESCAN_VALUE, 1],
        ),
    ):
        assert select_project(client) == (1, "personal-proj")
    saved = save_cache.call_args.args[0]
    assert [page.slug for page in saved] == ["", "acme"]
    assert client.set_organization.call_args_list[-1].args == (None,)


def test_empty_cache_scans_and_saves() -> None:
    client = _client(org=None)
    client.list_organizations.return_value = []
    client.list_projects.return_value = [ProjectInfo(id=1, name="personal-proj")]
    with (
        patch(f"{_ENTITIES}.load_orgs_cache", return_value=[]),
        patch(f"{_ENTITIES}.save_orgs_cache") as save_cache,
        patch(f"{_ENTITIES}.primitives.select_one", return_value=1),
    ):
        assert select_project(client) == (1, "personal-proj")
    save_cache.assert_called_once()


def test_no_projects_anywhere_exits() -> None:
    client = _client(org=None)
    empty = [OrgProjects(slug="", name="Личное пространство", projects=[])]
    with (
        patch(f"{_ENTITIES}.load_orgs_cache", return_value=empty),
        pytest.raises(SystemExit),
    ):
        select_project(client)
