"""Connection lifecycle contract for ``_ClientBase``.

Every other unit test injects a ready-made port via ``api=``, which is
exactly the branch ``__enter__`` short-circuits.  The rest of the class --
the ``client_factory`` seam, the ``ExitStack`` that owns the connection and
the exception forwarded on the way out -- therefore ran only under the
integration suite, so a fake factory here is the first thing that pins it.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from types import TracebackType
from typing import Any, Literal, NoReturn
from unittest.mock import MagicMock

import pytest
import urllib3
import urllib3.exceptions
from cvat_sdk.api_client.exceptions import ApiException

from cveta2.adapters.cvat.sdk_adapter import SdkCvatApiAdapter
from cveta2.application.ports.cvat import CvatApiPort
from cveta2.application.ports.dtos import RawDataMeta, RawFrame, RawJob
from cveta2.composition.client import CvatClient
from cveta2.domain.errors import CvatApiError
from cveta2.domain.models import LabelInfo
from tests.helpers import CFG, client_with_api, csv_row, make_df


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

    A client that ignored its injected factory would otherwise try to reach
    the config's host through the real ``cvat_sdk.make_client``.
    """

    def _explode(**_kwargs: Any) -> NoReturn:
        msg = "the injected client_factory must be the one used"
        raise AssertionError(msg)

    monkeypatch.setattr("cveta2.adapters.cvat.connection.make_client", _explode)


def _client() -> tuple[CvatClient, _RecordingFactory]:
    """Build a client wired to a recording factory instead of the real SDK."""
    factory = _RecordingFactory()
    return CvatClient(CFG, factory), factory


class TestConnectionLifecycle:
    """Enter opens exactly one connection; exit closes it exactly once."""

    def test_enter_opens_one_connection_through_the_injected_factory(self) -> None:
        """The factory stored in ``__init__`` is what ``__enter__`` must use."""
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

    @pytest.mark.parametrize(
        "timeout",
        [30.0, None, 0.0],
        ids=["value", "none_clears", "zero_clears"],
    )
    def test_enter_installs_the_request_timeout_before_the_factory_runs(
        self, monkeypatch: pytest.MonkeyPatch, timeout: float | None
    ) -> None:
        """The SDK timeout must be process-wide and in place before login.

        ``make_client`` logs in and checks the server version inside the
        factory call, so a timeout installed on the opened client would
        leave that window free to hang forever.  The value goes through
        verbatim -- ``None`` and ``0`` must clear a previous run's timeout,
        not keep it.
        """
        factory = _RecordingFactory()
        installs: list[tuple[float | None, int]] = []
        monkeypatch.setattr(
            "cveta2.adapters.cvat.connection.install_global_request_timeout",
            lambda value: installs.append((value, len(factory.calls))),
        )
        cfg = CFG.model_copy(update={"request_timeout": timeout})

        with CvatClient(cfg, factory):
            pass

        assert installs == [(timeout, 0)]
        assert len(factory.calls) == 1

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
        assert client.is_ready

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


def _failing_factory(boom: BaseException) -> Callable[..., NoReturn]:
    """Build an ``SdkClientFactory`` whose ``make_client`` step fails with *boom*."""

    def factory(**_kwargs: Any) -> NoReturn:
        raise boom

    return factory


class TestConnectionFailures:
    """Login and transport errors from ``make_client`` must leave as ``CvatApiError``.

    ``make_client`` performs the server-about request and the login inside
    the factory call, where no adapter method wraps it. ``cli._run_command``
    catches only ``Cveta2Error``, so a wrong password or an unreachable host
    used to print a traceback instead of the clean exit message.
    """

    def test_a_rejected_login_keeps_its_status_code(self) -> None:
        boom = ApiException(status=401, reason="Unauthorized")

        with (
            pytest.raises(CvatApiError) as caught,
            CvatClient(CFG, _failing_factory(boom)),
        ):
            pass

        assert caught.value.status_code == 401
        assert caught.value.__cause__ is boom

    @pytest.mark.parametrize(
        "boom",
        [
            urllib3.exceptions.MaxRetryError(
                urllib3.HTTPConnectionPool("cvat.example"),
                "/api/server/about",
                ConnectionRefusedError("boom"),
            ),
            OSError("connection refused"),
        ],
        ids=["urllib3", "oserror"],
    )
    def test_an_unreachable_host_names_itself(self, boom: BaseException) -> None:
        """The host is the actionable half of a connection failure."""
        with (
            pytest.raises(CvatApiError) as caught,
            CvatClient(CFG, _failing_factory(boom)),
        ):
            pass

        assert str(caught.value) == f"Не удалось подключиться к CVAT ({CFG.host}): {boom}"
        assert caught.value.__cause__ is boom

    def test_a_transport_error_inside_the_block_is_not_rewrapped(self) -> None:
        """Only the connection step is translated; the caller's body stays raw.

        The ``try`` must enclose the factory call alone. Wrapping the whole
        ``with``/``yield`` would turn every ``OSError`` a caller raises while
        connected into a bogus "could not connect" error.
        """
        client, factory = _client()
        boom = OSError("disk full")

        with pytest.raises(OSError, match="disk full"), client:
            raise boom

        assert factory.cm.exits[0][1] is boom


_CONTEXT_REQUIRED_OPS: list[tuple[str, Callable[[CvatClient], object]]] = [
    ("list_projects", lambda c: c.list_projects()),
    ("set_organization", lambda c: c.set_organization("acme")),
    ("open_task_session", lambda c: c.open_task_session(7)),
]


@pytest.mark.parametrize(
    "call",
    [call for _, call in _CONTEXT_REQUIRED_OPS],
    ids=[name for name, _ in _CONTEXT_REQUIRED_OPS],
)
def test_operation_after_the_block_asks_for_a_new_context(
    call: Callable[[CvatClient], object],
) -> None:
    """Leaving the block clears the port: callers get the actionable error."""
    client, _factory = _client()

    with client:
        pass

    with pytest.raises(RuntimeError, match="requires a context manager"):
        call(client)


class TestTaskWriteSessionReuse:
    """``open_task_session`` exists to make one write chain fetch metadata once."""

    @staticmethod
    def _api() -> MagicMock:
        api = MagicMock(spec=CvatApiPort)
        api.get_task_data_meta.return_value = RawDataMeta(frames=[RawFrame(name="a.jpg", width=640, height=480)])
        api.get_task_labels.return_value = [LabelInfo(id=9, name="cat")]
        api.get_task_jobs.return_value = [RawJob(id=3, start_frame=0, stop_frame=0)]
        return api

    def test_one_write_chain_fetches_task_metadata_once(self) -> None:
        """Annotations, issues and deleted frames share one metadata fetch."""
        api = self._api()
        client = client_with_api(api)
        df = make_df([csv_row("a.jpg", issue_state="new", issue_text="fix me")])

        session = client.open_task_session(5)
        assert session.task_id == 5
        assert session.api is api
        client.upload_task_annotations(5, df, session=session)
        client.create_task_issues(5, df, session=session)
        client.mark_frames_deleted(5, {"a.jpg"}, session=session)

        assert api.get_task_data_meta.call_count == 1
        assert api.get_task_labels.call_count == 1
        assert api.get_task_jobs.call_count == 1


# ---------------------------------------------------------------------------
# Public client: runtime settings are read late
# ---------------------------------------------------------------------------


def test_public_client_resolves_late_environment_and_worker_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Public clients observe runtime settings changed after construction."""
    from cveta2.adapters.config.settings import CvatConfig
    from cveta2.adapters.execution.concurrency import Workers, configure_workers
    from cveta2.domain.models import TaskInfo

    api = MagicMock(spec=CvatApiPort)
    api.get_task.return_value = TaskInfo(
        id=1, name="task", project_id=7, status="completed", subset="", updated_date=""
    )
    api.get_project_labels.return_value = []
    api.get_task_jobs.return_value = [RawJob(id=9, start_frame=0, stop_frame=0)]
    api.get_task_labels.return_value = [LabelInfo(id=2, name="car")]
    api.get_task_data_meta.return_value = RawDataMeta(frames=[RawFrame(name="a.jpg", width=100, height=100)])
    runner = MagicMock(side_effect=lambda items, work, **_kwargs: list(map(work, items)))
    monkeypatch.setattr("cveta2.composition.client.run_concurrent", runner)
    monkeypatch.delenv("CVETA2_RAISE_ON_FAILURE", raising=False)
    prior = Workers.s3, Workers.cvat
    client = CvatClient(CvatConfig(), api=api)
    try:
        monkeypatch.setenv("CVETA2_RAISE_ON_FAILURE", "true")
        configure_workers(s3=prior[0], cvat=3)
        ctx = client.prepare_fetch(7, task_selector=[1])
        assert ctx.raise_on_failure is True
        assert runner.call_args.kwargs["max_workers"] == 3

        configure_workers(s3=prior[0], cvat=4)
        assert client.set_task_jobs_status(1, stage="acceptance") == 1
        assert runner.call_args.kwargs["max_workers"] == 4

        configure_workers(s3=prior[0], cvat=5)
        rows = make_df([csv_row("a.jpg", issue_state="new", issue_text="fix")])
        assert client.create_task_issues(1, rows) == 1
        assert runner.call_args.kwargs["max_workers"] == 5
    finally:
        configure_workers(s3=prior[0], cvat=prior[1])


def test_public_client_observes_mutable_config_before_owned_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Connection settings and public identity use the same current config."""
    from cveta2.client import CvatClient as PublicCvatClient
    from cveta2.config import CvatConfig

    cfg = CvatConfig(host="https://old.example", organization="old", username="u", password="p")
    api = MagicMock(spec=CvatApiPort)
    api.get_project_tasks.return_value = []
    api.get_project_labels.return_value = []
    connected: list[tuple[str | None, str | None]] = []

    @contextmanager
    def open_session(resolved: CvatConfig, _factory: object) -> Iterator[CvatApiPort]:
        connected.append((resolved.host, resolved.organization))
        yield api

    monkeypatch.setattr("cveta2.composition.client.open_sdk_api", open_session)
    client = PublicCvatClient(cfg)
    cfg.host = "https://new.example"
    cfg.organization = "new"

    assert client.host == cfg.host
    assert client.default_organization == cfg.organization
    with client:
        assert client.api is api
        assert connected == [(client.host, client.default_organization)]
        assert client.prepare_fetch(7).host == cfg.host
    cfg.host = ""
    cfg.organization = None
    assert client.host == ""
    assert client.default_organization is None
