# Capability: Predictable operational errors

## User Scenarios & Testing

### User Story 1 - Diagnose malformed configuration safely (Priority: P1)

Users can locate invalid configuration without disclosing credential values in
the displayed error.

**Independent Test**: Load malformed YAML containing a sentinel credential through
the API and CLI; inspect the rendered error and exit status.

**Acceptance Scenarios**:

1. **Given** malformed YAML containing a credential, **when** configuration is
   loaded, **then** the domain error names the file and available error position
   without source snippets or input values.
2. **Given** the same file at the CLI, **when** a command loads it, **then** it
   fails cleanly without a traceback or credential value in displayed output.

### User Story 2 - Ignore invalid server retry delays (Priority: P2)

Transient CVAT failures retain their configured retry behavior when a server
supplies an invalid delay.

**Independent Test**: Invoke the real decorated read with controlled failures and
an invalid delay; observe attempts and the final typed failure without real waits.

**Acceptance Scenarios**:

1. **Given** a refused request with a negative, nonfinite or unparseable delay,
   **when** retrying, **then** the ordinary backoff applies and the configured
   attempt budget is honored.
2. **Given** a valid zero or positive delay, **when** retrying, **then** existing
   delay clamping and request-safety policies remain unchanged.

### Edge Cases

- Missing YAML source marks still produce a safe domain error.
- Syntax, scanner and constructor failures must not echo input values.
- Missing/date-form headers retain ordinary backoff; ambiguous non-idempotent
  writes remain unreplayed, regardless of retry headers.

## Requirements

### Functional Requirements

- **FR-001**: Malformed configuration diagnostics MUST omit YAML source content
  and scalar values while retaining the path and available line/column.
- **FR-002**: CLI configuration failures MUST remain actionable, Russian and free
  of incidental tracebacks; API callers retain typed errors and exception causes.
- **FR-003**: Retry delays MUST be accepted only when finite and nonnegative;
  invalid values MUST use the existing ordinary backoff.
- **FR-004**: Retry budgets, valid delay handling, read/write safety, configuration
  precedence and public signatures MUST remain compatible.

### Key Entities

- **Configuration diagnostic**: File identity and safe parse location/category.
- **Retry delay**: Optional finite nonnegative server delta in seconds.

## Success Criteria

### Measurable Outcomes

- **SC-001**: All malformed-config sentinel cases omit credential values from
  normal API error messages and CLI output.
- **SC-002**: Controlled invalid-header failures exhaust exactly the configured
  attempts and end with a typed CVAT error, never a sleep-related value error.
- **SC-003**: Existing valid configuration, delay and write-safety cases pass.

## Assumptions

- Both defects violate existing failure contracts; the cleanup removes no
  supported functionality and changes no remote services or dependency pins.
- Exception causes remain available to API callers for explicit debugging; the
  sanitization guarantee concerns the user-facing error, not deliberate traceback
  inspection of the original parser exception.

## Clarifications

### Session 2026-11-01

- Preserve supported behavior, as explicitly selected by the user. Existing
  failure contracts resolve the fallback and error-rendering choices; no further
  product questions are needed.
