# Portable usage skill maintenance

## Intent and architecture

Extend the existing documentation stage to maintain the corresponding portable
usage skill in corp-skills when CLI, API, configuration, input/output or failure
contracts change. Keep native Spec Kit artifacts and completed history intact.
The [architecture record](architecture.json) records inspected no-impact scope.
This is documentation maintenance, without application behavior changes.

## Tasks and acceptance

- [x] Inspect native guidance, current implementation and existing changes.
- [x] Validate architecture planning record before editing policy.
- [x] Add canonical skill ownership, change triggers and dependent validation tasks.
- [x] Verify documentation and inspect the complete task-owned diff.
- [x] Obtain fresh independent review and validate architecture acceptance.
The native commit/release workflow follows this accepted snapshot. Final delivery
refs are reported in the companion collection's dated verification and user handoff.

Checks: `uv run pytest tests/test_docs.py`, changed Markdown/link checks, and applicable commit/push hooks.

Parent owns policy edits; independent tool inspection and skill authoring run in
parallel. Integration, verification, fresh review and release are sequential.
Record executed checks and limitations here before acceptance.

## Verification before independent review

Architecture planning validation passed. Changed Markdown and local links were
checked; policy changes only affect documentation ownership and acceptance.
`uv run pytest tests/test_docs.py` passed: 197 tests. Changed policy/evidence
Markdown passed markdownlint-cli2 0.23.3. No CVAT operations were performed.

## Acceptance

Fresh independent native Codex review returned `ship` with no substantive findings
on 2026-10-14, after parent integration and verification. The reviewer checked the
companion portable package against current source and evaluated representative
usage/failure cases. Architecture acceptance validation passed. Task-owned changes
are limited to the policy paths and this evidence directory; application code,
dependencies and installed workflow tooling remain unchanged.

The companion packages and dated checks are maintained in
[corp-skills verification](https://github.com/BuckanovNikita/corp-skills/blob/main/verification/2026-10-14-tool-usage.md).
Live DeepSeek/OpenCode and service execution were not tested.
