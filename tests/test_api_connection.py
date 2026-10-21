"""Public API connection contracts."""

import pytest
from typing_extensions import Self

import cveta2
from cveta2.domain.errors import (
    Cveta2Error,
    MissingCredentialsError,
    MissingHostError,
)
from cveta2.interfaces.api.connection import _open


class TestOpenConnection:
    def test_injected_client_used_as_is(self) -> None:
        injected = cveta2.CvatClient(cveta2.CvatConfig(), api=object())  # type: ignore[arg-type]
        connection = cveta2.Connection(client=injected)
        with _open(connection) as client:
            assert client is injected

    def test_unentered_client_rejected(self) -> None:
        connection = cveta2.Connection(client=cveta2.CvatClient(cveta2.CvatConfig()))
        with (
            pytest.raises(Cveta2Error, match="не готов"),
            _open(connection),
        ):
            pytest.fail("must not yield")

    def test_missing_host_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "cveta2.interfaces.api.connection.CvatConfig.load",
            lambda *_a, **_k: cveta2.CvatConfig(),
        )
        with (
            pytest.raises(MissingHostError, match="CVAT_HOST"),
            _open(None),
        ):
            pytest.fail("must not yield")

    def test_missing_credentials_raise(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "cveta2.interfaces.api.connection.CvatConfig.load",
            lambda *_a, **_k: cveta2.CvatConfig(),
        )
        with (
            pytest.raises(MissingCredentialsError, match="CVAT_USERNAME"),
            _open(cveta2.Connection(host="http://cvat.test")),
        ):
            pytest.fail("must not yield")

    def test_explicit_settings_override_config(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "cveta2.interfaces.api.connection.CvatConfig.load",
            lambda *_a, **_k: cveta2.CvatConfig(host="http://from-config"),
        )
        captured: dict[str, str] = {}

        class _FakeClient:
            def __init__(self, cfg: cveta2.CvatConfig) -> None:
                captured["host"] = cfg.host
                captured["user"] = cfg.username or ""

            def __enter__(self) -> Self:
                return self

            def __exit__(self, *_exc: object) -> None:
                return None

        monkeypatch.setattr("cveta2.interfaces.api.connection.CvatClient", _FakeClient)
        connection = cveta2.Connection(
            host="http://explicit", username="user", password="pass"
        )
        with _open(connection):
            pass
        assert captured["host"] == "http://explicit"
        assert captured["user"] == "user"

    def test_empty_organization_explicitly_selects_personal_workspace(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "cveta2.interfaces.api.connection.CvatConfig.load",
            lambda *_a, **_k: cveta2.CvatConfig(
                host="http://from-config", organization="team"
            ),
        )
        captured: dict[str, str | None] = {}

        class _FakeClient:
            def __init__(self, cfg: cveta2.CvatConfig) -> None:
                captured["organization"] = cfg.organization

            def __enter__(self) -> Self:
                return self

            def __exit__(self, *_exc: object) -> None:
                return None

        monkeypatch.setattr("cveta2.interfaces.api.connection.CvatClient", _FakeClient)

        with _open(cveta2.Connection(organization="")):
            pass

        assert captured["organization"] is None
