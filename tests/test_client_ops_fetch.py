"""Tests for the ``_FetchMixin`` decision logic (``cveta2/_client_ops/fetch.py``).

Covers the pieces that decide *which* tasks reach the dataset and *what*
the prepared :class:`FetchContext` carries -- both invisible to the
end-to-end fetch scenarios, which only ever run one filter combination.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from cveta2._client.dtos import (
    RawAnnotations,
    RawAttribute,
    RawDataMeta,
    RawFrame,
)
from cveta2._client_ops.shared import FetchContext
from cveta2.client import CvatClient
from cveta2.config import CvatConfig
from cveta2.exceptions import CvatApiError, Cveta2Error, TaskNotFoundError
from cveta2.models import (
    BBoxAnnotation,
    LabelAttributeInfo,
    LabelInfo,
    ProjectInfo,
    TaskInfo,
)
from tests.fixtures.fake_cvat_api import FakeCvatApi
from tests.fixtures.fake_cvat_project import LoadedFixtures
from tests.helpers import make_raw_shape, make_task

if TYPE_CHECKING:
    from collections.abc import Sequence

_HOST = "https://cvat.example"

_LABELS = [
    LabelInfo(
        id=7,
        name="car",
        attributes=[LabelAttributeInfo(id=70, name="colour")],
    ),
]


def _fixtures(
    tasks: Sequence[TaskInfo],
    task_data: dict[int, tuple[RawDataMeta, RawAnnotations]] | None = None,
) -> LoadedFixtures:
    """Build a one-project fixture set with one attribute-bearing label."""
    return LoadedFixtures(
        project=ProjectInfo(id=1, name="proj"),
        tasks=list(tasks),
        labels=_LABELS,
        task_data=task_data or {},
    )


def _client(fixtures: LoadedFixtures, *, host: str = "") -> CvatClient:
    return CvatClient(CvatConfig(host=host), api=FakeCvatApi(fixtures))


# ---------------------------------------------------------------------------
# prepare_fetch: the FetchContext it returns
# ---------------------------------------------------------------------------


class TestPrepareFetchContext:
    """Every field of the returned ``FetchContext`` is a caller contract."""

    def test_context_carries_labels_host_and_project_name(self) -> None:
        """The context fields are read much later, in unrelated call sites.

        ``attr_names`` is only touched by shapes that carry attributes,
        and ``host``/``project_name`` only by the 5xx skip diagnostic, so
        nulling or dropping any of the three left every fetch test green.
        """
        client = _client(_fixtures([make_task(1)]), host=_HOST)

        ctx = client.prepare_fetch(1, project_name="my-project")

        assert [t.id for t in ctx.tasks] == [1]
        assert ctx.label_names == {7: "car"}
        assert ctx.attr_names == {70: "colour"}
        assert ctx.host == _HOST
        assert ctx.project_name == "my-project"
        assert ctx.raise_on_failure is False

    def test_context_defaults_to_empty_host_and_project_name(self) -> None:
        """Unset host and omitted project name must both render as ``""``.

        Nothing else pins the *default* of ``project_name``; a fetch with
        no project name behaves identically whatever placeholder it holds
        until a task 5xxs.
        """
        ctx = _client(_fixtures([make_task(1)])).prepare_fetch(1)

        assert ctx.host == ""
        assert ctx.project_name == ""

    def test_completed_only_reaches_the_filter(self) -> None:
        """``completed_only`` is forwarded through an options dataclass.

        Dropping it (or passing ``None``) falls back to the dataclass
        default ``False``, which only shows up when the project holds a
        task that is *not* completed.
        """
        tasks = [
            make_task(1, status="completed"),
            make_task(2, status="annotation"),
            make_task(3, status="completed"),
        ]
        client = _client(_fixtures(tasks))

        ctx = client.prepare_fetch(1, completed_only=True)

        assert [t.id for t in ctx.tasks] == [1, 3]

    def test_ignore_task_ids_reaches_the_filter(self) -> None:
        """Same forwarding hazard as ``completed_only``, opposite default."""
        tasks = [make_task(1), make_task(2), make_task(3)]
        client = _client(_fixtures(tasks))

        ctx = client.prepare_fetch(1, ignore_task_ids={2})

        assert [t.id for t in ctx.tasks] == [1, 3]

    def test_silent_task_ids_reaches_the_filter(
        self,
        capture_logs: list[str],
    ) -> None:
        """A silenced ignore is only observable as an *absent* warning.

        ``silent_task_ids`` changes nothing about which tasks are fetched,
        so dropping it from the options left the task list identical and
        merely re-introduced the warning the flag exists to suppress.
        """
        tasks = [make_task(1), make_task(2)]
        client = _client(_fixtures(tasks))

        ctx = client.prepare_fetch(1, ignore_task_ids={2}, silent_task_ids={2})

        assert [t.id for t in ctx.tasks] == [1]
        assert not any("Пропускаем" in message for message in capture_logs)

    def test_non_silent_ignore_still_warns(self, capture_logs: list[str]) -> None:
        """Counterpart to the silent case: without the flag, the warning fires."""
        tasks = [make_task(1), make_task(2)]
        client = _client(_fixtures(tasks))

        client.prepare_fetch(1, ignore_task_ids={2})

        assert any("Пропускаем" in message for message in capture_logs)


# ---------------------------------------------------------------------------
# resolve_task_selectors
# ---------------------------------------------------------------------------


class TestResolveTaskSelectors:
    """Selector precedence, cross-selector dedup and the not-found message."""

    def test_one_task_reached_by_id_and_by_name_yields_one_result(self) -> None:
        """The ``seen_ids`` dedup was removable without failing a test.

        Every existing caller passes selectors that each match a distinct
        task, so a set that never accumulates anything looks identical to
        one that does.
        """
        tasks = [make_task(5, name="task-five"), make_task(6, name="other")]

        matched = CvatClient.resolve_task_selectors(tasks, ["5", "task-five"])

        assert [t.id for t in matched] == [5]

    def test_numeric_selector_prefers_id_over_name(self) -> None:
        """A digit selector is an id first: names that look like ids lose."""
        tasks = [make_task(9, name="5"), make_task(5, name="five")]

        matched = CvatClient.resolve_task_selectors(tasks, ["5"])

        assert [t.id for t in matched] == [5]

    def test_numeric_selector_falls_back_to_name(self) -> None:
        """With no id match, a digit selector still matches a task named so."""
        tasks = [make_task(9, name="5"), make_task(8, name="eight")]

        matched = CvatClient.resolve_task_selectors(tasks, ["5"])

        assert [t.id for t in matched] == [9]

    def test_name_match_is_case_insensitive(self) -> None:
        tasks = [make_task(1, name="Alpha")]

        matched = CvatClient.resolve_task_selectors(tasks, ["ALPHA"])

        assert [t.id for t in matched] == [1]

    def test_not_found_message_lists_every_available_task(self) -> None:
        """The whole rendered message is asserted, separators included.

        It is the only output a user gets when a ``-t`` value is wrong,
        and every part of it -- the quoted selector, the comma-space
        separator, each ``'name' (id=N)`` pair -- was unpinned.
        """
        tasks = [make_task(1, name="alpha"), make_task(2, name="beta")]

        with pytest.raises(TaskNotFoundError) as exc_info:
            CvatClient.resolve_task_selectors(tasks, ["ghost"])

        assert str(exc_info.value) == (
            "Task not found: 'ghost'. Available tasks: 'alpha' (id=1), 'beta' (id=2)"
        )


# ---------------------------------------------------------------------------
# fetch_one_task
# ---------------------------------------------------------------------------


def _annotated_task_fixtures() -> tuple[TaskInfo, LoadedFixtures]:
    """One completed task with a single attribute-carrying rectangle."""
    task = make_task(1, name="task-1")
    shape = make_raw_shape(
        label_id=7,
        attributes=[RawAttribute(spec_id=70, value="red")],
    )
    data_meta = RawDataMeta(frames=[RawFrame(name="a.jpg", width=640, height=480)])
    return task, _fixtures(
        [task],
        {task.id: (data_meta, RawAnnotations(shapes=[shape]))},
    )


class TestFetchOneTask:
    """The 5xx status window and the label/attribute maps it is handed."""

    def test_attribute_names_come_from_the_context(self) -> None:
        """No coco8 fixture label declares an attribute.

        ``ctx.attr_names`` was therefore never read, and handing
        ``task_to_records`` a null map instead changed nothing.
        """
        task, fixtures = _annotated_task_fixtures()
        client = _client(fixtures)
        ctx = client.prepare_fetch(1)

        result = CvatClient.fetch_one_task(client.api, task, ctx)

        assert result is not None
        annotation = result.annotations[0]
        assert isinstance(annotation, BBoxAnnotation)
        assert annotation.instance_label == "car"
        assert annotation.attributes == {"colour": "red"}

    def test_status_600_is_outside_the_skip_window(self) -> None:
        """600 is the exclusive upper bound of the "server error" range.

        Every other 5xx test uses 500, which cannot tell ``< 600`` from
        ``<= 600``; only a status *on* the bound decides whether an
        unknown error is swallowed as a skip or re-raised.
        """
        task, fixtures = _annotated_task_fixtures()
        api = FakeCvatApi(fixtures, fail_task_ids={task.id}, fail_status=600)
        ctx = FetchContext(tasks=[task], label_names={}, attr_names={})

        with pytest.raises(CvatApiError):
            CvatClient.fetch_one_task(api, task, ctx)

    def test_status_599_is_skipped(self) -> None:
        """Counterpart to the 600 case: the last in-window status still skips."""
        task, fixtures = _annotated_task_fixtures()
        api = FakeCvatApi(fixtures, fail_task_ids={task.id}, fail_status=599)
        ctx = FetchContext(tasks=[task], label_names={}, attr_names={})

        assert CvatClient.fetch_one_task(api, task, ctx) is None

    def test_rate_limiting_aborts_instead_of_skipping_the_task(self) -> None:
        """A 429 here means the retry budget is already spent.

        Skipping would drop the task from the merged dataset for a reason
        that has nothing to do with its contents, and the only trace would
        be a log line — so the run stops instead.
        """
        task, fixtures = _annotated_task_fixtures()
        api = FakeCvatApi(fixtures, fail_task_ids={task.id}, fail_status=429)
        ctx = FetchContext(tasks=[task], label_names={}, attr_names={})

        with pytest.raises(Cveta2Error, match="cvat_workers"):
            CvatClient.fetch_one_task(api, task, ctx)

    def test_rate_limiting_aborts_even_when_failures_are_tolerated(self) -> None:
        """``raise_on_failure`` is off by default and must not soften a 429."""
        task, fixtures = _annotated_task_fixtures()
        api = FakeCvatApi(fixtures, fail_task_ids={task.id}, fail_status=429)
        ctx = FetchContext(
            tasks=[task], label_names={}, attr_names={}, raise_on_failure=False
        )

        with pytest.raises(Cveta2Error):
            CvatClient.fetch_one_task(api, task, ctx)
