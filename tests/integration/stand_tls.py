"""Tell a certificate-trust failure apart from a stand that is down.

The shared stands answer on ``https://<name>.k8s.docker.internal`` with a
certificate from the k8s-infra local CA. When this machine does not trust that
CA, the CVAT SDK, boto3 and requests all fail inside the TLS handshake, and the
error surfaces wrapped: ``ssl.SSLError`` is an ``OSError`` (which the suite
reads as "not reachable") and urllib3 hides it behind ``MaxRetryError``. These
helpers find the handshake failure in the chain so the scripts report a trust
problem with its remedy instead of a stand that does not answer.
"""

import ssl

TLS_REMEDY = (
    "the stands answer over HTTPS with a certificate from the k8s-infra local CA, "
    "and this process does not trust it: source scripts/integration_env.sh, whose "
    "k8s-infra helpers export SSL_CERT_FILE, REQUESTS_CA_BUNDLE and AWS_CA_BUNDLE, "
    "and check that the CA is installed "
    "(/usr/local/share/ca-certificates/k8s-infra-local-ca.crt, "
    "update-ca-certificates); the stand itself is not known to be down"
)


class StandTlsError(RuntimeError):
    """A stand could not be verified over TLS.

    Deliberately not an ``OSError``: the live tests skip on ``OSError`` as
    "stand not reachable", and a trust failure must fail, not skip.
    """


def _linked_errors(error: BaseException) -> list[BaseException]:
    linked: list[BaseException] = [
        candidate
        for candidate in (error.__cause__, error.__context__)
        if candidate is not None
    ]
    # getattr: urllib3's MaxRetryError keeps the underlying failure in `reason`,
    # and urllib3/requests/botocore wrappers keep it in `args`; neither is a
    # typed attribute shared by the three libraries.
    reason = getattr(error, "reason", None)
    if isinstance(reason, BaseException):
        linked.append(reason)
    linked.extend(arg for arg in error.args if isinstance(arg, BaseException))
    # getattr: botocore's BotoCoreError subclasses (SSLError among them) keep
    # the wrapped failure in a `kwargs` dict, not in args.
    kwargs = getattr(error, "kwargs", None)
    if isinstance(kwargs, dict):
        linked.extend(v for v in kwargs.values() if isinstance(v, BaseException))
    return linked


def find_tls_error(error: BaseException) -> ssl.SSLError | None:
    """Return the ``ssl.SSLError`` behind ``error``, or ``None`` when there is none."""
    seen: set[int] = set()
    pending: list[BaseException] = [error]
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, ssl.SSLError):
            return current
        pending.extend(_linked_errors(current))
    return None


def tls_failure_message(error: BaseException, url: str) -> str | None:
    """Describe a TLS failure reaching ``url``; ``None`` when ``error`` is not one."""
    tls_error = find_tls_error(error)
    if tls_error is None:
        return None
    return f"TLS verification of {url} failed ({tls_error}); {TLS_REMEDY}"
