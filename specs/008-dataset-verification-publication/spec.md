# Feature Specification: Dataset verification and reviewed publication

**Feature Branch**: `feat/dataset-verification-publication`
**Created**: 2026-10-20
**Status**: Clarified
**Input**: Consolidate released ed-killer capabilities into cveta2 with explicit
verification, preparation and dataset publication, following the agreed design.

## User Scenarios & Testing

### User Story 1 - Inspect and explicitly clean CSV data (Priority: P1)

A dataset owner checks a CSV using the cveta2 or clearml-yolo profile. Findings,
original rejected rows and proposed repaired rows are inspectable. Input files
are never overwritten. Cleanup requires an explicit choice.

**Independent Test**: Verify fixture CSVs through both CLI and prompt-free API.

**Acceptance Scenarios**:

1. **Given** malformed annotation groups and duplicate boxes, **When** verification
   runs without cleanup, **Then** it reports all findings without silently accepting
   repairs or filtering.
2. **Given** an explicit cleanup request, **When** validation succeeds after allowed
   corrections, **Then** clean CSV and diagnostics retain original row provenance.
3. **Given** literal cells such as `NA` or `001`, **When** CSVs are read, **Then**
   their original text remains intact.

### User Story 2 - Prepare a reviewable bundle (Priority: P1)

An owner assigns splits externally, then prepares an exported fetch directory.
Preparation resolves destination, parent, class identity, roots and cleanup policy;
it records the decisions and copies all four source CSVs for later inspection.

**Independent Test**: Prepare with fake network ports and actual local images.

**Acceptance Scenarios**:

1. **Given** all four fetch CSVs, valid images and train/val annotations, **When**
   preparation runs, **Then** it writes dataset.csv, dataset.yaml, tasks.yaml,
   diagnostics, source copies and a preparation record into a new directory.
2. **Given** missing decisions, unresolved findings, invalid splits, missing classes
   or inaccessible roots, **When** preparation runs, **Then** it reports actionable
   structured failures and does not produce an uploadable bundle.
3. **Given** an older CSV-only ClearML parent, **When** preparation runs, **Then**
   it blocks and advises choosing a new dataset name.

### User Story 3 - Publish the reviewed bundle later (Priority: P1)

An owner reviews the prepared directory and explicitly uploads it later on the
same machine. Corrections are made to inputs/settings followed by preparation again.

**Independent Test**: Publish an unchanged bundle using an instrumented store;
mutate each bound input or external prerequisite and assert no publication.

**Acceptance Scenarios**:

1. **Given** an unchanged valid bundle, **When** upload runs, **Then** it repeats
   full validation and publishes exactly dataset.csv, dataset.yaml and tasks.yaml.
2. **Given** changed payload/source bytes, class identities, inaccessible images or
   roots, or a newer parent, **When** upload runs, **Then** it blocks and requires
   preparation again.
3. **Given** a publication failure after child creation, **When** reporting failure,
   **Then** it includes the known child identity and never claims finalization.

### User Story 4 - Fetch without automatic publication (Priority: P2)

Fetching remains local export plus its established CVAT/S3 behavior. Explicit bundle
publication replaces the former automatic ClearML side effect.

**Independent Test**: Fetch through existing fake and live CVAT coverage.

**Acceptance Scenarios**:

1. **Given** legacy ClearML configuration, **When** fetch runs, **Then** it never
   initializes or publishes through ClearML.
2. **Given** old publishing flags or Python keywords, **When** called, **Then** the
   removed interface is rejected. Existing CVAT upload behavior remains supported.

## Requirements

- **FR-001**: Integrate the released ed-killer v0.6.0 validation and bundle policies
  into one cveta2 package; the source repository remains unchanged.
- **FR-002**: Provide `verify`, `verify_dataframe`, `schema_for`, `prepare_dataset`
  and `upload_dataset` prompt-free APIs with typed options/results and Cveta2Error
  failures. CLI owns interaction.
- **FR-003**: Preserve cveta2 and clearml-yolo schema, finite geometry, whole-image
  quarantine, profile-specific duplicate handling, class conflicts and positional
  diagnostics. Training boxes require sides and area greater than two; overflow
  strictly below ten pixels may be clipped only with trustworthy dimensions.
- **FR-004**: Use strict lexical CSV input, reject ambiguous headers/row widths and
  preserve original rejected values. Media checks decode canonical files once,
  account for EXIF orientation, and never download URI paths implicitly.
- **FR-005**: Verification defaults to report-only. Explicit cleanup authorizes
  accepted repairs and rejected-row removal; expose `requires_cleanup` separately
  from whether original input is valid. Structural failures cannot be cleaned away.
- **FR-006**: Bundle input contains dataset.csv, obsolete.csv, in_progress.csv and
  deleted.csv, including valid header-only files. Splits are assigned externally.
- **FR-007**: Reconcile classes by API `number` as prod_id, retain aliases and empty
  policy across renames, reject ambiguous identities and disappeared parent IDs,
  and quarantine unknown/empty classes by image.
- **FR-008**: Validate all configured roots and coverage of source paths before
  filtering. Local roots and S3 roots are independent; enforce symlink containment.
  Accept S3 URIs and existing bucket-relative cveta2 keys; a bare key must resolve
  to exactly one approved bucket. No per-object S3 probing is required.
- **FR-009**: Bundles require absolute readable supported local images with sides
  at least ten pixels, nonempty train and val sets, and at least one training box
  in train. Validation may contain only background images, preserving upstream policy.
- **FR-010**: Derive included task IDs from retained rows and obsolete IDs only
  from fully superseded completed tasks, using all four source tables. Preserve
  task-id recency, deletion precedence and explicit task completion.
- **FR-011**: Create a new prepared directory without overwriting inputs or existing
  output. Copy all four source CSVs; bind source/payload hashes, destination,
  parent, options, class decisions and roots in a local preparation record.
  Local broken-image reports retain every original row of affected images.
- **FR-012**: Upload accepts only a prepared directory and never performs cleanup.
  Revalidate retained data/media, source evidence, roots, current classes and
  latest parent; any mismatch blocks. Publish a stable copy of checked bytes.
- **FR-013**: Select only exact project/name finalized, nonarchived parents.
  Legacy parents without metadata block. Remove inherited child files/links and
  synchronously upload exactly three payload files, finalize and verify success.
  Do not change the parent or upload images/reports/source evidence.
- **FR-014**: Remove fetch's publish_clearml keyword, --no-clearml, setup-clearml,
  automatic mappings/settings and unused publisher implementation. Do not rewrite
  users' configuration files automatically. Preserve CVAT upload.
- **FR-015**: Verification exit codes are 0 for passed/explicitly cleaned valid
  outcomes, 1 for unresolved findings/cancellation and 2 for input/config/operational
  failure. Upload returns 0 only after finalization, 1 for cancellation and 2 for
  blocked/error outcomes.
- **FR-016**: Keep network, files, media, SDKs and prompts outside domain/application;
  application workflows receive typed ports. Keep ClearML optional and validation
  available without it. Support Python >=3.12,<3.14.
- **FR-017**: Update Russian CLI/user documentation and portable usage guidance;
  verify unit, architecture, documentation, packaging and tagged live integration
  behavior before independent review and the authorized Git-tag-only release.

## Key Entities

- **Validation result**: clean and original broken rows, row positions, issues,
  original validity and explicit cleanup requirement.
- **Dataset metadata**: public class API URL, stable class identities/aliases/empty
  decisions and independent local/S3 roots.
- **Task manifest**: sorted unique nonnegative included and obsolete task IDs.
- **Prepared bundle**: immutable publication payload, copied source evidence,
  reports and versioned local preparation record.
- **Publication**: finalized ClearML child identity/version and pinned parent.

## Clarifications

### Session 2026-10-20

- Consolidate the tools; do not add split generation or an automated end-to-end pipeline.
- Report first, clean only explicitly, and never clean during upload.
- Review and upload happen later on the same machine; correct inputs then prepare again.
- Copy all source CSVs and repeat full validation before publication.
- A newer parent requires preparation again rather than branching from an older one.
- Remove old fetch publishing interfaces directly, without a compatibility period.

## Success Criteria

- **SC-001**: Fixture coverage preserves upstream validation and bundle policy cases.
- **SC-002**: Every tested mutation of a bound file or prerequisite blocks before
  remote child creation.
- **SC-003**: A live finalized child contains exactly the three documented payload
  files, with parent and local source evidence unchanged.
- **SC-004**: Existing fetch/CVAT upload regression checks and architecture gates pass.
- **SC-005**: CLI and prompt-free API examples, package installation and portable
  guidance agree with the implemented interfaces.

## Assumptions and exclusions

The class API is public unauthenticated HTTP(S); credentials remain in existing
ClearML/environment configuration. Review is local rather than a cryptographic
approval system against a malicious machine owner. No remote service deployment,
package-registry publication, source-repository modification, split assignment or
automatic user-config migration is included.
