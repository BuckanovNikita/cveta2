# Enforce inward dependencies and isolate external effects

## Import direction

Public compatibility modules depend inward through interfaces, composition, adapters, application and domain. Use cases and client orchestration consume neutral contracts. Composition supplies implementations. Protected imports confine each SDK to its adapter, so a CVAT SDK import from domain code violates the contract. [Import-linter contracts](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/pyproject.toml) · [Architecture checks](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/tests/test_architecture.py)

## Effect ownership

Check where HTTP requests, disk writes and prompts occur, including calls hidden behind aliases. Fake CVAT and S3 services let offline tests observe rows, files and remote writes at the product boundary. [Effect checks](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/tests/architecture_effects.py) · [Fake CVAT](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/tests/fixtures/fake_cvat_api.py) · [Fake S3](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/tests/fixtures/fake_s3.py)
