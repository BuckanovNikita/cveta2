"""Configure shared execution policies before constructing external clients."""

from contextlib import AbstractContextManager

from cveta2.adapters.config.settings import NetworkConfig
from cveta2.adapters.cvat.transport import install_global_request_timeout
from cveta2.adapters.execution.concurrency import configure_workers
from cveta2.adapters.execution.retry import configure_retries
from cveta2.adapters.s3.errors import s3_failures_as_errors
from cveta2.adapters.s3.utils import set_default_data_timeout


def configure_data_timeout(timeout: float | None) -> None:
    """Apply the same configured timeout to CVAT requests and S3 clients."""
    set_default_data_timeout(timeout)
    install_global_request_timeout(timeout)


def configure_network(network: NetworkConfig) -> None:
    """Apply resolved retry budgets and worker counts for this runtime context."""
    configure_retries(network.retry_attempts, network.retry_max_wait)
    configure_workers(s3=network.s3_workers, cvat=network.cvat_workers)


def cli_external_failures() -> AbstractContextManager[None]:
    """Report external SDK failures as cveta2 errors on the command line only.

    The Python API keeps raising the SDK's own exceptions; the CLI boundary
    wraps each command in this to end such a failure with a message.
    """
    return s3_failures_as_errors()
