"""Tests for :mod:`cveta2.commands._helpers` — the shared CLI adapters."""

from __future__ import annotations

import argparse
import re
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from cveta2.client import CvatClient
from cveta2.commands._helpers import (
    config_path_from_args,
    project_cli_spec,
    require_host,
    resolve_project,
    resolve_project_and_cloud_storage,
    resolve_project_from_args,
)
from cveta2.config import CvatConfig
from cveta2.exceptions import MissingHostError
from cveta2.models import ProjectInfo
from tests.fixtures.fake_cvat_api import FakeCvatApi
from tests.helpers import make_cs_info, make_task

if TYPE_CHECKING:
    from pathlib import Path

_LOAD_CACHE = "cveta2.commands._helpers.load_projects_cache"


def _client(organization: str | None = None) -> CvatClient:
    api = FakeCvatApi.from_tasks([make_task(42)], project_name="alpha")
    return CvatClient(CvatConfig(organization=organization), api=api)


class TestConfigPathFromArgs:
    def test_config_flag_wins(self, tmp_path: Path) -> None:
        args = argparse.Namespace(config=str(tmp_path / "custom.yaml"))
        assert config_path_from_args(args) == tmp_path / "custom.yaml"

    def test_absent_flag_falls_back_to_the_default_path(
        self, isolated_config_path: Path
    ) -> None:
        """Commands that never declare ``--config`` must still resolve.

        The lookup goes through ``getattr(args, "config", None)``: dropping
        the default turns the absent attribute into an ``AttributeError``,
        and mutating the attribute name silently ignores a real ``--config``.
        """
        assert config_path_from_args(argparse.Namespace()) == isolated_config_path


class TestRequireHost:
    def test_configured_host_passes(self) -> None:
        require_host(CvatConfig(host="http://localhost:8080"))

    def test_missing_host_error_names_the_config_file(
        self, isolated_config_path: Path
    ) -> None:
        """The error has to say which file to edit.

        Both mutants of the raise — ``MissingHostError(None)`` and
        ``format(config_path=None)`` — still raise, but drop the one piece
        of actionable information the message carries.
        """
        with pytest.raises(
            MissingHostError, match=re.escape(str(isolated_config_path))
        ):
            require_host(CvatConfig())


class TestResolveProjectFromArgs:
    @pytest.mark.parametrize("spec", [None, "", "   "])
    def test_blank_spec_defers_to_the_caller(self, spec: str | None) -> None:
        """A blank spec returns ``None`` so the caller can prompt.

        The guard is ``not spec or not spec.strip()``; turning that ``or``
        into an ``and`` makes ``None.strip()`` raise before the function
        can bow out.
        """
        assert resolve_project_from_args(_client(), spec) is None

    def test_name_spec_is_resolved_against_the_cache(self) -> None:
        """The loaded cache must reach ``resolve_project_id``.

        Passing ``cached=None`` (or dropping the keyword) still resolves —
        by falling through to a live ``list_projects`` call — so the two
        only differ when the cache and the server disagree. Here the fake
        server calls this project 1 and the cache calls it 77.
        """
        cached = [ProjectInfo(id=77, name="alpha")]
        with patch(_LOAD_CACHE, return_value=cached):
            assert resolve_project_from_args(_client(), "alpha") == (77, "alpha")

    def test_numeric_spec_takes_its_name_from_the_matching_entry(self) -> None:
        """A numeric spec is named by the cache entry with *that* id.

        Pins the ``p.id == project_id`` scan: inverting it names the
        project after the first non-matching entry, nulling the assignment
        yields ``(5, None)``, and returning instead of breaking drops the
        result entirely.
        """
        cached = [ProjectInfo(id=4, name="beta"), ProjectInfo(id=5, name="gamma")]
        with patch(_LOAD_CACHE, return_value=cached):
            assert resolve_project_from_args(_client(), "5") == (5, "gamma")

    def test_numeric_spec_keeps_the_id_when_the_cache_is_silent(self) -> None:
        with patch(_LOAD_CACHE, return_value=[]):
            assert resolve_project_from_args(_client(), "5") == (5, "5")


class TestResolveProject:
    def test_falls_back_to_the_picker_with_the_session_client(self) -> None:
        """The interactive picker needs the very client that was opened.

        ``select_project(None)`` would page projects off a fresh, unbound
        client instead of the caller's session (and its organization).
        """
        client = _client()

        def _pick(picker_client: CvatClient) -> tuple[int, str]:
            return (9, "picked") if picker_client is client else (0, "wrong")

        with patch("cveta2.commands._helpers.select_project", side_effect=_pick):
            assert resolve_project(client, None) == (9, "picked")

    def test_explicit_spec_skips_the_picker(self) -> None:
        with (
            patch(_LOAD_CACHE, return_value=[]),
            patch("cveta2.commands._helpers.select_project") as picker,
        ):
            assert resolve_project(_client(), "alpha") == (1, "alpha")
        picker.assert_not_called()


class TestResolveProjectAndCloudStorage:
    def test_cloud_storage_is_detected_for_the_resolved_project(self) -> None:
        """The resolved id must be the one passed to CVAT.

        A mock answers every id, so ``detect_project_cloud_storage(None)``
        returns a perfectly plausible bucket; keying the fake on the id is
        what makes the difference visible.
        """
        client = MagicMock()
        client.detect_project_cloud_storage.side_effect = lambda project_id: (
            make_cs_info(bucket="right") if project_id == 7 else make_cs_info()
        )
        with patch(
            "cveta2.commands._helpers.resolve_project", return_value=(7, "proj")
        ):
            project_id, name, cs_info = resolve_project_and_cloud_storage(
                client, "proj"
            )

        assert (project_id, name) == (7, "proj")
        assert cs_info is not None
        assert cs_info.bucket == "right"


class TestProjectCliSpec:
    def test_default_org_is_not_prefixed(self) -> None:
        client = _client(organization="acme")
        assert project_cli_spec(client, "alpha") == "alpha"

    def test_switched_org_is_prefixed(self) -> None:
        client = _client(organization="acme")
        client.set_organization("other")
        assert project_cli_spec(client, "alpha") == "other/alpha"

    def test_personal_workspace_renders_as_a_bare_slash(self) -> None:
        """Switching away from a configured org to the personal workspace.

        ``/alpha`` is how the CLI spells "personal workspace", and it is
        the one prefixed form where the org part is empty.
        """
        client = _client(organization="acme")
        client.set_organization(None)
        assert project_cli_spec(client, "alpha") == "/alpha"
