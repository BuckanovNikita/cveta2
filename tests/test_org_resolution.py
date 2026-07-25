"""Tests for ORG/PROJECT spec parsing, org switching and project inference."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from cveta2.client import CvatClient
from cveta2.commands._helpers import resolve_project_from_args
from cveta2.config import CvatConfig
from cveta2.exceptions import Cveta2Error

if TYPE_CHECKING:
    from cveta2.models import TaskInfo
from cveta2.services.resolve import (
    apply_project_org,
    infer_project_from_tasks,
    resolve_project_spec,
    split_project_spec,
)
from tests.fixtures.fake_cvat_api import FakeCvatApi
from tests.helpers import make_task


def _fake_client(
    project_name: str = "alpha",
    organization: str | None = None,
) -> tuple[CvatClient, FakeCvatApi]:
    api = FakeCvatApi.from_tasks([make_task(42)], project_name=project_name)
    client = CvatClient(CvatConfig(organization=organization), api=api)
    return client, api


class TestSplitProjectSpec:
    @pytest.mark.parametrize(
        ("spec", "expected"),
        [
            ("alpha", (None, "alpha")),
            (7, (None, 7)),
            ("acme/alpha", ("acme", "alpha")),
            ("/alpha", ("", "alpha")),
            ("acme/al/pha", ("acme", "al/pha")),
            ("  acme / alpha ", ("acme", "alpha")),
        ],
    )
    def test_split(
        self, spec: int | str, expected: tuple[str | None, int | str]
    ) -> None:
        assert split_project_spec(spec) == expected

    def test_empty_project_part_raises(self) -> None:
        with pytest.raises(Cveta2Error, match="ORG/PROJECT"):
            split_project_spec("acme/")


class TestApplyProjectOrg:
    def test_bare_spec_keeps_session_org(self) -> None:
        client, api = _fake_client(organization="default-org")
        assert apply_project_org(client, "alpha") == "alpha"
        assert api.organization_calls == []
        assert client.organization == "default-org"

    def test_org_prefix_switches_session(self) -> None:
        client, api = _fake_client(organization="default-org")
        assert apply_project_org(client, "acme/alpha") == "alpha"
        assert api.organization_calls == ["acme"]
        assert client.organization == "acme"

    def test_leading_slash_selects_personal_workspace(self) -> None:
        client, api = _fake_client(organization="default-org")
        assert apply_project_org(client, "/alpha") == "alpha"
        assert api.organization_calls == [None]
        assert client.organization is None


class TestResolveProjectSpecWithOrg:
    def test_resolves_name_within_org(self) -> None:
        client, api = _fake_client(project_name="alpha")
        assert resolve_project_spec(client, "acme/alpha") == (1, "alpha")
        assert api.organization == "acme"

    def test_default_organization_property_stays(self) -> None:
        client, _api = _fake_client(organization="default-org")
        client.set_organization("acme")
        assert client.default_organization == "default-org"
        assert client.organization == "acme"


class TestResolveProjectFromArgsWithOrg:
    def test_org_spec_switches_session_and_resolves(self) -> None:
        client, api = _fake_client(project_name="alpha", organization="default-org")
        with patch(
            "cveta2.commands._helpers.load_projects_cache", return_value=[]
        ) as load_cache:
            assert resolve_project_from_args(client, "acme/alpha") == (1, "alpha")
        assert api.organization == "acme"
        assert load_cache.call_args.kwargs == {"org": "acme"}


class TestInferProjectFromTasks:
    def test_numeric_id_infers_project(self) -> None:
        client, _api = _fake_client()
        assert infer_project_from_tasks(client, ["42"]) == 1

    def test_int_spec_infers_project(self) -> None:
        client, _api = _fake_client()
        assert infer_project_from_tasks(client, [42]) == 1

    def test_names_only_returns_none(self) -> None:
        client, _api = _fake_client()
        assert infer_project_from_tasks(client, ["some-task-name"]) is None

    def test_empty_returns_none(self) -> None:
        client, _api = _fake_client()
        assert infer_project_from_tasks(client, []) is None

    def test_skips_names_until_numeric(self) -> None:
        client, _api = _fake_client()
        assert infer_project_from_tasks(client, ["task-name", "42"]) == 1

    def test_task_without_project_raises(self) -> None:
        api = FakeCvatApi.from_tasks([make_task(42)])
        api.get_task = _get_task_without_project  # type: ignore[method-assign]
        client = CvatClient(CvatConfig(), api=api)
        with pytest.raises(Cveta2Error, match="не принадлежит"):
            infer_project_from_tasks(client, [42])


def _get_task_without_project(task_id: int) -> TaskInfo:
    return make_task(task_id)
