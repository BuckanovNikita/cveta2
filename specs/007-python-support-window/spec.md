# Feature Specification: Python support window

**Created**: 2026-10-15
**Status**: Completed
**Input**: Support Python >=3.12,<3.14 for the user's projects worked on this week.

## Clarifications

No material ambiguity remains: Python 3.10 and 3.11 support is intentionally removed;
Python 3.14 and later are excluded. Keep the existing development interpreter 3.12.

## User Scenarios & Testing

### User Story 1 - Install on supported interpreters (Priority: P1)

A user installs and runs cveta2 on Python 3.12 or 3.13.

**Independent Test**: Install the built wheel outside the checkout on both versions,
import the package and execute CLI help; run the offline suite on both interpreters.

**Acceptance Scenarios**:

1. Given Python 3.12 or 3.13, installation succeeds and public CLI/API remain usable.
2. Given Python 3.11 or 3.14, package metadata rejects installation.
3. Given a contributor, all maintained guidance identifies the same support window.

### Edge Cases

Optional ClearML dependencies remain optional; existing locked dependency versions
should remain unchanged unless the narrower interpreter domain makes entries obsolete.

## Requirements

- **FR-001**: Package and lock metadata MUST declare >=3.12,<3.14.
- **FR-002**: Classifiers MUST advertise only supported Python minor versions.
- **FR-003**: Mypy MUST target the supported minimum, Python 3.12. Ruff retains
  its conservative py310 syntax/lint baseline without implying runtime support.
- **FR-004**: Development remains pinned to Python 3.12; application code, CLI,
  API, dataset contracts and dependency requirements MUST retain their behavior.
- **FR-005**: Current installation/development guidance and the portable usage skill
  MUST describe Python 3.12 and 3.13 support and the excluded versions.

## Success Criteria

- **SC-001**: Offline regression checks pass on both supported interpreters.
- **SC-002**: Isolated wheel installation and CLI/import smoke checks pass on both.
- **SC-003**: Wheel metadata rejects unsupported adjacent versions.
- **SC-004**: Lock consistency, static/architecture and documentation checks pass.

## Scope

No dependency upgrades, application refactors, live-service changes or deployments.
Parent integrates and obtains independent review; this bounded implementation stops
before commits/releases. Companion skill ownership remains with the parent.
