# Engineering glossary

## Architecture

**Import contract**:
A rule defining which cveta2 packages may depend on one another or import an external SDK. For example, an import of the CVAT SDK belongs in the CVAT adapter.
_Russian_: правило зависимостей между модулями

**Effect ownership**:
The assignment of an external operation, such as a CVAT request, disk write or interactive prompt, to the layer responsible for performing it.
_Russian_: ответственность за внешние операции

## Development and verification

**Affected unit tests**:
The unit tests selected for the current worktree using its recorded test dependencies. A full unit run exercises the entire unit suite and refreshes that history.
_Russian_: затронутые модульные тесты

**Testmon environment fingerprint**:
The identifier for inputs to test selection beyond Python source, including the interpreter, locked dependencies, verification configuration and test assets. It determines which recorded test history applies to a run.
_Russian_: отпечаток окружения testmon

**Clean-tip acceptance**:
The repository’s acceptance run against a committed revision with a clean worktree at both ends of the run. It includes checks, a package build, property tests and coverage with live services.
_Russian_: приёмочная проверка чистой ревизии

**Live session**:
An isolated CVAT, MinIO and ClearML environment provisioned for integration testing. A *kept session* retains those resources for inspection after a run.
_Russian_: сессия интеграционных тестов

## Packaging and release

**Release**:
A version of the cveta2 package identified by a Git tag. The release workflow derives the version and changelog from merged commits.
_Russian_: выпуск версии cveta2

For commands, enforcing rules and evidence at the recorded revision, see the [engineering index](index.md). For CVAT tasks, datasets and publication, see the [product glossary](../../../GLOSSARY.md).
