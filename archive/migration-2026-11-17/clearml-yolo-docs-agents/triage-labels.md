# Triage labels

Use these Linear readiness labels separately from lifecycle state:

- `needs-triage`: requires evaluation
- `needs-info`: awaiting missing information
- `ready-for-agent`: fully specified for agent execution
- `ready-for-human`: requires human implementation
- `wontfix`: will not be actioned; use the Canceled lifecycle state

Keep one current readiness classification. Readiness does not override dependencies,
verification or human merge requirements. Completion evidence belongs in the issue and
linked PR/evidence, not in a readiness label.
