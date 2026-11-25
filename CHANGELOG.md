# CHANGELOG

<!-- version list -->

## v0.16.0 (2026-11-25)

### Bug Fixes

- Accept an empty output bucket and keep one archive name constant
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- Correct three user-facing texts of the bundle flow
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- Drop the ignored class-answer fields from PrepareOptions
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- Export the managed result types from the public package
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- Hide URL credentials in verify option errors
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- Keep split mistakes out of CVAT feedback and harden split tests
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- Never print the line of a YAML syntax error
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- Prefill a split only when the image's other cells agree with the parent
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- Reconcile the configuration work with the Part 0 review fixes
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- Refuse an unfilled split in upload-dataset with the same words as verify
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- Refuse every credential-bearing api_url in dataset metadata
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- Summarise the classes of a first preparation in one line
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- Warn about a repeated upload before the parent check
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- **config**: Close the final-review findings of the configuration and setup work
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- **config**: Keep refusing unparsable URLs in the global file
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- **config**: Let a user remove a local override of a project the global file no longer has
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- **config**: Treat an empty overrides block as no override and tidy the merge error
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- **config**: Write team values against the raw global file, never local overrides
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- **doctor**: Never print ClearML credentials from request errors
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- **doctor**: Report a non-HTTP answer from the ClearML server as unreachable
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- **doctor**: Send the ClearML keys the way the SDK does
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- **doctor**: Verify the ClearML configuration against the server
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- **doctor**: Verify TLS with the same CA bundle as the ClearML SDK
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- **managed**: Compare the CVAT server only for datasets with CVAT sources
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- **managed**: Keep a pending receipt of a deleted task instead of stopping
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- **managed**: Keep every class-coverage error in fetch a warning
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- **managed**: Keep quarantines caused only by split mistakes out of CVAT feedback
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- **managed**: Let --first start a lineage over an unreadable latest version
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- **managed**: Name only split rows in split collisions
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- **managed**: Name rejected rows at publish and check roots before hashing
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- **managed**: Name the published and current split of each changed image
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- **managed**: Never echo a source URI from a validation error
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- **managed**: Read nothing from a non-managed latest version
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- **managed**: Stop when the CVAT server differs from the one fetched
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- **setup**: Check every remaining override before removing one value
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- **setup**: Check the remaining overrides when a whole local block is removed
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- **setup**: Hide URL credentials in setup --list
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

### Features

- Add class coverage, split carry-over and traceable-task rules for bundles
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- Add the dataset draft model and preparation value resolution
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- Build prepared-bundle sources as a deterministic tar.gz
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- Bundle workflow — fetch, verify, upload and managed datasets without the hash lock (SIP-278)
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- Configure once — global publication settings, local overrides and one setup command (SIP-279)
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- Fetch, verify, edit, upload-dataset — the bundle flow (SIP-283)
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- List changed splits of published images under pending
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- Make ClearML a required dependency ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- Make ClearML required and remove the split policy (SIP-306)
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- Managed dataset commands without the hash lock (SIP-280)
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- Prepare bundles from the draft, flags and parent without class questions
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- Publish the current bundle files without a hash lock
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- Remove the split policy; dataset prepare propagates published splits
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- Verify prepares a bundle from a directory with cleanup on by default
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- Write a draft dataset.yaml and class coverage warnings on full fetch
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- **config**: Add per-project publication settings and the local_overrides switch
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- **config**: Read local overrides into the effective configuration
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- **config**: Select the global configuration with --global-config and CVETA2_GLOBAL_CONFIG
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- **config**: Write publication fields, the overrides switch, new definitions and local overrides
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- **doctor**: Check the ClearML configuration
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- **managed**: Add split-rule, registry and source comparison helpers
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- **managed**: Dataset prepare cleans by default and reports pending items like verify
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- **managed**: Only a newly completed CVAT task stops a managed command
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- **managed**: Publish validates current files, keeps published splits and rebuilds bookkeeping
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- **managed**: Stop refusing on configuration and registry fingerprints
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- **managed**: Warn about class coverage in dataset fetch
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- **managed**: Write format-3 preparations without checksums
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- **setup**: List the effective configuration with value origins
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- **setup**: Merge setup-cache into setup and add the global wizard
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- **setup**: Set, unset and create configuration values with option flags
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

### Refactoring

- Drop the legacy split-policy handling ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- Drop the old global-configuration spellings and the setup-cache rejection
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- Pass the published file list, output_uri and parent files through the ClearML store
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- Start managed lineages explicitly with --first instead of adopting non-managed parents
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- **doctor**: Send the ClearML login check through requests
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

### Testing

- Cover --first over a version without dataset.yaml and in an empty dataset
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- Drop the tests that only assert the old spellings are gone
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

- Pin that upload-dataset never publishes a row without a valid split
  ([#37](https://github.com/BuckanovNikita/cveta2/pull/37),
  [`571a35a`](https://github.com/BuckanovNikita/cveta2/commit/571a35a9cfc53d43a378f7de33cfbd85da3c8e77))

### Breaking Changes

- A shared configuration that still has datasets.<name>.splits is rejected as an unknown key, and a
  parent published by cveta2 0.15 with managed.definition.splits is no longer read as a managed
  parent.


## v0.15.1 (2026-11-21)

### Bug Fixes

- Fail on missing images, share one bbox clip rule, reject non-canonical upload names (SIP-172,
  SIP-173, SIP-235) ([#31](https://github.com/BuckanovNikita/cveta2/pull/31),
  [`9492a39`](https://github.com/BuckanovNikita/cveta2/commit/9492a39fe1416fc9b924e4a2bf3938e0a188c749))

### Refactoring

- Declare type aliases with the type statement (SIP-215)
  ([`245f181`](https://github.com/BuckanovNikita/cveta2/commit/245f181089bf33a8c18012bf85bea1e1b5be5ad3))

- Enforce @override on overriding methods (SIP-214)
  ([#25](https://github.com/BuckanovNikita/cveta2/pull/25),
  [`6debf17`](https://github.com/BuckanovNikita/cveta2/commit/6debf1757f8f238a200211ab09aab4a5986ac661))

### Testing

- **integration**: Move the live-test stack to CVAT server 2.82.0 (SIP-231)
  ([#30](https://github.com/BuckanovNikita/cveta2/pull/30),
  [`c5e9df1`](https://github.com/BuckanovNikita/cveta2/commit/c5e9df1fede1e3e93ac713a57d58804e86e025df))


## v0.15.0 (2026-11-21)

### Build System

- Ship DOCS.md instead of GLOSSARY.md in the sdist
  ([#21](https://github.com/BuckanovNikita/cveta2/pull/21),
  [`118177c`](https://github.com/BuckanovNikita/cveta2/commit/118177cc96ed4a055a60083a755f94ce98db57b9))

- **release**: Keep the version in the package so a release leaves uv.lock alone (SIP-149)
  ([#20](https://github.com/BuckanovNikita/cveta2/pull/20),
  [`332dfb0`](https://github.com/BuckanovNikita/cveta2/commit/332dfb025388cb117a55f72618b900f60fc600b9))

### Documentation

- Add a short Russian README so the package builds again (SIP-161)
  ([#22](https://github.com/BuckanovNikita/cveta2/pull/22),
  [`027616d`](https://github.com/BuckanovNikita/cveta2/commit/027616d5dea7130f459fe97298c525d79760696e))

- Add configuration and cache pages with setup, setup-cache and doctor (SIP-164)
  ([#22](https://github.com/BuckanovNikita/cveta2/pull/22),
  [`027616d`](https://github.com/BuckanovNikita/cveta2/commit/027616d5dea7130f459fe97298c525d79760696e))

- Add details found in a serial live re-check (SIP-160)
  ([#22](https://github.com/BuckanovNikita/cveta2/pull/22),
  [`027616d`](https://github.com/BuckanovNikita/cveta2/commit/027616d5dea7130f459fe97298c525d79760696e))

- Add Russian user documentation for the CLI, Python API and dataset format (SIP-160)
  ([#22](https://github.com/BuckanovNikita/cveta2/pull/22),
  [`027616d`](https://github.com/BuckanovNikita/cveta2/commit/027616d5dea7130f459fe97298c525d79760696e))

- Add the dataset command page for managed datasets (SIP-169)
  ([#22](https://github.com/BuckanovNikita/cveta2/pull/22),
  [`027616d`](https://github.com/BuckanovNikita/cveta2/commit/027616d5dea7130f459fe97298c525d79760696e))

- Add the domain glossary with the Russian wording of each term (SIP-162)
  ([#22](https://github.com/BuckanovNikita/cveta2/pull/22),
  [`027616d`](https://github.com/BuckanovNikita/cveta2/commit/027616d5dea7130f459fe97298c525d79760696e))

- Add the fetch, fetch-task, whats-new and s3-sync command pages (SIP-166)
  ([#22](https://github.com/BuckanovNikita/cveta2/pull/22),
  [`027616d`](https://github.com/BuckanovNikita/cveta2/commit/027616d5dea7130f459fe97298c525d79760696e))

- Add the labels, ignore and task command pages (SIP-165)
  ([#22](https://github.com/BuckanovNikita/cveta2/pull/22),
  [`027616d`](https://github.com/BuckanovNikita/cveta2/commit/027616d5dea7130f459fe97298c525d79760696e))

- Add the Python API page (SIP-170) ([#22](https://github.com/BuckanovNikita/cveta2/pull/22),
  [`027616d`](https://github.com/BuckanovNikita/cveta2/commit/027616d5dea7130f459fe97298c525d79760696e))

- Add the upload, merge and convert command pages (SIP-167)
  ([#22](https://github.com/BuckanovNikita/cveta2/pull/22),
  [`027616d`](https://github.com/BuckanovNikita/cveta2/commit/027616d5dea7130f459fe97298c525d79760696e))

- Add the verify and upload-dataset command pages (SIP-168)
  ([#22](https://github.com/BuckanovNikita/cveta2/pull/22),
  [`027616d`](https://github.com/BuckanovNikita/cveta2/commit/027616d5dea7130f459fe97298c525d79760696e))

- Add the workflows page and docs index, finish the README and glossary (SIP-171)
  ([#22](https://github.com/BuckanovNikita/cveta2/pull/22),
  [`027616d`](https://github.com/BuckanovNikita/cveta2/commit/027616d5dea7130f459fe97298c525d79760696e))

- Compress agent instructions and docs into AGENTS.md and DOCS.md
  ([#21](https://github.com/BuckanovNikita/cveta2/pull/21),
  [`118177c`](https://github.com/BuckanovNikita/cveta2/commit/118177cc96ed4a055a60083a755f94ce98db57b9))

- Compress agent instructions and docs into AGENTS.md and DOCS.md (SIP-159)
  ([#21](https://github.com/BuckanovNikita/cveta2/pull/21),
  [`118177c`](https://github.com/BuckanovNikita/cveta2/commit/118177cc96ed4a055a60083a755f94ce98db57b9))

- Correct three statements found in review (SIP-160)
  ([#22](https://github.com/BuckanovNikita/cveta2/pull/22),
  [`027616d`](https://github.com/BuckanovNikita/cveta2/commit/027616d5dea7130f459fe97298c525d79760696e))

- Describe the CSV columns, full-fetch files and prepared dataset directory (SIP-163)
  ([#22](https://github.com/BuckanovNikita/cveta2/pull/22),
  [`027616d`](https://github.com/BuckanovNikita/cveta2/commit/027616d5dea7130f459fe97298c525d79760696e))

- Drop facts the repository already states from AGENTS.md and DOCS.md
  ([`a1f7ddf`](https://github.com/BuckanovNikita/cveta2/commit/a1f7ddfe2f21edacdbf2ea67cd7c72347995bed8))

- Drop the manual restrictions section from the upload page (SIP-160)
  ([#22](https://github.com/BuckanovNikita/cveta2/pull/22),
  [`027616d`](https://github.com/BuckanovNikita/cveta2/commit/027616d5dea7130f459fe97298c525d79760696e))

- **agents**: Add agent skills setup with Linear as the issue tracker
  ([`dfdc890`](https://github.com/BuckanovNikita/cveta2/commit/dfdc890051ec28f2b3193d8ed961c7b12b2b4683))

### Features

- **cvat**: Require CVAT 2.82.0 (SIP-216)
  ([`24753f6`](https://github.com/BuckanovNikita/cveta2/commit/24753f69b2a789d03aca3cdb2364312d5efea6f6))

### Refactoring

- Lint as Python 3.12 and adopt PEP 695 generics and Self (SIP-213)
  ([#24](https://github.com/BuckanovNikita/cveta2/pull/24),
  [`79df55b`](https://github.com/BuckanovNikita/cveta2/commit/79df55b44bb62fe24990a148699afbe7ad535f4d))

### Breaking Changes

- **cvat**: The minimum supported CVAT server is 2.82.0, and upload.image_quality: 0 is rejected
  when the configuration is loaded (the allowed range is 1-100).


## v0.14.1 (2026-11-18)

### Build System

- **sdist**: Stop shipping the frozen contract files (SIP-144)
  ([#17](https://github.com/BuckanovNikita/cveta2/pull/17),
  [`4df7fd0`](https://github.com/BuckanovNikita/cveta2/commit/4df7fd00074a4214508170672f5bc0af11721217))

### Continuous Integration

- **release**: Pin checkout and setup-python to Node.js 24 releases (SIP-145)
  ([#16](https://github.com/BuckanovNikita/cveta2/pull/16),
  [`bf0ba54`](https://github.com/BuckanovNikita/cveta2/commit/bf0ba545109d0eb46289f377d3439a49efc34df3))

### Performance Improvements

- **managed**: Keep fetch reuse for sources whose definition did not change (SIP-147)
  ([#18](https://github.com/BuckanovNikita/cveta2/pull/18),
  [`9a06842`](https://github.com/BuckanovNikita/cveta2/commit/9a0684285414903406df19004efd984703b77fa6))


## v0.14.0 (2026-11-18)

### Bug Fixes

- **bundle**: Check reused yaml anchors once ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **bundle**: Keep pending deletions as evidence of an open task
  ([#15](https://github.com/BuckanovNikita/cveta2/pull/15),
  [`25d0dbe`](https://github.com/BuckanovNikita/cveta2/commit/25d0dbec224978179d9b263d821a99319b9cbe65))

- **bundle**: Report deeply nested yaml and json as upload errors
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **bundle**: Stop listing image extensions that cannot be decoded
  ([#13](https://github.com/BuckanovNikita/cveta2/pull/13),
  [`14e3058`](https://github.com/BuckanovNikita/cveta2/commit/14e3058d5a3c20b07800f71570eb424e1cb0acb7))

- **cache**: Cache annotations per job and rebuild records every fetch
  ([#15](https://github.com/BuckanovNikita/cveta2/pull/15),
  [`25d0dbe`](https://github.com/BuckanovNikita/cveta2/commit/25d0dbec224978179d9b263d821a99319b9cbe65))

- **cache**: Cover invalidation when the cache settings cannot load
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **cache**: Invalidate the cache that the selected configuration names
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **cache**: Keep an unusable s3 mirror from breaking fetch and mutations
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **cache**: Keep the mirror on denied deletes and skip undated jobs
  ([#15](https://github.com/BuckanovNikita/cveta2/pull/15),
  [`25d0dbe`](https://github.com/BuckanovNikita/cveta2/commit/25d0dbec224978179d9b263d821a99319b9cbe65))

- **cache**: Serve a fully cached task with one CVAT request
  ([#15](https://github.com/BuckanovNikita/cveta2/pull/15),
  [`25d0dbe`](https://github.com/BuckanovNikita/cveta2/commit/25d0dbec224978179d9b263d821a99319b9cbe65))

- **client**: Treat non-decimal digits in selectors as names
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **client**: Warn about image names mark-deleted cannot match
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **config**: Create the migrated shared team file with the umask mode
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **config**: Keep concurrent shared-policy edits instead of reverting them
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **config**: Keep legacy migration working with the stricter s3 roots
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **config**: Name the file and position in shared YAML diagnostics
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **config**: Reject malformed s3 roots when configuration loads
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **config**: Report a damaged migration journal with its recovery steps
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **config**: Report an unreadable config directory as a typed error
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **config**: Report unreadable or unwritable personal config as a typed error
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **config**: Save the personal config atomically and owner-only
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **convert**: Clip out-of-image boxes in YOLO export
  ([#13](https://github.com/BuckanovNikita/cveta2/pull/13),
  [`14e3058`](https://github.com/BuckanovNikita/cveta2/commit/14e3058d5a3c20b07800f71570eb424e1cb0acb7))

- **convert**: Clip out-of-image boxes in YOLO export (SIP-78)
  ([#13](https://github.com/BuckanovNikita/cveta2/pull/13),
  [`14e3058`](https://github.com/BuckanovNikita/cveta2/commit/14e3058d5a3c20b07800f71570eb424e1cb0acb7))

- **convert**: Confine local image lookup to the search directory
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **convert**: Match prediction images by suffix case-insensitively
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **convert**: Name rounding in the dropped-box warning
  ([#13](https://github.com/BuckanovNikita/cveta2/pull/13),
  [`14e3058`](https://github.com/BuckanovNikita/cveta2/commit/14e3058d5a3c20b07800f71570eb424e1cb0acb7))

- **convert**: Never use the previous export as its own image source
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **convert**: Probe fixed suffix cases instead of listing the directory
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **convert**: Reject linked yolo label and metadata destinations
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **convert**: Skip unreadable yolo labels and name bad inputs
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **cvat**: Report sdk connection setup failures as CvatApiError
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **cvat**: Return issue comments in creation order
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **cvat**: Stop urllib3 from replaying non-safe requests
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **cvat**: Translate sdk deserialization errors into CvatApiError
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **dataset**: Exit 2 on managed dataset operational errors
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **dataset**: Report an uncreatable managed fetch output parent
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **doctor**: Leave the per-user prompt history out of cache permission checks
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **fetch**: Completed tasks decide deletions; annotation cache per job (SIP-85, SIP-82)
  ([#15](https://github.com/BuckanovNikita/cveta2/pull/15),
  [`25d0dbe`](https://github.com/BuckanovNikita/cveta2/commit/25d0dbec224978179d9b263d821a99319b9cbe65))

- **hooks**: Keep commit-message validation active when hooks are skipped
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **integration**: Admit the session quota only on schedulable nodes
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **integration**: Bound live-session seeding with a deadline
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **integration**: Clean blocked setup after infrastructure loss
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **integration**: Delete a namespace whose create was accepted but not confirmed
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **integration**: Refuse to overwrite a kept session record from pytest
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **integration**: Report lost connectivity after readyz as unavailable
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **integration**: Stop seed children and request deletion first on interrupt
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **integration**: Tear sessions down on SIGTERM and stop by name past a bad record
  ([`d74addc`](https://github.com/BuckanovNikita/cveta2/commit/d74addc82076b67c6459c3a34bbf227f4380ead1))

- **integration**: Treat a refused API connection as an unavailable cluster
  ([`4bd3e32`](https://github.com/BuckanovNikita/cveta2/commit/4bd3e32d4c15352069798150ba6351a4c646e098))

- **labels**: Require retyped names when the usage count is incomplete
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **managed**: Bind fetch reuse and preparation to relevant fields only
  ([#13](https://github.com/BuckanovNikita/cveta2/pull/13),
  [`14e3058`](https://github.com/BuckanovNikita/cveta2/commit/14e3058d5a3c20b07800f71570eb424e1cb0acb7))

- **managed**: Bind fetch reuse and preparation to relevant fields only (SIP-88)
  ([#13](https://github.com/BuckanovNikita/cveta2/pull/13),
  [`14e3058`](https://github.com/BuckanovNikita/cveta2/commit/14e3058d5a3c20b07800f71570eb424e1cb0acb7))

- **managed**: Check s3 roots and source nesting at preparation
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **managed**: Keep a legacy parent's published splits on adoption
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **managed**: Preserve full label and registry evidence
  ([#3](https://github.com/BuckanovNikita/cveta2/pull/3),
  [`edeee69`](https://github.com/BuckanovNikita/cveta2/commit/edeee69bd20e5655653c4263fb864aef00dd7d54))

- **managed**: Preserve full label and registry evidence (SIP-99)
  ([#3](https://github.com/BuckanovNikita/cveta2/pull/3),
  [`edeee69`](https://github.com/BuckanovNikita/cveta2/commit/edeee69bd20e5655653c4263fb864aef00dd7d54))

- **managed**: Rebase pending feedback only to the end of its chain
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **managed**: Reject parents without dataset.yaml
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **managed**: Retry feedback after a sibling issue moved the task
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **managed**: Share the feedback ledger across preparations of one fetch
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **mutation**: Fail a run whose budget expires before any mutant is judged
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **mutation**: Retain expiry after graceful worker exit
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **partition**: Let only completed tasks decide deletions
  ([#15](https://github.com/BuckanovNikita/cveta2/pull/15),
  [`25d0dbe`](https://github.com/BuckanovNikita/cveta2/commit/25d0dbec224978179d9b263d821a99319b9cbe65))

- **partition**: Mark every reopened image in in_progress.csv
  ([#15](https://github.com/BuckanovNikita/cveta2/pull/15),
  [`25d0dbe`](https://github.com/BuckanovNikita/cveta2/commit/25d0dbec224978179d9b263d821a99319b9cbe65))

- **review**: Close cumulative remediation gaps
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **review**: Integrate review remediation (SIP-68)
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **review**: Resolve independent integration findings
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **s3**: End CLI S3 failures with a message naming the storage
  ([#13](https://github.com/BuckanovNikita/cveta2/pull/13),
  [`14e3058`](https://github.com/BuckanovNikita/cveta2/commit/14e3058d5a3c20b07800f71570eb424e1cb0acb7))

- **s3**: Keep the per-transfer traceback below the CLI's default level
  ([#13](https://github.com/BuckanovNikita/cveta2/pull/13),
  [`14e3058`](https://github.com/BuckanovNikita/cveta2/commit/14e3058d5a3c20b07800f71570eb424e1cb0acb7))

- **s3**: Log one line per failed transfer, keeping the traceback at debug
  ([#13](https://github.com/BuckanovNikita/cveta2/pull/13),
  [`14e3058`](https://github.com/BuckanovNikita/cveta2/commit/14e3058d5a3c20b07800f71570eb424e1cb0acb7))

- **s3**: Translate only operational S3 failures
  ([#13](https://github.com/BuckanovNikita/cveta2/pull/13),
  [`14e3058`](https://github.com/BuckanovNikita/cveta2/commit/14e3058d5a3c20b07800f71570eb424e1cb0acb7))

- **s3,upload**: CLI S3 failures without traceback; annotation-write checkpoint on resume (SIP-80,
  SIP-81) ([#13](https://github.com/BuckanovNikita/cveta2/pull/13),
  [`14e3058`](https://github.com/BuckanovNikita/cveta2/commit/14e3058d5a3c20b07800f71570eb424e1cb0acb7))

- **s3-sync**: Fail the command when objects could not be downloaded
  ([#13](https://github.com/BuckanovNikita/cveta2/pull/13),
  [`14e3058`](https://github.com/BuckanovNikita/cveta2/commit/14e3058d5a3c20b07800f71570eb424e1cb0acb7))

- **setup**: Attach an existing shared file from the setup wizard
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **setup**: Keep one-run environment overrides out of the attached-mode save
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **setup**: Treat closed standard input at a prompt as non-interactive
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **upload**: Drop the pending annotation mark when the task is replaced
  ([#13](https://github.com/BuckanovNikita/cveta2/pull/13),
  [`14e3058`](https://github.com/BuckanovNikita/cveta2/commit/14e3058d5a3c20b07800f71570eb424e1cb0acb7))

- **upload**: Hold an exclusive lock for the whole upload run
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **upload**: Join prefix-relative server files onto the storage prefix
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **upload**: Let a definitively rejected task create run again
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **upload**: Name the storage when images fail to reach S3
  ([#13](https://github.com/BuckanovNikita/cveta2/pull/13),
  [`14e3058`](https://github.com/BuckanovNikita/cveta2/commit/14e3058d5a3c20b07800f71570eb424e1cb0acb7))

- **upload**: Refuse unsafe image names before any lookup or remote effect
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **upload**: Report an unreadable --in-progress file as a typed error
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **upload**: Run unlocked without touching a lock file where fcntl is missing
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **upload**: Wait and re-check before resending interrupted annotations
  ([#13](https://github.com/BuckanovNikita/cveta2/pull/13),
  [`14e3058`](https://github.com/BuckanovNikita/cveta2/commit/14e3058d5a3c20b07800f71570eb424e1cb0acb7))

- **verification**: Invalidate testmon history when pytest startup code changes
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **verify**: Accept the multi-issue issue_state that fetch writes
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **whats-new**: Ignore unusable task_id cells in the baseline
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **whats-new**: Skip a baseline sibling with invalid encoding
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

### Build System

- **deps**: Pillow 13 and drop undecodable image extensions (SIP-84)
  ([#13](https://github.com/BuckanovNikita/cveta2/pull/13),
  [`14e3058`](https://github.com/BuckanovNikita/cveta2/commit/14e3058d5a3c20b07800f71570eb424e1cb0acb7))

- **deps**: Upgrade Pillow to 13.0.0 and require 11.3 or newer
  ([#13](https://github.com/BuckanovNikita/cveta2/pull/13),
  [`14e3058`](https://github.com/BuckanovNikita/cveta2/commit/14e3058d5a3c20b07800f71570eb424e1cb0acb7))

### Continuous Integration

- **release**: Check the release subject and set the bot as author
  ([#14](https://github.com/BuckanovNikita/cveta2/pull/14),
  [`db3aca9`](https://github.com/BuckanovNikita/cveta2/commit/db3aca9de7fefc2247c3c9436b25f1a232afaf29))

- **release**: Cut releases with semantic-release after merges into main
  ([#14](https://github.com/BuckanovNikita/cveta2/pull/14),
  [`db3aca9`](https://github.com/BuckanovNikita/cveta2/commit/db3aca9de7fefc2247c3c9436b25f1a232afaf29))

- **release**: Cut releases with semantic-release after merges into main (SIP-143)
  ([#14](https://github.com/BuckanovNikita/cveta2/pull/14),
  [`db3aca9`](https://github.com/BuckanovNikita/cveta2/commit/db3aca9de7fefc2247c3c9436b25f1a232afaf29))

- **release**: Run plain semantic-release without the wrapper script
  ([#14](https://github.com/BuckanovNikita/cveta2/pull/14),
  [`db3aca9`](https://github.com/BuckanovNikita/cveta2/commit/db3aca9de7fefc2247c3c9436b25f1a232afaf29))

### Documentation

- Apply independent review of the contract wording changes
  ([#13](https://github.com/BuckanovNikita/cveta2/pull/13),
  [`14e3058`](https://github.com/BuckanovNikita/cveta2/commit/14e3058d5a3c20b07800f71570eb424e1cb0acb7))

- Describe the 60/20/20 managed split as a default
  ([#13](https://github.com/BuckanovNikita/cveta2/pull/13),
  [`14e3058`](https://github.com/BuckanovNikita/cveta2/commit/14e3058d5a3c20b07800f71570eb424e1cb0acb7))

- Keep snapshot guidance focused on user actions
  ([#3](https://github.com/BuckanovNikita/cveta2/pull/3),
  [`edeee69`](https://github.com/BuckanovNikita/cveta2/commit/edeee69bd20e5655653c4263fb864aef00dd7d54))

- State that the Linear contracts are active
  ([#13](https://github.com/BuckanovNikita/cveta2/pull/13),
  [`14e3058`](https://github.com/BuckanovNikita/cveta2/commit/14e3058d5a3c20b07800f71570eb424e1cb0acb7))

- State the Linear contracts are active and correct three guide statements (SIP-134, SIP-135,
  SIP-136, SIP-139) ([#13](https://github.com/BuckanovNikita/cveta2/pull/13),
  [`14e3058`](https://github.com/BuckanovNikita/cveta2/commit/14e3058d5a3c20b07800f71570eb424e1cb0acb7))

- **agents**: Define the documentation-only gate and waiver by merge
  ([#6](https://github.com/BuckanovNikita/cveta2/pull/6),
  [`ef038f1`](https://github.com/BuckanovNikita/cveta2/commit/ef038f11933efa224559f8ddeb98a28f70963f84))

- **cache**: Describe invalidation and unavailable s3 mirror behaviour
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **cli**: Describe wizard attachment and the prompt-history exclusion
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **cli**: Keep the upload recovery notes as separate paragraphs
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **cli**: State that either a zero width or height stops the export
  ([#13](https://github.com/BuckanovNikita/cveta2/pull/13),
  [`14e3058`](https://github.com/BuckanovNikita/cveta2/commit/14e3058d5a3c20b07800f71570eb424e1cb0acb7))

- **constitution**: Own one session namespace per live run
  ([`dac09b3`](https://github.com/BuckanovNikita/cveta2/commit/dac09b38bdd29a14e5845739699a40811fe5ee0c))

- **convert**: Describe export source exclusion and unreadable yolo inputs
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **managed**: Describe legacy parent adoption and csv-only parents
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **managed**: Scope when prepare or publish still need a new run
  ([#13](https://github.com/BuckanovNikita/cveta2/pull/13),
  [`14e3058`](https://github.com/BuckanovNikita/cveta2/commit/14e3058d5a3c20b07800f71570eb424e1cb0acb7))

- **managed**: State when a policy edit needs a new fetch or lineage
  ([#13](https://github.com/BuckanovNikita/cveta2/pull/13),
  [`14e3058`](https://github.com/BuckanovNikita/cveta2/commit/14e3058d5a3c20b07800f71570eb424e1cb0acb7))

- **plans**: Record the 2026-11-17 code review and its remediation plan
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **readme**: Align the rewritten guide with current behavior (SIP-89)
  ([#5](https://github.com/BuckanovNikita/cveta2/pull/5),
  [`66adb0a`](https://github.com/BuckanovNikita/cveta2/commit/66adb0a642c8b3bae5f8ccdab66a2088507e307e))

- **readme**: Bring the rewritten Russian guide up to date (SIP-89)
  ([#5](https://github.com/BuckanovNikita/cveta2/pull/5),
  [`66adb0a`](https://github.com/BuckanovNikita/cveta2/commit/66adb0a642c8b3bae5f8ccdab66a2088507e307e))

- **readme**: Correct the clearml extra scope and add install from main
  ([#13](https://github.com/BuckanovNikita/cveta2/pull/13),
  [`14e3058`](https://github.com/BuckanovNikita/cveta2/commit/14e3058d5a3c20b07800f71570eb424e1cb0acb7))

- **readme**: Rewrite the user guide in plain language
  ([#5](https://github.com/BuckanovNikita/cveta2/pull/5),
  [`66adb0a`](https://github.com/BuckanovNikita/cveta2/commit/66adb0a642c8b3bae5f8ccdab66a2088507e307e))

- **release**: Stop merging while a release commit lacks its tag
  ([#14](https://github.com/BuckanovNikita/cveta2/pull/14),
  [`db3aca9`](https://github.com/BuckanovNikita/cveta2/commit/db3aca9de7fefc2247c3c9436b25f1a232afaf29))

- **specs**: Align lifecycle contract with the implemented commands
  ([`3fdde91`](https://github.com/BuckanovNikita/cveta2/commit/3fdde91da96f9d39467e503c7ba39355267fa746))

- **specs**: Correct measurement claims and kept-session design
  ([`a8e9324`](https://github.com/BuckanovNikita/cveta2/commit/a8e9324aaaef7dec188e3b038835151825f0fb13))

- **specs**: Record clean-tip acceptance of session-owned infrastructure
  ([`911621d`](https://github.com/BuckanovNikita/cveta2/commit/911621d1b6d2c7fd3ecd2f663b87b415be46efe0))

- **specs**: Record live verification of session-owned infrastructure
  ([`739c964`](https://github.com/BuckanovNikita/cveta2/commit/739c964f9f0bd594fc9ab76672a1739f123ee778))

- **specs**: Record test-phase interrupts and correct run attributions
  ([`63cd255`](https://github.com/BuckanovNikita/cveta2/commit/63cd25522f29c566a25840a944f6486e7d3451ed))

- **specs**: Specify session-owned live-test infrastructure
  ([`283fc7e`](https://github.com/BuckanovNikita/cveta2/commit/283fc7e9f6dfe97dd740ed90eb82e52351ea829d))

### Features

- **cvat**: Read job update times and per-job annotations
  ([#15](https://github.com/BuckanovNikita/cveta2/pull/15),
  [`25d0dbe`](https://github.com/BuckanovNikita/cveta2/commit/25d0dbec224978179d9b263d821a99319b9cbe65))

- **merge**: Drop old images reopened after a completed deletion
  ([#15](https://github.com/BuckanovNikita/cveta2/pull/15),
  [`25d0dbe`](https://github.com/BuckanovNikita/cveta2/commit/25d0dbec224978179d9b263d821a99319b9cbe65))

### Refactoring

- **convert**: Split per-directory image lookup out of resolve_images
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **managed**: Alias external registry field names
  ([#3](https://github.com/BuckanovNikita/cveta2/pull/3),
  [`edeee69`](https://github.com/BuckanovNikita/cveta2/commit/edeee69bd20e5655653c4263fb864aef00dd7d54))

- **upload**: Extract task creation from _ensure_task
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

### Testing

- Cover mutation gaps in config and class API
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- Pin reopen and layout edges found by mutation testing
  ([#15](https://github.com/BuckanovNikita/cveta2/pull/15),
  [`25d0dbe`](https://github.com/BuckanovNikita/cveta2/commit/25d0dbec224978179d9b263d821a99319b9cbe65))

- **architecture**: Flag clock, asyncio and path-walk effects in inner layers
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **bundle**: Give the legacy in-progress evidence a shape column
  ([#15](https://github.com/BuckanovNikita/cveta2/pull/15),
  [`25d0dbe`](https://github.com/BuckanovNikita/cveta2/commit/25d0dbec224978179d9b263d821a99319b9cbe65))

- **cli**: Check S3 exit messages and logs carry no traceback text
  ([#13](https://github.com/BuckanovNikita/cveta2/pull/13),
  [`14e3058`](https://github.com/BuckanovNikita/cveta2/commit/14e3058d5a3c20b07800f71570eb424e1cb0acb7))

- **cli**: Stop reading stderr to prove an S3 exit has no traceback
  ([#13](https://github.com/BuckanovNikita/cveta2/pull/13),
  [`14e3058`](https://github.com/BuckanovNikita/cveta2/commit/14e3058d5a3c20b07800f71570eb424e1cb0acb7))

- **convert**: Count several clipped and dropped boxes in one image
  ([#13](https://github.com/BuckanovNikita/cveta2/pull/13),
  [`14e3058`](https://github.com/BuckanovNikita/cveta2/commit/14e3058d5a3c20b07800f71570eb424e1cb0acb7))

- **convert**: Cover output exclusion in both image lookup passes
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **doctor**: Decode the prompt history file name before building a path
  ([#4](https://github.com/BuckanovNikita/cveta2/pull/4),
  [`dda2fb2`](https://github.com/BuckanovNikita/cveta2/commit/dda2fb2dde7afd093175c6df62cd0f1bcc9b3623))

- **integration**: Check a moved job reaches the next cached fetch
  ([#15](https://github.com/BuckanovNikita/cveta2/pull/15),
  [`25d0dbe`](https://github.com/BuckanovNikita/cveta2/commit/25d0dbec224978179d9b263d821a99319b9cbe65))

- **integration**: Deploy session-owned CVAT, MinIO and ClearML
  ([`c8d26d8`](https://github.com/BuckanovNikita/cveta2/commit/c8d26d897708556c3be47f32a7457e7c407badc4))

- **integration**: Report blocked setup once and keep its cause
  ([`bbed6e0`](https://github.com/BuckanovNikita/cveta2/commit/bbed6e035ae3d9ebef116ec88f607a32dde275f6))

- **managed**: Pin fingerprint order, metadata binding and dataset lookup
  ([#13](https://github.com/BuckanovNikita/cveta2/pull/13),
  [`14e3058`](https://github.com/BuckanovNikita/cveta2/commit/14e3058d5a3c20b07800f71570eb424e1cb0acb7))

- **managed**: Protect persisted evidence compatibility
  ([#3](https://github.com/BuckanovNikita/cveta2/pull/3),
  [`edeee69`](https://github.com/BuckanovNikita/cveta2/commit/edeee69bd20e5655653c4263fb864aef00dd7d54))

- **partition**: Pin the accepted edges of completed deletions
  ([#15](https://github.com/BuckanovNikita/cveta2/pull/15),
  [`25d0dbe`](https://github.com/BuckanovNikita/cveta2/commit/25d0dbec224978179d9b263d821a99319b9cbe65))

- **s3**: Pin the storage note on a failure inside an upload batch
  ([#13](https://github.com/BuckanovNikita/cveta2/pull/13),
  [`14e3058`](https://github.com/BuckanovNikita/cveta2/commit/14e3058d5a3c20b07800f71570eb424e1cb0acb7))

- **s3-sync**: Cover --root and a skipped project in the command
  ([#13](https://github.com/BuckanovNikita/cveta2/pull/13),
  [`14e3058`](https://github.com/BuckanovNikita/cveta2/commit/14e3058d5a3c20b07800f71570eb424e1cb0acb7))

- **upload**: Resume after the pending mark could not be cleared
  ([#13](https://github.com/BuckanovNikita/cveta2/pull/13),
  [`14e3058`](https://github.com/BuckanovNikita/cveta2/commit/14e3058d5a3c20b07800f71570eb424e1cb0acb7))


## v0.13.3 (2026-11-09)

### Bug Fixes

- Serialize affected test selection
  ([`0405ea0`](https://github.com/BuckanovNikita/cveta2/commit/0405ea033510eaa90a624b8a8907de11b10206fd))

- Verify committed fixture changes in final hook runs
  ([`4f99a3e`](https://github.com/BuckanovNikita/cveta2/commit/4f99a3e7248e978f8a84ca7b886c8b65a0e2da15))

- **hooks**: Reject deleted workflow files before legacy fallback
  ([`e8c308c`](https://github.com/BuckanovNikita/cveta2/commit/e8c308ca81d2c0ee2288bb765ac7589546c77c47))

- **hooks**: Verify interpreter selection changes
  ([`e937b6f`](https://github.com/BuckanovNikita/cveta2/commit/e937b6fad31e619a0550df5a03822a8cf8dca3c7))

- **verification**: Preserve release gates and infrastructure outcomes
  ([`f2e8cc2`](https://github.com/BuckanovNikita/cveta2/commit/f2e8cc2eda7ca91a438e2d1748d8c7a8455c1399))

- **verification**: Retain Python 3.12 registry error handling
  ([`bd6ca39`](https://github.com/BuckanovNikita/cveta2/commit/bd6ca396ac837adc5865125d8762ac43eabc1b4b))

### Documentation

- Clarify domain boundaries and preserve specification meaning
  ([`936fa93`](https://github.com/BuckanovNikita/cveta2/commit/936fa932a95c69a0e5159a3685358c3600922c2a))

- Consolidate specifications into functional descriptions
  ([`c55c77e`](https://github.com/BuckanovNikita/cveta2/commit/c55c77ea088e242808bb6b344ed17ce57c10c101))

- Define self-contained functional behavior
  ([`8437049`](https://github.com/BuckanovNikita/cveta2/commit/843704982e012a6f4f24dcbf928b1023bf398826))

- Drop the portable usage skill stage
  ([`da52705`](https://github.com/BuckanovNikita/cveta2/commit/da5270599c07ea9108e0689ab6d28b6e91264873))

- Replace progress records with fresh product specifications
  ([`8b6b11f`](https://github.com/BuckanovNikita/cveta2/commit/8b6b11f52509e29136dc58cb185a6d711fd99541))

- Retarget dataset-contract links and name the pre-reset checkpoint
  ([`0bb9a24`](https://github.com/BuckanovNikita/cveta2/commit/0bb9a24d4a6c2e6caeadcb351f1454b394ace47f))

- **hooks**: Name the configured rewriting hook
  ([`3044f2b`](https://github.com/BuckanovNikita/cveta2/commit/3044f2bfe538d4f443c4a7f6821753e47e4ae070))

- **skills**: Fix live-test helper resolution and release push gate
  ([`30d0033`](https://github.com/BuckanovNikita/cveta2/commit/30d0033aff351000118d5f386ef71f4c7fc5645f))

- **verification**: Record acceptance and convergence evidence
  ([`31fcc31`](https://github.com/BuckanovNikita/cveta2/commit/31fcc3176d320e82fdec8954a349fece4eae71ff))

### Testing

- Remove development tooling self-tests
  ([`7422092`](https://github.com/BuckanovNikita/cveta2/commit/7422092ed1cc0bb05c843d17afcd20b319a8ad96))


## v0.13.2 (2026-11-06)

### Bug Fixes

- **scripts**: Address independent review of the scripts simplification
  ([`45d16e7`](https://github.com/BuckanovNikita/cveta2/commit/45d16e77004b0925f0394075374a4f433e6e792c))

### Build System

- **deps**: Drop the unused inline-snapshot dev dependency
  ([`fe42408`](https://github.com/BuckanovNikita/cveta2/commit/fe424085069da78df2820d95c2e00045df0adc25))

### Documentation

- Bind stand delivery evidence to the preserved candidate
  ([`c1137ec`](https://github.com/BuckanovNikita/cveta2/commit/c1137ecbf741b946afd2d06272dae95ef43e6de4))

- Close verified HTTPS stand delivery
  ([`fdfd09c`](https://github.com/BuckanovNikita/cveta2/commit/fdfd09c97772ae18affbf66df05391500eb94d0c))

- Reconcile HTTPS stand delivery and instruction receipts
  ([`6252649`](https://github.com/BuckanovNikita/cveta2/commit/62526490184e69d853ea45d8c58e3a1dab3795ab))

- Record managed dataset release acceptance
  ([`3ec0fc7`](https://github.com/BuckanovNikita/cveta2/commit/3ec0fc798058ab4875acba1c22d00ccd2f0ee414))

- **agents**: Refactor agent instructions and skills to current best practices
  ([`922a087`](https://github.com/BuckanovNikita/cveta2/commit/922a0873b5d7bdc0dafdb1b54d9ae40b691c9ace))

- **plans**: Cover the Spec Kit upgrade in the skills layout record
  ([`a4f89cb`](https://github.com/BuckanovNikita/cveta2/commit/a4f89cbbcf335a3b848f0949bb0149140e904b05))

- **plans**: Plan development speed changes and record open discussion
  ([`4cf5fdd`](https://github.com/BuckanovNikita/cveta2/commit/4cf5fdd7b7b2d5134fd9f3183c99b1a1b037ee3c))

- **plans**: Record the commit gate and acceptance of the gates simplification
  ([`ef9cf6e`](https://github.com/BuckanovNikita/cveta2/commit/ef9cf6e8c91b844a083291c94dea587d11f75054))

### Refactoring

- **gates**: Run every gate at commit and make mutation change-scoped
  ([`96e33be`](https://github.com/BuckanovNikita/cveta2/commit/96e33be3d482b86dacf450dcd753cb4ddb217650))

- **integration**: Replace the shell lifecycle with tests/integration/lifecycle.py
  ([`f2755c8`](https://github.com/BuckanovNikita/cveta2/commit/f2755c8f79d150abf315668e0cb8fbbbf158d7ca))

- **scripts**: Merge the mutation gate and drop CONTRIBUTING.md
  ([`28eeedd`](https://github.com/BuckanovNikita/cveta2/commit/28eeedd7e7d0646b45c2a3bc63db30c399c35bf3))

- **scripts**: Replace custom hooks and drop unused operator tools
  ([`89b607d`](https://github.com/BuckanovNikita/cveta2/commit/89b607d79514b7821b1461e0e7db656ccdc21331))

- **skills**: Keep policy in guidance and share skill sources via symlinks
  ([`f884ba5`](https://github.com/BuckanovNikita/cveta2/commit/f884ba53f26970ff048e40fbc965df07f040ffcd))

### Testing

- Restore review-flagged checks and add a Hypothesis explore profile
  ([`63c0fc4`](https://github.com/BuckanovNikita/cveta2/commit/63c0fc45f4c4875b1ffaa6c7bc394cdbb959ddf2))

- **convert**: Replace example lists with properties for conversion, partition and retry
  ([`b513825`](https://github.com/BuckanovNikita/cveta2/commit/b513825e30a34396e55f4ead99cafdf38eab063f))

- **core**: Fold origin-named test files into module tests and add merge properties
  ([`116e316`](https://github.com/BuckanovNikita/cveta2/commit/116e3165198e81e13b1d608387697e34afe7c523))

- **fetch**: Merge duplicated fetch scenarios and share the storage fake
  ([`b68919c`](https://github.com/BuckanovNikita/cveta2/commit/b68919c01b29f6675d4e235ae8394ce8e24b2335))

- **integration**: Record live HTTPS stand run and independent review
  ([`d3ef946`](https://github.com/BuckanovNikita/cveta2/commit/d3ef946bb4dc97d98690adff2684853a9437a5ff))

- **integration**: Use https docker.internal stands and report TLS failures
  ([`9174b14`](https://github.com/BuckanovNikita/cveta2/commit/9174b1432ac51b185e8e8a1c199c4cdf9f09d7cd))

- **tooling**: Keep harness tests to the behaviour they guard
  ([`cb679d6`](https://github.com/BuckanovNikita/cveta2/commit/cb679d6f3da490d28c5a2c7d1965e5d738181ce2))

- **upload**: Parametrize upload and S3 tests and drop duplicates
  ([`cf081e7`](https://github.com/BuckanovNikita/cveta2/commit/cf081e7d1f18e4ccc62d28d4d8fb1d34f4158c85))


## v0.13.1 (2026-11-02)

### Bug Fixes

- Normalize shared personal-workspace identities
  ([`962fad5`](https://github.com/BuckanovNikita/cveta2/commit/962fad53b279c4a57f0460c6e9de8dd2f11bb772))


## v0.13.0 (2026-11-02)

### Documentation

- Close cleanup release delivery and convergence
  ([`9d64379`](https://github.com/BuckanovNikita/cveta2/commit/9d643792cfcb0abfbef00658a797fcce43b0d628))

- Standardize cross-host instruction imports
  ([`039efac`](https://github.com/BuckanovNikita/cveta2/commit/039efacc2f1dadb892cef6bbc46b00372987ae79))

### Features

- Manage datasets with authoritative shared project configuration
  ([`57c751f`](https://github.com/BuckanovNikita/cveta2/commit/57c751f1cceeb6e546c86e30e7c2937835e8c7b1))

### Testing

- Run worker isolation guard before dependent cases
  ([`cd0ead5`](https://github.com/BuckanovNikita/cveta2/commit/cd0ead51efe9e12b43b15d965285c3cfe220b97d))

### Breaking Changes

- Project identities and dataset policy belong exclusively to the shared configuration. Mixed legacy
  settings require a reviewed migration; personal settings and environment identity overrides cannot
  shadow selected shared mappings.


## v0.12.1 (2026-11-01)

### Bug Fixes

- Preserve incomplete tasks and operational error handling
  ([`bce719b`](https://github.com/BuckanovNikita/cveta2/commit/bce719b4de51dde7bdb656690790f2f50c292346))

### Documentation

- Accept cleanup and live release verification
  ([`fd82293`](https://github.com/BuckanovNikita/cveta2/commit/fd82293e54ca60b19cc56440f4d690ef416d5a38))

- Prepare verified cleanup patch release
  ([`c66e7c1`](https://github.com/BuckanovNikita/cveta2/commit/c66e7c1ee62940314ed30eefe6876c2f1974fb8e))

- Record cleanup verification and live release blocker
  ([`24d1045`](https://github.com/BuckanovNikita/cveta2/commit/24d1045fe77605d8ed6b092b054c1c2a283d23ac))

- Record fetch diagnostics acceptance and release receipts
  ([`d1a40ac`](https://github.com/BuckanovNikita/cveta2/commit/d1a40ac3f325f13b25345318b799d66c1f185310))


## v0.12.0 (2026-10-29)

### Features

- Speed up fetches and expose safe CVAT request diagnostics
  ([`bc03d40`](https://github.com/BuckanovNikita/cveta2/commit/bc03d408ed4685852a1280a6458af141d33a123d))


## v0.11.1 (2026-10-21)

### Documentation

- Checkpoint specification and review history before consolidation
  ([`af0073e`](https://github.com/BuckanovNikita/cveta2/commit/af0073e5bd8a8799f0cfd322cfb27c8efd7b747d))

- Consolidate current specification into a recoverable baseline
  ([`e690227`](https://github.com/BuckanovNikita/cveta2/commit/e69022727a73747bbd5723e34fa96b093f42c34c))

- Prepare explicit cleanup patch release
  ([`313d4c8`](https://github.com/BuckanovNikita/cveta2/commit/313d4c82ffd0ee4f8f0f04b5e893bfa5c2e48005))

- Record cleanup verification and completed delivery
  ([`456463b`](https://github.com/BuckanovNikita/cveta2/commit/456463b937f5264ca238f309a8b4d2da95a07303))

- Record dataset publication acceptance and releases
  ([`6af3e18`](https://github.com/BuckanovNikita/cveta2/commit/6af3e18aa7db27049a94005c0e736669893076fa))

### Refactoring

- Separate upload, transport and interface responsibilities
  ([`db4514c`](https://github.com/BuckanovNikita/cveta2/commit/db4514c05f6652b4ed96020d7b1e4d7feb43db0d))


## v0.11.0 (2026-10-20)

### Documentation

- Record Python compatibility release delivery
  ([`0509c7f`](https://github.com/BuckanovNikita/cveta2/commit/0509c7fdb3e7a7c4d7c59f48bb29af675277b2ec))

### Features

- Add dataset verification and reviewed ClearML publication
  ([`78138b8`](https://github.com/BuckanovNikita/cveta2/commit/78138b80af33e2651711b399cd428aad646b431c))

### Breaking Changes

- Fetch no longer publishes to ClearML. Remove --no-clearml, publish_clearml, setup-clearml and
  automatic publication configuration; prepare with verify --bundle and publish separately with
  upload-dataset.


## v0.10.0 (2026-10-15)

### Documentation

- Align Python lifecycle within native Spec Kit
  ([`9f100d0`](https://github.com/BuckanovNikita/cveta2/commit/9f100d030dc8ab4fc5ff89d8310ac6fd68c3fe92))

- Keep portable usage skill current
  ([`00a6063`](https://github.com/BuckanovNikita/cveta2/commit/00a6063f3a4eef2a817b9d75ed1ebe084fc208a9))

- Record clean architecture delivery
  ([`6cb911b`](https://github.com/BuckanovNikita/cveta2/commit/6cb911b49b7b55fdd9679084624f5fa03f567047))

- Record Python workflow delivery evidence
  ([`d93cb81`](https://github.com/BuckanovNikita/cveta2/commit/d93cb8124b13bc0a581432ac6d1bd79cea09ce73))

### Features

- Support only Python 3.12 and 3.13
  ([`7f91109`](https://github.com/BuckanovNikita/cveta2/commit/7f91109ddd36e85ff7912fddafb7136d6700959b))

### Breaking Changes

- Python 3.10 and 3.11 are no longer supported. Python 3.14 and later are excluded.


## v0.9.1 (2026-10-14)

### Bug Fixes

- **architecture**: Enforce inward dependencies and explicit effects
  ([`d67a83a`](https://github.com/BuckanovNikita/cveta2/commit/d67a83aed079dbc484c5e57678800e850687a4ed))

### Documentation

- Record fetch skip validation delivery
  ([`253c5c1`](https://github.com/BuckanovNikita/cveta2/commit/253c5c18ccb483cdf0aa1e575b1a4a42419f0ef5))


## v0.9.0 (2026-10-12)

### Documentation

- Record polygon bounding box verification and release
  ([`cff0a95`](https://github.com/BuckanovNikita/cveta2/commit/cff0a95ad5af205a572dc53d66fe52869e8278eb))

### Features

- Accept completed annotation jobs before project fetch
  ([`a1e92b9`](https://github.com/BuckanovNikita/cveta2/commit/a1e92b98f04d7965b79b2ea6b561a17d83aeb50f))


## v0.8.0 (2026-10-12)

### Features

- Convert standalone CVAT polygons to bounding boxes
  ([`41c045e`](https://github.com/BuckanovNikita/cveta2/commit/41c045e76757b6af65687fe7da49a4e7aa30218d))


## v0.7.0 (2026-10-06)

### Bug Fixes

- Resolve reviewed CVAT, dataset and interface failures
  ([`a6d3d66`](https://github.com/BuckanovNikita/cveta2/commit/a6d3d6672b918649a9a2442527872041a56ac22c))

### Breaking Changes

- Ambiguous names require IDs; legacy upload manifests no longer authorize resume; repeated COCO
  export replaces metadata-owned output; noncanonical S3 destinations reject; doctor exits nonzero
  when required configuration checks fail.


## v0.6.0 (2026-09-06)

### Documentation

- Describe the shared-stand integration topology and the agent-infra block
  ([`1717184`](https://github.com/BuckanovNikita/cveta2/commit/17171844f1f5daf7c282be16b50a47f0753a5eab))

- Make SSH keepalives the default for gated pushes
  ([`82b5087`](https://github.com/BuckanovNikita/cveta2/commit/82b5087b9b52154dfe8630e21a35ca18d834f52f))

- Sweep retired infra tokens after the shared-stand migration
  ([`1a77d1f`](https://github.com/BuckanovNikita/cveta2/commit/1a77d1fe48fe742c186c5e04c982c1afd5ae5da6))

### Features

- **integration**: ClearML tests on the shared stand and the keep slot in the gate
  ([`141322e`](https://github.com/BuckanovNikita/cveta2/commit/141322ee748ebeceaffe63b1d77835401a942900))

- **integration**: Mint the run tag through the skill and read credentials from the project Secrets
  ([`3037a2a`](https://github.com/BuckanovNikita/cveta2/commit/3037a2a50727d2b832f01a26f114d9fca84e995d))

- **integration**: Run against the shared MinIO and CVAT stands with no Compose
  ([`a9b7c56`](https://github.com/BuckanovNikita/cveta2/commit/a9b7c56b0d3d96ae16391396ccad2ae8a767fea1))

### Refactoring

- **integration**: Cvat_stand verifies membership instead of self-registering and drops --stale
  ([`705586b`](https://github.com/BuckanovNikita/cveta2/commit/705586bed067af909cf973c9e41da429507a1849))


## v0.5.4 (2026-09-05)

### Bug Fixes

- Close the verified defects from the fetch, upload and convert audit
  ([`5eaf98f`](https://github.com/BuckanovNikita/cveta2/commit/5eaf98f29ec3c365e198be55cc3262613901546b))

### Documentation

- **skills**: Clarify CVAT task workflows
  ([`512e0e0`](https://github.com/BuckanovNikita/cveta2/commit/512e0e03063af3132fc8047f920c48eadf544cdd))


## v0.5.3 (2026-09-04)

### Bug Fixes

- Isolate network settings between parallel callers
  ([`547756b`](https://github.com/BuckanovNikita/cveta2/commit/547756b31a61adccee227a265b1500e9f408c234))

### Testing

- Align integration cache freshness contract
  ([`ca2f0a8`](https://github.com/BuckanovNikita/cveta2/commit/ca2f0a8ad72934130beabbba1409b130f030d449))

- Run integration tests against the cluster CVAT stand
  ([`13371d2`](https://github.com/BuckanovNikita/cveta2/commit/13371d2993e5ef808032f93ca38537d3e315e9f3))

- Stop unit runs from spending the stand's anonymous request budget
  ([`6e34697`](https://github.com/BuckanovNikita/cveta2/commit/6e34697bac4e81a3a57744ec1e934599c14600ad))

- Strengthen path conversion mutation coverage
  ([`40c0038`](https://github.com/BuckanovNikita/cveta2/commit/40c00381a0ecef40674d0b2c997ec4b1815eb632))


## v0.5.2 (2026-09-04)

### Bug Fixes

- Harden dataset and configuration workflows
  ([`62cad9d`](https://github.com/BuckanovNikita/cveta2/commit/62cad9dd7c385ab1380b0672f4a77f2c83c2538e))


## v0.5.1 (2026-09-02)

### Bug Fixes

- Close the remaining verified defects in resolution, config paths and I/O
  ([`33c55bb`](https://github.com/BuckanovNikita/cveta2/commit/33c55bbca2630e301eb7b5aa0a7946c5068120a7))

- Correct ten verified defects found by the project-wide review
  ([`c63853f`](https://github.com/BuckanovNikita/cveta2/commit/c63853f0a61abbbd29aa25c7bf6ef283bed08b50))

- **scripts**: Let the integration stack honour INTEGRATION_USER and port env overrides
  ([`f54e21d`](https://github.com/BuckanovNikita/cveta2/commit/f54e21d6b8cda5b8c74182313b2e996fe5965624))

### Documentation

- Describe the upload refusal of unreachable images and list-form names
  ([`f501542`](https://github.com/BuckanovNikita/cveta2/commit/f50154240efb904ba04464945293e89995960be6))

- Fix the miscounted out-of-scope list in the mutation-testing skill
  ([`341131b`](https://github.com/BuckanovNikita/cveta2/commit/341131bbf144acf0a1e97168f32eeabf8e137018))

- Remove restated prose and collapse cross-document duplication
  ([`a2cf8ca`](https://github.com/BuckanovNikita/cveta2/commit/a2cf8ca749ae7151b0ddac8a0ad8730f7395097e))

### Refactoring

- Remove duplicated logic and needless indirection found by the review
  ([`a63f8bc`](https://github.com/BuckanovNikita/cveta2/commit/a63f8bce4bbd145528c11636726c5a67177186ee))

### Testing

- Kill the two survivors the full mutation profile found
  ([`0e47759`](https://github.com/BuckanovNikita/cveta2/commit/0e4775993bdb1b6c6c255c19bcc7ffe443df0ad6))


## v0.5.0 (2026-08-28)

### Documentation

- Describe task_id ordering and the cache's status-only freshness
  ([`6742b71`](https://github.com/BuckanovNikita/cveta2/commit/6742b710a38b424d824ae6b075ea5337a8864baa))

### Features

- Order tasks by task_id instead of task_updated_date
  ([`8e3ba4f`](https://github.com/BuckanovNikita/cveta2/commit/8e3ba4fb48d1c12f01f82dfcf5d807062c16ae2d))

### Testing

- Close the sibling-CSV gaps and re-triage the mutation allowlist
  ([`c79916e`](https://github.com/BuckanovNikita/cveta2/commit/c79916ebf25439b8e90d91c045d85be1620f0ef5))

- **integration**: Expect Cveta2Error from drop_label_annotations
  ([`7acea36`](https://github.com/BuckanovNikita/cveta2/commit/7acea365bc4c002d4575f9d4af96da08bb95c729))

- **integration**: Pin the label-edit premise against a live CVAT
  ([`b2a6b57`](https://github.com/BuckanovNikita/cveta2/commit/b2a6b57db36b1bf29ae1af7ddeb346f21301a659))

### Breaking Changes

- `merge --by-time` is renamed to `--by-task` and now resolves conflicts by task_id rather than
  task_updated_date; the Python API's `cveta2.merge(by_time=)` becomes `by_task=`.
  `WhatsNewResult.cutoff` changes from an ISO date string to an int task id and `updated_task_ids`
  is gone, as is the client's `list_tasks_completed_after` (replaced by `list_new_completed_tasks`).


## v0.4.0 (2026-08-23)

### Bug Fixes

- Replace silent failures and leaking exception types with domain errors
  ([`6474b41`](https://github.com/BuckanovNikita/cveta2/commit/6474b41ae717e4f20736e6c02cd8c27c40d50bee))

- **client**: Stop a throttled size read from re-uploading task data
  ([`251c218`](https://github.com/BuckanovNikita/cveta2/commit/251c2181f8c963764047a6b5877f8607d4bee3e6))

- **commands**: Qualify echoed -p with the session organization
  ([`b0f9cc3`](https://github.com/BuckanovNikita/cveta2/commit/b0f9cc3397aa8196a7576ba337bc0d8d9761392d))

- **s3-sync**: Describe the projects it actually covers
  ([`22b47bd`](https://github.com/BuckanovNikita/cveta2/commit/22b47bdd43858b1f061c5e11e04176617339f89f))

- **scripts**: Put scripts/ under ruff and mypy, and prune dead suppressions
  ([`cdfe309`](https://github.com/BuckanovNikita/cveta2/commit/cdfe30938f2e98c4759e17780fd708384a483d33))

### Documentation

- Split the README reference into docs/ and correct what had drifted
  ([`f200948`](https://github.com/BuckanovNikita/cveta2/commit/f200948bbdcf4e0c6187e59a557626b5ae204fad))

### Features

- **upload**: Honour cache.images_root when resolving local images
  ([`340a027`](https://github.com/BuckanovNikita/cveta2/commit/340a0272a631330aaa50342e4dfeb0415fe4dbe0))

### Refactoring

- Collapse repeated parameter tuples and share duplicated orchestration
  ([`d52426d`](https://github.com/BuckanovNikita/cveta2/commit/d52426d3acb7aefecbe58918a33c35ba8cfdddb0))

### Testing

- Check the docs against the code
  ([`151a410`](https://github.com/BuckanovNikita/cveta2/commit/151a4103fe20155c2c2554f6ab05be8f13487876))

- Cover cveta2 ignore, make three tests able to fail, and dedup fixtures
  ([`392c27e`](https://github.com/BuckanovNikita/cveta2/commit/392c27ef7be615e1eb14ba0b4fc1f0056c457dc2))

- Split test_convert.py along the three modules it covers
  ([`4b21412`](https://github.com/BuckanovNikita/cveta2/commit/4b2141234b67e764099dd4205347380a2dad5e6d))


## v0.3.0 (2026-08-21)

### Bug Fixes

- **convert**: Emit job_stage/job_state instead of the removed task_status
  ([`f25b0f3`](https://github.com/BuckanovNikita/cveta2/commit/f25b0f3cc6bd40ea344c50cf42a41026be4cd780))

- **integration**: Make the stack work against CVAT v2.59.1
  ([`26471ad`](https://github.com/BuckanovNikita/cveta2/commit/26471adf23e6a5704c9a09cf7f5214e5fdc93fdd))

### Features

- Replace task_status with per-job job_stage and job_state
  ([`f50c5b1`](https://github.com/BuckanovNikita/cveta2/commit/f50c5b1bb388d10b1ba1ce26b90b69bb732f4552))

### Testing

- **integration**: Pin CVAT's finished-task rule against a live server
  ([`e865648`](https://github.com/BuckanovNikita/cveta2/commit/e865648efbc9e55f600eee76f1013ab88ba91665))

### Breaking Changes

- The `task_status` column is gone from dataset.csv, obsolete.csv, in_progress.csv and deleted.csv,
  replaced by `job_stage` and `job_state`. `whats_new` requires the new columns, so a CSV fetched
  before this change must be refetched.


## v0.2.1 (2026-08-21)

### Performance Improvements

- **fetch**: Make a single-task fetch cost the task, not the project
  ([`2c76e08`](https://github.com/BuckanovNikita/cveta2/commit/2c76e0883442b865b9884e0136614188176feb5c))

### Testing

- **fetch**: Close the mutation gaps the single-task fast path opened
  ([`2cf7582`](https://github.com/BuckanovNikita/cveta2/commit/2cf7582e193889cfeb241505efa2025ea7fe504e))


## v0.2.0 (2026-08-16)

### Bug Fixes

- **upload**: Report a task with no attached data as empty, not as an error
  ([`1652ce2`](https://github.com/BuckanovNikita/cveta2/commit/1652ce25a114153f7afe6db8677ef85c01bf35ab))

### Features

- **doctor**: Repair shared-cache permissions with `doctor --cache`
  ([`df85689`](https://github.com/BuckanovNikita/cveta2/commit/df85689f81d07e13dee05f3427a83e91d8069611))

- **retry**: Retry 429 and 5xx, and never repeat an ambiguous write
  ([`bcc8932`](https://github.com/BuckanovNikita/cveta2/commit/bcc8932dd200ffe0c8eaf456a1e1373399edc592))

- **transfer**: Run S3 and CVAT work concurrently
  ([`5eee206`](https://github.com/BuckanovNikita/cveta2/commit/5eee2069c0cea6526ee3390bce71c6221acc9032))

- **upload**: Continue an interrupted upload with --resume
  ([`f58d818`](https://github.com/BuckanovNikita/cveta2/commit/f58d8184345522322aac1927054479b9a1842086))

### Testing

- **integration**: Prove concurrency and resume against a live CVAT
  ([`873822a`](https://github.com/BuckanovNikita/cveta2/commit/873822a09e73457b132ec7095e2036bb1a1cf5b2))


## v0.1.1 (2026-08-15)

### Bug Fixes

- **integration**: Resolve the compose directory with dirname
  ([`6ae6bfb`](https://github.com/BuckanovNikita/cveta2/commit/6ae6bfb143e424f89db713362cc91cf8182e3828))

- **packaging**: Drop the vendored CVAT submodule
  ([`cf3d6c0`](https://github.com/BuckanovNikita/cveta2/commit/cf3d6c0336ca07164a53e37547a040a36c1e4151))

### Documentation

- Fix the commit skill's layer map and name the mutation gate
  ([`f2a8b6b`](https://github.com/BuckanovNikita/cveta2/commit/f2a8b6b3e3d769f0fac2d7bbab77e5efdec6c990))


## v0.1.0 (2026-08-13)

- Initial Release
