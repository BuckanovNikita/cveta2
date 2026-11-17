# Triage labels

Use one current readiness classification, separately from lifecycle state:

- `needs-triage`: evaluation required.
- `needs-info`: material information missing.
- `ready-for-agent`: specified for agent execution.
- `ready-for-human`: requires human implementation.
- `wontfix`: will not be actioned; use the Canceled lifecycle state.

Readiness never overrides dependencies, verification or human merge requirements.
Completion evidence belongs in the issue and linked PR/evidence, not its label.
