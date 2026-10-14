# Python workflow alignment

Date: 2026-10-14. Route: native lightweight documentation maintenance.

## Contract and inspected baseline

Preserve the project-owned Spec Kit lifecycle, full stage order, explicit feature
selector, existing commit/mutation/integration skills, and portable usage skill
maintenance. Align shared lifecycle discovery, automatic authorized progression,
standing commit/push authorization, explicit stopping points, language guidance,
and architecture planning/acceptance. No application feature specification is
needed for this policy-only change. No runtime, dependencies, configuration,
checker, installed workflow skill/template, inactive feature, or release changes.
This delegated work stops before commits, pushes, final integrated review and
acceptance; the parent owns those stages.

Inspected AGENTS.md, CONTRIBUTING.md, canonical engineering and constitution,
pyproject.toml, tests/test_docs.py, tests/conftest.py, the project commit skill,
and the shared Python workflow/architecture skills and references. The package
floor is Python 3.10; development is pinned to 3.12, mypy targets 3.11. Existing
pytest defaults retain tests.env_isolation. The initial worktree/index is clean.

## Architecture

[architecture.json](architecture.json) records no runtime or import-contract
impact: only project guidance and task-owned planning/evidence change. Existing
import/effect checks and public CLI/API/dataset contracts remain authoritative.
Validate the planning record before policy edits. At final acceptance reconcile
the complete owned diff and documentation checks; parent integration/review and
acceptance validation remain pending.

## Tasks and dependencies

1. Record proposed scope and pass the architecture planning validator.
2. Run the existing documentation tests to establish the baseline.
3. Align AGENTS, engineering, constitution (minor amendment), and Russian
   contributor workflow guidance; preserve the native process and usage-skill text.
4. Run documentation tests, changed Markdown/link checks and whitespace checks;
   record dated evidence and limitations.
5. Parent reviews the integrated diff, reconciles architecture scope, validates
   acceptance and performs authorized delivery within the user's stopping point.

This is one bounded documentation workstream. No further delegation is needed.

Implementation, parent documentation checks, fresh independent review (`ship`)
and architecture acceptance validation are complete. Native delivery remains the
next sequential stage; its actual outcomes belong in dated evidence.

## Acceptance commands

Use the shared architecture validator with --phase plan before policy edits and
--phase acceptance after parent reconciliation. Run the established
`uv run --no-sync python -m pytest tests/test_docs.py -n 0` with the existing
prepared environment selected externally, preserving tests.env_isolation.
Run `git diff --check` and check local links/anchors and balanced Markdown fences
for changed guidance and task evidence, including this nested directory omitted
from the documentation test's discovery. Store actual results in
[verification-2026-10-14.md](verification-2026-10-14.md).

## Public documentation and usage skill

No public command, API, configuration, authentication, dataset/conversion format,
default, side effect, or failure recovery changes. Existing public guides and the
portable usage skill need no behavior-contract update; its maintenance section
in canonical engineering guidance is preserved.

## Worker checkpoint

Tasks 1-4 completed; actual results and unchanged CONTRIBUTING lint baseline are
recorded in the linked dated evidence. Task 5 remains parent-owned and pending.
The final worker diff covers only the proposed documentation scope; portable
usage maintenance, existing feature history, runtime/configuration/checkers and
installed framework files were preserved.
