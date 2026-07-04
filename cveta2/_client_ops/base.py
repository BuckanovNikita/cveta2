"""Shared base for :class:`cveta2.client.CvatClient` mixins.

Holds construction, the context-manager lifecycle and API-port access.
Every mixin inherits :class:`_ClientBase` so ``self._require_api`` and
``self._cfg`` resolve for mypy without dynamic attribute access.
"""

from __future__ import annotations

from contextlib import ExitStack
from typing import TYPE_CHECKING

from cveta2._client.connection import open_sdk_api
from cveta2.config import CvatConfig

if TYPE_CHECKING:
    from types import TracebackType

    from typing_extensions import Self

    from cveta2._client.connection import SdkClientFactory
    from cveta2._client.ports import CvatApiPort


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
        # Persistent API opened by __enter__, closed by __exit__.
        self._persistent_api: CvatApiPort | None = None
        self._exit_stack: ExitStack | None = None

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
    def host(self) -> str:
        """The configured CVAT host."""
        return self._cfg.host or ""

    def _require_api(self, method_name: str) -> CvatApiPort:
        """Return the injected or persistent API port, or raise."""
        api = self._api or self._persistent_api
        if api is None:
            msg = (
                f"{method_name}() requires a context manager. "
                "Use: with CvatClient(cfg) as client: ..."
            )
            raise RuntimeError(msg)
        return api
