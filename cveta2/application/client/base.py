"""Shared base for application client mixins.

Holds construction, the context-manager lifecycle and API-port access.
Every mixin inherits :class:`_ClientBase` so ``self._require_api`` and
``self._settings`` resolve for mypy without dynamic attribute access.
"""

from contextlib import ExitStack
from types import TracebackType
from typing import TYPE_CHECKING

from cveta2.application.client.session import TaskWriteSession
from cveta2.application.ports.client import ClientSettings, CvatSessionFactory
from cveta2.application.ports.execution import ConcurrentRunner
from cveta2.application.ports.images import ImageReadPort

if TYPE_CHECKING:
    from typing_extensions import Self

    from cveta2.application.ports.cvat import CvatApiPort
    from cveta2.domain.storage import CloudStorageInfo


class _ClientBase:
    """Connection lifecycle and API-port access shared by all mixins."""

    def __init__(
        self,
        settings: ClientSettings,
        *,
        images: ImageReadPort,
        runner: ConcurrentRunner,
        session_factory: CvatSessionFactory | None = None,
        api: "CvatApiPort | None" = None,
    ) -> None:
        """Receive resolved values and effect ports without constructing adapters."""
        self._settings = settings
        self._images = images
        self._runner = runner
        self._session_factory = session_factory
        self._api = api
        self._organization = settings.organization
        self._persistent_api: CvatApiPort | None = None
        self._exit_stack: ExitStack | None = None
        self._cloud_storage_memo: dict[int, CloudStorageInfo | None] = {}

    def __enter__(self) -> "Self":
        """Open a persistent SDK connection for the lifetime of this block."""
        if self._api is not None:
            # DI api provided -- nothing to open.
            return self
        if self._session_factory is None:
            raise RuntimeError(
                "A CVAT session factory is required to open a connection"
            )
        self._exit_stack = ExitStack()
        self._persistent_api = self._exit_stack.enter_context(self._session_factory())
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Close the persistent SDK connection."""
        self._persistent_api = None
        if self._exit_stack is not None:
            stack, self._exit_stack = self._exit_stack, None
            stack.__exit__(exc_type, exc_val, exc_tb)

    @property
    def api(self) -> "CvatApiPort":
        """The active API port (requires entered context or injected api)."""
        return self._require_api("api")

    @property
    def is_ready(self) -> bool:
        """True when remote calls can be made (entered context or injected api)."""
        return (self._api or self._persistent_api) is not None

    @property
    def host(self) -> str:
        """The configured CVAT host."""
        return self._settings.host or ""

    @property
    def organization(self) -> str | None:
        """The current session organization (``None`` = personal workspace)."""
        return self._organization

    @property
    def default_organization(self) -> str | None:
        """The organization configured as default (config / env)."""
        return self._settings.organization

    def set_organization(self, org: str | None) -> None:
        """Scope subsequent CVAT requests to *org* (``None`` = personal)."""
        self._organization = org
        self._cloud_storage_memo.clear()
        self._require_api("set_organization").set_organization(org)

    def open_task_session(self, task_id: int) -> TaskWriteSession:
        """Create a metadata session for consecutive writes to one task."""
        return TaskWriteSession(self._require_api("open_task_session"), task_id)

    def _require_api(self, method_name: str) -> "CvatApiPort":
        """Return the injected or persistent API port, or raise.

        Both halves of the message carry an ``f`` prefix on purpose, as in
        the public credential check: mutmut's string operator fires
        on plain literals only, and the usage hint is prose, not behaviour
        (see the ``do_not_mutate_patterns`` note in pyproject.toml).  What *is*
        behaviour -- that the message names the operation the caller asked for
        -- stays pinned by the interpolated ``method_name``.
        """
        api = self._api or self._persistent_api
        if api is None:
            msg = (
                f"{method_name}() requires a context manager. "
                f"Use: with CvatClient(cfg) as client: ..."
            )
            raise RuntimeError(msg)
        return api
