# Capability: HTTPS docker.internal integration stands

## Baseline delta

This delta changes only development and live-integration tooling: `scripts/integration_*.sh`, `tests/integration/`, their offline unit tests, contributor guidance and the project `running-integration-tests` skill. The cveta2 runtime package, CLI, Python API, configuration schema, dataset contract and packaged files are unchanged. The [baseline](../baseline.md) does not describe stand URLs or integration tooling, so it needs no reconciliation for this delta.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Live runs reach the HTTPS stands (Priority: P1)

A developer or agent sources `scripts/integration_env.sh` and runs the integration lifecycle (`integration_up.sh`, `integration_test.sh`, `integration_stop.sh`, or the pre-push gate). The CVAT, MinIO and ClearML endpoints come from the helpers' `env` output and are `https://<name>.k8s.docker.internal`; the CA bundle variables from the same output are exported to every process of the run, so curl, the CVAT SDK, boto3 and the ClearML SDK verify the stands' certificates.

**Why this priority**: The live Secrets switch to the HTTPS names; without this the gate and live tests cannot reach the stands with certificate verification enabled.

**Independent Test**: With fake helpers emitting HTTPS endpoints plus the CA variables, `integration_env.sh` exports the HTTPS endpoints and the four CA variables, and a child process sees `SSL_CERT_FILE`.

**Acceptance Scenarios**:

1. **Given** helper output with HTTPS endpoints and CA variables, **When** the environment script is sourced, **Then** `CVAT_INTEGRATION_HOST`, `MINIO_ENDPOINT`, `MINIO_CONSOLE` and `CLEARML_API_HOST` are the HTTPS names and `SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE`, `AWS_CA_BUNDLE` and `NODE_EXTRA_CA_CERTS` are exported unchanged.
2. **Given** no `CVAT_INTEGRATION_HOST` override, **When** live fixtures build their configuration, **Then** the default host is `https://cvat.k8s.docker.internal`.
3. **Given** the in-cluster MinIO endpoint for CVAT, **When** the environment is sourced, **Then** `MINIO_ENDPOINT_FOR_CVAT` stays the cluster-internal `http://…svc…` address.

### User Story 2 - Trust failures are reported as TLS problems (Priority: P1)

When the machine does not trust the local CA, the stand answers but the TLS handshake fails. The gate, the stand scripts and the live fixtures name the failure as TLS verification of the stand URL, give the remedy (install the k8s-infra CA, source the environment), and never present it as a stand that is down or skip live tests because of it.

**Why this priority**: A trust failure misreported as "stand down" sends the operator to the wrong diagnosis; a skipped live test hides the failure entirely.

**Independent Test**: Offline tests inject curl exit 60, a urllib3 `MaxRetryError` wrapping `SSLCertVerificationError`, and botocore's `SSLError`; each reports `TLS verification of <url> failed` with the remedy, while curl exit 7 and a refused connection are still reported as not answering.

**Acceptance Scenarios**:

1. **Given** an armed gate and curl exit status in the TLS set (for example 60), **When** the gate runs, **Then** it fails with "TLS verification of the CVAT stand … failed (curl exit 60)" plus the certificate-trust remedy, and does not say "does not answer".
2. **Given** curl exit 7, **When** the gate runs, **Then** it reports "does not answer (curl exit 7)" without mentioning TLS.
3. **Given** a CVAT login that fails in the TLS handshake, **When** `cvat_stand.py verify`, `seed_cvat.py` or the live SDK fixture logs in, **Then** the failure is raised as `TLS verification of <host> failed (…)` with the remedy, the client is closed, and the live fixture error is not an `OSError` (so it fails instead of skipping).
4. **Given** the MinIO bucket seeding fails with botocore's `SSLError`, **When** `seed_cvat.py` runs, **Then** it exits 1 with `TLS verification of <MinIO endpoint> failed`.
5. **Given** ClearML `whoami` fails in the gate or the test script, **Then** the message adds that a certificate or SSL error in that output is a trust problem, with the same remedy.

### Edge Cases

- TLS errors wrapped in `__cause__`, `__context__`, urllib3 `reason`, exception `args` or botocore `kwargs` are all found; cyclic exception chains terminate.
- A refused connection or DNS failure is not classified as TLS.
- The old `*.k8s.localhost` names remain served over HTTP but are no longer configured; guidance tells operators to fix trust rather than switch back or disable verification.
- The CA variables are exported only when the k8s-infra helpers emit them (CA installed); the scripts do not hard-code bundle paths.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Live-integration defaults and offline test fixtures MUST use the HTTPS names (`https://cvat.k8s.docker.internal`, `https://s3.k8s.docker.internal`, `https://minio.k8s.docker.internal`, `https://api.clearml.k8s.docker.internal`, and the ClearML web/files names) instead of `http://*.k8s.localhost`.
- **FR-002**: `scripts/integration_env.sh` MUST export the helper-provided `SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE`, `AWS_CA_BUNDLE` and `NODE_EXTRA_CA_CERTS` unchanged to every process of the run, without hard-coding or storing them.
- **FR-003**: The gate MUST classify curl TLS exit statuses separately from an unreachable CVAT stand and print the certificate-trust remedy.
- **FR-004**: `cvat_stand.py`, `seed_cvat.py` (CVAT login and MinIO seeding) and the live SDK fixture MUST report TLS handshake failures as `TLS verification of <url> failed (<ssl error>); <remedy>`; the live-fixture error MUST NOT be an `OSError`, so live tests fail rather than skip.
- **FR-005**: Non-TLS connection failures MUST keep their existing reporting and skip behavior.
- **FR-006**: ClearML authentication failures in the gate and test script MUST mention that a certificate or SSL error is a trust problem, with the remedy.
- **FR-007**: Contributor guidance (`CONTRIBUTING.md`, Russian) and the project `running-integration-tests` skill MUST describe the HTTPS names, the CA trust variables and the TLS troubleshooting path.
- **FR-008**: The TLS classification helper MUST remain test tooling that depends only on the standard library, and no runtime `cveta2` module may import test or script tooling.

### Key Entities

- **Stand TLS failure**: an `ssl.SSLError` found anywhere in a wrapped exception chain, rendered with the stand URL and remedy.
- **Helper CA environment**: the four CA bundle variables emitted by the k8s-infra `env` helpers next to the Secret keys.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Offline unit tests prove HTTPS endpoint and CA variable export through the environment script (FR-001, FR-002).
- **SC-002**: Offline unit tests prove every TLS failure path named in FR-003–FR-006 reports TLS with the remedy, and the non-TLS paths keep their previous classification.
- **SC-003**: The full non-integration regression suite, Ruff, strict mypy, import-linter contracts and the architecture effect checker pass.
- **SC-004**: A live run against the HTTPS stands passes with exact-tag cleanup. This is required before relying on the gate after the Secret switch; the completed run is recorded in live integration evidence.

## Assumptions

- The k8s-infra helpers own endpoint values, CA installation and the CA variable values; cveta2 consumes their `env` output and stores none of them.
- The CVAT server reaches MinIO through its cluster-internal HTTP address, which is unaffected by the host-facing name change.
- No clarification was required: the endpoint names and CA variables are defined by the k8s-infra helpers and the implemented diff.
