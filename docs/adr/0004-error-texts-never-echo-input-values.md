# Identify invalid input by location and refuse ambiguous URL credentials

A configuration or dataset diagnostic may be pasted into a shared issue. Identify the field, path, line, column or row. A YAML syntax error should omit the source line, and diagnostics for an external exception should identify its class. A regression check must establish that the offending value is absent from the output.

## URL credentials

Configuration, command-line flags, source snapshots and dataset metadata can all carry URLs. A password can contain an unescaped slash, causing a conventional URL parser to stop reading the authority early. The credential check therefore also detects a colon before the last `@`. It can reject a legitimate URL such as `https://host:8080/a@b`. The cost of renaming such a path was accepted to keep credentials out of logs and published metadata. [review interfaces tests](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/tests/test_review_interfaces.py)

## Observed exception at the snapshot

An invalid nonnumeric timeout supplied through `CVETA2_DATA_TIMEOUT` can still appear in a warning. [Timeout diagnostic discrepancy](https://linear.app/sip-ds-team/issue/SIP-342/reconcile-timeout-diagnostics-with-the-input-redaction-adr)
