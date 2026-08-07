"""Connection lifecycle contract for ``_ClientBase``.

Every other unit test injects a ready-made port via ``api=``, which is
exactly the branch ``__enter__`` short-circuits.  The rest of the class --
the ``client_factory`` seam, the ``ExitStack`` that owns the connection and
the exception forwarded on the way out -- therefore ran only under the
integration suite, so a fake factory here is the first thing that pins it.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Literal, NoReturn
from unittest.mock import MagicMock

import pytest

from cveta2._client.dtos import RawDataMeta, RawFrame, RawJob
from cveta2._client.ports import CvatApiPort
from cveta2._client.sdk_adapter import SdkCvatApiAdapter
from cveta2.client import CvatClient
from cveta2.models import LabelInfo
from tests.helpers import CFG, client_with_api, csv_row, make_df

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import TracebackType


class _RecordingSdkCm:
    """Stand-in for the context manager ``cvat_sdk.make_client`` returns.

    Records the ``(exc_type, exc_val, exc_tb)`` triple that reaches it
    through the ``ExitStack``, which is the only place ``__exit__``'s
    forwarding is observable from outside the client.
    """

    def __init__(self) -> None:
        self.sdk_client = object()
        self.exits: list[tuple[object, object, object]] = []

    def __enter__(self) -> object:
        return self.sdk_client

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> Literal[False]:
        self.exits.append((exc_type, exc_val, exc_tb))
        return False


class _RecordingFactory:
    """``SdkClientFactory`` stub recording the kwargs of every call."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.cm = _RecordingSdkCm()

    def __call__(self, **kwargs: Any) -> _RecordingSdkCm:
        self.calls.append(kwargs)
        return self.cm


@pytest.fixture(autouse=True)
def _forbid_the_real_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    """Turn the default SDK factory into an immediate error.

    Several mutations drop ``self._client_factory`` from the
    ``open_sdk_api`` call, and ``open_sdk_api`` then falls back to the real
    ``cvat_sdk.make_client``.  Left alone that tries to reach the config's
    host, so the mutant would be recorded as a timeout instead of a kill --
    and the suite would depend on a DNS failure for its speed.
    """

    def _explode(**_kwargs: Any) -> NoReturn:
        msg = "the injected client_factory must be the one used"
        raise AssertionError(msg)

    monkeypatch.setattr("cveta2._client.connection.make_client", _explode)


def _client() -> tuple[CvatClient, _RecordingFactory]:
    """Build a client wired to a recording factory instead of the real SDK."""
    factory = _RecordingFactory()
    return CvatClient(CFG, factory), factory


class TestConnectionLifecycle:
    """Enter opens exactly one connection; exit closes it exactly once."""

    def test_enter_opens_one_connection_through_the_injected_factory(self) -> None:
        """The factory stored in ``__init__`` is what ``__enter__`` must use.

        Nothing asserted that ``client_factory`` survived construction or
        reached ``open_sdk_api``, so dropping it, passing it as the config,
        or passing the config as ``None`` all left the tests green while
        silently falling back to a real network client.
        """
        client, factory = _client()

        with client as entered:
            assert entered is client
            assert client.is_ready
            api = client.api
            assert isinstance(api, SdkCvatApiAdapter)
            assert api.client is factory.cm.sdk_client

        assert len(factory.calls) == 1
        assert factory.calls[0] == {
            "host": CFG.host,
            "credentials": (CFG.username, CFG.password),
        }

    def test_injected_api_short_circuits_the_factory(self) -> None:
        """``api=`` means "already connected" -- no SDK client may be opened.

        The DI guard is what every other unit test relies on, yet none of
        them owns a factory that could notice it being called anyway.
        """
        injected = MagicMock(spec=CvatApiPort)
        factory = _RecordingFactory()
        client = CvatClient(CFG, factory, api=injected)

        with client as entered:
            assert entered.api is injected

        assert factory.calls == []
        assert factory.cm.exits == []

    def test_exit_closes_the_connection_once_and_only_once(self) -> None:
        """The stack swap in ``__exit__`` is what makes a second exit a no-op.

        Without it a re-entrant or duplicated ``__exit__`` would close the
        same SDK client twice; nothing pinned either the single close or
        the idempotence.
        """
        client, factory = _client()

        with client:
            pass

        assert len(factory.cm.exits) == 1
        assert client.is_ready is False

        client.__exit__(None, None, None)

        assert len(factory.cm.exits) == 1

    def test_operation_after_the_block_asks_for_a_new_context(self) -> None:
        """Leaving the block must clear the port, not merely falsify it.

        ``_persistent_api`` is read through ``or``, so any falsy value keeps
        ``_require_api`` from raising and the caller gets an
        ``AttributeError`` from a stale handle instead of the actionable
        "requires a context manager" message.
        """
        client, _factory = _client()

        with client:
            pass

        with pytest.raises(RuntimeError, match=r"list_projects\(\) requires"):
            client.list_projects()

    def test_exit_forwards_the_original_exception_to_the_sdk_client(self) -> None:
        """A failure inside the block must reach the SDK client unaltered.

        ``ExitStack`` hands the triple to the ``open_sdk_api`` generator,
        which throws it in; blanking ``exc_type`` unwinds as a clean exit
        and blanking ``exc_val`` makes contextlib synthesise a *different*
        exception instance, so the SDK sees a success or the wrong error.
        """
        client, factory = _client()
        boom = ValueError("boom")

        with pytest.raises(ValueError, match="boom"), client:
            raise boom

        exc_type, exc_val, exc_tb = factory.cm.exits[0]
        assert exc_type is ValueError
        assert exc_val is boom
        assert exc_tb is not None


_CONTEXT_REQUIRED_OPS: list[tuple[str, Callable[[CvatClient], object]]] = [
    ("set_organization", lambda c: c.set_organization("acme")),
    ("open_task_session", lambda c: c.open_task_session(7)),
]


@pytest.mark.parametrize(
    ("operation", "call"),
    _CONTEXT_REQUIRED_OPS,
    ids=[name for name, _ in _CONTEXT_REQUIRED_OPS],
)
def test_operation_outside_context_manager_names_itself(
    operation: str,
    call: Callable[[CvatClient], object],
) -> None:
    """The literal each method hands ``_require_api`` must be its own name.

    Both strings only ever reach this error message, so nothing separated
    ``"set_organization"`` from ``None`` or ``"SET_ORGANIZATION"`` -- the
    user would be told to wrap a call they never made.
    """
    client = CvatClient(CFG)

    expected = re.escape(f"{operation}() requires a context manager")
    with pytest.raises(RuntimeError, match=expected):
        call(client)


class TestTaskWriteSessionReuse:
    """``open_task_session`` exists to make one write chain fetch metadata once."""

    @staticmethod
    def _api() -> MagicMock:
        api = MagicMock(spec=CvatApiPort)
        api.get_task_data_meta.return_value = RawDataMeta(
            frames=[RawFrame(name="a.jpg", width=640, height=480)]
        )
        api.get_task_labels.return_value = [LabelInfo(id=9, name="cat")]
        api.get_task_jobs.return_value = [RawJob(id=3, start_frame=0, stop_frame=0)]
        return api

    def test_session_binds_the_requested_task(self) -> None:
        """A session must carry the caller's task id, not a default.

        Everything downstream reads ``session.task_id``, so a session built
        for the wrong task would silently write to it.
        """
        api = self._api()

        session = client_with_api(api).open_task_session(41)

        assert session.task_id == 41
        assert session.api is api

    def test_one_write_chain_fetches_task_metadata_once(self) -> None:
        """Reusing a session is the whole point of ``open_task_session``.

        Annotations, issues and deleted frames each need ``data_meta``.
        Nothing asserted the session actually memoises it, so a regression
        would cost one extra CVAT round-trip per write op and ship silently.
        """
        api = self._api()
        client = client_with_api(api)
        df = make_df([csv_row("a.jpg", issue_state="new", issue_text="fix me")])

        session = client.open_task_session(5)
        client.upload_task_annotations(5, df, session=session)
        client.create_task_issues(5, df, session=session)
        client.mark_frames_deleted(5, {"a.jpg"}, session=session)

        assert api.get_task_data_meta.call_count == 1
        assert api.get_task_labels.call_count == 1
        assert api.get_task_jobs.call_count == 1
