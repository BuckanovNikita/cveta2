# Engineering architecture and tooling for cveta2 0.16.2

Maintainer capabilities at commit [8bf1e29](https://github.com/BuckanovNikita/cveta2/tree/8bf1e29ad4176e47419c87797b554315798051b3), recorded on 2026-11-28. Find the maintainer task below, then follow its decision and enforcing rule. Use the [engineering glossary](glossary.md) for terminology. Historical rationale is unknown wherever only the rule and its effects are recorded.

## Architecture

| Maintainer task | Rule or outcome | Decision | Evidence at 8bf1e29 |
| --- | --- | --- | --- |
| Dependency direction and external SDK ownership | Import-linter enforces layers, acyclic siblings and dedicated SDK importers. Importing CVAT’s SDK from a use case violates the contract. | [0013](0013-dependency-and-side-effect-boundaries.md) | [Rule](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/pyproject.toml#L327) |
| Ownership of I/O and prompts | Architecture checks look for effects in the wrong layer, including calls routed through aliases. | [0013](0013-dependency-and-side-effect-boundaries.md) | [Examples](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/tests/architecture_effects.py) |
| Offline product fixtures | Fake CVAT and S3 services and the small detection dataset exercise externally visible results without running live services. | [0013](0013-dependency-and-side-effect-boundaries.md) | [Examples](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/tests/fixtures/fake_cvat_project.py) |

## Development and verification

| Maintainer task | Rule or outcome | Decision | Evidence at 8bf1e29 |
| --- | --- | --- | --- |
| Editor formatting | The checked-in VS Code Python settings choose Ruff and enable formatting on save. | [0014](0014-verification-workflows.md) | [Rule](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/.vscode/settings.json) |
| `task fix` | Apply safe Ruff fixes and formatting before staging. | [0014](0014-verification-workflows.md) | [Rule](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/Taskfile.yml#L16) |
| `task check` | Check the lock, Ruff lint and formatting, import contracts, mypy, unused code and dependencies. | [0013](0013-dependency-and-side-effect-boundaries.md), [0014](0014-verification-workflows.md) | [Rule](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/Taskfile.yml#L22) |
| `task test` | Run affected units with worktree-local history and an environment fingerprint. | [0014](0014-verification-workflows.md) | [Rule](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/Taskfile.yml#L38) |
| `task test-full` | Run the full unit suite and refresh testmon dependency information. | [0014](0014-verification-workflows.md) | [Rule](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/Taskfile.yml#L44) |
| `task verify` | Run static checks followed by affected units. | [0014](0014-verification-workflows.md) | [Rule](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/Taskfile.yml#L68) |
| `task properties` | Explore randomized properties with the designated Hypothesis profile. | [0014](0014-verification-workflows.md) | [Rule](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/Taskfile.yml#L85) |
| `task mutation` | Mutate changed functions in an isolated copy of the index. Request strict mode to fail on surviving mutants. | [0014](0014-verification-workflows.md) | [Source](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/scripts/mutation.py#L7) |
| Benchmark fetch | Measure the fetch pipeline under controlled latency and emit results for comparing runs. | [0014](0014-verification-workflows.md) | [Source](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/scripts/benchmark_fetch.py) |
| `task infra-check` | Run a bounded, read-only infrastructure check. Exit 0 means available, 3 unavailable, and 1 an error. | [0014](0014-verification-workflows.md) | [Rule](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/Taskfile.yml#L74) |
| `task integration` | Preflight and run the live CVAT, MinIO and ClearML suites against session-owned resources. | [0014](0014-verification-workflows.md) | [Rule](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/Taskfile.yml#L79) |
| Live stand lifecycle | Use lifecycle up, env and stop to provision a session, inspect its connection environment or tear it down. | [0014](0014-verification-workflows.md) | [Source](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/tests/integration/lifecycle.py#L1440) |
| Seed live fixtures | Populate CVAT with known task, frame and annotation cases for tests against a real server. | [0014](0014-verification-workflows.md) | [Examples](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/tests/integration/seed_cvat.py) |
| Clone a CVAT project to cloud storage | Create a test project backed by S3, retaining each source task’s frame selection and order. | [0014](0014-verification-workflows.md) | [Test case](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/tests/integration/test_review_remediation.py#L131) |
| `task acceptance` | Require a clean tip and run checks, build, property exploration and live coverage, then verify the tip is clean. | [0014](0014-verification-workflows.md) | [Rule](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/Taskfile.yml#L104) |

## Packaging, releases and automation

| Maintainer task | Rule or outcome | Decision | Evidence at 8bf1e29 |
| --- | --- | --- | --- |
| `task build` | Build distributions into a uniquely owned temporary directory and clean it up on exit. | [0015](0015-packaging-release-and-github-automation.md) | [Rule](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/Taskfile.yml#L58) |
| Installable package and CLI entry point | Hatch packages cveta2 for supported Python versions and installs the cveta2 command. | [0015](0015-packaging-release-and-github-automation.md) | [Rule](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/pyproject.toml#L46) |
| Version, changelog and Git tags | Merged PRs into main trigger serialized semantic-release processing under the configured Conventional Commit rules. | [0015](0015-packaging-release-and-github-automation.md) | [Rule](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/.github/workflows/release.yml) |
| Automated PR review | Opening, updating, reopening or marking a PR ready can invoke the configured review action. | [0015](0015-packaging-release-and-github-automation.md) | [Rule](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/.github/workflows/claude-code-review.yml) |
| Mention-driven assistance | Eligible issue or review events with an @claude mention invoke the separate assistant workflow. | [0015](0015-packaging-release-and-github-automation.md) | [Rule](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/.github/workflows/claude.yml) |

## Repository coordination

| Maintainer task | Rule or outcome | Decision | Evidence at 8bf1e29 |
| --- | --- | --- | --- |
| Session status | Print the current branch, worktree context and any recorded live session so concurrent work is visible. | [0016](0016-repository-coordination.md) | [Rule](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/scripts/session_status.sh) |
| Track issues, blockers and PRs | Use the SIP team’s cveta2 project, native dependencies and the issue identifier in the PR title. | [0016](0016-repository-coordination.md) | [Guide](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/docs/agents/issue-tracker.md) |
| Triage and readiness | Map triage roles to Linear statuses and the designated human-ready label. | [0016](0016-repository-coordination.md) | [Guide](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/docs/agents/triage-labels.md) |
| Domain vocabulary and decision review | Consult the glossary and related ADRs before changing an established decision. | [0016](0016-repository-coordination.md) | [Guide](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/docs/agents/domain.md) |

## Evidence from 2026-11-28

Two offline pytest runs against an archive of `8bf1e29` passed (1,092 and 847 cases). The live integration tests, Kubernetes lifecycle, release and GitHub workflows were inspected as source.
