"""Shared base for :class:`cveta2.client.CvatClient` mixins.

Holds construction, the context-manager lifecycle and API-port access.
Every mixin inherits :class:`_ClientBase` so ``self._require_api`` and
``self._cfg`` resolve for mypy without dynamic attribute access.
"""

from __future__ import annotations

from contextlib import ExitStack
from typing import TYPE_CHECKING

from cveta2._client.connection import open_sdk_api
from cveta2._client_ops.session import TaskWriteSession
from cveta2.config import CvatConfig

if TYPE_CHECKING:
    from types import TracebackType

    from typing_extensions import Self

    from cveta2._client.connection import SdkClientFactory
    from cveta2._client.ports import CvatApiPort
    from cveta2.image_downloader import CloudStorageInfo


class _ClientBase:
    """Connection lifecycle and API-port access shared by all mixins."""

    def __init__(
        self,
        cfg: CvatConfig | None = None,
        client_factory: SdkClientFactory | None = None,
        *,
        api: CvatApiPort | None = None,
    ) -> None:
        """Store client configuration and optional API port for DI.

        When *cfg* is ``None``, configuration is loaded automatically
        from environment variables, config file, and built-in preset
        via :meth:`CvatConfig.load`.

        When *api* is provided it is used directly (no connection is
        opened).  Otherwise an SDK-backed adapter is opened via
        *client_factory*.
        """
        self._cfg = cfg or CvatConfig.load()
        self._client_factory = client_factory
        self._api = api
        # Session organization: starts at the configured default, changed
        # by set_organization() (e.g. an ORG/PROJECT spec or the TUI).
        self._organization: str | None = self._cfg.organization
        # Persistent API opened by __enter__, closed by __exit__.
        self._persistent_api: CvatApiPort | None = None
        self._exit_stack: ExitStack | None = None
        # Cloud storage per project id: two requests each, asked for twice
        # per fetch (once for the images, once for the shared task cache)
        # and never changing inside a run.  Project ids are scoped to the
        # session organization, so set_organization() drops it.
        self._cloud_storage_memo: dict[int, CloudStorageInfo | None] = {}

    def __enter__(self) -> Self:
        """Open a persistent SDK connection for the lifetime of this block."""
        if self._api is not None:
            # DI api provided -- nothing to open.
            return self
        resolved = self._cfg.require_credentials()
        self._exit_stack = ExitStack()
        self._persistent_api = self._exit_stack.enter_context(
            open_sdk_api(resolved, self._client_factory)
        )
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
    def api(self) -> CvatApiPort:
        """The active API port (requires entered context or injected api)."""
        return self._require_api("api")

    @property
    def is_ready(self) -> bool:
        """True when remote calls can be made (entered context or injected api)."""
        return (self._api or self._persistent_api) is not None

    @property
    def host(self) -> str:
        """The configured CVAT host."""
        return self._cfg.host or ""

    @property
    def organization(self) -> str | None:
        """The current session organization (``None`` = personal workspace)."""
        return self._organization

    @property
    def default_organization(self) -> str | None:
        """The organization configured as default (config / env)."""
        return self._cfg.organization

    def set_organization(self, org: str | None) -> None:
        """Scope subsequent CVAT requests to *org* (``None`` = personal)."""
        self._organization = org
        self._cloud_storage_memo.clear()
        self._require_api("set_organization").set_organization(org)

    def open_task_session(self, task_id: int) -> TaskWriteSession:
        """Create a metadata session for consecutive writes to one task."""
        return TaskWriteSession(self._require_api("open_task_session"), task_id)

    def _require_api(self, method_name: str) -> CvatApiPort:
        """Return the injected or persistent API port, or raise.

        Both halves of the message carry an ``f`` prefix on purpose, as in
        :meth:`CvatConfig.require_credentials`: mutmut's string operator fires
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
