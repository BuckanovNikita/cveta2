# Documentation migration verification

**Date**: 2026-09-30 | **Feature**: [spec.md](../spec.md)

## Scope and preservation

- Dataset contract and historical bug review match their source bytes.
- Architecture module and behavior sections are unchanged; navigation changed.
- Working-tree ownership, code conventions, verification, mutation, integration,
  configuration, and release guidance retain their original operational rules.
- Machine procedure duplication delegates to the existing global infrastructure
  skill and project wrappers, preserving the owned-tag and cleanup boundaries.
- Source hashes and migration details are in
  [source-migration-2026-09-30.json](source-migration-2026-09-30.json).
- User guides, changelog, existing workflow tools, unrelated skill links,
  application version, dependencies, and hooks remain in place. Application
  source changes only the dataset-reference docstring.

## Checks

| Check | Observed result |
|---|---|
| Initial relocation regression checks | Expected failures: old dataset links and root infra-block assumption; corrected by migration |
| Documentation checks before this evidence file | `uv run pytest tests/test_docs.py`: 53 passed |
| Static checks | Ruff lint and format checks passed for tests/test_docs.py and cveta2/api.py; mypy reported no issues in both files |
| Lock consistency | `uv lock --check` passed without changing uv.lock |
| Source package | Temporary `uv build --sdist` succeeded; archive includes the relocated dataset contract with identical content and no retired root copy |
| Spec Kit setup | Both integrations healthy, Codex default, all managed-file hashes intact |
| Feature prerequisites | Current spec, plan, and tasks resolve through the local feature pointer |
| Read-only review | No material findings; final evidence and convergence were the remaining completion work |
| Final document checks | `uv run pytest tests/test_docs.py`: 55 passed, including this evidence; Ruff lint and format checks passed |

Temporary source-package artifacts were removed. No full application suite or
live integration run was needed for this documentation and packaging change.
Interactive agent execution remains untested. No commit, push, or release.

## Constitution and convergence

Post-implementation Constitution Check: all five principles remain satisfied.
The migration changes documentation ownership only, preserves the established
architecture and output contract, uses the existing checks, and retains
working-tree, shared-resource, and release boundaries.

Final assessment covers eight functional requirements, four success criteria,
four user-story acceptance scenarios, the destination/consumer/packaging
choices in the plan, and all eight tasks. No missing, partial, contradictory,
or unrequested work remains within the specified migration scope. Converged;
no new convergence tasks are required. Historical review suggestions are
preserved evidence, not current implementation tasks.
