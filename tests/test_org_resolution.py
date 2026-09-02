"""Tests for ORG/PROJECT spec parsing, org switching and project inference."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from cveta2.client import CvatClient
from cveta2.commands._helpers import resolve_project_from_args
from cveta2.config import CvatConfig
from cveta2.exceptions import Cveta2Error
from cveta2.models import ProjectInfo

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

    @pytest.mark.parametrize("spec", [1, "1", " 1 "], ids=["int", "digits", "padded"])
    def test_numeric_spec_looks_the_name_up(self, spec: int | str) -> None:
        """A numeric spec resolves to the matching project's name.

        Two projects are required: with only one in the fake, ``p.id ==
        project_id`` and ``p.id != project_id`` both yield that project's name,
        so the lookup cannot be distinguished from "take whatever is first".
        """
        api = FakeCvatApi.from_tasks(
            [make_task(42)],
            project_name="alpha",
            other_projects=[ProjectInfo(id=2, name="beta")],
        )
        client = CvatClient(CvatConfig(), api=api)

        assert resolve_project_spec(client, spec) == (1, "alpha")

    def test_numeric_spec_falls_back_to_the_id_as_name(self) -> None:
        """An id nobody owns still yields a usable name, not None.

        Reading the project raises rather than answering, and the id has to
        stand in: the name reaches log lines, the task-cache directory and
        the ignore-list key, so "None" there would be shown to the user.
        """
        api = FakeCvatApi.from_tasks([make_task(42)], project_name="alpha")
        client = CvatClient(CvatConfig(), api=api)

        assert resolve_project_spec(client, 999) == (999, "999")

    def test_a_project_with_no_name_falls_back_to_the_id(self) -> None:
        """An unnamed project is the same problem as an unreadable one."""
        api = FakeCvatApi.from_tasks([make_task(42)], project_name="")
        client = CvatClient(CvatConfig(), api=api)

        assert resolve_project_spec(client, 1) == (1, "1")

    @pytest.mark.parametrize("spec", ["beta", " BETA "], ids=["exact", "cased"])
    def test_name_spec_returns_the_canonical_cvat_spelling(self, spec: str) -> None:
        """A name resolves to the matching project *and* CVAT's spelling of it.

        The name lookup is case-insensitive, so the name that keys the ignore
        list, the image-cache directory and the ClearML dataset must be the
        one CVAT holds — not whatever the caller typed.  Two projects keep
        the lookup distinguishable from "take whatever is first".
        """
        api = FakeCvatApi.from_tasks(
            [make_task(42)],
            project_name="alpha",
            other_projects=[ProjectInfo(id=2, name="beta")],
        )
        client = CvatClient(CvatConfig(), api=api)

        assert resolve_project_spec(client, spec) == (2, "beta")

    def test_name_spec_is_matched_against_the_cache_first(self) -> None:
        """A cached entry answers the name lookup without a listing request.

        The cache says 77 where the server says 1, and the cached spelling
        is the one returned, so dropping ``cached=`` on the way to the client
        is visible in both halves of the result.
        """
        client, api = _fake_client(project_name="alpha")
        cached = [ProjectInfo(id=77, name="Alpha")]

        assert resolve_project_spec(client, "ALPHA", cached=cached) == (77, "Alpha")
        assert api.call_counts["list_projects"] == 0

    def test_numeric_spec_is_named_from_the_cache_before_cvat(self) -> None:
        """A cached entry with the matching id names the project without a request."""
        client, api = _fake_client(project_name="alpha")
        cached = [ProjectInfo(id=2, name="beta"), ProjectInfo(id=1, name="Alpha")]

        assert resolve_project_spec(client, "1", cached=cached) == (1, "Alpha")
        assert api.call_counts["get_project"] == 0

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

    def test_only_the_first_slash_separates_the_org(self) -> None:
        """A project name containing a slash must not be split a second time.

        The helper switches the org before loading the cache and then hands
        the bare spec down; resolving ``acme/al/pha`` must switch to ``acme``
        exactly once and look up ``al/pha``, never org ``al`` / project ``pha``.
        """
        client, api = _fake_client(project_name="al/pha", organization="default-org")
        with patch("cveta2.commands._helpers.load_projects_cache", return_value=[]):
            assert resolve_project_from_args(client, "acme/al/pha") == (1, "al/pha")
        assert api.organization_calls == ["acme"]


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
