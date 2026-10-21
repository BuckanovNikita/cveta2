"""Configure shared execution policies before constructing external clients."""

from cveta2.adapters.config.settings import NetworkConfig
from cveta2.adapters.cvat.transport import install_global_request_timeout
from cveta2.adapters.execution.concurrency import configure_workers
from cveta2.adapters.execution.retry import configure_retries
from cveta2.adapters.s3.utils import set_default_data_timeout


def configure_data_timeout(timeout: float | None) -> None:
    """Apply the same configured timeout to CVAT requests and S3 clients."""
    set_default_data_timeout(timeout)
    install_global_request_timeout(timeout)


def configure_network(network: NetworkConfig) -> None:
    """Apply resolved retry budgets and worker counts for this runtime context."""
    configure_retries(network.retry_attempts, network.retry_max_wait)
    configure_workers(s3=network.s3_workers, cvat=network.cvat_workers)
