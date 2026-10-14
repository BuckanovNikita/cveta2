"""Resolved client settings and neutral connection/session boundaries."""

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Protocol

from cveta2.application.ports.cvat import CvatApiPort

CvatSessionFactory = Callable[[], AbstractContextManager[CvatApiPort]]


@dataclass(frozen=True)
class ClientSettings:
    """Values resolved by composition before client operations run."""

    host: str = ""
    organization: str | None = None
    cvat_workers: int = 1
    raise_on_failure: bool = False


class CvatConnectionSettings(Protocol):
    """Credential and timeout values consumed by the CVAT SDK adapter."""

    @property
    def host(self) -> str:
        """The resolved CVAT server URL."""
        ...

    @property
    def username(self) -> str | None:
        """The resolved login name."""
        ...

    @property
    def password(self) -> str | None:
        """The resolved login secret."""
        ...

    @property
    def organization(self) -> str | None:
        """The configured organization slug."""
        ...

    @property
    def request_timeout(self) -> float | None:
        """The request timeout, including login and version checks."""
        ...
