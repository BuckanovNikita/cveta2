"""tests/integration/stand_tls.py: a trust failure is found however it is wrapped."""

import ssl

from urllib3.exceptions import MaxRetryError, NewConnectionError
from urllib3.exceptions import SSLError as Urllib3SSLError

from tests.integration.stand_tls import (
    StandTlsError,
    find_tls_error,
    tls_failure_message,
)

HOST = "https://cvat.k8s.docker.internal"


def untrusted_certificate_error() -> MaxRetryError:
    """Build what urllib3 raises when the local CA is not trusted.

    The handshake error is wrapped in urllib3's SSLError, and the retry error
    is raised while handling it.
    """
    handshake = ssl.SSLCertVerificationError(
        1,
        "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate",
    )
    wrapped = Urllib3SSLError(handshake)
    try:
        try:
            raise handshake
        except ssl.SSLError:
            raise MaxRetryError(None, "/api/auth/login", wrapped) from wrapped  # type: ignore[arg-type]
    except MaxRetryError as exc:
        return exc


def refused_connection_error() -> MaxRetryError:
    refused = NewConnectionError(None, "Failed to establish a new connection")  # type: ignore[arg-type]
    return MaxRetryError(None, "/api/auth/login", refused)  # type: ignore[arg-type]


def test_the_handshake_error_is_found_behind_urllib3s_retry_error() -> None:
    found = find_tls_error(untrusted_certificate_error())
    assert isinstance(found, ssl.SSLCertVerificationError)


def test_a_wrapper_that_only_carries_the_error_in_its_args_is_searched() -> None:
    handshake = ssl.SSLError(1, "tlsv1 alert unknown ca")
    wrapper = ConnectionError(Urllib3SSLError(handshake))
    assert find_tls_error(wrapper) is handshake


def test_a_refused_connection_is_not_a_tls_failure() -> None:
    assert find_tls_error(refused_connection_error()) is None
    assert find_tls_error(ConnectionRefusedError(111, "refused")) is None
    assert tls_failure_message(refused_connection_error(), HOST) is None


def test_a_cyclic_chain_terminates() -> None:
    first = RuntimeError("first")
    second = RuntimeError("second")
    first.__context__ = second
    second.__context__ = first
    assert find_tls_error(first) is None


def test_the_message_names_tls_the_host_and_the_ca_to_trust() -> None:
    message = tls_failure_message(untrusted_certificate_error(), HOST)
    assert message is not None
    assert message.startswith(f"TLS verification of {HOST}")
    assert "k8s-infra-local-ca.crt" in message


def test_the_tls_error_is_not_an_oserror_so_live_tests_cannot_skip_it() -> None:
    assert not issubclass(StandTlsError, OSError)
