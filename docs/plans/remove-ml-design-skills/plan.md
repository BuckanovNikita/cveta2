# Remove ML-SystemDesign skills

Remove the obsolete installer metadata for `ai-stage-gate`,
`lossless-doc-compress` and `ml-system-design-review` on `project-cleunap`.
All three skills are absent from both local host directories; the initial
working tree is clean. Global skills and historical evidence remain outside scope.

## Architecture

The [architecture record](architecture.json) records inspected runtime non-impact.
Only the installer lockfile, dedicated ignore entries and maintenance evidence change.
Validate the record before removal and after reconciliation.

## Tasks and acceptance

- [x] Validate the planning architecture record.
- [x] Remove `skills-lock.json`, whose entries all originate from ML-SystemDesign,
  and the three dedicated `.gitignore` entries.
- [x] Check whitespace, inspect the complete diff and confirm local skills are absent.
- [x] Validate architecture acceptance.
- Commit only task-owned paths.

Tests, including pytest and mutation hooks, are skipped by explicit user request.
Other configured commit checks remain enabled. Stop after the requested commit;
no push, merge or release is part of this task. A `chore` commit has no version bump.

## Verification evidence — 2026-11-06

Architecture validator planning and acceptance phases exited 0. `git diff --check`
passed. Inspection confirmed all six candidate paths (three skills under each
host's skill directory) are absent. Final scope matches the architecture record:
two metadata removals and this maintenance record; no runtime impact and no
unrelated changes. The local architecture link resolves. Tests were not run,
as requested; application behavior was not exercised.
