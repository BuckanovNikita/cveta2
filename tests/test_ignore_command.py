"""Behavioural coverage for ``cveta2 ignore``.

The command re-implements add/remove over ``IgnoreConfig`` rather than
delegating to ``api.ignore``, so the two can drift; these tests pin the
command's own behaviour, including the remove-miss warning that the api
layer does not emit.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from cveta2.commands.ignore import run_ignore
from cveta2.config import IgnoreConfig
from cveta2.exceptions import TaskNotFoundError
from tests.fixtures.fake_cvat_api import FakeCvatApi
from tests.helpers import (
    CFG,
    build_fake,
    client_with_api,
    parse_cli_args,
    patch_cli_client,
)

if TYPE_CHECKING:
    from cveta2.client import CvatClient
    from cveta2.config import CvatConfig
    from tests.fixtures.fake_cvat_project import LoadedFixtures

_LIST_PROJECT = "coco8-dev"


@pytest.fixture
def fake(coco8_fixtures: LoadedFixtures) -> LoadedFixtures:
    return build_fake(coco8_fixtures, ["normal"], statuses=["completed"])


def _run(fake: LoadedFixtures, *argv: str) -> None:
    """Dispatch ``cveta2 ignore -p <project>`` against a fake-backed client."""
    client = client_with_api(FakeCvatApi(fake))

    def make_client(_cfg: CvatConfig, **_kw: object) -> CvatClient:
        return client

    args = parse_cli_args("ignore", "-p", fake.project.name, *argv)
    with patch_cli_client(factory=make_client, config=CFG):
        run_ignore(args)


class TestAdd:
    def test_add_persists_every_field(self, fake: LoadedFixtures) -> None:
        task = fake.tasks[0]

        _run(fake, "--add", str(task.id), "--description", "дубликаты", "--silent")

        entries = IgnoreConfig.load().get_ignored_entries(fake.project.name)
        assert [(e.id, e.name, e.description, e.silent) for e in entries] == [
            (task.id, task.name, "дубликаты", True)
        ]

    def test_add_defaults_are_not_silent_and_carry_no_description(
        self, fake: LoadedFixtures
    ) -> None:
        _run(fake, "--add", str(fake.tasks[0].id))

        entry = IgnoreConfig.load().get_ignored_entries(fake.project.name)[0]
        assert (entry.description, entry.silent) == ("", False)

    def test_re_adding_an_ignored_task_warns_and_changes_nothing(
        self, fake: LoadedFixtures, capture_logs: list[str]
    ) -> None:
        """``--add 456 --silent`` on an already-ignored task used to claim success.

        The entry stayed loud and the per-fetch warning kept firing; the user
        must be told the flags were not applied and how to apply them.
        """
        task = fake.tasks[0]
        _run(fake, "--add", str(task.id))

        _run(fake, "--add", str(task.id), "--silent", "--description", "шум")

        assert any("уже в ignore-списке" in line for line in capture_logs)
        entries = IgnoreConfig.load().get_ignored_entries(fake.project.name)
        assert [(e.id, e.description, e.silent) for e in entries] == [
            (task.id, "", False)
        ]

    def test_a_task_can_be_named_instead_of_numbered(
        self, fake: LoadedFixtures
    ) -> None:
        task = fake.tasks[0]

        _run(fake, "--add", task.name)

        assert IgnoreConfig.load().get_ignored_tasks(fake.project.name) == [task.id]

    def test_an_unknown_selector_is_rejected_before_anything_is_written(
        self, fake: LoadedFixtures
    ) -> None:
        with pytest.raises(TaskNotFoundError):
            _run(fake, "--add", "no-such-task")

        assert IgnoreConfig.load().get_ignored_entries(fake.project.name) == []


class TestRemove:
    def test_remove_drops_only_the_named_entry(self, fake: LoadedFixtures) -> None:
        task = fake.tasks[0]
        cfg = IgnoreConfig.load()
        cfg.add_task(fake.project.name, task.id, task.name)
        cfg.add_task(fake.project.name, 9999, "оставить")
        cfg.save()

        _run(fake, "--remove", str(task.id))

        assert IgnoreConfig.load().get_ignored_tasks(fake.project.name) == [9999]

    def test_removing_a_task_that_was_never_ignored_warns(
        self,
        fake: LoadedFixtures,
        capture_logs: list[str],
    ) -> None:
        """The api layer stays silent here; the command deliberately does not."""
        _run(fake, "--remove", str(fake.tasks[0].id))

        assert any("не найдена" in line for line in capture_logs)


class TestList:
    def test_list_reports_entries_without_opening_a_client(
        self, capture_info_logs: list[str]
    ) -> None:
        cfg = IgnoreConfig.load()
        cfg.add_task(_LIST_PROJECT, 7, "Партия 3", "дубликаты")
        cfg.save()

        args = parse_cli_args("ignore", "--list")
        with patch("cveta2.commands._bootstrap.CvatClient") as client_cls:
            run_ignore(args)

        client_cls.assert_not_called()
        assert any("Партия 3" in line for line in capture_info_logs)

    def test_an_empty_config_says_so(self, capture_info_logs: list[str]) -> None:
        run_ignore(parse_cli_args("ignore", "--list"))

        assert any("пусты" in line for line in capture_info_logs)
