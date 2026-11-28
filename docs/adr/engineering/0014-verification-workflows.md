# Give fast local checks and clean-tip acceptance distinct entry points

## Local checks

Task runs isolate tool caches by worktree. Affected-unit runs use testmon history and the environment fingerprint. A full-unit run refreshes that history. Use property exploration for randomized cases, the fetch benchmark for controlled latency and changed-function mutation for targeted test strength. Mutation findings are advisory by default and can fail a strict run. [Task definitions](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/Taskfile.yml) · [Test selection inputs](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/scripts/testmon_environment.py) · [Mutation scope](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/scripts/mutation.py)

## Live checks and acceptance

Preflight checks Kubernetes availability before running CVAT, MinIO and ClearML in a dedicated session. A kept session can be inspected and stopped later. Cloning and seeding provide live fixtures. Clean-tip acceptance checks the worktree before and after static checks, a temporary build, property tests and the live coverage run. A distinct preflight outcome identifies infrastructure unavailability. [Integration lifecycle](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/tests/integration/lifecycle.py) · [Acceptance sequence](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/Taskfile.yml) · [Live fixtures](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/tests/integration/conftest.py)
