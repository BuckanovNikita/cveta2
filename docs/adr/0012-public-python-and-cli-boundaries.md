# Keep a noninteractive Python API behind stable public names

## Calling the public API

CLI callers can select inputs interactively and receive an exit status. Python callers supply choices explicitly and receive typed results or exceptions. Public exports preserve object identity and historical pickle names. Importing an inner module can proceed without initializing a storage or CVAT SDK. [Package exports](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/cveta2/__init__.py) · [Compatibility tests](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/tests/test_api_compatibility.py) · [Import isolation](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/tests/test_architecture.py)

## Reusing a CVAT connection

`Connection` supplies settings or an existing client. A context-managed `CvatClient` can query projects, tasks and labels, write tasks, retrieve images or read task annotations without writing CSVs. Job and frame metadata identify the positions attached to each record. [Connection cases](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/tests/test_api_connection.py) · [Client contract](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/docs/python-api.md) · [Client operations](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/tests/test_client_ops_fetch.py)

## Recovering from transport failures

Request timeouts bound CVAT calls. Retryable reads can be repeated. After an ambiguous write failure the caller can reconcile remote state before repeating the operation. S3 transfer results expose individual failures, and CLI dispatch translates supported SDK errors. [CVAT and S3 retry cases](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/tests/test_retry_policy.py) · [Request timeout cases](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/tests/test_request_timeout.py)
